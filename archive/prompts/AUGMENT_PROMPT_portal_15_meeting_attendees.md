# AUGMENT PROMPT — Portal 15: FR.225 Meeting Attendees & Guest Token Signing

## Context
Certiva — FastAPI backend + Next.js 14 App Router frontend.
**DO NOT BREAK THE EXISTING PORTAL. All changes are additive.**

ISO 17021-1 requires opening and closing meeting attendance records (FR.225).
External organization attendees (no Certiva account) sign via tokenized email links.
The CB planner or lead auditor pre-registers attendees; the system emails each a signing link.
Attendees click the link, confirm identity via OTP, and sign opening / closing independently.

---

## What this builds

**Backend:**
1. `AuditSetMeetingAttendee` table in `db_models.py`
2. Two new email functions in `email_service.py`
3. New `meeting_router.py` with a protected router (CB/auditor management) and a public
   router (unauthenticated token-based signing)
4. Register both routers in `main.py`

**Frontend:**
5. New `MeetingAttendeesSection.tsx` on the CB portal `/clients/[id]` page
6. New public page `app/sign/meeting/[token]/page.tsx` — no auth required
7. Add "Attendees" tab to the auditor portal audit detail page (read-only view with stage picker)

---

## Backend

### 1. `backend/audit_set/db_models.py` — add `AuditSetMeetingAttendee`

Add this class after `AuditSetCommitteeMember`:

```python
# ---------------------------------------------------------------------------
# Table 8 — audit_set_meeting_attendees
# External organization personnel who sign FR.225 opening and closing meetings.
# No Certiva account — signed via tokenized email links.
# ---------------------------------------------------------------------------

class AuditSetMeetingAttendee(Base):
    __tablename__ = "audit_set_meeting_attendees"

    id               = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    audit_set_id     = Column(String, ForeignKey("audit_sets.id", ondelete="CASCADE"), nullable=False)
    stage_type       = Column(String, nullable=False)  # "stage_1" | "stage_2" | "surveillance" | "recertification"
    full_name        = Column(String, nullable=False)
    title            = Column(String, nullable=True)   # e.g. "General Manager", "Quality Engineer"
    email            = Column(String, nullable=False)
    # Token for the signing link — UUID, hard to guess
    token            = Column(String, unique=True, nullable=False,
                              default=lambda: str(uuid.uuid4()))
    token_expires_at = Column(DateTime, nullable=True)  # 72h from creation
    # Opening meeting
    opening_otp_hash    = Column(String, nullable=True)
    opening_otp_expires = Column(DateTime, nullable=True)
    opening_signed_at   = Column(DateTime, nullable=True)
    opening_signed_ip   = Column(String, nullable=True)
    # Closing meeting
    closing_otp_hash    = Column(String, nullable=True)
    closing_otp_expires = Column(DateTime, nullable=True)
    closing_signed_at   = Column(DateTime, nullable=True)
    closing_signed_ip   = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
```

No `_safe_add_column` needed — `Base.metadata.create_all()` creates it on boot.

---

### 2. `backend/email_service.py` — add two functions

Add these after `send_otp_code`:

```python
def send_meeting_signing_link(
    to: str,
    full_name: str,
    company_name: str,
    stage_label: str,
    sign_url: str,
) -> bool:
    """Sent to an external meeting attendee with their personal signing link."""
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
      <h2 style="color:#1A4731">IFC Global LLC — Audit Meeting Attendance</h2>
      <p>Dear {full_name},</p>
      <p>You are registered as a meeting attendee for the IFC Global audit of
         <strong>{company_name}</strong> ({stage_label}).</p>
      <p>Please use your personal signing link to record your attendance at the
         opening and closing meetings. Each signature requires a one-time code
         sent to this email.</p>
      <p style="margin:24px 0">
        <a href="{sign_url}" style="background:#1A4731;color:white;padding:12px 24px;
           border-radius:4px;text-decoration:none;font-weight:bold">Sign Meetings</a>
      </p>
      <p style="color:#888;font-size:12px">
        This link is personal and expires in 72 hours. Do not share it.<br>
        If you believe this was sent in error, please ignore this email.<br>
        IFC Global LLC · application@ifcglobal.us
      </p>
    </div>
    """
    return _send(to, f"IFC Global — Audit Meeting Sign-in: {company_name}", html)


def send_meeting_otp(
    to: str,
    full_name: str,
    event_type: str,   # "opening" or "closing"
    company_name: str,
    otp: str,
) -> bool:
    """OTP code for signing an opening or closing meeting."""
    label = "Opening Meeting" if event_type == "opening" else "Closing Meeting"
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
      <h2 style="color:#1A4731">IFC Global — Meeting Signature Code</h2>
      <p>Dear {full_name},</p>
      <p>Use the following code to sign the <strong>{label}</strong>
         attendance record for <strong>{company_name}</strong>:</p>
      <div style="background:#1A4731;color:white;padding:24px;border-radius:6px;
                  margin:16px 0;text-align:center">
        <span style="font-size:36px;letter-spacing:8px;font-weight:bold">{otp}</span>
      </div>
      <p style="color:#666">This code expires in 10 minutes. Do not share it.</p>
      <p style="color:#666;font-size:12px">IFC Global LLC · application@ifcglobal.us</p>
    </div>
    """
    return _send(to, f"IFC Global — {label} Signature Code", html)
```

---

### 3. New file `backend/audit_set/meeting_router.py`

```python
"""
BATUHAN — FR.225 Meeting Attendees & guest token signing (Prompt 15).

Two routers:
  protected_router  — CB / auditor management (auth required)
  public_router     — guest signing flow (NO auth)
"""
from __future__ import annotations
import hashlib
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from audit_set.db_models import AuditSet, AuditSetMeetingAttendee, get_db
from auth.db_models import PlatformUser
from auth.dependencies import get_current_user
from email_service import send_meeting_signing_link, send_meeting_otp
from config.settings import get_settings

# ── Constants ─────────────────────────────────────────────────────────────────

STAGE_LABELS: dict[str, str] = {
    "stage_1":        "Stage 1",
    "stage_2":        "Stage 2",
    "surveillance":   "Surveillance",
    "recertification":"Recertification",
}
TOKEN_TTL_HOURS = 72
OTP_EXPIRY_MIN  = 10
CB_ROLES        = {"admin", "planner", "officer", "executive"}
ALLOWED_ROLES   = CB_ROLES | {"auditor"}


def _hash(val: str) -> str:
    return hashlib.sha256(val.encode()).hexdigest()


def _att_dict(a: AuditSetMeetingAttendee) -> dict:
    return {
        "id":               a.id,
        "audit_set_id":     a.audit_set_id,
        "stage_type":       a.stage_type,
        "stage_label":      STAGE_LABELS.get(a.stage_type, a.stage_type),
        "full_name":        a.full_name,
        "title":            a.title,
        "email":            a.email,
        "token_expires_at": a.token_expires_at.isoformat() if a.token_expires_at else None,
        "opening_signed":   a.opening_signed_at is not None,
        "opening_signed_at":a.opening_signed_at.isoformat() if a.opening_signed_at else None,
        "closing_signed":   a.closing_signed_at is not None,
        "closing_signed_at":a.closing_signed_at.isoformat() if a.closing_signed_at else None,
        "created_at":       a.created_at.isoformat() if a.created_at else None,
    }


# ── Protected router (CB + auditor management) ────────────────────────────────

protected_router = APIRouter(prefix="/audit-sets", tags=["meeting-attendees"])


@protected_router.get("/{audit_set_id}/meeting-attendees")
def list_attendees(
    audit_set_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in ALLOWED_ROLES:
        raise HTTPException(403, "Not authorized")
    attendees = (
        db.query(AuditSetMeetingAttendee)
        .filter_by(audit_set_id=audit_set_id)
        .order_by(AuditSetMeetingAttendee.stage_type, AuditSetMeetingAttendee.created_at)
        .all()
    )
    return [_att_dict(a) for a in attendees]


class AddAttendeeSchema(BaseModel):
    stage_type: str
    full_name:  str
    title:      str | None = None
    email:      str


@protected_router.post("/{audit_set_id}/meeting-attendees")
def add_attendee(
    audit_set_id: str,
    body: AddAttendeeSchema,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in ALLOWED_ROLES:
        raise HTTPException(403, "Not authorized")

    if body.stage_type not in STAGE_LABELS:
        raise HTTPException(400, f"Invalid stage_type. Must be one of: {list(STAGE_LABELS)}")

    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Audit set not found")

    settings = get_settings()
    expires_at = datetime.utcnow() + timedelta(hours=TOKEN_TTL_HOURS)

    attendee = AuditSetMeetingAttendee(
        audit_set_id=audit_set_id,
        stage_type=body.stage_type,
        full_name=body.full_name.strip(),
        title=body.title,
        email=body.email.lower().strip(),
        token_expires_at=expires_at,
    )
    db.add(attendee)
    db.commit()
    db.refresh(attendee)

    # Send signing link immediately
    sign_url = f"{settings.email_base_url}/sign/meeting/{attendee.token}"
    try:
        send_meeting_signing_link(
            to=attendee.email,
            full_name=attendee.full_name,
            company_name=audit_set.company_name or "",
            stage_label=STAGE_LABELS[body.stage_type],
            sign_url=sign_url,
        )
    except Exception:
        pass  # best-effort

    return _att_dict(attendee)


@protected_router.delete("/{audit_set_id}/meeting-attendees/{att_id}")
def remove_attendee(
    audit_set_id: str,
    att_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "Only CB staff can remove attendees")

    att = db.query(AuditSetMeetingAttendee).filter_by(
        id=att_id, audit_set_id=audit_set_id
    ).first()
    if not att:
        raise HTTPException(404, "Attendee not found")

    if att.opening_signed_at or att.closing_signed_at:
        raise HTTPException(409, "Cannot remove an attendee who has already signed")

    db.delete(att)
    db.commit()
    return {"removed": True}


@protected_router.post("/{audit_set_id}/meeting-attendees/{att_id}/resend")
def resend_invite(
    audit_set_id: str,
    att_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in ALLOWED_ROLES:
        raise HTTPException(403, "Not authorized")

    att = db.query(AuditSetMeetingAttendee).filter_by(
        id=att_id, audit_set_id=audit_set_id
    ).first()
    if not att:
        raise HTTPException(404, "Attendee not found")

    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    settings = get_settings()

    # Extend expiry by 72h from now on resend
    att.token_expires_at = datetime.utcnow() + timedelta(hours=TOKEN_TTL_HOURS)
    db.commit()

    sign_url = f"{settings.email_base_url}/sign/meeting/{att.token}"
    try:
        send_meeting_signing_link(
            to=att.email,
            full_name=att.full_name,
            company_name=audit_set.company_name if audit_set else "",
            stage_label=STAGE_LABELS.get(att.stage_type, att.stage_type),
            sign_url=sign_url,
        )
    except Exception:
        pass

    return {"resent": True}


# ── Public router (guest signing — NO auth dependency) ────────────────────────

public_router = APIRouter(prefix="/sign/meeting", tags=["meeting-signing"])


def _get_attendee_by_token(token: str, db: Session) -> AuditSetMeetingAttendee:
    att = db.query(AuditSetMeetingAttendee).filter_by(token=token).first()
    if not att:
        raise HTTPException(404, "Signing link not found")
    if att.token_expires_at and datetime.utcnow() > att.token_expires_at:
        # Expired, but only block if neither event is signed yet
        if not att.opening_signed_at and not att.closing_signed_at:
            raise HTTPException(410, "This signing link has expired")
    return att


@public_router.get("/{token}")
def get_signing_info(token: str, db: Session = Depends(get_db)):
    """
    Public endpoint — returns attendee and audit info needed to render the
    signing page. No sensitive data (no email, no OTP hashes).
    """
    att = _get_attendee_by_token(token, db)
    audit_set = db.query(AuditSet).filter_by(id=att.audit_set_id).first()
    return {
        "full_name":        att.full_name,
        "title":            att.title,
        "company_name":     audit_set.company_name if audit_set else "",
        "stage_label":      STAGE_LABELS.get(att.stage_type, att.stage_type),
        "opening_signed":   att.opening_signed_at is not None,
        "opening_signed_at":att.opening_signed_at.isoformat() if att.opening_signed_at else None,
        "closing_signed":   att.closing_signed_at is not None,
        "closing_signed_at":att.closing_signed_at.isoformat() if att.closing_signed_at else None,
        "token_expires_at": att.token_expires_at.isoformat() if att.token_expires_at else None,
    }


@public_router.post("/{token}/request-otp")
def request_meeting_otp(
    token: str,
    event_type: str,   # query param: "opening" or "closing"
    db: Session = Depends(get_db),
):
    if event_type not in ("opening", "closing"):
        raise HTTPException(400, "event_type must be 'opening' or 'closing'")

    att = _get_attendee_by_token(token, db)

    # Check not already signed
    if event_type == "opening" and att.opening_signed_at:
        raise HTTPException(400, "Opening meeting already signed")
    if event_type == "closing" and att.closing_signed_at:
        raise HTTPException(400, "Closing meeting already signed")

    audit_set = db.query(AuditSet).filter_by(id=att.audit_set_id).first()

    otp = f"{secrets.randbelow(900000) + 100000}"
    otp_hash    = _hash(otp)
    otp_expires = datetime.utcnow() + timedelta(minutes=OTP_EXPIRY_MIN)

    if event_type == "opening":
        att.opening_otp_hash    = otp_hash
        att.opening_otp_expires = otp_expires
    else:
        att.closing_otp_hash    = otp_hash
        att.closing_otp_expires = otp_expires

    db.commit()

    try:
        send_meeting_otp(
            to=att.email,
            full_name=att.full_name,
            event_type=event_type,
            company_name=audit_set.company_name if audit_set else "",
            otp=otp,
        )
    except Exception:
        pass

    return {"message": f"Code sent to your registered email. Valid for {OTP_EXPIRY_MIN} minutes."}


@public_router.post("/{token}/verify")
def verify_meeting_signature(
    token: str,
    event_type: str,   # query param: "opening" or "closing"
    otp: str,          # query param
    request: Request,
    db: Session = Depends(get_db),
):
    if event_type not in ("opening", "closing"):
        raise HTTPException(400, "event_type must be 'opening' or 'closing'")

    att = _get_attendee_by_token(token, db)

    if event_type == "opening":
        if att.opening_signed_at:
            raise HTTPException(400, "Already signed")
        if not att.opening_otp_hash or not att.opening_otp_expires:
            raise HTTPException(400, "No pending OTP. Request one first.")
        if datetime.utcnow() > att.opening_otp_expires:
            raise HTTPException(400, "OTP expired. Please request a new one.")
        if _hash(otp.strip()) != att.opening_otp_hash:
            raise HTTPException(400, "Invalid code.")
        att.opening_signed_at = datetime.utcnow()
        att.opening_signed_ip = request.client.host if request.client else None
        att.opening_otp_hash  = None
        att.opening_otp_expires = None
    else:
        if att.closing_signed_at:
            raise HTTPException(400, "Already signed")
        if not att.closing_otp_hash or not att.closing_otp_expires:
            raise HTTPException(400, "No pending OTP. Request one first.")
        if datetime.utcnow() > att.closing_otp_expires:
            raise HTTPException(400, "OTP expired. Please request a new one.")
        if _hash(otp.strip()) != att.closing_otp_hash:
            raise HTTPException(400, "Invalid code.")
        att.closing_signed_at = datetime.utcnow()
        att.closing_signed_ip = request.client.host if request.client else None
        att.closing_otp_hash  = None
        att.closing_otp_expires = None

    db.commit()
    signed_at = (att.opening_signed_at if event_type == "opening" else att.closing_signed_at)
    return {"signed": True, "event_type": event_type, "signed_at": signed_at.isoformat()}
```

---

### 4. `backend/main.py` — register both routers

```python
from audit_set.meeting_router import protected_router as meeting_protected_router
from audit_set.meeting_router import public_router as meeting_public_router
```

Register both. The public router has no auth and responds to `/sign/meeting/…` — place it
before any catch-all wildcard route (if any). The protected router goes with other
`/audit-sets` routers:

```python
app.include_router(meeting_protected_router)   # beside other /audit-sets routers
app.include_router(meeting_public_router)      # separate prefix /sign/meeting
```

---

## Frontend

### 5. New file `frontend/src/components/ui/MeetingAttendeesSection.tsx`

```tsx
'use client'

import { useEffect, useState } from 'react'
import api from '@/lib/api'

interface Attendee {
  id:               string
  stage_type:       string
  stage_label:      string
  full_name:        string
  title:            string | null
  email:            string
  opening_signed:   boolean
  opening_signed_at: string | null
  closing_signed:   boolean
  closing_signed_at: string | null
  created_at:       string
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

function SignBadge({ signed, label }: { signed: boolean; label: string }) {
  if (signed) {
    return (
      <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-700">
        {label} ✓
      </span>
    )
  }
  return (
    <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-400">
      {label} Pending
    </span>
  )
}

export function MeetingAttendeesSection({
  auditSetId,
  workflowStatus,
}: {
  auditSetId: string
  workflowStatus: string | null
}) {
  const [attendees, setAttendees] = useState<Attendee[]>([])
  const [loading, setLoading]     = useState(true)
  const [showAdd, setShowAdd]     = useState(false)
  const [form, setForm]           = useState({
    stage_type: 'stage_1',
    full_name:  '',
    title:      '',
    email:      '',
  })
  const [busy, setBusy]   = useState(false)
  const [error, setError] = useState('')

  // Only show from in_planning onwards
  const showSection = workflowStatus && workflowStatus !== 'pending_review'
  if (!showSection) return null

  async function load() {
    try {
      const r = await api.get<Attendee[]>(`/audit-sets/${auditSetId}/meeting-attendees`)
      setAttendees(r.data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [auditSetId])

  async function addAttendee(e: React.FormEvent) {
    e.preventDefault()
    if (!form.full_name.trim() || !form.email.trim()) return
    setBusy(true)
    setError('')
    try {
      await api.post(`/audit-sets/${auditSetId}/meeting-attendees`, {
        stage_type: form.stage_type,
        full_name:  form.full_name.trim(),
        title:      form.title.trim() || null,
        email:      form.email.trim(),
      })
      setForm({ stage_type: 'stage_1', full_name: '', title: '', email: '' })
      setShowAdd(false)
      await load()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail || 'Failed to add attendee')
    } finally {
      setBusy(false)
    }
  }

  async function removeAttendee(id: string) {
    if (!confirm('Remove this attendee?')) return
    try {
      await api.delete(`/audit-sets/${auditSetId}/meeting-attendees/${id}`)
      setAttendees(prev => prev.filter(a => a.id !== id))
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      alert(detail || 'Removal failed')
    }
  }

  async function resendInvite(id: string) {
    try {
      await api.post(`/audit-sets/${auditSetId}/meeting-attendees/${id}/resend`)
      alert('Invite resent.')
    } catch {
      alert('Resend failed.')
    }
  }

  // Group by stage_type
  const grouped = attendees.reduce<Record<string, Attendee[]>>((acc, a) => {
    acc[a.stage_type] = acc[a.stage_type] || []
    acc[a.stage_type].push(a)
    return acc
  }, {})

  return (
    <div className="mt-6">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-700">
          Meeting Attendees (FR.225)
        </h2>
        <button
          type="button"
          onClick={() => { setShowAdd(!showAdd); setError('') }}
          className="rounded-lg border border-[#1A4731] px-3 py-1.5 text-xs font-medium text-[#1A4731] hover:bg-green-50"
        >
          {showAdd ? 'Cancel' : '+ Add Attendee'}
        </button>
      </div>

      {/* Add form */}
      {showAdd && (
        <form
          onSubmit={addAttendee}
          className="mb-4 rounded-xl border border-amber-200 bg-amber-50 p-4"
        >
          <p className="mb-3 text-sm font-medium text-gray-700">New Meeting Attendee</p>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-600">Stage</label>
              <select
                value={form.stage_type}
                onChange={e => setForm(f => ({ ...f, stage_type: e.target.value }))}
                className="w-full rounded-lg border px-3 py-2 text-sm"
              >
                {STAGE_TYPES.map(s => (
                  <option key={s.value} value={s.value}>{s.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-600">Full Name *</label>
              <input
                value={form.full_name}
                onChange={e => setForm(f => ({ ...f, full_name: e.target.value }))}
                required
                placeholder="Jane Smith"
                className="w-full rounded-lg border px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-600">Title / Role</label>
              <input
                value={form.title}
                onChange={e => setForm(f => ({ ...f, title: e.target.value }))}
                placeholder="General Manager"
                className="w-full rounded-lg border px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-600">Email *</label>
              <input
                type="email"
                value={form.email}
                onChange={e => setForm(f => ({ ...f, email: e.target.value }))}
                required
                placeholder="jane@company.com"
                className="w-full rounded-lg border px-3 py-2 text-sm"
              />
            </div>
          </div>
          <div className="mt-3 flex items-center gap-3">
            <button
              type="submit"
              disabled={busy}
              className="rounded-lg bg-[#1A4731] px-4 py-2 text-sm text-white disabled:opacity-40"
            >
              {busy ? 'Adding…' : 'Add & Send Invite'}
            </button>
            <p className="text-xs text-gray-400">
              A signing link will be emailed to the attendee immediately.
            </p>
          </div>
          {error && <p className="mt-2 text-xs text-red-500">{error}</p>}
        </form>
      )}

      {/* Attendee list */}
      {loading ? (
        <p className="text-xs text-gray-400">Loading…</p>
      ) : attendees.length === 0 ? (
        <div className="rounded-xl border bg-white px-4 py-6 text-center text-xs text-gray-400">
          No attendees registered yet. Add them above — each receives a personal signing link.
        </div>
      ) : (
        <div className="space-y-3">
          {Object.entries(grouped).map(([stageType, list]) => (
            <div key={stageType} className="rounded-xl border bg-white">
              <div className="border-b px-4 py-2.5">
                <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                  {STAGE_TYPES.find(s => s.value === stageType)?.label ?? stageType}
                </p>
              </div>
              <div className="divide-y divide-gray-50">
                {list.map(a => (
                  <div key={a.id} className="flex items-center justify-between px-4 py-3">
                    <div>
                      <p className="text-sm font-medium text-gray-800">
                        {a.full_name}
                        {a.title && (
                          <span className="ml-1.5 text-xs text-gray-400">— {a.title}</span>
                        )}
                      </p>
                      <p className="mt-0.5 text-xs text-gray-400">{a.email}</p>
                    </div>
                    <div className="flex items-center gap-2 flex-wrap justify-end">
                      <SignBadge signed={a.opening_signed} label="Opening" />
                      <SignBadge signed={a.closing_signed} label="Closing" />
                      <button
                        type="button"
                        onClick={() => resendInvite(a.id)}
                        className="text-xs text-gray-400 hover:text-[#1A4731] underline"
                      >
                        Resend
                      </button>
                      {!a.opening_signed && !a.closing_signed && (
                        <button
                          type="button"
                          onClick={() => removeAttendee(a.id)}
                          className="text-xs text-gray-400 hover:text-red-500"
                        >
                          Remove
                        </button>
                      )}
                    </div>
                  </div>
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

### 6. New public page `frontend/src/app/sign/meeting/[token]/page.tsx`

This page lives outside any auth-guarded layout group.

```tsx
'use client'

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'

// Use raw fetch — no auth token needed
const API_BASE = process.env.NEXT_PUBLIC_API_URL || ''

interface SigningInfo {
  full_name:        string
  title:            string | null
  company_name:     string
  stage_label:      string
  opening_signed:   boolean
  opening_signed_at: string | null
  closing_signed:   boolean
  closing_signed_at: string | null
  token_expires_at: string | null
}

function fmtDate(iso: string | null) {
  if (!iso) return ''
  return new Date(iso).toLocaleString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

type EventType = 'opening' | 'closing'

function EventCard({
  type,
  label,
  signed,
  signedAt,
  token,
  onSigned,
}: {
  type:    EventType
  label:   string
  signed:  boolean
  signedAt: string | null
  token:   string
  onSigned: () => void
}) {
  const [step, setStep]   = useState<'idle' | 'sending' | 'otp' | 'verifying' | 'done'>('idle')
  const [otp, setOtp]     = useState('')
  const [error, setError] = useState('')

  if (signed) {
    return (
      <div className="rounded-xl border border-green-200 bg-green-50 p-5">
        <p className="font-semibold text-green-700">{label} ✓</p>
        <p className="mt-1 text-xs text-green-600">Signed {fmtDate(signedAt)}</p>
      </div>
    )
  }

  async function requestOtp() {
    setStep('sending')
    setError('')
    try {
      const r = await fetch(`${API_BASE}/sign/meeting/${token}/request-otp?event_type=${type}`, {
        method: 'POST',
      })
      if (!r.ok) {
        const d = await r.json()
        throw new Error(d.detail || 'Failed to send code')
      }
      setStep('otp')
    } catch (e: unknown) {
      setError((e as Error).message || 'Failed to send code')
      setStep('idle')
    }
  }

  async function verifyOtp() {
    setStep('verifying')
    setError('')
    try {
      const r = await fetch(
        `${API_BASE}/sign/meeting/${token}/verify?event_type=${type}&otp=${encodeURIComponent(otp)}`,
        { method: 'POST' },
      )
      if (!r.ok) {
        const d = await r.json()
        throw new Error(d.detail || 'Invalid code')
      }
      setStep('done')
      onSigned()
    } catch (e: unknown) {
      setError((e as Error).message || 'Verification failed')
      setStep('otp')
    }
  }

  return (
    <div className="rounded-xl border bg-white p-5">
      <p className="font-semibold text-gray-800">{label}</p>
      <p className="mt-0.5 text-xs text-gray-400">Not yet signed</p>

      {step === 'idle' && (
        <button
          type="button"
          onClick={requestOtp}
          className="mt-4 rounded-lg bg-[#1A4731] px-5 py-2.5 text-sm font-medium text-white hover:bg-[#143828]"
        >
          Sign {label}
        </button>
      )}

      {step === 'sending' && (
        <p className="mt-4 text-sm text-gray-400">Sending code to your email…</p>
      )}

      {step === 'otp' && (
        <div className="mt-4 space-y-3">
          <p className="text-sm text-gray-600">
            A 6-digit code has been sent to your email address. Enter it below:
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
              disabled={otp.length !== 6}
              className="rounded-lg bg-[#1A4731] px-5 py-2 text-sm font-medium text-white disabled:opacity-40"
            >
              Confirm Signature
            </button>
            <button
              type="button"
              onClick={requestOtp}
              className="text-sm text-gray-400 underline"
            >
              Resend code
            </button>
          </div>
        </div>
      )}

      {step === 'verifying' && (
        <p className="mt-4 text-sm text-gray-400">Verifying…</p>
      )}

      {step === 'done' && (
        <p className="mt-4 text-sm font-medium text-green-600">Signed ✓</p>
      )}

      {error && <p className="mt-2 text-xs text-red-500">{error}</p>}
    </div>
  )
}

export default function MeetingSigningPage() {
  const { token } = useParams<{ token: string }>()
  const [info, setInfo]       = useState<SigningInfo | null>(null)
  const [status, setStatus]   = useState<'loading' | 'ready' | 'error' | 'expired'>('loading')
  const [errMsg, setErrMsg]   = useState('')

  async function load() {
    try {
      const r = await fetch(`${API_BASE}/sign/meeting/${token}`)
      if (r.status === 410) {
        setStatus('expired')
        return
      }
      if (!r.ok) {
        const d = await r.json().catch(() => ({}))
        throw new Error(d.detail || 'Link not found')
      }
      const data: SigningInfo = await r.json()
      setInfo(data)
      setStatus('ready')
    } catch (e: unknown) {
      setErrMsg((e as Error).message || 'An error occurred')
      setStatus('error')
    }
  }

  useEffect(() => { load() }, [token])

  if (status === 'loading') {
    return (
      <main className="flex min-h-screen items-center justify-center bg-gray-50">
        <p className="text-sm text-gray-400">Loading…</p>
      </main>
    )
  }

  if (status === 'expired') {
    return (
      <main className="flex min-h-screen items-center justify-center bg-gray-50 p-6">
        <div className="max-w-md rounded-2xl bg-white p-8 text-center shadow-sm">
          <p className="text-2xl">⏰</p>
          <h1 className="mt-3 text-xl font-bold text-gray-800">Link Expired</h1>
          <p className="mt-2 text-sm text-gray-500">
            This signing link has expired. Please contact IFC Global LLC for a new link.
          </p>
          <p className="mt-4 text-xs text-gray-400">application@ifcglobal.us</p>
        </div>
      </main>
    )
  }

  if (status === 'error' || !info) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-gray-50 p-6">
        <div className="max-w-md rounded-2xl bg-white p-8 text-center shadow-sm">
          <h1 className="text-xl font-bold text-gray-800">Link Not Found</h1>
          <p className="mt-2 text-sm text-gray-500">{errMsg || 'This signing link is invalid.'}</p>
        </div>
      </main>
    )
  }

  const bothSigned = info.opening_signed && info.closing_signed

  return (
    <main className="min-h-screen bg-gray-50 p-6">
      <div className="mx-auto max-w-md">
        {/* Header */}
        <div className="mb-6 text-center">
          <div
            className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full"
            style={{ background: '#1A4731' }}
          >
            <span className="text-2xl text-white">✓</span>
          </div>
          <h1 className="text-xl font-bold text-gray-900">Audit Meeting Attendance</h1>
          <p className="mt-1 text-sm text-gray-500">{info.company_name}</p>
          <p className="text-xs text-gray-400">{info.stage_label}</p>
        </div>

        {/* Attendee info */}
        <div className="mb-5 rounded-xl border bg-white p-4 text-center">
          <p className="font-semibold text-gray-800">{info.full_name}</p>
          {info.title && <p className="text-xs text-gray-400">{info.title}</p>}
        </div>

        {bothSigned ? (
          <div className="rounded-xl border border-green-200 bg-green-50 p-6 text-center">
            <p className="text-2xl">🎉</p>
            <p className="mt-2 font-semibold text-green-700">All signatures complete</p>
            <p className="mt-1 text-xs text-green-600">
              Opening: {fmtDate(info.opening_signed_at)}<br />
              Closing: {fmtDate(info.closing_signed_at)}
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            <EventCard
              type="opening"
              label="Opening Meeting"
              signed={info.opening_signed}
              signedAt={info.opening_signed_at}
              token={token}
              onSigned={load}
            />
            <EventCard
              type="closing"
              label="Closing Meeting"
              signed={info.closing_signed}
              signedAt={info.closing_signed_at}
              token={token}
              onSigned={load}
            />
            <p className="text-center text-xs text-gray-400">
              Each signature requires a one-time code sent to your email.
            </p>
          </div>
        )}

        <p className="mt-6 text-center text-xs text-gray-300">
          IFC Global LLC · Powered by Certiva
        </p>
      </div>
    </main>
  )
}
```

---

### 7. `frontend/src/app/(auditor)/auditor/audit/[id]/page.tsx` — add "Attendees" tab

Add `'attendees'` to the `Tab` type:
```tsx
type Tab = 'overview' | 'messages' | 'upload' | 'attendees'
```

Add the tab button in the tab bar alongside the others:
```tsx
{(['overview', 'messages', 'upload', 'attendees'] as const).map((t) => (
  // ... existing tab button code ...
  {t === 'upload' ? 'Upload Documents' : t === 'attendees' ? 'Attendees' : t}
```

Add the attendees tab panel after the upload tab panel:

```tsx
{/* Attendees tab — read-only list with signing status */}
{tab === 'attendees' && (
  <AuditorAttendeesView auditSetId={id} />
)}
```

Add the `AuditorAttendeesView` component at the top of the file (before `export default`):

```tsx
function AuditorAttendeesView({ auditSetId }: { auditSetId: string }) {
  const [attendees, setAttendees] = useState<{
    id: string; stage_label: string; full_name: string; title: string | null
    email: string; opening_signed: boolean; closing_signed: boolean
    stage_type: string
  }[]>([])
  const [loading, setLoading] = useState(true)
  const [form, setForm]   = useState({ stage_type: 'stage_1', full_name: '', title: '', email: '' })
  const [busy, setBusy]   = useState(false)
  const [addMsg, setAddMsg] = useState('')

  const STAGE_OPTS = [
    { value: 'stage_1', label: 'Stage 1' },
    { value: 'stage_2', label: 'Stage 2' },
    { value: 'surveillance', label: 'Surveillance' },
    { value: 'recertification', label: 'Recertification' },
  ]

  useEffect(() => {
    api.get(`/audit-sets/${auditSetId}/meeting-attendees`)
      .then(r => setAttendees(r.data as typeof attendees))
      .finally(() => setLoading(false))
  }, [auditSetId])

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setAddMsg('')
    try {
      const r = await api.post(`/audit-sets/${auditSetId}/meeting-attendees`, {
        stage_type: form.stage_type,
        full_name:  form.full_name.trim(),
        title:      form.title.trim() || null,
        email:      form.email.trim(),
      })
      setAttendees(prev => [...prev, r.data as typeof attendees[0]])
      setForm({ stage_type: 'stage_1', full_name: '', title: '', email: '' })
      setAddMsg('Attendee added and invite sent.')
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setAddMsg(detail || 'Failed to add attendee')
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <p className="text-sm text-gray-400">Loading…</p>

  const grouped = attendees.reduce<Record<string, typeof attendees>>((acc, a) => {
    acc[a.stage_type] = acc[a.stage_type] || []
    acc[a.stage_type].push(a)
    return acc
  }, {})

  return (
    <div className="space-y-4">
      {/* Add form */}
      <div className="rounded-xl border bg-white p-5">
        <p className="mb-3 text-sm font-medium text-gray-700">Add Meeting Attendee</p>
        <form onSubmit={handleAdd} className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <select
              value={form.stage_type}
              onChange={e => setForm(f => ({ ...f, stage_type: e.target.value }))}
              className="rounded-lg border px-3 py-2 text-sm"
            >
              {STAGE_OPTS.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
            <input
              value={form.full_name} required placeholder="Full Name *"
              onChange={e => setForm(f => ({ ...f, full_name: e.target.value }))}
              className="rounded-lg border px-3 py-2 text-sm"
            />
            <input
              value={form.title} placeholder="Title / Role"
              onChange={e => setForm(f => ({ ...f, title: e.target.value }))}
              className="rounded-lg border px-3 py-2 text-sm"
            />
            <input
              type="email" value={form.email} required placeholder="Email *"
              onChange={e => setForm(f => ({ ...f, email: e.target.value }))}
              className="rounded-lg border px-3 py-2 text-sm"
            />
          </div>
          <button
            type="submit" disabled={busy}
            className="rounded-lg bg-[#1A4731] px-4 py-2 text-sm text-white disabled:opacity-40"
          >
            {busy ? 'Adding…' : 'Add & Send Invite'}
          </button>
          {addMsg && <p className="text-xs text-gray-500">{addMsg}</p>}
        </form>
      </div>

      {/* Attendee list */}
      {Object.entries(grouped).map(([stage, list]) => (
        <div key={stage} className="rounded-xl border bg-white">
          <div className="border-b px-4 py-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">
              {STAGE_OPTS.find(s => s.value === stage)?.label ?? stage}
            </p>
          </div>
          <div className="divide-y divide-gray-50">
            {list.map(a => (
              <div key={a.id} className="flex items-center justify-between px-4 py-3">
                <div>
                  <p className="text-sm font-medium">{a.full_name}
                    {a.title && <span className="ml-1 text-xs text-gray-400">— {a.title}</span>}
                  </p>
                  <p className="text-xs text-gray-400">{a.email}</p>
                </div>
                <div className="flex gap-2">
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${a.opening_signed ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-400'}`}>
                    {a.opening_signed ? 'Opening ✓' : 'Opening —'}
                  </span>
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${a.closing_signed ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-400'}`}>
                    {a.closing_signed ? 'Closing ✓' : 'Closing —'}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
      {attendees.length === 0 && (
        <p className="py-8 text-center text-sm text-gray-400">No attendees registered yet.</p>
      )}
    </div>
  )
}
```

---

### 8. Wire into `frontend/src/app/(app)/clients/[id]/page.tsx`

Add import:
```tsx
import { MeetingAttendeesSection } from '@/components/ui/MeetingAttendeesSection'
```

Add **after** `<CommitteeSection …/>`:
```tsx
<MeetingAttendeesSection
  auditSetId={id}
  workflowStatus={data.workflow_status ?? null}
/>
```

---

## Verification

1. `python3 -m py_compile backend/audit_set/meeting_router.py backend/email_service.py backend/audit_set/db_models.py`
2. `cd frontend && npx tsc --noEmit`
3. Manual test — CB portal add attendee:
   a. Navigate to any plan in `in_planning` or later
   b. "Meeting Attendees (FR.225)" section appears → click "+ Add Attendee"
   c. Fill name, title, email, stage → "Add & Send Invite" → email sent with `/sign/meeting/{token}` link
   d. Attendee row appears with "Opening Pending / Closing Pending"
4. Manual test — guest signing page:
   a. Open the signing link (copy from email or DB token column)
   b. Page shows attendee name, company, stage — no login prompt
   c. Click "Sign Opening Meeting" → "Sending code…" → OTP input appears
   d. Enter code → Confirm → "Opening ✓" row goes green
   e. Repeat for Closing → "All signatures complete" message
   f. Refresh page → shows both signatures with timestamps
5. Manual test — expiry:
   a. Set `token_expires_at` in DB to past → open link → "Link Expired" page
6. Manual test — auditor portal:
   a. Log in as auditor → audit detail → "Attendees" tab
   b. Add an attendee from the auditor portal → same invite email flow
   c. Signing status shown as read badges
7. Confirm CB portal "Remove" blocked for signed attendees (HTTP 409 shown in alert)
8. Commit and push to main

## Constraints
DO NOT modify any other endpoint, component, or page beyond what is listed.

New files:
- `backend/audit_set/meeting_router.py`
- `frontend/src/components/ui/MeetingAttendeesSection.tsx`
- `frontend/src/app/sign/meeting/[token]/page.tsx`

Modified files:
- `backend/audit_set/db_models.py` — add `AuditSetMeetingAttendee`
- `backend/email_service.py` — add `send_meeting_signing_link`, `send_meeting_otp`
- `backend/main.py` — register both routers
- `frontend/src/app/(app)/clients/[id]/page.tsx` — wire MeetingAttendeesSection
- `frontend/src/app/(auditor)/auditor/audit/[id]/page.tsx` — add Attendees tab
