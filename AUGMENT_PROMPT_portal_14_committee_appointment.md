# AUGMENT PROMPT — Portal 14: Certification Committee Appointment

## Context
Certiva — FastAPI backend + Next.js 14 App Router frontend.
**DO NOT BREAK THE EXISTING PORTAL. All changes are additive.**

Role system: admin, planner, officer, executive, auditor, client.
CB_ROLES = {admin, planner, officer, executive}.
`AuditDocumentSignature` table (Prompt 12) and FR.218 slot seeding (Prompt 13) are live.
The FR.218 `cb_reviewer` slot is seeded with `signer_user_id = null` for FSMS/ISMS plans.
This prompt provides the formal appointment mechanism that fills it.

---

## What this builds

The certification committee is a CB-internal review body required by ISO 17021-1.
The **reviewer** member must:
1. Have EA code coverage matching the plan's scope
2. NOT be assigned to any stage's audit team for this plan

Prompt 14 builds:
- DB model: `AuditSetCommitteeMember` table
- Backend: 3 new endpoints in a new `committee_router.py`
- Backend: Harden `signatures_router.py` — `cb_reviewer` no longer self-assignable; must be
  appointed via the committee flow
- Frontend: `CommitteeSection.tsx` on the client detail page with inline user picker

**Not in scope for this prompt:**
FR.231/229/232 report review signing (those come with the auditor portal report upload).
The appointment mechanism alone unblocks FR.218 reviewer signing through the existing
OTP infrastructure.

---

## Backend

### 1. `backend/audit_set/db_models.py` — add `AuditSetCommitteeMember`

Add this class at the end of the file (after `AuditDocumentSignature`):

```python
# ---------------------------------------------------------------------------
# Table 7 — audit_set_committee_members
# Certification committee appointments for ISO 17021-1 review and decision.
# ---------------------------------------------------------------------------

class AuditSetCommitteeMember(Base):
    __tablename__ = "audit_set_committee_members"

    id                      = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    audit_set_id            = Column(String, ForeignKey("audit_sets.id", ondelete="CASCADE"), nullable=False)
    user_id                 = Column(String, nullable=False)   # PlatformUser.id
    user_name               = Column(String, nullable=False)   # denormalized for display
    user_email              = Column(String, nullable=False)   # denormalized for email
    role                    = Column(String, nullable=False)   # "reviewer" | "decision_maker"
    appointed_by            = Column(String, nullable=True)    # PlatformUser.id of the appointing user
    ea_codes_at_appointment = Column(JSON, nullable=True)      # snapshot of EA codes at time of appointment
    appointed_at            = Column(DateTime, default=datetime.utcnow, nullable=False)
```

No `_safe_add_column` needed — `Base.metadata.create_all()` creates it on boot.

Also add `AuditSetCommitteeMember` to all relevant `__init__` exports (same pattern as
existing models).

---

### 2. New file `backend/audit_set/committee_router.py`

```python
"""
BATUHAN — Certification Committee appointment (Prompt 14).

Endpoints under /audit-sets:
  GET  /audit-sets/{id}/committee
    → list appointed committee members for this audit set

  GET  /audit-sets/{id}/committee/eligible-users
    → list CB users eligible to serve as committee reviewer:
      - CB role (admin/planner/officer/executive)
      - EA code match (if user has an auditor profile)
      - NOT assigned to any stage's audit team

  POST /audit-sets/{id}/committee/appoint
    → appoint a user; if role=="reviewer", fills FR.218 cb_reviewer sig slot
      and updates get_internal_signatures to return them as assigned

  DELETE /audit-sets/{id}/committee/{member_id}
    → remove appointment (only if user has not yet signed anything)
"""
from __future__ import annotations
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from audit_set.db_models import (
    AuditSet, AuditSetCommitteeMember, AuditSetStage,
    AuditDocumentSignature, get_db,
)
from auth.db_models import PlatformUser, get_db as get_auth_db
from auth.dependencies import get_current_user

router = APIRouter(prefix="/audit-sets", tags=["committee"])

CB_ROLES = {"admin", "planner", "officer", "executive"}


def _collect_stage_auditor_ids(stages: list) -> set[str]:
    """Return the set of auditors.auditors.id values assigned to any stage."""
    ids: set[str] = set()
    for s in stages:
        if s.lead_auditor_id:
            ids.add(s.lead_auditor_id)
        for group in (s.auditors or [], s.technical_experts or [],
                      s.observers or [], s.ik_experts or [], s.evaluators or []):
            for p in group:
                if isinstance(p, dict) and p.get("id"):
                    ids.add(p["id"])
    return ids


@router.get("/{audit_set_id}/committee")
def get_committee(
    audit_set_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """Return current committee appointments for this audit set (CB only)."""
    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "Not authorized")

    members = (
        db.query(AuditSetCommitteeMember)
        .filter_by(audit_set_id=audit_set_id)
        .order_by(AuditSetCommitteeMember.appointed_at)
        .all()
    )
    # Enrich with signing status from FR.218 reviewer slot (if applicable)
    reviewer_sigs = {
        s.signer_user_id: s
        for s in db.query(AuditDocumentSignature).filter_by(
            audit_set_id=audit_set_id,
            signer_role_label="cb_reviewer",
        ).all()
    }
    return [
        {
            "id":                      m.id,
            "user_id":                 m.user_id,
            "user_name":               m.user_name,
            "user_email":              m.user_email,
            "role":                    m.role,
            "appointed_by":            m.appointed_by,
            "ea_codes_at_appointment": m.ea_codes_at_appointment,
            "appointed_at":            m.appointed_at.isoformat() if m.appointed_at else None,
            "has_signed_fr218":        (
                reviewer_sigs.get(m.user_id) is not None
                and reviewer_sigs[m.user_id].signed_at is not None
            ),
        }
        for m in members
    ]


@router.get("/{audit_set_id}/committee/eligible-users")
def get_eligible_users(
    audit_set_id: str,
    db: Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """
    Return CB users who can be appointed to the certification committee.
    Eligibility: CB role + not already appointed + not on any stage team.
    For reviewer role: EA codes must cover the plan's ea_code (when auditor profile exists).
    """
    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "Not authorized")

    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Audit set not found")

    # Auditor IDs already on any stage
    stages = db.query(AuditSetStage).filter_by(audit_set_id=audit_set_id).all()
    stage_auditor_ids = _collect_stage_auditor_ids(stages)

    # Already appointed users for this audit set
    already_appointed_user_ids = {
        m.user_id for m in
        db.query(AuditSetCommitteeMember).filter_by(audit_set_id=audit_set_id).all()
    }

    # All active CB-role users
    cb_users = (
        auth_db.query(PlatformUser)
        .filter(
            PlatformUser.role.in_(CB_ROLES),
            PlatformUser.is_active == True,  # noqa: E712
        )
        .all()
    )

    # Lazy-import Auditor to avoid circular deps
    from auditors.models import Auditor as AuditorModel

    plan_ea_code = (audit_set.ea_code or "").strip()

    results = []
    for u in cb_users:
        if u.id in already_appointed_user_ids:
            continue  # already on this committee

        ea_codes: list[str] = []
        on_audit_team = False

        # If user has an auditor profile, check EA codes and team assignment
        if u.auditor_id:
            if u.auditor_id in stage_auditor_ids:
                on_audit_team = True
            auditor = db.query(AuditorModel).filter_by(id=u.auditor_id).first()
            if auditor:
                ea_codes = auditor.ea_codes or []

        if on_audit_team:
            continue  # excluded — conflict of interest

        # EA code match: true if plan has no ea_code OR auditor has it OR user has no auditor profile
        if ea_codes:
            ea_match = (not plan_ea_code) or (plan_ea_code in ea_codes)
        else:
            # No auditor profile — can still be appointed; admin marks them eligible manually
            ea_match = True  # shown but flagged below

        results.append({
            "user_id":              u.id,
            "full_name":            u.full_name,
            "email":                u.email,
            "role":                 u.role,
            "ea_codes":             ea_codes,
            "ea_match":             ea_match,
            "has_auditor_profile":  bool(u.auditor_id),
            "eligible_as_reviewer": ea_match,
        })

    # Sort: auditors with EA match first, then everyone else
    results.sort(key=lambda x: (not x["eligible_as_reviewer"], x["full_name"]))
    return results


class AppointRequest(BaseModel):
    user_id: str
    role: str  # "reviewer" | "decision_maker"


@router.post("/{audit_set_id}/committee/appoint")
def appoint_committee_member(
    audit_set_id: str,
    body: AppointRequest,
    db: Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """
    Appoint a CB user to the certification committee.
    If role is "reviewer":
      - Fills the FR.218 cb_reviewer AuditDocumentSignature slot (signer_user_id)
      - Does not create a new slot — the slot was seeded in Prompt 13 on in_planning transition
      - If no reviewer slot exists (non-FSMS/ISMS plan), the appointment is still recorded
    """
    if current_user.role not in {"admin", "planner"}:
        raise HTTPException(403, "Only admin or planner can appoint committee members")

    if body.role not in ("reviewer", "decision_maker"):
        raise HTTPException(400, "role must be 'reviewer' or 'decision_maker'")

    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Audit set not found")

    # Validate the user is a CB user and not already appointed
    user = auth_db.query(PlatformUser).filter_by(id=body.user_id).first()
    if not user or user.role not in CB_ROLES:
        raise HTTPException(400, "User not found or not a CB user")

    already = db.query(AuditSetCommitteeMember).filter_by(
        audit_set_id=audit_set_id, user_id=body.user_id
    ).first()
    if already:
        raise HTTPException(409, "User is already a committee member for this audit set")

    # Collect EA codes snapshot
    from auditors.models import Auditor as AuditorModel
    ea_codes_snapshot: list[str] = []
    if user.auditor_id:
        auditor = db.query(AuditorModel).filter_by(id=user.auditor_id).first()
        if auditor:
            ea_codes_snapshot = auditor.ea_codes or []

    member = AuditSetCommitteeMember(
        audit_set_id=audit_set_id,
        user_id=user.id,
        user_name=user.full_name,
        user_email=user.email,
        role=body.role,
        appointed_by=current_user.id,
        ea_codes_at_appointment=ea_codes_snapshot,
    )
    db.add(member)

    # If reviewer — fill the FR.218 cb_reviewer signature slot
    if body.role == "reviewer":
        sig = (
            db.query(AuditDocumentSignature)
            .filter_by(
                audit_set_id=audit_set_id,
                document_type="FR218",
                signer_role_label="cb_reviewer",
            )
            .first()
        )
        if sig:
            if sig.signed_at:
                # Already signed — don't overwrite; but still record the appointment
                pass
            else:
                sig.signer_user_id = user.id
                sig.signer_name    = user.full_name
                sig.signer_email   = user.email

    db.commit()
    return {
        "appointed": True,
        "user_id":   user.id,
        "user_name": user.full_name,
        "role":      body.role,
    }


@router.delete("/{audit_set_id}/committee/{member_id}")
def remove_committee_member(
    audit_set_id: str,
    member_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """
    Remove a committee appointment.
    Blocked if the member has already signed anything for this audit set.
    """
    if current_user.role not in {"admin", "planner"}:
        raise HTTPException(403, "Not authorized")

    member = db.query(AuditSetCommitteeMember).filter_by(
        id=member_id, audit_set_id=audit_set_id
    ).first()
    if not member:
        raise HTTPException(404, "Committee member not found")

    # Block removal if they have already signed any slot
    has_signed = (
        db.query(AuditDocumentSignature)
        .filter_by(audit_set_id=audit_set_id, signer_user_id=member.user_id)
        .filter(AuditDocumentSignature.signed_at.isnot(None))
        .count()
    ) > 0
    if has_signed:
        raise HTTPException(
            409, "Cannot remove a committee member who has already signed documents"
        )

    # If this was the reviewer — clear the FR.218 sig slot back to unassigned
    if member.role == "reviewer":
        sig = (
            db.query(AuditDocumentSignature)
            .filter_by(
                audit_set_id=audit_set_id,
                document_type="FR218",
                signer_role_label="cb_reviewer",
                signer_user_id=member.user_id,
            )
            .first()
        )
        if sig:
            sig.signer_user_id = None
            sig.signer_name    = None
            sig.signer_email   = None

    db.delete(member)
    db.commit()
    return {"removed": True}
```

Register in `backend/main.py` — add alongside existing audit_set routers:
```python
from audit_set.committee_router import router as committee_router
app.include_router(committee_router)
```
Place it BEFORE the catch-all `/{audit_set_id}` routes, same as `signatures_router`.

---

### 3. `backend/audit_set/signatures_router.py` — harden `cb_reviewer` self-assign

The `cb_reviewer` slot must now be filled only via formal committee appointment.
Remove it from the self-assign eligibility checks in both `request_cb_signature_otp`
and `verify_cb_signature`.

In `request_cb_signature_otp`, replace the self-assign block with:

```python
# Self-assign if the slot is unassigned and the caller is eligible
# NOTE: cb_reviewer is no longer self-assignable — appointment required (Prompt 14)
if sig.signer_user_id is None:
    eligible = False
    if sig.signer_role_label == "cb_cert_manager" and current_user.role in ("admin", "executive"):
        eligible = True
    if not eligible:
        raise HTTPException(403, "You are not eligible to sign this slot")
    sig.signer_user_id = current_user.id
    sig.signer_name    = current_user.full_name
    sig.signer_email   = current_user.email
    db.commit()
elif sig.signer_user_id != current_user.id:
    raise HTTPException(403, "This signature is not assigned to you")
```

Apply the same change to the self-assign block in `verify_cb_signature` (same replacement).

Also update `get_my_pending_signatures` — remove `cb_reviewer` from `eligible_labels`:

```python
eligible_labels: list[str] = []
if current_user.role in ("admin", "executive"):
    eligible_labels.append("cb_cert_manager")
# cb_reviewer is NO LONGER claimable — it is assigned via committee appointment
```

And update `get_internal_signatures` — remove `cb_reviewer` from `eligible_labels`:

```python
eligible_labels: set[str] = set()
if current_user.role in ("admin", "executive"):
    eligible_labels.add("cb_cert_manager")
# cb_reviewer removed — assigned via committee appointment only
```

The `pending_appointment` flag remains:
```python
"pending_appointment": s.signer_role_label == "cb_reviewer" and s.signer_user_id is None,
```
This correctly shows "Pending committee appointment" until a reviewer is formally appointed.
Once appointed, `signer_user_id` is filled, so `pending_appointment` becomes `false` and
the reviewer sees a Sign button on their next page visit.

---

## Frontend

### 4. New file `frontend/src/components/ui/CommitteeSection.tsx`

```tsx
'use client'

import { useEffect, useState } from 'react'
import api from '@/lib/api'

interface CommitteeMember {
  id: string
  user_id: string
  user_name: string
  user_email: string
  role: 'reviewer' | 'decision_maker'
  appointed_by: string | null
  ea_codes_at_appointment: string[] | null
  appointed_at: string
  has_signed_fr218: boolean
}

interface EligibleUser {
  user_id: string
  full_name: string
  email: string
  role: string
  ea_codes: string[]
  ea_match: boolean
  has_auditor_profile: boolean
  eligible_as_reviewer: boolean
}

const ROLE_LABELS: Record<string, string> = {
  reviewer:        'Reviewer',
  decision_maker:  'Decision Maker',
}

function fmtDate(iso: string | null) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

export function CommitteeSection({
  auditSetId,
  workflowStatus,
}: {
  auditSetId: string
  workflowStatus: string | null
}) {
  const [members, setMembers]       = useState<CommitteeMember[]>([])
  const [showPicker, setShowPicker] = useState(false)
  const [pickRole, setPickRole]     = useState<'reviewer' | 'decision_maker'>('reviewer')
  const [eligible, setEligible]     = useState<EligibleUser[]>([])
  const [loadingEligible, setLoadingEligible] = useState(false)
  const [busy, setBusy]             = useState(false)
  const [error, setError]           = useState('')

  // Only show after application approved
  const showSection = workflowStatus && workflowStatus !== 'pending_review'
  if (!showSection) return null

  async function loadMembers() {
    try {
      const r = await api.get<CommitteeMember[]>(`/audit-sets/${auditSetId}/committee`)
      setMembers(r.data)
    } catch {}
  }

  useEffect(() => { loadMembers() }, [auditSetId])

  async function openPicker(role: 'reviewer' | 'decision_maker') {
    setPickRole(role)
    setShowPicker(true)
    setError('')
    setLoadingEligible(true)
    try {
      const r = await api.get<EligibleUser[]>(`/audit-sets/${auditSetId}/committee/eligible-users`)
      setEligible(r.data)
    } catch {
      setError('Failed to load eligible users')
    } finally {
      setLoadingEligible(false)
    }
  }

  async function appoint(userId: string) {
    setBusy(true)
    setError('')
    try {
      await api.post(`/audit-sets/${auditSetId}/committee/appoint`, {
        user_id: userId,
        role: pickRole,
      })
      setShowPicker(false)
      await loadMembers()
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'Appointment failed')
    } finally {
      setBusy(false)
    }
  }

  async function removeMember(memberId: string) {
    if (!confirm('Remove this committee member?')) return
    setBusy(true)
    try {
      await api.delete(`/audit-sets/${auditSetId}/committee/${memberId}`)
      await loadMembers()
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      alert(detail || 'Removal failed')
    } finally {
      setBusy(false)
    }
  }

  const hasReviewer = members.some(m => m.role === 'reviewer')

  return (
    <div className="mt-6">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-700">
          Certification Committee
        </h2>
        <div className="flex gap-2">
          {!hasReviewer && (
            <button
              type="button"
              onClick={() => openPicker('reviewer')}
              disabled={busy}
              className="rounded-lg border border-[#1A4731] px-3 py-1.5 text-xs font-medium text-[#1A4731] hover:bg-green-50 disabled:opacity-40"
            >
              + Appoint Reviewer
            </button>
          )}
          <button
            type="button"
            onClick={() => openPicker('decision_maker')}
            disabled={busy}
            className="rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-40"
          >
            + Add Decision Maker
          </button>
        </div>
      </div>

      {/* Member list */}
      <div className="rounded-xl border bg-white">
        {members.length === 0 ? (
          <div className="px-4 py-6 text-center text-xs text-gray-400">
            No committee members appointed yet.
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {members.map(m => (
              <div key={m.id} className="flex items-center justify-between px-4 py-3">
                <div>
                  <p className="text-sm font-medium text-gray-800">{m.user_name}</p>
                  <p className="mt-0.5 text-xs text-gray-400">
                    {ROLE_LABELS[m.role]} · appointed {fmtDate(m.appointed_at)}
                    {m.ea_codes_at_appointment && m.ea_codes_at_appointment.length > 0
                      ? ` · EA: ${m.ea_codes_at_appointment.join(', ')}`
                      : ''}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  {m.has_signed_fr218 && (
                    <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-700">
                      FR.218 ✓
                    </span>
                  )}
                  {!m.has_signed_fr218 && (
                    <button
                      type="button"
                      onClick={() => removeMember(m.id)}
                      disabled={busy}
                      className="text-xs text-gray-400 hover:text-red-500 disabled:opacity-40"
                    >
                      Remove
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Inline picker panel */}
      {showPicker && (
        <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-4">
          <div className="mb-3 flex items-center justify-between">
            <p className="text-sm font-semibold text-gray-700">
              Select {ROLE_LABELS[pickRole]}
            </p>
            <button
              type="button"
              onClick={() => { setShowPicker(false); setError('') }}
              className="text-xs text-gray-400 hover:text-gray-600"
            >
              Cancel
            </button>
          </div>

          {loadingEligible ? (
            <p className="text-xs text-gray-400">Loading eligible users…</p>
          ) : eligible.length === 0 ? (
            <p className="text-xs text-gray-400">No eligible users available.</p>
          ) : (
            <div className="space-y-1.5">
              {eligible.map(u => (
                <div
                  key={u.user_id}
                  className={`flex items-center justify-between rounded-lg border bg-white px-3 py-2.5 ${
                    pickRole === 'reviewer' && !u.eligible_as_reviewer
                      ? 'opacity-50'
                      : ''
                  }`}
                >
                  <div>
                    <p className="text-xs font-medium text-gray-800">{u.full_name}</p>
                    <p className="mt-0.5 text-xs text-gray-400">
                      {u.role}
                      {u.ea_codes.length > 0 ? ` · EA: ${u.ea_codes.join(', ')}` : ''}
                      {!u.has_auditor_profile ? ' · no auditor profile' : ''}
                      {u.has_auditor_profile && !u.ea_match ? ' · ⚠ EA codes may not match' : ''}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => appoint(u.user_id)}
                    disabled={busy}
                    className="rounded bg-[#1A4731] px-2.5 py-1 text-xs text-white disabled:opacity-40"
                  >
                    {busy ? '…' : 'Appoint'}
                  </button>
                </div>
              ))}
            </div>
          )}
          {error && <p className="mt-2 text-xs text-red-500">{error}</p>}
        </div>
      )}
    </div>
  )
}
```

### 5. Wire into `frontend/src/app/(app)/clients/[id]/page.tsx`

Add import:
```tsx
import { CommitteeSection } from '@/components/ui/CommitteeSection'
```

Add **after** `<InternalApprovalsSection …/>`:
```tsx
<CommitteeSection
  auditSetId={id}
  workflowStatus={data.workflow_status ?? null}
/>
```

---

## Verification

1. `python3 -m py_compile backend/audit_set/committee_router.py backend/audit_set/signatures_router.py backend/audit_set/db_models.py`
2. `cd frontend && npx tsc --noEmit`
3. Manual test — committee appointment + FR.218 reviewer signing:
   a. Approve a plan that includes ISO 22000 or ISO 27001 → `in_planning`
   b. On `/clients/{id}` → "Certification Committee" section appears beneath "Internal Approvals"
   c. Click "+ Appoint Reviewer" → picker opens with CB users sorted by EA match
   d. Appoint a user → member row appears; FR.218 "Independent Reviewer" row in
      InternalApprovalsSection now shows their name (no longer "Pending committee appointment")
   e. Log in as the appointed reviewer → FR.218 reviewer row shows Sign button
   f. Sign via OTP → row flips to ✓ and FR.218 badge shows "Fully Signed ✓" (once planner
      and cert_manager have also signed)
4. Test remove: appoint a reviewer → remove before signing → FR.218 reviewer slot goes back
   to "Pending committee appointment"
5. Test remove block: appoint → sign → attempt remove → expect HTTP 409
6. Confirm `GET /audit-sets/my-pending-signatures` no longer includes unassigned cb_reviewer slots
   for admin/executive users (they can only see it after being formally appointed)
7. Commit and push to main

## Constraint
DO NOT modify any other endpoint, component, or page beyond what is listed.

New files:
- `backend/audit_set/committee_router.py`
- `frontend/src/components/ui/CommitteeSection.tsx`

Modified files:
- `backend/audit_set/db_models.py` — add `AuditSetCommitteeMember` model
- `backend/audit_set/signatures_router.py` — remove cb_reviewer self-assign from 3 locations
- `backend/main.py` — register `committee_router`
- `frontend/src/app/(app)/clients/[id]/page.tsx` — wire CommitteeSection
