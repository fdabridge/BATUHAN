# AUGMENT PROMPT — Portal 19: FR.231/FR.229/FR.232 Audit Report Signing

## Context
Certiva — FastAPI backend + Next.js 14 App Router frontend.
**DO NOT BREAK THE EXISTING PORTAL. All changes are additive.**

**FR.231 / FR.229 / FR.232 — Audit Reports**
After each audit stage, the Lead Auditor uploads the formal report and signs it.
The appointed Committee Reviewer then reviews and approves from the CB portal.
This is the last two-party signing feature and completes the FR.2xx signature matrix.

Report form mapping (informational — auditor selects):
- FR.231 / FR.231-1 → Stage 1 audits
- FR.232 / FR.232-1 → Stage 2, Surveillance, Recertification audits
- FR.229          → ISMS/PIMS audits (ISO 27001 scope)

Two-party signing, strict order:
1. Lead Auditor — uploads the report file AND signs it from the auditor portal
2. Committee Reviewer — the user appointed via `AuditSetCommitteeMember` (role="reviewer")
   reviews and approves from the CB portal via OTP

**This feature is separate from the existing "Upload Documents" tab** — that tab handles
generic auditor-to-CB file delivery. This tab handles formal, committee-reviewed audit
reports with an electronic audit trail.

---

## What this builds

**Backend:**
1. `AuditSetAuditReport` table in `db_models.py`
2. New `report_router.py`
3. Two new email functions in `email_service.py`
4. Register router in `main.py`

**Frontend:**
5. New `AuditReportSection.tsx` (CB portal `/clients/[id]`)
6. `AuditorReportsView` component + "Reports" tab in `/auditor/audit/[id]/page.tsx`
7. Wire `AuditReportSection` into `(app)/clients/[id]/page.tsx`

---

## Backend

### 1. `backend/audit_set/db_models.py` — add `AuditSetAuditReport`

Add after `AuditSetImpartialityDeclaration` (or at the end of the file):

```python
# ---------------------------------------------------------------------------
# Table 12 — audit_set_audit_reports
# FR.231 / FR.229 / FR.232 — Formal audit reports requiring committee review.
# Two-party signing: Lead Auditor signs first, then Committee Reviewer approves.
# ---------------------------------------------------------------------------

class AuditSetAuditReport(Base):
    __tablename__ = "audit_set_audit_reports"

    id           = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    audit_set_id = Column(String, ForeignKey("audit_sets.id", ondelete="CASCADE"), nullable=False)
    stage_type   = Column(String, nullable=False)   # "stage_1" | "stage_2" | "surveillance" | "recertification"
    report_form  = Column(String, nullable=False)   # "FR.231" | "FR.229" | "FR.232"
    label        = Column(String, nullable=False)   # short description e.g. "Stage 2 Audit Report"
    file_path    = Column(String, nullable=False)
    file_name    = Column(String, nullable=True)

    # ── Lead Auditor signature (party 1) ───────────────────────────────────
    la_user_id      = Column(String, nullable=True)
    la_signed_at    = Column(DateTime, nullable=True)
    la_signed_ip    = Column(String, nullable=True)
    la_otp_hash     = Column(String, nullable=True)
    la_otp_expires  = Column(DateTime, nullable=True)

    # ── Committee Reviewer approval (party 2) ─────────────────────────────
    reviewer_user_id      = Column(String, nullable=True)
    reviewer_signed_at    = Column(DateTime, nullable=True)
    reviewer_signed_ip    = Column(String, nullable=True)
    reviewer_otp_hash     = Column(String, nullable=True)
    reviewer_otp_expires  = Column(DateTime, nullable=True)

    # ── Status ─────────────────────────────────────────────────────────────
    # "pending_la"     → awaiting Lead Auditor signature
    # "pending_review" → LA signed; awaiting committee reviewer approval
    # "approved"       → both signed — report is final
    status       = Column(String, default="pending_la", nullable=False)

    uploaded_by  = Column(String, nullable=True)   # PlatformUser.id of uploader
    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False)
```

No `_safe_add_column` needed — created by `Base.metadata.create_all` on boot.

---

### 2. New file `backend/audit_set/report_router.py`

```python
"""
BATUHAN — FR.231 / FR.229 / FR.232 Audit Report Signing (Prompt 19).

Lead Auditor uploads the report file and signs it (auditor portal).
Committee Reviewer then approves via OTP (CB portal).

Routes:
  POST /audit-sets/{id}/audit-reports/upload             (auditor + admin/planner)
  GET  /audit-sets/{id}/audit-reports                    (CB + auditor)
  GET  /audit-sets/{id}/audit-reports/{rid}/download     (CB + auditor)
  POST /audit-sets/{id}/audit-reports/{rid}/sign/la/request-otp   (lead auditor)
  POST /audit-sets/{id}/audit-reports/{rid}/sign/la/verify         (lead auditor)
  POST /audit-sets/{id}/audit-reports/{rid}/sign/review/request-otp  (committee reviewer)
  POST /audit-sets/{id}/audit-reports/{rid}/sign/review/verify       (committee reviewer)
"""
from __future__ import annotations
import hashlib
import os
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from audit_set.db_models import (
    AuditSet, AuditSetAuditReport, AuditSetCommitteeMember, AuditSetStage, get_db,
)
from auth.db_models import PlatformUser, get_db as get_auth_db
from auth.dependencies import get_current_user
from config.settings import get_settings
from email_service import send_audit_report_review_request, send_otp_code

router = APIRouter(tags=["audit_reports"])

CB_ROLES      = {"admin", "planner", "officer", "executive"}
UPLOAD_ROLES  = {"auditor", "admin", "planner"}
AUDITOR_ROLES = {"auditor", "admin"}
OTP_EXPIRY    = 10  # minutes

VALID_FORMS = {"FR.231", "FR.229", "FR.232"}


def _hash(val: str) -> str:
    return hashlib.sha256(val.encode()).hexdigest()


def _report_dict(
    r: AuditSetAuditReport,
    can_review: bool = False,
) -> dict:
    return {
        "id":              r.id,
        "audit_set_id":    r.audit_set_id,
        "stage_type":      r.stage_type,
        "report_form":     r.report_form,
        "label":           r.label,
        "file_name":       r.file_name,
        "status":          r.status,
        "la_signed_at":    r.la_signed_at.isoformat() if r.la_signed_at else None,
        "reviewer_signed_at": r.reviewer_signed_at.isoformat() if r.reviewer_signed_at else None,
        "created_at":      r.created_at.isoformat() if r.created_at else None,
        # True only when current user is the committee reviewer AND status==pending_review
        "can_review":      can_review,
    }


def _get_committee_reviewer(
    audit_set_id: str,
    current_user: PlatformUser,
    db: Session,
) -> AuditSetCommitteeMember | None:
    """Return the AuditSetCommitteeMember record if current user is the appointed reviewer."""
    return db.query(AuditSetCommitteeMember).filter_by(
        audit_set_id=audit_set_id,
        user_id=current_user.id,
        role="reviewer",
    ).first()


# ── Upload ────────────────────────────────────────────────────────────────────

@router.post("/audit-sets/{audit_set_id}/audit-reports/upload")
async def upload_audit_report(
    audit_set_id: str,
    stage_type:   str = Form(...),
    report_form:  str = Form(...),
    label:        str = Form(...),
    file: UploadFile = File(...),
    db:       Session = Depends(get_db),
    auth_db:  Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """
    Lead Auditor (or CB admin/planner) uploads the formal audit report.
    Creates a record in pending_la status for the Lead Auditor to sign.
    """
    if current_user.role not in UPLOAD_ROLES:
        raise HTTPException(403, "Not authorized to upload audit reports")
    if report_form not in VALID_FORMS:
        raise HTTPException(400, f"report_form must be one of: {sorted(VALID_FORMS)}")

    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Audit set not found")

    settings = get_settings()
    upload_dir = os.path.join(settings.storage_base_path, "audit_reports", audit_set_id)
    os.makedirs(upload_dir, exist_ok=True)

    safe_name = f"{secrets.token_hex(6)}_{file.filename or 'report'}"
    file_path = os.path.join(upload_dir, safe_name)
    content   = await file.read()
    with open(file_path, "wb") as fh:
        fh.write(content)

    report = AuditSetAuditReport(
        audit_set_id=audit_set_id,
        stage_type=stage_type,
        report_form=report_form,
        label=label.strip(),
        file_path=file_path,
        file_name=file.filename or safe_name,
        status="pending_la",
        uploaded_by=current_user.id,
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    return _report_dict(report)


# ── List and download ─────────────────────────────────────────────────────────

@router.get("/audit-sets/{audit_set_id}/audit-reports")
def list_audit_reports(
    audit_set_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in CB_ROLES | AUDITOR_ROLES:
        raise HTTPException(403, "Not authorized")

    is_reviewer = _get_committee_reviewer(audit_set_id, current_user, db) is not None

    rows = (
        db.query(AuditSetAuditReport)
        .filter_by(audit_set_id=audit_set_id)
        .order_by(AuditSetAuditReport.created_at)
        .all()
    )
    return [
        _report_dict(
            r,
            can_review=is_reviewer and r.status == "pending_review",
        )
        for r in rows
    ]


@router.get("/audit-sets/{audit_set_id}/audit-reports/{rid}/download")
def download_audit_report(
    audit_set_id: str,
    rid: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in CB_ROLES | AUDITOR_ROLES:
        raise HTTPException(403, "Not authorized")

    report = db.query(AuditSetAuditReport).filter_by(
        id=rid, audit_set_id=audit_set_id
    ).first()
    if not report:
        raise HTTPException(404, "Report not found")
    if not report.file_path or not os.path.exists(report.file_path):
        raise HTTPException(404, "File not found on server")

    return FileResponse(
        report.file_path,
        filename=report.file_name or "audit_report.docx",
        media_type="application/octet-stream",
    )


# ── Lead Auditor: sign party 1 ───────────────────────────────────────────────

def _check_la_auth(
    report: AuditSetAuditReport,
    current_user: PlatformUser,
    db: Session,
) -> None:
    """Verify current user is the Lead Auditor for this report's stage."""
    if current_user.role == "admin":
        return  # admin bypass for testing

    if current_user.role != "auditor":
        raise HTTPException(403, "Auditor access only")
    if not current_user.auditor_id:
        raise HTTPException(403, "No auditor profile linked to your account")

    stage = (
        db.query(AuditSetStage)
        .filter_by(audit_set_id=report.audit_set_id, stage_type=report.stage_type)
        .order_by(AuditSetStage.stage_order)
        .first()
    )
    if not stage:
        raise HTTPException(404, "Stage not found")
    if stage.lead_auditor_id != current_user.auditor_id:
        raise HTTPException(
            403, "Only the Lead Auditor for this stage may sign the report"
        )


@router.post("/audit-sets/{audit_set_id}/audit-reports/{rid}/sign/la/request-otp")
def la_request_otp(
    audit_set_id: str,
    rid: str,
    db:      Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    report = db.query(AuditSetAuditReport).filter_by(
        id=rid, audit_set_id=audit_set_id
    ).first()
    if not report:
        raise HTTPException(404, "Report not found")
    _check_la_auth(report, current_user, db)
    if report.la_signed_at:
        raise HTTPException(400, "Already signed")

    otp             = f"{secrets.randbelow(900000) + 100000}"
    report.la_otp_hash    = _hash(otp)
    report.la_otp_expires = datetime.utcnow() + timedelta(minutes=OTP_EXPIRY)
    db.commit()

    try:
        send_otp_code(
            to=current_user.email,
            full_name=current_user.full_name,
            otp=otp,
            document_label=f"{report.report_form} — {report.label}",
        )
    except Exception:
        pass

    return {"message": f"Code sent to {current_user.email}. Valid for {OTP_EXPIRY} minutes."}


@router.post("/audit-sets/{audit_set_id}/audit-reports/{rid}/sign/la/verify")
def la_verify_otp(
    audit_set_id: str,
    rid: str,
    otp: str,
    request: Request,
    db:      Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    report = db.query(AuditSetAuditReport).filter_by(
        id=rid, audit_set_id=audit_set_id
    ).first()
    if not report:
        raise HTTPException(404, "Report not found")
    _check_la_auth(report, current_user, db)
    if report.la_signed_at:
        raise HTTPException(400, "Already signed")
    if not report.la_otp_hash or not report.la_otp_expires:
        raise HTTPException(400, "No pending OTP. Request one first.")
    if datetime.utcnow() > report.la_otp_expires:
        raise HTTPException(400, "OTP expired. Please request a new one.")
    if _hash(otp.strip()) != report.la_otp_hash:
        raise HTTPException(400, "Invalid code.")

    report.la_user_id      = current_user.id
    report.la_signed_at    = datetime.utcnow()
    report.la_signed_ip    = request.client.host if request.client else None
    report.la_otp_hash     = None
    report.la_otp_expires  = None
    report.status          = "pending_review"
    db.commit()

    # Notify the appointed committee reviewer
    reviewer = db.query(AuditSetCommitteeMember).filter_by(
        audit_set_id=audit_set_id, role="reviewer"
    ).first()
    if reviewer:
        try:
            audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
            send_audit_report_review_request(
                to=reviewer.user_email,
                full_name=reviewer.user_name,
                company_name=audit_set.company_name if audit_set else audit_set_id,
                stage_label=report.stage_type.replace("_", " ").title(),
                report_form=report.report_form,
                label=report.label,
            )
        except Exception:
            pass

    return {
        "signed": True,
        "status": "pending_review",
        "la_signed_at": report.la_signed_at.isoformat(),
    }


# ── Committee Reviewer: approve party 2 ──────────────────────────────────────

def _check_reviewer_auth(
    report: AuditSetAuditReport,
    current_user: PlatformUser,
    db: Session,
) -> AuditSetCommitteeMember:
    """Verify current user is the appointed committee reviewer for this audit set."""
    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "CB access only")

    member = _get_committee_reviewer(report.audit_set_id, current_user, db)
    if not member:
        raise HTTPException(
            403,
            "You are not the appointed committee reviewer for this audit set. "
            "Contact an admin to assign or reassign the reviewer role.",
        )
    return member


@router.post("/audit-sets/{audit_set_id}/audit-reports/{rid}/sign/review/request-otp")
def review_request_otp(
    audit_set_id: str,
    rid: str,
    db:      Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    report = db.query(AuditSetAuditReport).filter_by(
        id=rid, audit_set_id=audit_set_id
    ).first()
    if not report:
        raise HTTPException(404, "Report not found")
    _check_reviewer_auth(report, current_user, db)
    if report.status != "pending_review":
        raise HTTPException(
            400,
            "Report is not awaiting review. "
            + ("Lead Auditor must sign first." if report.status == "pending_la" else "Already approved.")
        )

    otp = f"{secrets.randbelow(900000) + 100000}"
    report.reviewer_otp_hash    = _hash(otp)
    report.reviewer_otp_expires = datetime.utcnow() + timedelta(minutes=OTP_EXPIRY)
    db.commit()

    try:
        send_otp_code(
            to=current_user.email,
            full_name=current_user.full_name,
            otp=otp,
            document_label=f"{report.report_form} Review — {report.label}",
        )
    except Exception:
        pass

    return {"message": f"Code sent to {current_user.email}. Valid for {OTP_EXPIRY} minutes."}


@router.post("/audit-sets/{audit_set_id}/audit-reports/{rid}/sign/review/verify")
def review_verify_otp(
    audit_set_id: str,
    rid: str,
    otp: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    report = db.query(AuditSetAuditReport).filter_by(
        id=rid, audit_set_id=audit_set_id
    ).first()
    if not report:
        raise HTTPException(404, "Report not found")
    _check_reviewer_auth(report, current_user, db)
    if report.reviewer_signed_at:
        raise HTTPException(400, "Already approved")
    if not report.reviewer_otp_hash or not report.reviewer_otp_expires:
        raise HTTPException(400, "No pending OTP. Request one first.")
    if datetime.utcnow() > report.reviewer_otp_expires:
        raise HTTPException(400, "OTP expired. Please request a new one.")
    if _hash(otp.strip()) != report.reviewer_otp_hash:
        raise HTTPException(400, "Invalid code.")

    report.reviewer_user_id      = current_user.id
    report.reviewer_signed_at    = datetime.utcnow()
    report.reviewer_signed_ip    = request.client.host if request.client else None
    report.reviewer_otp_hash     = None
    report.reviewer_otp_expires  = None
    report.status                = "approved"
    db.commit()

    return {
        "approved": True,
        "status": "approved",
        "reviewer_signed_at": report.reviewer_signed_at.isoformat(),
    }
```

---

### 3. `backend/email_service.py` — add one function

Append before the final blank line:

```python
def send_audit_report_review_request(
    to: str,
    full_name: str,
    company_name: str,
    stage_label: str,
    report_form: str,
    label: str,
) -> bool:
    """Sent to the committee reviewer after the Lead Auditor signs the audit report."""
    settings = get_settings()
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
      <h2 style="color:#1A4731">IFC Global LLC — Audit Report Ready for Review</h2>
      <p>Dear {full_name},</p>
      <p>The Lead Auditor has signed the audit report for <strong>{company_name}</strong>
         ({stage_label}). As the appointed committee reviewer, your approval is required
         before the report can be finalised.</p>
      <div style="background:#f5f5f5;padding:16px;border-radius:6px;margin:16px 0">
        <p style="margin:0"><strong>Form:</strong> {report_form}</p>
        <p style="margin:4px 0 0"><strong>Report:</strong> {label}</p>
      </div>
      <p>Please log in to the portal, navigate to the client record, and approve the
         report under the <strong>Audit Reports</strong> section.</p>
      <p><a href="{settings.email_base_url}/app/clients"
            style="background:#1A4731;color:white;padding:10px 20px;border-radius:4px;
                   text-decoration:none">Go to Portal</a></p>
      <p style="color:#666;font-size:12px">IFC Global LLC · application@ifcglobal.us</p>
    </div>
    """
    return _send(
        to,
        f"IFC Global — Audit Report Ready for Review: {company_name}",
        html,
    )
```

---

### 4. `backend/main.py` — register router

```python
from audit_set.report_router import router as report_router
app.include_router(report_router)
```

Place alongside the other audit_set routers.

---

## Frontend

### 5. New file `frontend/src/components/ui/AuditReportSection.tsx`

CB portal — view all reports, approve pending ones (if assigned reviewer).

```tsx
'use client'

import { useEffect, useRef, useState } from 'react'
import api from '@/lib/api'

interface AuditReport {
  id:                   string
  stage_type:           string
  report_form:          string
  label:                string
  file_name:            string | null
  status:               string
  la_signed_at:         string | null
  reviewer_signed_at:   string | null
  can_review:           boolean
  created_at:           string
}

const STAGE_LABELS: Record<string, string> = {
  stage_1: 'Stage 1', stage_2: 'Stage 2',
  surveillance: 'Surveillance', recertification: 'Recertification',
}

const STATUS_CONFIG: Record<string, { label: string; chip: string }> = {
  pending_la:     { label: 'Awaiting Lead Auditor',  chip: 'bg-amber-100 text-amber-700' },
  pending_review: { label: 'Awaiting Review',         chip: 'bg-blue-100 text-blue-700' },
  approved:       { label: 'Approved',                chip: 'bg-green-100 text-green-700' },
}

function fmtDate(iso: string | null) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric',
  })
}

export function AuditReportSection({
  auditSetId,
  workflowStatus,
}: {
  auditSetId: string
  workflowStatus: string | null
}) {
  const [reports, setReports]   = useState<AuditReport[]>([])
  const [loading, setLoading]   = useState(true)
  const [otpStates, setOtpStates] = useState<Record<string, 'idle' | 'otp_sent' | 'done'>>({})
  const [otpValues, setOtpValues] = useState<Record<string, string>>({})
  const [messages, setMessages]   = useState<Record<string, string>>({})
  const [busy, setBusy]           = useState<Record<string, boolean>>({})

  // Show from audit_in_progress onwards
  const relevantStatuses = new Set([
    'audit_in_progress', 'under_review', 'certified',
  ])
  if (!workflowStatus || !relevantStatuses.has(workflowStatus)) return null

  async function load() {
    try {
      const r = await api.get<AuditReport[]>(`/audit-sets/${auditSetId}/audit-reports`)
      setReports(r.data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [auditSetId])

  async function download(id: string, fileName: string | null) {
    const r = await api.get(`/audit-sets/${auditSetId}/audit-reports/${id}/download`, {
      responseType: 'blob',
    })
    const url = window.URL.createObjectURL(new Blob([r.data]))
    const a   = document.createElement('a')
    a.href = url; a.download = fileName || 'report.docx'
    document.body.appendChild(a); a.click(); a.remove()
    window.URL.revokeObjectURL(url)
  }

  async function requestReviewOtp(id: string) {
    setBusy(b => ({ ...b, [id]: true }))
    setMessages(m => ({ ...m, [id]: '' }))
    try {
      await api.post(`/audit-sets/${auditSetId}/audit-reports/${id}/sign/review/request-otp`)
      setOtpStates(s => ({ ...s, [id]: 'otp_sent' }))
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setMessages(m => ({ ...m, [id]: detail || 'Failed to send code' }))
    } finally {
      setBusy(b => ({ ...b, [id]: false }))
    }
  }

  async function verifyReviewOtp(id: string) {
    setBusy(b => ({ ...b, [id]: true }))
    setMessages(m => ({ ...m, [id]: '' }))
    try {
      await api.post(
        `/audit-sets/${auditSetId}/audit-reports/${id}/sign/review/verify?otp=${otpValues[id] ?? ''}`,
      )
      setOtpStates(s => ({ ...s, [id]: 'done' }))
      setReports(prev => prev.map(r =>
        r.id === id
          ? { ...r, status: 'approved', reviewer_signed_at: new Date().toISOString(), can_review: false }
          : r,
      ))
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setMessages(m => ({ ...m, [id]: detail || 'Invalid code' }))
    } finally {
      setBusy(b => ({ ...b, [id]: false }))
    }
  }

  return (
    <div className="mt-6">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-700">
        Audit Reports (FR.231 / FR.229 / FR.232)
      </h2>

      {loading ? (
        <p className="text-xs text-gray-400">Loading…</p>
      ) : reports.length === 0 ? (
        <div className="rounded-xl border bg-white px-4 py-6 text-center text-xs text-gray-400">
          No reports uploaded yet. Lead Auditors upload from the Reports tab in their portal.
        </div>
      ) : (
        <div className="space-y-2">
          {reports.map(r => {
            const cfg   = STATUS_CONFIG[r.status] ?? { label: r.status, chip: 'bg-gray-100 text-gray-500' }
            const state = otpStates[r.id] || 'idle'

            return (
              <div key={r.id} className={`rounded-xl border bg-white p-4 ${r.can_review && r.status === 'pending_review' ? 'border-blue-200' : ''}`}>
                <div className="mb-2 flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="font-medium text-gray-800 truncate">{r.label}</p>
                    <p className="mt-0.5 text-xs text-gray-400">
                      {STAGE_LABELS[r.stage_type] ?? r.stage_type} · {r.report_form}
                      {r.la_signed_at && ` · LA signed ${fmtDate(r.la_signed_at)}`}
                      {r.reviewer_signed_at && ` · Approved ${fmtDate(r.reviewer_signed_at)}`}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${cfg.chip}`}>
                      {cfg.label}
                    </span>
                    <button
                      type="button"
                      onClick={() => download(r.id, r.file_name)}
                      className="text-xs text-[#1A4731] underline"
                    >
                      Download
                    </button>
                  </div>
                </div>

                {/* Reviewer approval flow (only for assigned reviewer) */}
                {r.can_review && state === 'idle' && (
                  <button
                    type="button"
                    onClick={() => requestReviewOtp(r.id)}
                    disabled={busy[r.id]}
                    className="mt-1 rounded-lg bg-[#1A4731] px-4 py-2 text-sm text-white disabled:opacity-40 hover:bg-[#143828]"
                  >
                    {busy[r.id] ? 'Sending code…' : 'Review & Approve'}
                  </button>
                )}

                {r.can_review && state === 'otp_sent' && (
                  <div className="mt-2 flex items-center gap-3">
                    <input
                      className="w-36 rounded-lg border px-3 py-2 text-center font-mono text-lg tracking-widest focus:outline-none focus:ring-2 focus:ring-[#1A4731]/30"
                      placeholder="000000" maxLength={6}
                      value={otpValues[r.id] ?? ''}
                      onChange={e => setOtpValues(v => ({
                        ...v, [r.id]: e.target.value.replace(/\D/g, ''),
                      }))}
                    />
                    <button
                      type="button"
                      onClick={() => verifyReviewOtp(r.id)}
                      disabled={(otpValues[r.id] ?? '').length !== 6 || busy[r.id]}
                      className="rounded-lg bg-[#1A4731] px-4 py-2 text-sm text-white disabled:opacity-40"
                    >
                      {busy[r.id] ? '…' : 'Confirm Approval'}
                    </button>
                    <button
                      type="button"
                      onClick={() => requestReviewOtp(r.id)}
                      className="text-xs text-gray-400 underline"
                    >
                      Resend
                    </button>
                  </div>
                )}

                {state === 'done' && (
                  <p className="mt-1 text-sm font-medium text-green-600">Report approved ✓</p>
                )}
                {messages[r.id] && (
                  <p className="mt-1 text-xs text-red-500">{messages[r.id]}</p>
                )}
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

### 6. `frontend/src/app/(auditor)/auditor/audit/[id]/page.tsx` — add "Reports" tab

**Step A — Add `'reports'` to the Tab type:**

```tsx
type Tab = 'overview' | 'messages' | 'upload' | 'attendees' | 'nc_forms' | 'declarations' | 'reports'
```

**Step B — Add `AuditorReportsView` component** (add after `AuditorDeclarationsView`, before `export default`):

```tsx
const STAGE_OPTS_REPORTS = [
  { value: 'stage_1',         label: 'Stage 1' },
  { value: 'stage_2',         label: 'Stage 2' },
  { value: 'surveillance',    label: 'Surveillance' },
  { value: 'recertification', label: 'Recertification' },
]

const FORM_OPTS = [
  { value: 'FR.231', label: 'FR.231 — Stage 1 Audit Report' },
  { value: 'FR.232', label: 'FR.232 — Stage 2 / Surveillance / Recertification Report' },
  { value: 'FR.229', label: 'FR.229 — ISMS/PIMS Audit Report (ISO 27001)' },
]

function AuditorReportsView({ auditSetId }: { auditSetId: string }) {
  const [reports, setReports] = useState<{
    id: string; stage_type: string; report_form: string; label: string
    file_name: string | null; status: string
    la_signed_at: string | null; reviewer_signed_at: string | null
  }[]>([])
  const [loading, setLoading]   = useState(true)
  const [showUpload, setShowUpload] = useState(false)
  const [form, setForm]   = useState({ stage_type: 'stage_1', report_form: 'FR.231', label: '' })
  const [file, setFile]   = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadMsg, setUploadMsg] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)
  // OTP state per report
  const [otpState, setOtpState] = useState<Record<string, 'idle' | 'otp_sent' | 'done'>>({})
  const [otpValues, setOtpValues] = useState<Record<string, string>>({})
  const [messages, setMessages]   = useState<Record<string, string>>({})
  const [busy, setBusy]           = useState<Record<string, boolean>>({})

  const STAGE_LABELS: Record<string, string> = {
    stage_1: 'Stage 1', stage_2: 'Stage 2',
    surveillance: 'Surveillance', recertification: 'Recertification',
  }
  const STATUS_CONFIG: Record<string, { label: string; chip: string }> = {
    pending_la:     { label: 'Signature Required',  chip: 'bg-amber-100 text-amber-700' },
    pending_review: { label: 'Awaiting CB Review',   chip: 'bg-blue-100 text-blue-700' },
    approved:       { label: 'Approved ✓',           chip: 'bg-green-100 text-green-700' },
  }

  async function load() {
    try {
      const r = await api.get(`/audit-sets/${auditSetId}/audit-reports`)
      setReports(r.data as typeof reports)
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { load() }, [auditSetId])

  async function download(id: string, fileName: string | null) {
    const r = await api.get(`/audit-sets/${auditSetId}/audit-reports/${id}/download`, {
      responseType: 'blob',
    })
    const url = window.URL.createObjectURL(new Blob([r.data]))
    const a   = document.createElement('a')
    a.href = url; a.download = fileName || 'report.docx'
    document.body.appendChild(a); a.click(); a.remove()
    window.URL.revokeObjectURL(url)
  }

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault()
    if (!file || !form.label.trim()) return
    setUploading(true)
    setUploadMsg('')
    try {
      const fd = new FormData()
      fd.append('stage_type', form.stage_type)
      fd.append('report_form', form.report_form)
      fd.append('label', form.label.trim())
      fd.append('file', file)
      const r = await api.post(`/audit-sets/${auditSetId}/audit-reports/upload`, fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setReports(prev => [...prev, r.data as typeof reports[0]])
      setForm({ stage_type: 'stage_1', report_form: 'FR.231', label: '' })
      setFile(null)
      if (fileRef.current) fileRef.current.value = ''
      setShowUpload(false)
      setUploadMsg('')
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setUploadMsg(detail || 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  async function requestOtp(id: string) {
    setBusy(b => ({ ...b, [id]: true }))
    setMessages(m => ({ ...m, [id]: '' }))
    try {
      await api.post(`/audit-sets/${auditSetId}/audit-reports/${id}/sign/la/request-otp`)
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
      await api.post(
        `/audit-sets/${auditSetId}/audit-reports/${id}/sign/la/verify?otp=${otpValues[id] ?? ''}`,
      )
      setOtpState(s => ({ ...s, [id]: 'done' }))
      setReports(prev => prev.map(r =>
        r.id === id
          ? { ...r, status: 'pending_review', la_signed_at: new Date().toISOString() }
          : r,
      ))
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setMessages(m => ({ ...m, [id]: detail || 'Invalid code' }))
    } finally {
      setBusy(b => ({ ...b, [id]: false }))
    }
  }

  if (loading) return <p className="text-sm text-gray-400">Loading…</p>

  const pending  = reports.filter(r => r.status === 'pending_la')
  const uploaded = reports.filter(r => r.status !== 'pending_la')

  return (
    <div className="space-y-5">
      {/* Upload button */}
      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => { setShowUpload(!showUpload); setUploadMsg('') }}
          className="rounded-lg border border-[#1A4731] px-3 py-1.5 text-xs font-medium text-[#1A4731] hover:bg-green-50"
        >
          {showUpload ? 'Cancel' : '+ Upload Report'}
        </button>
      </div>

      {/* Upload form */}
      {showUpload && (
        <form
          onSubmit={handleUpload}
          className="space-y-3 rounded-xl border border-amber-200 bg-amber-50 p-4"
        >
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-600">Stage</label>
              <select
                value={form.stage_type}
                onChange={e => setForm(f => ({ ...f, stage_type: e.target.value }))}
                className="w-full rounded-lg border bg-white px-3 py-2 text-sm"
              >
                {STAGE_OPTS_REPORTS.map(s => (
                  <option key={s.value} value={s.value}>{s.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-600">Report Form</label>
              <select
                value={form.report_form}
                onChange={e => setForm(f => ({ ...f, report_form: e.target.value }))}
                className="w-full rounded-lg border bg-white px-3 py-2 text-sm"
              >
                {FORM_OPTS.map(o => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-600">Label</label>
            <input
              required
              value={form.label}
              onChange={e => setForm(f => ({ ...f, label: e.target.value }))}
              placeholder="e.g. Stage 2 Audit Report — ACME Manufacturing"
              className="w-full rounded-lg border bg-white px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-gray-600">File</label>
            <input
              ref={fileRef}
              required type="file"
              onChange={e => setFile(e.target.files?.[0] || null)}
              className="text-sm"
            />
          </div>
          <button
            type="submit"
            disabled={uploading || !file || !form.label.trim()}
            className="rounded-lg bg-[#1A4731] px-4 py-2 text-sm text-white disabled:opacity-40"
          >
            {uploading ? 'Uploading…' : 'Upload Report'}
          </button>
          {uploadMsg && <p className="text-xs text-red-600">{uploadMsg}</p>}
        </form>
      )}

      {/* My pending reports — sign flow */}
      {pending.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-amber-600">
            Awaiting Your Signature
          </p>
          {pending.map(r => {
            const state = otpState[r.id] || 'idle'
            const cfg   = STATUS_CONFIG[r.status] ?? { label: r.status, chip: '' }
            return (
              <div key={r.id} className="rounded-xl border border-amber-200 bg-amber-50 p-4">
                <div className="mb-3 flex items-start justify-between">
                  <div>
                    <p className="font-medium text-gray-800">{r.label}</p>
                    <p className="text-xs text-gray-400">
                      {STAGE_LABELS[r.stage_type] ?? r.stage_type} · {r.report_form}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${cfg.chip}`}>
                      {cfg.label}
                    </span>
                    <button
                      type="button"
                      onClick={() => download(r.id, r.file_name)}
                      className="text-xs text-[#1A4731] underline"
                    >
                      Download
                    </button>
                  </div>
                </div>
                {state === 'idle' && (
                  <button
                    type="button"
                    onClick={() => requestOtp(r.id)}
                    disabled={busy[r.id]}
                    className="rounded-lg bg-[#1A4731] px-4 py-2 text-sm text-white disabled:opacity-40"
                  >
                    {busy[r.id] ? 'Sending…' : 'Sign Report'}
                  </button>
                )}
                {state === 'otp_sent' && (
                  <div className="flex items-center gap-3">
                    <input
                      className="w-36 rounded-lg border px-3 py-2 text-center font-mono text-lg tracking-widest"
                      placeholder="000000" maxLength={6}
                      value={otpValues[r.id] ?? ''}
                      onChange={e => setOtpValues(v => ({
                        ...v, [r.id]: e.target.value.replace(/\D/g, ''),
                      }))}
                    />
                    <button
                      type="button"
                      onClick={() => verifyOtp(r.id)}
                      disabled={(otpValues[r.id] ?? '').length !== 6 || busy[r.id]}
                      className="rounded-lg bg-[#1A4731] px-4 py-2 text-sm text-white disabled:opacity-40"
                    >
                      {busy[r.id] ? '…' : 'Confirm'}
                    </button>
                    <button
                      type="button"
                      onClick={() => requestOtp(r.id)}
                      className="text-xs text-gray-400 underline"
                    >
                      Resend
                    </button>
                  </div>
                )}
                {state === 'done' && (
                  <p className="text-sm font-medium text-green-600">
                    Report signed ✓ — sent to CB for review.
                  </p>
                )}
                {messages[r.id] && (
                  <p className="mt-1 text-xs text-red-500">{messages[r.id]}</p>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Other reports (pending_review / approved) */}
      {uploaded.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
            Submitted
          </p>
          <div className="rounded-xl border bg-white divide-y divide-gray-50">
            {uploaded.map(r => {
              const cfg = STATUS_CONFIG[r.status] ?? { label: r.status, chip: 'bg-gray-100 text-gray-500' }
              return (
                <div key={r.id} className="flex items-center justify-between px-4 py-3">
                  <div>
                    <p className="text-sm font-medium text-gray-800">{r.label}</p>
                    <p className="text-xs text-gray-400">
                      {STAGE_LABELS[r.stage_type] ?? r.stage_type} · {r.report_form}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${cfg.chip}`}>
                      {cfg.label}
                    </span>
                    <button
                      type="button"
                      onClick={() => download(r.id, r.file_name)}
                      className="text-xs text-[#1A4731] underline"
                    >
                      Download
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {reports.length === 0 && !showUpload && (
        <p className="py-8 text-center text-sm text-gray-400">
          No reports uploaded yet. Click "+ Upload Report" to begin.
        </p>
      )}
    </div>
  )
}
```

**Step C — Add tab button and panel:**

Add `'reports'` to the tabs array:
```tsx
{(['overview', 'messages', 'upload', 'attendees', 'nc_forms', 'declarations', 'reports'] as const).map((t) => (
  <button ...>
    {t === 'upload' ? 'Upload Documents'
     : t === 'attendees' ? 'Attendees'
     : t === 'nc_forms' ? 'NC Forms'
     : t === 'declarations' ? 'Declarations'
     : t === 'reports' ? 'Reports'
     : t}
  </button>
))}
```

Add panel after the `{tab === 'declarations' && ...}` block:
```tsx
{tab === 'reports' && (
  <AuditorReportsView auditSetId={id} />
)}
```

---

### 7. `frontend/src/app/(app)/clients/[id]/page.tsx` — wire AuditReportSection

Add import:
```tsx
import { AuditReportSection } from '@/components/ui/AuditReportSection'
```

Add **after** `<DeclarationManagementSection …/>`:
```tsx
<AuditReportSection
  auditSetId={id}
  workflowStatus={data.workflow_status ?? null}
/>
```

---

## Verification

1. `python3 -m py_compile backend/audit_set/report_router.py backend/audit_set/db_models.py backend/email_service.py`
2. `cd frontend && npx tsc --noEmit`
3. Auditor upload + LA sign:
   a. Auditor logs in → `/auditor/audit/{id}` → "Reports" tab → "+ Upload Report"
   b. Select Stage 2, FR.232, enter label, attach file → Upload
   c. Report appears in "Awaiting Your Signature" amber card with Download link
   d. "Sign Report" → OTP → confirm → status changes to "Awaiting CB Review"
   e. Committee reviewer receives email notification
4. Committee Reviewer approval (CB portal):
   a. Reviewer logs in → `/clients/{id}` → "Audit Reports" section
   b. Report shows with "Awaiting Review" chip + blue border
   c. "Review & Approve" button visible (only to assigned reviewer, not other CB users)
   d. OTP → "Confirm Approval" → "Report approved ✓"
   e. Status chip changes to "Approved ✓" green for all CB users
5. Non-reviewer CB user: sees the report but NO "Review & Approve" button (server returns `can_review: false`)
6. Guard — reviewer trying to approve a `pending_la` report → 400 "Lead Auditor must sign first"
7. Guard — non-Lead-Auditor trying to sign → 403 "Only the Lead Auditor for this stage may sign the report"
8. Guard — non-reviewer CB user calling review/request-otp → 403 "You are not the appointed committee reviewer"
9. Empty state: Reports tab with no uploads → "No reports uploaded yet. Click + Upload Report to begin."
10. Commit and push to main

## Constraints
DO NOT modify any other file beyond what is listed.

New files:
- `backend/audit_set/report_router.py`
- `frontend/src/components/ui/AuditReportSection.tsx`

Modified files:
- `backend/audit_set/db_models.py` — add `AuditSetAuditReport`
- `backend/email_service.py` — add `send_audit_report_review_request`
- `backend/main.py` — register report_router
- `frontend/src/app/(auditor)/auditor/audit/[id]/page.tsx` — add AuditorReportsView + Reports tab
- `frontend/src/app/(app)/clients/[id]/page.tsx` — wire AuditReportSection
