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
    AuditSet, AuditSetAuditReport, AuditSetCommitteeMember,
    AuditSetStage, AuditSetStatusEvent, get_db,
)
from auth.db_models import PlatformUser, get_db as get_auth_db
from auth.dependencies import get_current_user
from config.settings import get_settings
from email_service import (
    send_audit_report_review_request,
    send_client_status_update,
    send_otp_code,
)

router = APIRouter(tags=["audit_reports"])

CB_ROLES      = {"admin", "planner", "officer", "executive", "gm"}
UPLOAD_ROLES  = {"auditor", "admin", "planner"}
AUDITOR_ROLES = {"auditor", "admin"}
OTP_EXPIRY    = 10  # minutes

VALID_FORMS = {"FR.231", "FR.229", "FR.232"}


def _hash(val: str) -> str:
    return hashlib.sha256(val.encode()).hexdigest()


def _report_dict(r: AuditSetAuditReport, can_review: bool = False) -> dict:
    return {
        "id":                 r.id,
        "audit_set_id":       r.audit_set_id,
        "stage_type":         r.stage_type,
        "report_form":        r.report_form,
        "label":              r.label,
        "file_name":          r.file_name,
        "status":             r.status,
        "la_signed_at":       r.la_signed_at.isoformat() if r.la_signed_at else None,
        "reviewer_signed_at": r.reviewer_signed_at.isoformat() if r.reviewer_signed_at else None,
        "created_at":         r.created_at.isoformat() if r.created_at else None,
        "can_review":         can_review,
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
        _report_dict(r, can_review=is_reviewer and r.status == "pending_review")
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

    otp = f"{secrets.randbelow(900000) + 100000}"
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


# ── Lead Auditor: direct-sign (no OTP) ──────────────────────────────────────

@router.post("/audit-sets/{audit_set_id}/audit-reports/{rid}/sign/la/direct")
def la_sign_direct(
    audit_set_id: str,
    rid: str,
    db: Session = Depends(get_db),
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

    report.la_signed_at = datetime.utcnow()
    report.status       = "pending_review"
    db.commit()
    db.refresh(report)
    return _report_dict(report)


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

    # ── Auto-advance workflow: under_review → certified ───────────────────────
    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if audit_set and audit_set.workflow_status == "under_review":
        audit_set.workflow_status  = "certified"
        audit_set.cert_issued_date = datetime.utcnow().date()
        db.add(AuditSetStatusEvent(
            audit_set_id=audit_set_id,
            from_status="under_review",
            to_status="certified",
            triggered_by=current_user.id,
            notes=f"Audit report '{report.report_form} — {report.label}' approved by committee reviewer.",
        ))
        db.commit()

        # Notify the linked client account (silent failure — best-effort)
        try:
            client_user = auth_db.query(PlatformUser).filter_by(
                audit_set_id=audit_set_id, role="client",
            ).first()
            if client_user:
                send_client_status_update(
                    to=client_user.email,
                    full_name=client_user.full_name,
                    new_status="certified",
                    notes="Your audit report has been reviewed and approved by the certification committee.",
                )
        except Exception:
            pass

    return {
        "approved": True,
        "status": "approved",
        "reviewer_signed_at": report.reviewer_signed_at.isoformat(),
        "workflow_advanced": audit_set.workflow_status == "certified" if audit_set else False,
    }


# ── Committee Reviewer: direct-approve (no OTP) ──────────────────────────────

@router.post("/audit-sets/{audit_set_id}/audit-reports/{rid}/sign/review/direct")
def review_sign_direct(
    audit_set_id: str,
    rid: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    # Admin and executive can always approve.
    # Other roles must be a registered Committee Reviewer for this audit set.
    if current_user.role not in ("admin", "executive"):
        reviewer = _get_committee_reviewer(audit_set_id, current_user, db)
        if not reviewer:
            raise HTTPException(403, "You are not a registered reviewer for this audit set")

    report = db.query(AuditSetAuditReport).filter_by(
        id=rid, audit_set_id=audit_set_id
    ).first()
    if not report:
        raise HTTPException(404, "Report not found")
    if report.status == "approved":
        raise HTTPException(400, "Report already approved")
    if report.status != "pending_review":
        raise HTTPException(400, f"Report status is '{report.status}', expected 'pending_review'")

    report.reviewer_signed_at = datetime.utcnow()
    report.status             = "approved"
    db.commit()
    db.refresh(report)
    return _report_dict(report, can_review=False)
