"""
BATUHAN — FR.231 / FR.229 / FR.232 Audit Report Signing.

Lead Auditor uploads and signs via direct-sign (auditor portal).
Assigned Reviewer Auditor (or CM/admin bypass) approves via direct-sign.

Routes:
  POST /audit-sets/{id}/audit-reports/upload                     (auditor + admin/planner)
  GET  /audit-sets/{id}/audit-reports                            (CB + auditor)
  GET  /audit-sets/{id}/audit-reports/reviewer-candidates        (CB)
  GET  /audit-sets/{id}/audit-reports/{rid}/download             (CB + auditor)
  PUT  /audit-sets/{id}/audit-reports/{rid}/reviewer             (planner/admin)
  POST /audit-sets/{id}/audit-reports/{rid}/sign/la/direct       (lead auditor)
  POST /audit-sets/{id}/audit-reports/{rid}/sign/review/direct   (reviewer auditor / CM)
"""
from __future__ import annotations
import os
import secrets
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from audit_set.db_models import (
    AuditSet, AuditSetAuditReport, AuditSetCommitteeMember,
    AuditSetStage, AuditSetStatusEvent, get_db,
)
from auth.db_models import PlatformUser, get_db as get_auth_db
from auth.dependencies import get_current_user
from config.settings import get_settings
from email_service import (
    send_audit_report_review_request,
    send_client_status_update,
)

router = APIRouter(tags=["audit_reports"])

# Portal 75 — certification_manager added so the CM can list, download and
# approve audit reports (same access as other CB staff).
CB_ROLES      = {"admin", "planner", "planner_us", "officer", "executive", "gm", "certification_manager"}
UPLOAD_ROLES  = {"auditor", "admin", "planner", "planner_us"}
AUDITOR_ROLES = {"auditor", "admin"}
# (OTP_EXPIRY removed — OTP signing was removed system-wide)

VALID_FORMS = {"FR.231", "FR.229", "FR.232"}

# Portal 76 — maps AuditSet.standards abbreviations to ISO standard names
# (same mapping as committee_router._STD_CODE_TO_ISO).
_STD_CODE_TO_ISO: dict[str, str] = {
    "QMS":   "ISO 9001",
    "EMS":   "ISO 14001",
    "OHSMS": "ISO 45001",
    "FSMS":  "ISO 22000",
    "ISMS":  "ISO 27001",
    "MDQMS": "ISO 13485",
    "ENMS":  "ISO 50001",
    "ABMS":  "ISO 37001",
}





def _report_dict(r: AuditSetAuditReport, can_review: bool = False) -> dict:
    return {
        "id":                     r.id,
        "audit_set_id":           r.audit_set_id,
        "stage_type":             r.stage_type,
        "report_form":            r.report_form,
        "label":                  r.label,
        "file_name":              r.file_name,
        "status":                 r.status,
        "la_signed_at":           r.la_signed_at.isoformat() if r.la_signed_at else None,
        "reviewer_signed_at":     r.reviewer_signed_at.isoformat() if r.reviewer_signed_at else None,
        "created_at":             r.created_at.isoformat() if r.created_at else None,
        "can_review":             can_review,
        # Portal 76 — reviewer assignment
        "reviewer_auditor_id":    r.reviewer_auditor_id,
        "reviewer_auditor_name":  r.reviewer_auditor_name,
    }


def _get_committee_reviewer(
    audit_set_id: str, current_user: PlatformUser, db: Session,
) -> AuditSetCommitteeMember | None:
    return db.query(AuditSetCommitteeMember).filter_by(
        audit_set_id=audit_set_id, user_id=current_user.id, role="reviewer",
    ).first()


# ── Upload ────────────────────────────────────────────────────────────────────

@router.post("/audit-sets/{audit_set_id}/audit-reports/upload")
async def upload_audit_report(
    audit_set_id: str,
    stage_type:   str = Form(...),
    report_form:  str = Form(...),
    label:        str = Form(...),
    report_date:  Optional[date] = Form(None),
    file: UploadFile = File(...),
    db:       Session = Depends(get_db),
    auth_db:  Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
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

    record_date = datetime.combine(report_date, datetime.min.time()) if report_date else datetime.utcnow()
    report = AuditSetAuditReport(
        audit_set_id=audit_set_id,
        stage_type=stage_type,
        report_form=report_form,
        label=label.strip(),
        file_path=file_path,
        file_name=file.filename or safe_name,
        status="pending_la",
        uploaded_by=current_user.id,
        created_at=record_date,
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

    # Portal 76 — CM/admin bypass, assigned auditor reviewer, or legacy committee reviewer.
    is_cm = current_user.role in ("certification_manager", "admin", "executive")
    is_assigned_reviewer = (
        current_user.role == "auditor"
        and current_user.auditor_id is not None
    )
    is_reviewer = (
        is_cm
        or is_assigned_reviewer  # can_review per-report determined below
        or (_get_committee_reviewer(audit_set_id, current_user, db) is not None)
    )

    rows = (
        db.query(AuditSetAuditReport)
        .filter_by(audit_set_id=audit_set_id)
        .order_by(AuditSetAuditReport.created_at)
        .all()
    )

    def _can_review(r: AuditSetAuditReport) -> bool:
        if r.status != "pending_review":
            return False
        if is_cm:
            return True
        if is_assigned_reviewer:
            return (r.reviewer_auditor_id is not None
                    and current_user.auditor_id == r.reviewer_auditor_id)
        return is_reviewer  # legacy committee reviewer

    return [_report_dict(r, can_review=_can_review(r)) for r in rows]



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


class SignReportBody(BaseModel):
    signed_date: Optional[date] = None


# ── Lead Auditor: direct-sign ────────────────────────────────────────────────

@router.post("/audit-sets/{audit_set_id}/audit-reports/{rid}/sign/la/direct")
def la_sign_direct(
    audit_set_id: str,
    rid:     str,
    request: Request,
    body:    SignReportBody = Body(default_factory=SignReportBody),
    db:      Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    report = db.query(AuditSetAuditReport).filter_by(
        id=rid, audit_set_id=audit_set_id
    ).first()
    if not report:
        raise HTTPException(404, "Report not found")
    _check_la_auth(report, current_user, db)
    if report.la_signed_at:
        raise HTTPException(400, "Report already signed by Lead Auditor")
    if report.status not in ("pending_la",):
        raise HTTPException(400, f"Report status is '{report.status}', expected 'pending_la'")

    report.la_user_id   = current_user.id
    report.la_signed_at = (
        datetime.combine(body.signed_date, datetime.min.time())
        if body.signed_date else datetime.utcnow()
    )
    report.la_signed_ip = request.client.host if request.client else None
    report.status       = "pending_review"
    db.commit()

    # Notify assigned reviewer that the report is ready for their signature.
    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    _notify_reviewer(db, report, audit_set)

    db.refresh(report)
    return _report_dict(report)


# ── Committee Reviewer: approve party 2 ──────────────────────────────────────

def _notify_reviewer(
    db: Session,
    report: AuditSetAuditReport,
    audit_set,
) -> None:
    """Send review-request email to the assigned reviewer (auditor or committee member)."""
    company = (audit_set.company_name if audit_set else report.audit_set_id) or ""
    stage   = report.stage_type.replace("_", " ").title()

    # Prefer assigned auditor reviewer (Portal 76)
    if report.reviewer_auditor_id:
        from auditors.models import Auditor as _Auditor
        auditor = db.query(_Auditor).filter_by(id=report.reviewer_auditor_id).first()
        if auditor and auditor.email:
            try:
                send_audit_report_review_request(
                    to=auditor.email,
                    full_name=auditor.name,
                    company_name=company,
                    stage_label=stage,
                    report_form=report.report_form,
                    label=report.label,
                )
            except Exception:
                pass
            return

    # Fallback: legacy committee reviewer
    reviewer = db.query(AuditSetCommitteeMember).filter_by(
        audit_set_id=report.audit_set_id, role="reviewer"
    ).first()
    if reviewer:
        try:
            send_audit_report_review_request(
                to=reviewer.user_email,
                full_name=reviewer.user_name,
                company_name=company,
                stage_label=stage,
                report_form=report.report_form,
                label=report.label,
            )
        except Exception:
            pass


def _check_reviewer_auth(
    report: AuditSetAuditReport,
    current_user: PlatformUser,
    db: Session,
) -> None:
    """Verify current user may sign the reviewer slot.

    Priority order:
    1. Admin / certification_manager / executive — always allowed (bypass).
    2. Auditor whose auditor_id matches report.reviewer_auditor_id.
    3. CB staff member who is the appointed AuditSetCommitteeMember reviewer
       (backward-compat fallback).
    """
    # 1. Admin/CM bypass
    if current_user.role in ("admin", "certification_manager", "executive"):
        return

    # 2. Assigned auditor reviewer
    if current_user.role == "auditor":
        if not report.reviewer_auditor_id:
            raise HTTPException(
                403,
                "No reviewer has been assigned to this report yet. "
                "Ask a planner to assign a reviewer.",
            )
        if current_user.auditor_id != report.reviewer_auditor_id:
            raise HTTPException(
                403, "You are not the assigned reviewer for this report."
            )
        return

    # 3. Legacy CB committee reviewer fallback
    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "Not authorised to review this report.")
    member = _get_committee_reviewer(report.audit_set_id, current_user, db)
    if not member:
        raise HTTPException(
            403,
            "You are not the appointed committee reviewer for this audit set. "
            "Contact an admin to assign or reassign the reviewer role.",
        )


# ── Reviewer: direct-sign (Portal 77 — only signing path, no OTP) ────────────

@router.post("/audit-sets/{audit_set_id}/audit-reports/{rid}/sign/review/direct")
def review_sign_direct(
    audit_set_id: str,
    rid:     str,
    request: Request,
    body:    SignReportBody = Body(default_factory=SignReportBody),
    db:      Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    # Fetch once — 404 first, then auth.
    report = db.query(AuditSetAuditReport).filter_by(
        id=rid, audit_set_id=audit_set_id
    ).first()
    if not report:
        raise HTTPException(404, "Report not found")

    _check_reviewer_auth(report, current_user, db)

    if report.status == "approved":
        raise HTTPException(400, "Report already approved")
    if report.status != "pending_review":
        raise HTTPException(400, f"Report status is '{report.status}', expected 'pending_review'")

    signed_dt = (
        datetime.combine(body.signed_date, datetime.min.time())
        if body.signed_date else datetime.utcnow()
    )
    report.reviewer_user_id   = current_user.id
    report.reviewer_signed_at = signed_dt
    report.reviewer_signed_ip = request.client.host if request.client else None
    report.status             = "approved"
    db.commit()

    # ── Auto-advance workflow: under_review → certified ───────────────────────
    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if audit_set and audit_set.workflow_status == "under_review":
        audit_set.workflow_status  = "certified"
        audit_set.cert_issued_date = body.signed_date or datetime.utcnow().date()
        db.add(AuditSetStatusEvent(
            audit_set_id=audit_set_id,
            from_status="under_review",
            to_status="certified",
            triggered_by=current_user.id,
            notes=(
                f"Audit report '{report.report_form} — {report.label}' "
                "approved by assigned reviewer."
            ),
        ))
        db.commit()

        # Notify client — best-effort
        try:
            client_user = auth_db.query(PlatformUser).filter_by(
                audit_set_id=audit_set_id, role="client",
            ).first()
            if client_user:
                send_client_status_update(
                    to=client_user.email,
                    full_name=client_user.full_name,
                    new_status="certified",
                    notes=(
                        "Your audit report has been reviewed and approved "
                        "by the certification committee."
                    ),
                )
        except Exception:
            pass

    db.refresh(report)
    return _report_dict(report, can_review=False)


# ── Reviewer assignment (Portal 76) ──────────────────────────────────────────

class AssignReviewerBody(BaseModel):
    auditor_id: str


@router.put("/audit-sets/{audit_set_id}/audit-reports/{rid}/reviewer")
def assign_reviewer(
    audit_set_id: str,
    rid:          str,
    body:         AssignReviewerBody,
    db:      Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """Assign or re-assign a reviewer auditor to this report.

    The auditor must have at least one standard qualification overlapping with
    the audit set's standards.  Planner/admin only.
    """
    if current_user.role not in ("admin", "planner", "planner_us", "certification_manager", "executive"):
        raise HTTPException(403, "Planner or admin access required")

    report = db.query(AuditSetAuditReport).filter_by(
        id=rid, audit_set_id=audit_set_id
    ).first()
    if not report:
        raise HTTPException(404, "Report not found")

    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Audit set not found")

    from auditors.models import Auditor as _Auditor, AuditorStandardQualification as _ASQ
    auditor = db.query(_Auditor).filter_by(id=body.auditor_id).first()
    if not auditor:
        raise HTTPException(404, "Auditor not found")

    # Eligibility: auditor must cover at least one audit standard
    audit_iso = {_STD_CODE_TO_ISO.get(s, s) for s in (audit_set.standards or [])}
    if audit_iso:
        qualified_isos = {
            q.standard_code
            for q in db.query(_ASQ).filter_by(
                auditor_id=body.auditor_id, is_qualified=True
            ).all()
            if q.standard_code
        }
        # Normalise: strip "ISO " prefix and spaces for loose matching
        def _norm(s: str) -> str:
            return s.lower().replace("iso ", "").replace(" ", "").replace("/iec", "")
        audit_norms     = {_norm(s) for s in audit_iso}
        qualified_norms = {_norm(s) for s in qualified_isos}
        if not audit_norms.intersection(qualified_norms):
            raise HTTPException(
                400,
                f"Auditor '{auditor.name}' does not cover any of the required standards: "
                f"{', '.join(sorted(audit_set.standards or []))}."
            )

    report.reviewer_auditor_id   = auditor.id
    report.reviewer_auditor_name = auditor.name
    db.commit()
    db.refresh(report)
    return _report_dict(report)


@router.get("/audit-sets/{audit_set_id}/audit-reports/reviewer-candidates")
def get_reviewer_candidates(
    audit_set_id: str,
    db:      Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """List auditors eligible to be assigned as reviewer for this audit set.

    An auditor is eligible if they cover at least one standard of the audit.
    """
    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "CB access only")

    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Audit set not found")

    from auditors.models import Auditor as _Auditor, AuditorStandardQualification as _ASQ

    audit_iso = {_STD_CODE_TO_ISO.get(s, s) for s in (audit_set.standards or [])}

    def _norm(s: str) -> str:
        return s.lower().replace("iso ", "").replace(" ", "").replace("/iec", "")

    audit_norms = {_norm(s) for s in audit_iso}

    all_auditors = db.query(_Auditor).filter_by(is_active=True).all()
    results = []
    for a in all_auditors:
        qualifications = db.query(_ASQ).filter_by(
            auditor_id=a.id, is_qualified=True
        ).all()
        qualified_norms = {_norm(q.standard_code) for q in qualifications if q.standard_code}
        covers = not audit_norms or bool(audit_norms.intersection(qualified_norms))
        if covers:
            results.append({
                "id":           a.id,
                "name":         a.name,
                "email":        a.email,
                "standards":    [q.standard_code for q in qualifications if q.standard_code],
                "covers_audit": covers,
            })
    results.sort(key=lambda x: x["name"] or "")
    return results
