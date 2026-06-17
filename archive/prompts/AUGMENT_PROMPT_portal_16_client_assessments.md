# AUGMENT PROMPT — Portal 16: FR.223 Audit Plan Acknowledgment + FR.211 Auditor Assessments

## Context
Certiva — FastAPI backend + Next.js 14 App Router frontend.
**DO NOT BREAK THE EXISTING PORTAL. All changes are additive.**

Two client-signing features:

**FR.223 — Audit Plan:** Client acknowledges the audit plan released by CB.
Already fully supported by the existing shared-document + OTP flow.
Only change needed: add "audit_plan" to the document type dropdown in the CB portal.
No backend changes — `documents_router.release_document` already releases non-quotation/agreement
documents directly to "released" status, skipping the CB signing queue.

**FR.211 — Auditor Assessment:** After each audit stage, the client evaluates each auditor
(Lead Auditor + team auditors) with a 1–5 rating and free-text comments, then signs.
This is a structured portal form — not a document upload.

**FR.230 — NC Form (multi-party: Lead Auditor + client):** Deferred to Prompt 17.

---

## What this builds

**Backend:**
1. `AuditSetAuditorAssessment` table in `db_models.py`
2. New `assessment_router.py` — CB creation endpoints + client signing endpoints
3. Register in `main.py`

**Frontend:**
4. `SharedDocumentsSection.tsx` — add "audit_plan" and "nc_form" to DOC_TYPES
5. New `AssessmentManagementSection.tsx` on CB portal `/clients/[id]`
6. New page `(client)/client/assessments/page.tsx`
7. Add "Assessments" nav link to `(client)/layout.tsx`
8. Wire `AssessmentManagementSection` into `(app)/clients/[id]/page.tsx`

---

## Backend

### 1. `backend/audit_set/db_models.py` — add `AuditSetAuditorAssessment`

Add after `AuditSetCommitteeMember` (or at the end of the file):

```python
# ---------------------------------------------------------------------------
# Table 9 — audit_set_auditor_assessments
# FR.211 — Client evaluates each auditor after an audit stage (ISO 17021-1).
# ---------------------------------------------------------------------------

class AuditSetAuditorAssessment(Base):
    __tablename__ = "audit_set_auditor_assessments"

    id              = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    audit_set_id    = Column(String, ForeignKey("audit_sets.id", ondelete="CASCADE"), nullable=False)
    stage_type      = Column(String, nullable=False)  # "stage_1" | "stage_2" | "surveillance"
    stage_order     = Column(Integer, nullable=True)  # disambiguates multiple surveillance stages
    auditor_name    = Column(String, nullable=False)  # denormalized
    auditor_role    = Column(String, nullable=True)   # "Lead Auditor" | "Team Auditor"
    auditor_ref_id  = Column(String, nullable=True)   # soft FK → auditors.auditors.id
    # Client evaluation (filled before signing)
    rating          = Column(Integer, nullable=True)  # 1–5
    comments        = Column(Text, nullable=True)
    # Signature
    signed_by       = Column(String, nullable=True)   # PlatformUser.id
    signed_at       = Column(DateTime, nullable=True)
    signed_ip       = Column(String, nullable=True)
    otp_hash        = Column(String, nullable=True)
    otp_expires_at  = Column(DateTime, nullable=True)

    created_at      = Column(DateTime, default=datetime.utcnow, nullable=False)
```

No `_safe_add_column` needed — created by `Base.metadata.create_all` on boot.

---

### 2. New file `backend/audit_set/assessment_router.py`

```python
"""
BATUHAN — FR.211 Auditor Assessment (Prompt 16).

CB creates assessment records after a stage completes.
Client fills in rating + comments, then signs via OTP.

Endpoints:
  POST /audit-sets/{id}/assessments/create-for-stage?stage_type=…
  GET  /audit-sets/{id}/assessments          (CB view — all assessments + status)
  GET  /client/my-audit-set/assessments      (client view — own audit set)
  PATCH /client/my-audit-set/assessments/{aid}/draft  (save rating+comments before signing)
  POST  /client/my-audit-set/assessments/{aid}/sign/request-otp
  POST  /client/my-audit-set/assessments/{aid}/sign/verify
"""
from __future__ import annotations
import hashlib
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from audit_set.db_models import (
    AuditSet, AuditSetAuditorAssessment, AuditSetStage, get_db,
)
from auth.db_models import PlatformUser, get_db as get_auth_db
from auth.dependencies import get_current_user
from email_service import send_otp_code

router = APIRouter(tags=["assessments"])

CB_ROLES   = {"admin", "planner", "officer", "executive"}
OTP_EXPIRY = 10  # minutes


def _hash(val: str) -> str:
    return hashlib.sha256(val.encode()).hexdigest()


def _assessment_dict(a: AuditSetAuditorAssessment) -> dict:
    return {
        "id":            a.id,
        "audit_set_id":  a.audit_set_id,
        "stage_type":    a.stage_type,
        "stage_order":   a.stage_order,
        "auditor_name":  a.auditor_name,
        "auditor_role":  a.auditor_role,
        "rating":        a.rating,
        "comments":      a.comments,
        "is_signed":     a.signed_at is not None,
        "signed_at":     a.signed_at.isoformat() if a.signed_at else None,
        "created_at":    a.created_at.isoformat() if a.created_at else None,
    }


# ── CB: create assessments for a stage ───────────────────────────────────────

@router.post("/audit-sets/{audit_set_id}/assessments/create-for-stage")
def create_assessments_for_stage(
    audit_set_id: str,
    stage_type:   str,                        # query param
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """
    Auto-populate FR.211 assessment records for all auditors on the given stage.
    Idempotent: skips records that already exist for the same auditor + stage.
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
        raise HTTPException(404, f"No stage of type '{stage_type}' found for this audit set")

    # Collect unique auditors from this stage
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
    # Technical experts also receive assessments
    for te in (stage.technical_experts or []):
        if isinstance(te, dict) and te.get("name"):
            entries.append({
                "name":   te["name"],
                "role":   "Technical Expert",
                "ref_id": te.get("id"),
            })

    if not entries:
        raise HTTPException(
            422, "No auditors assigned to this stage — assign team members before creating assessments"
        )

    # Existing records for deduplication
    existing = {
        (a.auditor_name, a.stage_type)
        for a in db.query(AuditSetAuditorAssessment)
                   .filter_by(audit_set_id=audit_set_id, stage_type=stage_type)
                   .all()
    }

    created = 0
    for entry in entries:
        key = (entry["name"], stage_type)
        if key in existing:
            continue
        db.add(AuditSetAuditorAssessment(
            audit_set_id=audit_set_id,
            stage_type=stage_type,
            stage_order=stage.stage_order,
            auditor_name=entry["name"],
            auditor_role=entry["role"],
            auditor_ref_id=entry["ref_id"],
        ))
        created += 1

    db.commit()
    return {"created": created, "skipped": len(entries) - created}


@router.get("/audit-sets/{audit_set_id}/assessments")
def get_cb_assessments(
    audit_set_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """CB view — list all assessments for this audit set with signing status."""
    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "Not authorized")

    rows = (
        db.query(AuditSetAuditorAssessment)
        .filter_by(audit_set_id=audit_set_id)
        .order_by(AuditSetAuditorAssessment.stage_type, AuditSetAuditorAssessment.created_at)
        .all()
    )
    return [_assessment_dict(r) for r in rows]


# ── Client: view, fill, sign assessments ─────────────────────────────────────

def _get_client_assessment(
    aid: str,
    current_user: PlatformUser,
    db: Session,
) -> AuditSetAuditorAssessment:
    if current_user.role != "client" or not current_user.audit_set_id:
        raise HTTPException(403, "Client access only")
    a = db.query(AuditSetAuditorAssessment).filter_by(
        id=aid, audit_set_id=current_user.audit_set_id
    ).first()
    if not a:
        raise HTTPException(404, "Assessment not found")
    return a


@router.get("/client/my-audit-set/assessments")
def get_client_assessments(
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role != "client" or not current_user.audit_set_id:
        raise HTTPException(403, "Client access only")

    rows = (
        db.query(AuditSetAuditorAssessment)
        .filter_by(audit_set_id=current_user.audit_set_id)
        .order_by(AuditSetAuditorAssessment.stage_type, AuditSetAuditorAssessment.created_at)
        .all()
    )
    return [_assessment_dict(r) for r in rows]


class DraftSchema(BaseModel):
    rating:   int          # 1–5
    comments: str | None = None


@router.patch("/client/my-audit-set/assessments/{aid}/draft")
def save_assessment_draft(
    aid: str,
    body: DraftSchema,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """Save rating + comments before signing. Can be called multiple times."""
    a = _get_client_assessment(aid, current_user, db)
    if a.signed_at:
        raise HTTPException(400, "Assessment already signed — cannot edit")
    if not (1 <= body.rating <= 5):
        raise HTTPException(400, "Rating must be 1–5")
    a.rating   = body.rating
    a.comments = (body.comments or "").strip() or None
    db.commit()
    return _assessment_dict(a)


@router.post("/client/my-audit-set/assessments/{aid}/sign/request-otp")
def request_assessment_otp(
    aid: str,
    db: Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    a = _get_client_assessment(aid, current_user, db)
    if a.signed_at:
        raise HTTPException(400, "Already signed")
    if not a.rating:
        raise HTTPException(400, "Please submit your rating before signing")

    otp = f"{secrets.randbelow(900000) + 100000}"
    a.otp_hash       = _hash(otp)
    a.otp_expires_at = datetime.utcnow() + timedelta(minutes=OTP_EXPIRY)
    db.commit()

    try:
        send_otp_code(
            to=current_user.email,
            full_name=current_user.full_name,
            otp=otp,
            document_label=f"Auditor Assessment — {a.auditor_name}",
        )
    except Exception:
        pass

    return {"message": f"Code sent to {current_user.email}. Valid for {OTP_EXPIRY} minutes."}


@router.post("/client/my-audit-set/assessments/{aid}/sign/verify")
def verify_assessment_signature(
    aid: str,
    otp: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    a = _get_client_assessment(aid, current_user, db)
    if a.signed_at:
        raise HTTPException(400, "Already signed")
    if not a.rating:
        raise HTTPException(400, "Rating must be set before signing")
    if not a.otp_hash or not a.otp_expires_at:
        raise HTTPException(400, "No pending OTP. Request one first.")
    if datetime.utcnow() > a.otp_expires_at:
        raise HTTPException(400, "OTP expired. Please request a new one.")
    if _hash(otp.strip()) != a.otp_hash:
        raise HTTPException(400, "Invalid code.")

    a.signed_by      = current_user.id
    a.signed_at      = datetime.utcnow()
    a.signed_ip      = request.client.host if request.client else None
    a.otp_hash       = None
    a.otp_expires_at = None
    db.commit()

    return {"signed": True, "signed_at": a.signed_at.isoformat()}
```

---

### 3. `backend/main.py` — register router

```python
from audit_set.assessment_router import router as assessment_router
app.include_router(assessment_router)
```

Place alongside the other audit_set routers (after committee_router, before documents_router).

---

## Frontend

### 4. `frontend/src/components/ui/SharedDocumentsSection.tsx` — extend DOC_TYPES

Find the `DOC_TYPES` array and replace it with:

```tsx
const DOC_TYPES = [
  { value: 'quotation',   label: 'Quotation (FR.220)' },
  { value: 'agreement',   label: 'Agreement (FR.221)' },
  { value: 'audit_plan',  label: 'Audit Plan (FR.223)' },
  { value: 'nc_form',     label: 'NC Notification (FR.230)' },
  { value: 'certificate', label: 'Certificate' },
]
```

No other changes to this file.

---

### 5. New file `frontend/src/components/ui/AssessmentManagementSection.tsx`

CB portal view — shows assessment records, lets CB planner trigger creation per stage.

```tsx
'use client'

import { useEffect, useState } from 'react'
import api from '@/lib/api'

interface Assessment {
  id:           string
  stage_type:   string
  stage_order:  number | null
  auditor_name: string
  auditor_role: string | null
  rating:       number | null
  is_signed:    boolean
  signed_at:    string | null
}

const STAGE_TYPES = [
  { value: 'stage_1',        label: 'Stage 1' },
  { value: 'stage_2',        label: 'Stage 2' },
  { value: 'surveillance',   label: 'Surveillance' },
  { value: 'recertification',label: 'Recertification' },
]

function fmtDate(iso: string | null) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

const STARS = [1, 2, 3, 4, 5]

export function AssessmentManagementSection({
  auditSetId,
  workflowStatus,
}: {
  auditSetId: string
  workflowStatus: string | null
}) {
  const [assessments, setAssessments] = useState<Assessment[]>([])
  const [loading, setLoading]         = useState(true)
  const [creating, setCreating]       = useState(false)
  const [stageToCreate, setStageToCreate] = useState('stage_1')
  const [createMsg, setCreateMsg]     = useState('')
  const [busy, setBusy]               = useState(false)

  // Only show from audit_in_progress onwards
  const relevantStatuses = new Set([
    'audit_scheduled', 'audit_in_progress', 'under_review', 'certified',
  ])
  if (!workflowStatus || !relevantStatuses.has(workflowStatus)) return null

  async function load() {
    try {
      const r = await api.get<Assessment[]>(`/audit-sets/${auditSetId}/assessments`)
      setAssessments(r.data)
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
        `/audit-sets/${auditSetId}/assessments/create-for-stage?stage_type=${stageToCreate}`,
      )
      const { created, skipped } = r.data
      setCreateMsg(`Created ${created} new assessment form(s)${skipped ? `, ${skipped} already existed` : ''}.`)
      setCreating(false)
      await load()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setCreateMsg(detail || 'Failed to create assessments')
    } finally {
      setBusy(false)
    }
  }

  // Group by stage_type
  const grouped = assessments.reduce<Record<string, Assessment[]>>((acc, a) => {
    const key = a.stage_type + (a.stage_order ? `_${a.stage_order}` : '')
    acc[key] = acc[key] || []
    acc[key].push(a)
    return acc
  }, {})

  return (
    <div className="mt-6">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-700">
          Auditor Assessments (FR.211)
        </h2>
        <button
          type="button"
          onClick={() => { setCreating(!creating); setCreateMsg('') }}
          className="rounded-lg border border-[#1A4731] px-3 py-1.5 text-xs font-medium text-[#1A4731] hover:bg-green-50"
        >
          {creating ? 'Cancel' : '+ Create Assessments'}
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
            {busy ? 'Creating…' : 'Create Forms'}
          </button>
          {createMsg && <p className="text-xs text-gray-600">{createMsg}</p>}
        </div>
      )}

      {/* Assessment list */}
      {loading ? (
        <p className="text-xs text-gray-400">Loading…</p>
      ) : assessments.length === 0 ? (
        <div className="rounded-xl border bg-white px-4 py-6 text-center text-xs text-gray-400">
          No assessments yet. Click "+ Create Assessments" after an audit stage completes.
        </div>
      ) : (
        <div className="space-y-3">
          {Object.entries(grouped).map(([key, list]) => {
            const stageLabel = STAGE_TYPES.find(s => list[0].stage_type.startsWith(s.value))?.label
              ?? list[0].stage_type
            const allSigned = list.every(a => a.is_signed)
            return (
              <div key={key} className="rounded-xl border bg-white">
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
                  {list.map(a => (
                    <div key={a.id} className="flex items-center justify-between px-4 py-3">
                      <div>
                        <p className="text-sm font-medium text-gray-800">{a.auditor_name}</p>
                        <p className="mt-0.5 text-xs text-gray-400">{a.auditor_role}</p>
                      </div>
                      <div className="flex items-center gap-3">
                        {a.is_signed ? (
                          <div className="text-right">
                            <div className="flex gap-0.5">
                              {STARS.map(n => (
                                <span key={n} className={`text-sm ${(a.rating ?? 0) >= n ? 'text-amber-400' : 'text-gray-200'}`}>★</span>
                              ))}
                            </div>
                            <p className="text-xs text-gray-400">Signed {fmtDate(a.signed_at)}</p>
                          </div>
                        ) : (
                          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-700">
                            Awaiting Client
                          </span>
                        )}
                      </div>
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

### 6. New file `frontend/src/app/(client)/client/assessments/page.tsx`

```tsx
'use client'

import { useEffect, useState } from 'react'
import api from '@/lib/api'

interface Assessment {
  id:           string
  stage_type:   string
  stage_order:  number | null
  auditor_name: string
  auditor_role: string | null
  rating:       number | null
  comments:     string | null
  is_signed:    boolean
  signed_at:    string | null
}

const STAGE_LABELS: Record<string, string> = {
  stage_1:        'Stage 1',
  stage_2:        'Stage 2',
  surveillance:   'Surveillance',
  recertification:'Recertification',
}

function fmtDate(iso: string | null) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })
}

function StarPicker({ value, onChange }: { value: number; onChange: (n: number) => void }) {
  const [hovered, setHovered] = useState(0)
  return (
    <div className="flex gap-1">
      {[1, 2, 3, 4, 5].map(n => (
        <button
          key={n}
          type="button"
          onClick={() => onChange(n)}
          onMouseEnter={() => setHovered(n)}
          onMouseLeave={() => setHovered(0)}
          className="text-2xl leading-none transition-transform hover:scale-110 focus:outline-none"
          aria-label={`Rate ${n} star${n !== 1 ? 's' : ''}`}
        >
          <span className={(hovered || value) >= n ? 'text-amber-400' : 'text-gray-200'}>★</span>
        </button>
      ))}
    </div>
  )
}

function AssessmentCard({ assessment, onSigned }: { assessment: Assessment; onSigned: () => void }) {
  const [rating, setRating]     = useState(assessment.rating ?? 0)
  const [comments, setComments] = useState(assessment.comments ?? '')
  const [step, setStep]         = useState<'form' | 'otp' | 'done'>('form')
  const [otp, setOtp]           = useState('')
  const [error, setError]       = useState('')
  const [busy, setBusy]         = useState(false)

  if (assessment.is_signed) {
    return (
      <div className="rounded-xl border border-green-200 bg-green-50 p-5">
        <div className="flex items-start justify-between">
          <div>
            <p className="font-semibold text-gray-800">{assessment.auditor_name}</p>
            <p className="mt-0.5 text-xs text-gray-500">{assessment.auditor_role}</p>
          </div>
          <span className="rounded-full bg-green-100 px-2.5 py-1 text-xs font-semibold text-green-700">
            ✓ Submitted {fmtDate(assessment.signed_at)}
          </span>
        </div>
        <div className="mt-3 flex gap-0.5">
          {[1, 2, 3, 4, 5].map(n => (
            <span key={n} className={`text-xl ${(assessment.rating ?? 0) >= n ? 'text-amber-400' : 'text-gray-200'}`}>★</span>
          ))}
        </div>
        {assessment.comments && (
          <p className="mt-2 text-sm text-gray-600 italic">"{assessment.comments}"</p>
        )}
      </div>
    )
  }

  async function saveDraft() {
    if (!rating) return
    setBusy(true)
    setError('')
    try {
      await api.patch(`/client/my-audit-set/assessments/${assessment.id}/draft`, {
        rating,
        comments: comments || null,
      })
    } catch {
      // ignore — saving draft silently
    } finally {
      setBusy(false)
    }
  }

  async function requestOtp() {
    if (!rating) { setError('Please select a rating before signing'); return }
    setBusy(true)
    setError('')
    try {
      // Save draft first, then request OTP
      await api.patch(`/client/my-audit-set/assessments/${assessment.id}/draft`, {
        rating,
        comments: comments || null,
      })
      await api.post(`/client/my-audit-set/assessments/${assessment.id}/sign/request-otp`)
      setStep('otp')
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'Failed to send code')
    } finally {
      setBusy(false)
    }
  }

  async function verifyOtp() {
    setBusy(true)
    setError('')
    try {
      await api.post(
        `/client/my-audit-set/assessments/${assessment.id}/sign/verify?otp=${otp}`,
      )
      setStep('done')
      onSigned()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'Invalid code')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="rounded-xl border bg-white p-5">
      <div className="mb-4">
        <p className="font-semibold text-gray-800">{assessment.auditor_name}</p>
        <p className="mt-0.5 text-xs text-gray-400">
          {assessment.auditor_role} · {STAGE_LABELS[assessment.stage_type] ?? assessment.stage_type}
        </p>
      </div>

      {step === 'form' && (
        <div className="space-y-3">
          <div>
            <p className="mb-1.5 text-sm font-medium text-gray-700">Overall Rating</p>
            <StarPicker value={rating} onChange={setRating} />
            {rating > 0 && (
              <p className="mt-1 text-xs text-gray-400">
                {['', 'Poor', 'Fair', 'Good', 'Very Good', 'Excellent'][rating]}
              </p>
            )}
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              Comments <span className="font-normal text-gray-400">(optional)</span>
            </label>
            <textarea
              rows={3}
              value={comments}
              onChange={e => setComments(e.target.value)}
              onBlur={saveDraft}
              placeholder="Your feedback about this auditor's conduct and professionalism…"
              className="w-full rounded-lg border px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-[#1A4731]/30"
            />
          </div>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={requestOtp}
              disabled={!rating || busy}
              className="rounded-lg bg-[#1A4731] px-5 py-2.5 text-sm font-medium text-white disabled:opacity-40 hover:bg-[#143828]"
            >
              {busy ? 'Please wait…' : 'Submit & Sign'}
            </button>
            <p className="text-xs text-gray-400">
              You will receive a 6-digit code by email.
            </p>
          </div>
          {error && <p className="text-xs text-red-500">{error}</p>}
        </div>
      )}

      {step === 'otp' && (
        <div className="space-y-3">
          <p className="text-sm text-gray-600">
            A 6-digit verification code has been sent to your email:
          </p>
          <input
            className="w-40 rounded-lg border px-3 py-2 text-center font-mono text-xl tracking-widest focus:outline-none focus:ring-2 focus:ring-[#1A4731]/30"
            placeholder="000000"
            maxLength={6}
            value={otp}
            onChange={e => setOtp(e.target.value.replace(/\D/g, ''))}
          />
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={verifyOtp}
              disabled={otp.length !== 6 || busy}
              className="rounded-lg bg-[#1A4731] px-5 py-2 text-sm font-medium text-white disabled:opacity-40"
            >
              {busy ? '…' : 'Confirm Signature'}
            </button>
            <button type="button" onClick={() => setStep('form')} className="text-sm text-gray-400">
              Back
            </button>
            <button
              type="button"
              onClick={requestOtp}
              className="text-xs text-gray-400 underline"
            >
              Resend code
            </button>
          </div>
          {error && <p className="text-xs text-red-500">{error}</p>}
        </div>
      )}

      {step === 'done' && (
        <p className="text-sm font-medium text-green-600">Assessment submitted and signed ✓</p>
      )}
    </div>
  )
}

export default function ClientAssessmentsPage() {
  const [assessments, setAssessments] = useState<Assessment[]>([])
  const [loading, setLoading] = useState(true)

  async function load() {
    try {
      const r = await api.get<Assessment[]>('/client/my-audit-set/assessments')
      setAssessments(r.data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  if (loading) return <div className="p-8 text-sm text-gray-400">Loading assessments…</div>

  // Group by stage
  const grouped = assessments.reduce<Record<string, Assessment[]>>((acc, a) => {
    acc[a.stage_type] = acc[a.stage_type] || []
    acc[a.stage_type].push(a)
    return acc
  }, {})

  return (
    <div className="mx-auto max-w-2xl p-6">
      <div className="mb-6">
        <h1 className="text-xl font-bold text-gray-900">Auditor Assessments</h1>
        <p className="mt-1 text-sm text-gray-400">
          Please rate each auditor who conducted your audit. Your feedback helps IFC Global
          maintain quality and is required for ISO 17021-1 compliance.
        </p>
      </div>

      {assessments.length === 0 ? (
        <div className="py-16 text-center text-sm text-gray-400">
          No assessments available yet. These will appear after each audit stage is complete.
        </div>
      ) : (
        <div className="space-y-6">
          {Object.entries(grouped).map(([stageType, list]) => (
            <div key={stageType}>
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500">
                {STAGE_LABELS[stageType] ?? stageType}
              </h2>
              <div className="space-y-3">
                {list.map(a => (
                  <AssessmentCard key={a.id} assessment={a} onSigned={load} />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
```

---

### 7. `frontend/src/app/(client)/layout.tsx` — add "Assessments" nav link

Find the `NAV` array and add the assessments entry:

```tsx
const NAV = [
  { href: '/client/overview',     label: 'Overview'     },
  { href: '/client/documents',    label: 'Documents'    },
  { href: '/client/assessments',  label: 'Assessments'  },
  { href: '/client/messages',     label: 'Messages'     },
]
```

---

### 8. `frontend/src/app/(app)/clients/[id]/page.tsx` — wire AssessmentManagementSection

Add import:
```tsx
import { AssessmentManagementSection } from '@/components/ui/AssessmentManagementSection'
```

Add **after** `<MeetingAttendeesSection …/>`:
```tsx
<AssessmentManagementSection
  auditSetId={id}
  workflowStatus={data.workflow_status ?? null}
/>
```

---

## Verification

1. `python3 -m py_compile backend/audit_set/assessment_router.py backend/audit_set/db_models.py`
2. `cd frontend && npx tsc --noEmit`
3. Manual test — FR.223 audit plan:
   a. CB portal `/clients/{id}` → SharedDocuments → "+ Release Document"
   b. Document type dropdown now shows "Audit Plan (FR.223)"
   c. Upload a file with type audit_plan → document goes directly to "released" (no CB signing step)
   d. Client logs in → Documents page → sees "Audit Plan (FR.223)" with "Sign Document" button → OTP signing works
4. Manual test — FR.211 assessment creation:
   a. CB portal `/clients/{id}` → "Auditor Assessments (FR.211)" section appears (workflow ≥ audit_scheduled)
   b. Click "+ Create Assessments" → select Stage 1 → "Create Forms" → rows appear for lead auditor + team members
   c. Click again for same stage → skipped message ("0 created, N already existed")
5. Manual test — client assessment signing:
   a. Client logs in → "Assessments" nav link appears → page loads
   b. Assessment cards show for each auditor
   c. Select 4 stars + add comment → "Submit & Sign" → OTP sent → code entry → "Assessment submitted and signed ✓"
   d. Card transitions to signed state with star rating and timestamp
   e. CB portal assessment section shows filled stars + "Signed [date]"
6. Confirm: `/client/assessments` page with no assessments created shows "No assessments available yet"
7. Confirm: rating required before signing — trying to sign without rating returns 400
8. Commit and push to main

## Constraints
DO NOT modify any other endpoint, component, or page beyond what is listed.

New files:
- `backend/audit_set/assessment_router.py`
- `frontend/src/components/ui/AssessmentManagementSection.tsx`
- `frontend/src/app/(client)/client/assessments/page.tsx`

Modified files:
- `backend/audit_set/db_models.py` — add `AuditSetAuditorAssessment`
- `backend/main.py` — register assessment_router
- `frontend/src/components/ui/SharedDocumentsSection.tsx` — extend DOC_TYPES
- `frontend/src/app/(client)/layout.tsx` — add Assessments nav link
- `frontend/src/app/(app)/clients/[id]/page.tsx` — wire AssessmentManagementSection
