# AUGMENT PROMPT — Portal 18: FR.224 Impartiality Declarations

## Context
Certiva — FastAPI backend + Next.js 14 App Router frontend.
**DO NOT BREAK THE EXISTING PORTAL. All changes are additive.**

**FR.224 — Audit Team Information Form (Impartiality Declaration)**
Every person on the audit team (Lead Auditor, Team Auditors, Technical Experts, Observers)
must individually sign an impartiality declaration before the audit stage.

Each person declares:
- No commercial or other relations with the client organization in the past 2 years
- Will not have such relations for the next 2 years
- Not acting as a consultant to this organization
- Will maintain confidentiality throughout and after the audit

This is a purely auditor-side signing flow. The client does not sign.
CB staff seed the declaration records per stage (same pattern as FR.211 assessments).
Each auditor signs their own declaration from the auditor portal.

---

## What this builds

**Backend:**
1. `AuditSetImpartialityDeclaration` table in `db_models.py`
2. New `declaration_router.py`
3. One new email function in `email_service.py`
4. Register router in `main.py`

**Frontend:**
5. New `DeclarationManagementSection.tsx` (CB portal `/clients/[id]`)
6. `AuditorDeclarationsView` component + "Declarations" tab in `/auditor/audit/[id]/page.tsx`
7. Wire `DeclarationManagementSection` into `(app)/clients/[id]/page.tsx`

---

## Backend

### 1. `backend/audit_set/db_models.py` — add `AuditSetImpartialityDeclaration`

Add after `AuditSetNCForm` (or at the end of the file):

```python
# ---------------------------------------------------------------------------
# Table 11 — audit_set_impartiality_declarations
# FR.224 — Impartiality declaration signed by each audit team member.
# One record per person per stage. Seeded by CB; signed by the auditor.
# ---------------------------------------------------------------------------

class AuditSetImpartialityDeclaration(Base):
    __tablename__ = "audit_set_impartiality_declarations"

    id             = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    audit_set_id   = Column(String, ForeignKey("audit_sets.id", ondelete="CASCADE"), nullable=False)
    stage_type     = Column(String, nullable=False)
    stage_order    = Column(Integer, nullable=True)
    member_name    = Column(String, nullable=False)   # denormalized
    member_role    = Column(String, nullable=False)   # "Lead Auditor"|"Team Auditor"|"Technical Expert"|"Observer"
    auditor_ref_id = Column(String, nullable=True)    # soft FK → auditors.id (for self-sign matching)

    # Signature
    signed_by      = Column(String, nullable=True)    # PlatformUser.id
    signed_at      = Column(DateTime, nullable=True)
    signed_ip      = Column(String, nullable=True)
    otp_hash       = Column(String, nullable=True)
    otp_expires_at = Column(DateTime, nullable=True)

    created_at     = Column(DateTime, default=datetime.utcnow, nullable=False)
```

No `_safe_add_column` needed — created by `Base.metadata.create_all` on boot.

---

### 2. New file `backend/audit_set/declaration_router.py`

```python
"""
BATUHAN — FR.224 Impartiality Declarations (Prompt 18).

CB creates declaration records per stage (for all team members).
Each auditor signs their own declaration via OTP from the auditor portal.

Endpoints:
  POST /audit-sets/{id}/declarations/create-for-stage?stage_type=…  (CB admin/planner)
  GET  /audit-sets/{id}/declarations                                  (CB + auditor)
  POST /audit-sets/{id}/declarations/{did}/sign/request-otp          (auditor — own record only)
  POST /audit-sets/{id}/declarations/{did}/sign/verify               (auditor — own record only)
"""
from __future__ import annotations
import hashlib
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from audit_set.db_models import (
    AuditSet, AuditSetImpartialityDeclaration, AuditSetStage, get_db,
)
from auth.db_models import PlatformUser, get_db as get_auth_db
from auth.dependencies import get_current_user
from email_service import send_impartiality_declaration_request, send_otp_code

router = APIRouter(tags=["declarations"])

CB_ROLES      = {"admin", "planner", "officer", "executive"}
AUDITOR_ROLES = {"auditor", "admin"}
OTP_EXPIRY    = 10  # minutes


def _hash(val: str) -> str:
    return hashlib.sha256(val.encode()).hexdigest()


def _decl_dict(d: AuditSetImpartialityDeclaration) -> dict:
    return {
        "id":             d.id,
        "audit_set_id":   d.audit_set_id,
        "stage_type":     d.stage_type,
        "stage_order":    d.stage_order,
        "member_name":    d.member_name,
        "member_role":    d.member_role,
        "auditor_ref_id": d.auditor_ref_id,
        "is_signed":      d.signed_at is not None,
        "signed_at":      d.signed_at.isoformat() if d.signed_at else None,
        "created_at":     d.created_at.isoformat() if d.created_at else None,
    }


# ── CB: create declarations for a stage ──────────────────────────────────────

@router.post("/audit-sets/{audit_set_id}/declarations/create-for-stage")
def create_declarations_for_stage(
    audit_set_id: str,
    stage_type:   str,
    db:       Session = Depends(get_db),
    auth_db:  Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """
    Seed one declaration record per team member for this stage.
    Idempotent: skips records already present for (member_name, stage_type).
    Emails each auditor who has a linked PlatformUser account.
    """
    if current_user.role not in {"admin", "planner"}:
        raise HTTPException(403, "Not authorized")

    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Audit set not found")

    stage = (
        db.query(AuditSetStage)
        .filter_by(audit_set_id=audit_set_id, stage_type=stage_type)
        .order_by(AuditSetStage.stage_order)
        .first()
    )
    if not stage:
        raise HTTPException(404, f"No stage of type '{stage_type}' found")

    # Collect all team members
    entries: list[dict] = []
    if stage.lead_auditor_name:
        entries.append({
            "name":   stage.lead_auditor_name,
            "role":   "Lead Auditor",
            "ref_id": stage.lead_auditor_id,
        })
    for a in (stage.auditors or []):
        if isinstance(a, dict) and a.get("name"):
            entries.append({
                "name":   a["name"],
                "role":   "Team Auditor",
                "ref_id": a.get("id"),
            })
    for te in (stage.technical_experts or []):
        if isinstance(te, dict) and te.get("name"):
            entries.append({
                "name":   te["name"],
                "role":   "Technical Expert",
                "ref_id": te.get("id"),
            })
    for obs in (stage.observers or []):
        if isinstance(obs, dict) and obs.get("name"):
            entries.append({
                "name":   obs["name"],
                "role":   "Observer",
                "ref_id": obs.get("id"),
            })

    if not entries:
        raise HTTPException(
            422,
            "No team members assigned to this stage — assign the audit team before creating declarations",
        )

    # Existing records for deduplication
    existing = {
        (d.member_name, d.stage_type)
        for d in db.query(AuditSetImpartialityDeclaration)
                   .filter_by(audit_set_id=audit_set_id, stage_type=stage_type)
                   .all()
    }

    created = 0
    for entry in entries:
        key = (entry["name"], stage_type)
        if key in existing:
            continue
        db.add(AuditSetImpartialityDeclaration(
            audit_set_id=audit_set_id,
            stage_type=stage_type,
            stage_order=stage.stage_order,
            member_name=entry["name"],
            member_role=entry["role"],
            auditor_ref_id=entry["ref_id"],
        ))
        created += 1

    db.commit()

    # Email notification to each team member who has a PlatformUser account
    stage_label = stage_type.replace("_", " ").title()
    for entry in entries:
        if not entry["ref_id"]:
            continue
        user = auth_db.query(PlatformUser).filter_by(auditor_id=entry["ref_id"]).first()
        if not user:
            continue
        try:
            send_impartiality_declaration_request(
                to=user.email,
                full_name=user.full_name,
                company_name=audit_set.company_name,
                stage_label=stage_label,
                role=entry["role"],
            )
        except Exception:
            pass

    return {"created": created, "skipped": len(entries) - created}


# ── CB + Auditor: list declarations ──────────────────────────────────────────

@router.get("/audit-sets/{audit_set_id}/declarations")
def list_declarations(
    audit_set_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """
    CB sees all declarations for this audit set.
    Auditors also see all declarations (to know team status), but can only
    sign their own.
    """
    if current_user.role not in CB_ROLES | AUDITOR_ROLES:
        raise HTTPException(403, "Not authorized")

    rows = (
        db.query(AuditSetImpartialityDeclaration)
        .filter_by(audit_set_id=audit_set_id)
        .order_by(
            AuditSetImpartialityDeclaration.stage_type,
            AuditSetImpartialityDeclaration.created_at,
        )
        .all()
    )
    return [_decl_dict(r) for r in rows]


# ── Auditor: sign own declaration ─────────────────────────────────────────────

def _get_own_declaration(
    did: str,
    audit_set_id: str,
    current_user: PlatformUser,
    db: Session,
) -> AuditSetImpartialityDeclaration:
    """Fetch declaration and verify current user is the named team member."""
    if current_user.role not in AUDITOR_ROLES:
        raise HTTPException(403, "Auditor portal access only")

    decl = db.query(AuditSetImpartialityDeclaration).filter_by(
        id=did, audit_set_id=audit_set_id
    ).first()
    if not decl:
        raise HTTPException(404, "Declaration not found")

    # Authorization: the declaration must belong to this auditor
    # admin bypass — allows testing without an auditor profile
    if current_user.role == "admin":
        return decl

    if not current_user.auditor_id:
        raise HTTPException(403, "No auditor profile linked to your account")
    if decl.auditor_ref_id != current_user.auditor_id:
        raise HTTPException(403, "This declaration is not assigned to you")

    return decl


@router.post("/audit-sets/{audit_set_id}/declarations/{did}/sign/request-otp")
def declaration_request_otp(
    audit_set_id: str,
    did: str,
    db:       Session = Depends(get_db),
    auth_db:  Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    decl = _get_own_declaration(did, audit_set_id, current_user, db)
    if decl.signed_at:
        raise HTTPException(400, "Already signed")

    otp             = f"{secrets.randbelow(900000) + 100000}"
    decl.otp_hash       = _hash(otp)
    decl.otp_expires_at = datetime.utcnow() + timedelta(minutes=OTP_EXPIRY)
    db.commit()

    try:
        send_otp_code(
            to=current_user.email,
            full_name=current_user.full_name,
            otp=otp,
            document_label=f"Impartiality Declaration — {decl.stage_type.replace('_',' ').title()}",
        )
    except Exception:
        pass

    return {"message": f"Code sent to {current_user.email}. Valid for {OTP_EXPIRY} minutes."}


@router.post("/audit-sets/{audit_set_id}/declarations/{did}/sign/verify")
def declaration_verify_otp(
    audit_set_id: str,
    did: str,
    otp: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    decl = _get_own_declaration(did, audit_set_id, current_user, db)
    if decl.signed_at:
        raise HTTPException(400, "Already signed")
    if not decl.otp_hash or not decl.otp_expires_at:
        raise HTTPException(400, "No pending OTP. Request one first.")
    if datetime.utcnow() > decl.otp_expires_at:
        raise HTTPException(400, "OTP expired. Please request a new one.")
    if _hash(otp.strip()) != decl.otp_hash:
        raise HTTPException(400, "Invalid code.")

    decl.signed_by      = current_user.id
    decl.signed_at      = datetime.utcnow()
    decl.signed_ip      = request.client.host if request.client else None
    decl.otp_hash       = None
    decl.otp_expires_at = None
    db.commit()

    return {"signed": True, "signed_at": decl.signed_at.isoformat()}
```

---

### 3. `backend/email_service.py` — add one function

Append before the final blank line:

```python
def send_impartiality_declaration_request(
    to: str,
    full_name: str,
    company_name: str,
    stage_label: str,
    role: str,
) -> bool:
    """Sent to each audit team member when CB creates declaration records for a stage."""
    settings = get_settings()
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
      <h2 style="color:#1A4731">IFC Global LLC — Impartiality Declaration Required</h2>
      <p>Dear {full_name},</p>
      <p>You are assigned as <strong>{role}</strong> for the audit of
         <strong>{company_name}</strong> ({stage_label}).</p>
      <p>As required by ISO 17021-1, you must sign an impartiality declaration
         before the audit commences. Please log in to the portal, navigate to
         the relevant audit assignment, and complete the declaration under the
         <strong>Declarations</strong> tab.</p>
      <p><a href="{settings.email_base_url}/auditor/dashboard"
            style="background:#1A4731;color:white;padding:10px 20px;border-radius:4px;
                   text-decoration:none">Go to Portal</a></p>
      <p style="color:#666;font-size:12px">IFC Global LLC · application@ifcglobal.us</p>
    </div>
    """
    return _send(to, f"IFC Global — Impartiality Declaration Required: {company_name}", html)
```

---

### 4. `backend/main.py` — register router

```python
from audit_set.declaration_router import router as declaration_router
app.include_router(declaration_router)
```

Place alongside the other audit_set routers.

---

## Frontend

### 5. New file `frontend/src/components/ui/DeclarationManagementSection.tsx`

CB portal card — create declarations per stage, view signing status.

```tsx
'use client'

import { useEffect, useState } from 'react'
import api from '@/lib/api'

interface Declaration {
  id:           string
  stage_type:   string
  stage_order:  number | null
  member_name:  string
  member_role:  string
  is_signed:    boolean
  signed_at:    string | null
}

const STAGE_TYPES = [
  { value: 'stage_1',         label: 'Stage 1' },
  { value: 'stage_2',         label: 'Stage 2' },
  { value: 'surveillance',    label: 'Surveillance' },
  { value: 'recertification', label: 'Recertification' },
]

function fmtDate(iso: string | null) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
}

const ROLE_COLOR: Record<string, string> = {
  'Lead Auditor':     'bg-purple-100 text-purple-700',
  'Team Auditor':     'bg-blue-100 text-blue-700',
  'Technical Expert': 'bg-teal-100 text-teal-700',
  'Observer':         'bg-gray-100 text-gray-500',
}

export function DeclarationManagementSection({
  auditSetId,
  workflowStatus,
}: {
  auditSetId: string
  workflowStatus: string | null
}) {
  const [declarations, setDeclarations] = useState<Declaration[]>([])
  const [loading, setLoading]     = useState(true)
  const [creating, setCreating]   = useState(false)
  const [stageToCreate, setStageToCreate] = useState('stage_1')
  const [createMsg, setCreateMsg] = useState('')
  const [busy, setBusy]           = useState(false)

  // Show from in_planning onwards — declarations should be signed before the audit
  const relevantStatuses = new Set([
    'in_planning', 'quotation_sent', 'agreement_signed',
    'audit_scheduled', 'audit_in_progress', 'under_review', 'certified',
  ])
  if (!workflowStatus || !relevantStatuses.has(workflowStatus)) return null

  async function load() {
    try {
      const r = await api.get<Declaration[]>(`/audit-sets/${auditSetId}/declarations`)
      setDeclarations(r.data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [auditSetId])

  async function createForStage() {
    setBusy(true)
    setCreateMsg('')
    try {
      const r = await api.post<{ created: number; skipped: number }>(
        `/audit-sets/${auditSetId}/declarations/create-for-stage?stage_type=${stageToCreate}`,
      )
      const { created, skipped } = r.data
      setCreateMsg(
        `Created ${created} declaration form(s)${skipped ? `, ${skipped} already existed` : ''}.`,
      )
      setCreating(false)
      await load()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setCreateMsg(detail || 'Failed to create declarations')
    } finally {
      setBusy(false)
    }
  }

  // Group by stage
  const grouped = declarations.reduce<Record<string, Declaration[]>>((acc, d) => {
    acc[d.stage_type] = acc[d.stage_type] || []
    acc[d.stage_type].push(d)
    return acc
  }, {})

  return (
    <div className="mt-6">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-700">
          Impartiality Declarations (FR.224)
        </h2>
        <button
          type="button"
          onClick={() => { setCreating(!creating); setCreateMsg('') }}
          className="rounded-lg border border-[#1A4731] px-3 py-1.5 text-xs font-medium text-[#1A4731] hover:bg-green-50"
        >
          {creating ? 'Cancel' : '+ Create Declarations'}
        </button>
      </div>

      {/* Create form */}
      {creating && (
        <div className="mb-4 flex items-end gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4">
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-600">Stage</label>
            <select
              value={stageToCreate}
              onChange={e => setStageToCreate(e.target.value)}
              className="rounded-lg border bg-white px-3 py-2 text-sm"
            >
              {STAGE_TYPES.map(s => (
                <option key={s.value} value={s.value}>{s.label}</option>
              ))}
            </select>
          </div>
          <button
            type="button"
            onClick={createForStage}
            disabled={busy}
            className="rounded-lg bg-[#1A4731] px-4 py-2 text-sm text-white disabled:opacity-40"
          >
            {busy ? 'Creating…' : 'Create & Notify Auditors'}
          </button>
          {createMsg && <p className="text-xs text-gray-600">{createMsg}</p>}
        </div>
      )}

      {loading ? (
        <p className="text-xs text-gray-400">Loading…</p>
      ) : declarations.length === 0 ? (
        <div className="rounded-xl border bg-white px-4 py-6 text-center text-xs text-gray-400">
          No declarations yet. Click "+ Create Declarations" after assigning the audit team.
        </div>
      ) : (
        <div className="space-y-3">
          {Object.entries(grouped).map(([stageType, list]) => {
            const stageLabel = STAGE_TYPES.find(s => s.value === stageType)?.label ?? stageType
            const allSigned  = list.every(d => d.is_signed)
            return (
              <div key={stageType} className="rounded-xl border bg-white">
                <div className="flex items-center justify-between border-b px-4 py-2.5">
                  <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                    {stageLabel}
                  </p>
                  {allSigned && (
                    <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-700">
                      All Signed ✓
                    </span>
                  )}
                </div>
                <div className="divide-y divide-gray-50">
                  {list.map(d => (
                    <div key={d.id} className="flex items-center justify-between px-4 py-3">
                      <div className="flex items-center gap-2">
                        <p className="text-sm font-medium text-gray-800">{d.member_name}</p>
                        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${ROLE_COLOR[d.member_role] ?? 'bg-gray-100 text-gray-500'}`}>
                          {d.member_role}
                        </span>
                      </div>
                      {d.is_signed ? (
                        <span className="text-xs text-gray-400">
                          Signed {fmtDate(d.signed_at)}
                        </span>
                      ) : (
                        <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-700">
                          Pending
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
```

---

### 6. `frontend/src/app/(auditor)/auditor/audit/[id]/page.tsx` — add "Declarations" tab

**Step A — Add `'declarations'` to the Tab type:**

```tsx
type Tab = 'overview' | 'messages' | 'upload' | 'attendees' | 'nc_forms' | 'declarations'
```

**Step B — Add `AuditorDeclarationsView` component** (add after `AuditorNCFormsView`, before `export default`):

```tsx
const DECLARATION_TEXT = [
  "I have no conflict of interest with the client organization and its representatives.",
  "I have had no commercial or other relevant relations with the client organization during the past two years.",
  "I will not have such relations for the next two years.",
  "I am not acting as a consultant to this organization in any management system area.",
  "I understand my obligation to maintain the confidentiality of all information obtained during and after the audit.",
]

function AuditorDeclarationsView({
  auditSetId,
  currentAuditorId,
}: {
  auditSetId: string
  currentAuditorId: string | null
}) {
  const [declarations, setDeclarations] = useState<{
    id: string; stage_type: string; member_name: string; member_role: string
    auditor_ref_id: string | null; is_signed: boolean; signed_at: string | null
  }[]>([])
  const [loading, setLoading]   = useState(true)
  const [otpState, setOtpState] = useState<Record<string, 'idle' | 'otp_sent' | 'done'>>({})
  const [otpValues, setOtpValues] = useState<Record<string, string>>({})
  const [messages, setMessages]   = useState<Record<string, string>>({})
  const [busy, setBusy]           = useState<Record<string, boolean>>({})
  const [confirmed, setConfirmed] = useState<Record<string, boolean>>({})

  const STAGE_LABELS: Record<string, string> = {
    stage_1: 'Stage 1', stage_2: 'Stage 2',
    surveillance: 'Surveillance', recertification: 'Recertification',
  }
  const ROLE_COLOR: Record<string, string> = {
    'Lead Auditor':     'bg-purple-100 text-purple-700',
    'Team Auditor':     'bg-blue-100 text-blue-700',
    'Technical Expert': 'bg-teal-100 text-teal-700',
    'Observer':         'bg-gray-100 text-gray-500',
  }

  useEffect(() => {
    api.get(`/audit-sets/${auditSetId}/declarations`)
      .then(r => setDeclarations(r.data as typeof declarations))
      .finally(() => setLoading(false))
  }, [auditSetId])

  // My own unsigned declarations — matched by auditor_ref_id OR admin bypass
  const myPending = declarations.filter(
    d => !d.is_signed && (
      currentAuditorId
        ? d.auditor_ref_id === currentAuditorId
        : true   // admin sees all unsigned (for testing)
    )
  )
  const otherDeclarations = declarations.filter(
    d => !(myPending.some(mp => mp.id === d.id))
  )

  async function requestOtp(id: string) {
    setBusy(b => ({ ...b, [id]: true }))
    setMessages(m => ({ ...m, [id]: '' }))
    try {
      await api.post(`/audit-sets/${auditSetId}/declarations/${id}/sign/request-otp`)
      setOtpState(s => ({ ...s, [id]: 'otp_sent' }))
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setMessages(m => ({ ...m, [id]: detail || 'Failed to send code' }))
    } finally {
      setBusy(b => ({ ...b, [id]: false }))
    }
  }

  async function verifyOtp(id: string) {
    setBusy(b => ({ ...b, [id]: true }))
    setMessages(m => ({ ...m, [id]: '' }))
    try {
      await api.post(`/audit-sets/${auditSetId}/declarations/${id}/sign/verify?otp=${otpValues[id] ?? ''}`)
      setOtpState(s => ({ ...s, [id]: 'done' }))
      setDeclarations(prev => prev.map(d =>
        d.id === id ? { ...d, is_signed: true, signed_at: new Date().toISOString() } : d,
      ))
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setMessages(m => ({ ...m, [id]: detail || 'Invalid code' }))
    } finally {
      setBusy(b => ({ ...b, [id]: false }))
    }
  }

  if (loading) return <p className="text-sm text-gray-400">Loading…</p>

  return (
    <div className="space-y-5">
      {declarations.length === 0 && (
        <p className="py-8 text-center text-sm text-gray-400">
          No declaration forms yet. The CB will create them before the audit.
        </p>
      )}

      {/* My pending declarations — with full declaration text */}
      {myPending.map(d => {
        const state = otpState[d.id] || 'idle'
        return (
          <div key={d.id} className="rounded-xl border border-amber-200 bg-white p-5">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <p className="font-semibold text-gray-800">Impartiality Declaration</p>
                <p className="mt-0.5 text-xs text-gray-400">
                  {STAGE_LABELS[d.stage_type] ?? d.stage_type} ·{' '}
                  <span className={`rounded-full px-1.5 py-0.5 text-xs ${ROLE_COLOR[d.member_role] ?? ''}`}>
                    {d.member_role}
                  </span>
                </p>
              </div>
              <span className="rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-semibold text-amber-700">
                Signature Required
              </span>
            </div>

            {/* Declaration text */}
            <div className="mb-4 rounded-lg bg-gray-50 p-4">
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500">
                I, {d.member_name}, hereby declare that:
              </p>
              <ul className="space-y-1.5">
                {DECLARATION_TEXT.map((line, i) => (
                  <li key={i} className="flex gap-2 text-sm text-gray-700">
                    <span className="mt-0.5 shrink-0 text-[#1A4731]">✓</span>
                    <span>{line}</span>
                  </li>
                ))}
              </ul>
            </div>

            {/* Confirm checkbox */}
            {state === 'idle' && (
              <div className="mb-3">
                <label className="flex cursor-pointer items-start gap-2 text-sm text-gray-700">
                  <input
                    type="checkbox"
                    checked={confirmed[d.id] || false}
                    onChange={e => setConfirmed(c => ({ ...c, [d.id]: e.target.checked }))}
                    className="mt-0.5 accent-[#1A4731]"
                  />
                  I confirm the above declaration is true and accurate.
                </label>
              </div>
            )}

            {state === 'idle' && (
              <button
                type="button"
                onClick={() => requestOtp(d.id)}
                disabled={!confirmed[d.id] || busy[d.id]}
                className="rounded-lg bg-[#1A4731] px-5 py-2.5 text-sm font-medium text-white disabled:opacity-40 hover:bg-[#143828]"
              >
                {busy[d.id] ? 'Sending code…' : 'Sign Declaration'}
              </button>
            )}

            {state === 'otp_sent' && (
              <div className="flex items-center gap-3">
                <input
                  className="w-36 rounded-lg border px-3 py-2 text-center font-mono text-lg tracking-widest focus:outline-none focus:ring-2 focus:ring-[#1A4731]/30"
                  placeholder="000000" maxLength={6}
                  value={otpValues[d.id] ?? ''}
                  onChange={e => setOtpValues(v => ({
                    ...v, [d.id]: e.target.value.replace(/\D/g, ''),
                  }))}
                />
                <button
                  type="button"
                  onClick={() => verifyOtp(d.id)}
                  disabled={(otpValues[d.id] ?? '').length !== 6 || busy[d.id]}
                  className="rounded-lg bg-[#1A4731] px-4 py-2 text-sm text-white disabled:opacity-40"
                >
                  {busy[d.id] ? '…' : 'Confirm Signature'}
                </button>
                <button type="button" onClick={() => requestOtp(d.id)} className="text-xs text-gray-400 underline">
                  Resend
                </button>
              </div>
            )}

            {state === 'done' && (
              <p className="text-sm font-medium text-green-600">Declaration signed ✓</p>
            )}
            {messages[d.id] && (
              <p className="mt-1 text-xs text-red-500">{messages[d.id]}</p>
            )}
          </div>
        )
      })}

      {/* All other declarations (team status) */}
      {otherDeclarations.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
            Team Status
          </p>
          <div className="rounded-xl border bg-white divide-y divide-gray-50">
            {otherDeclarations.map(d => (
              <div key={d.id} className="flex items-center justify-between px-4 py-3">
                <div className="flex items-center gap-2">
                  <p className="text-sm font-medium text-gray-800">{d.member_name}</p>
                  <span className={`rounded-full px-1.5 py-0.5 text-xs ${ROLE_COLOR[d.member_role] ?? 'bg-gray-100 text-gray-500'}`}>
                    {d.member_role}
                  </span>
                </div>
                {d.is_signed ? (
                  <span className="rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-semibold text-green-700">
                    ✓ Signed
                  </span>
                ) : (
                  <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-700">
                    Pending
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
```

**Step C — The `AuditorDeclarationsView` needs `currentAuditorId`. Thread it through from the page component.**

The page's `data` object (returned from `/auditor/my-assignments/{id}`) doesn't currently include the auditor's own `auditor_id`. The easiest way to get it is to read it from the current user's profile. Add a separate fetch for the current user:

```tsx
// At the top of AuditorAuditDetail, alongside the data state:
const [myAuditorId, setMyAuditorId] = useState<string | null>(null)

// In useEffect (alongside the existing api.get):
api.get<{ auditor_id: string | null }>('/me')
  .then(r => setMyAuditorId(r.data.auditor_id ?? null))
  .catch(() => {})
```

If `/me` doesn't exist yet, use `null` — the admin bypass in the backend handles it.
If `/me` already exists and returns the user's profile, use `auditor_id` from there.

**Step D — Add tab button and panel:**

Add `'declarations'` to the tabs array:
```tsx
{(['overview', 'messages', 'upload', 'attendees', 'nc_forms', 'declarations'] as const).map((t) => (
  <button ...>
    {t === 'upload' ? 'Upload Documents'
     : t === 'attendees' ? 'Attendees'
     : t === 'nc_forms' ? 'NC Forms'
     : t === 'declarations' ? 'Declarations'
     : t}
  </button>
))}
```

Add panel after the `{tab === 'nc_forms' && ...}` block:
```tsx
{tab === 'declarations' && (
  <AuditorDeclarationsView auditSetId={id} currentAuditorId={myAuditorId} />
)}
```

---

### 7. `frontend/src/app/(app)/clients/[id]/page.tsx` — wire DeclarationManagementSection

Add import:
```tsx
import { DeclarationManagementSection } from '@/components/ui/DeclarationManagementSection'
```

Add **after** `<NCFormManagementSection …/>`:
```tsx
<DeclarationManagementSection
  auditSetId={id}
  workflowStatus={data.workflow_status ?? null}
/>
```

---

## Verification

1. `python3 -m py_compile backend/audit_set/declaration_router.py backend/audit_set/db_models.py backend/email_service.py`
2. `cd frontend && npx tsc --noEmit`
3. CB creates declarations:
   a. CB → `/clients/{id}` → "Impartiality Declarations (FR.224)" appears (workflow ≥ in_planning)
   b. `+ Create Declarations` → Stage 1 → "Create & Notify Auditors" → rows appear for each team member with role-colored badges
   c. Each team member's linked email account receives an impartiality request email
   d. Click again → "0 created, N already existed"
4. Auditor signs:
   a. Auditor logs in → `/auditor/audit/{id}` → "Declarations" tab → own pending declaration shown with full declaration text + checkbox
   b. Check confirmation checkbox → "Sign Declaration" button enables → click → OTP sent
   c. Enter 6-digit code → "Confirm Signature" → green "Declaration signed ✓"
   d. CB portal → declaration row shows "Signed [date]" — all signed shows "All Signed ✓" badge
5. Team status section:
   a. Other team members' declarations appear in "Team Status" section (signed/pending)
   b. Auditor cannot click "Sign" on another team member's declaration (button not shown)
6. Guard: attempting `POST /declarations/{did}/sign/request-otp` on a declaration belonging to a different auditor → 403 "This declaration is not assigned to you"
7. Empty state: Declarations tab with no declarations → "No declaration forms yet. The CB will create them…"
8. Commit and push to main

## Constraints
DO NOT modify any other file beyond what is listed.

New files:
- `backend/audit_set/declaration_router.py`
- `frontend/src/components/ui/DeclarationManagementSection.tsx`

Modified files:
- `backend/audit_set/db_models.py` — add `AuditSetImpartialityDeclaration`
- `backend/email_service.py` — add `send_impartiality_declaration_request`
- `backend/main.py` — register declaration_router
- `frontend/src/app/(auditor)/auditor/audit/[id]/page.tsx` — add AuditorDeclarationsView + tab
- `frontend/src/app/(app)/clients/[id]/page.tsx` — wire DeclarationManagementSection
