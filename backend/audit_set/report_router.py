"""
BATUHAN — FR.231 / FR.231-1 / FR.229 / FR.232 Audit Report Signing.

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
import logging
import os
import secrets
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from audit_set.db_models import (
    AuditSet, AuditSetAuditReport, AuditSetCommitteeMember,
    AuditSetStage, AuditSetStatusEvent, DocumentSignatureField,
    VisualSignaturePlacement, get_db,
)
from audit_set.committee_slots import (
    committee_member_auditor_id,
    committee_member_name,
    planned_committee_chair,
)
from audit_set.doc_converter import prepare_document
from audit_set.pdf_flattener import flatten_document, has_completed_visual_signatures
from audit_set.report_signature_rules import (
    audit_report_has_all_required_approvals,
    audit_report_requires_certification_manager,
    audit_report_requires_appointed_reviewer,
)
from auth.db_models import PlatformUser, get_db as get_auth_db
from auth.dependencies import get_current_user
from auth.policy import resolve_realtime_action_datetime
from config.settings import get_settings
from storage.document_store import (
    delete as store_delete,
    ensure_local,
    invalidate_cache,
    resolve_docx_key,
    upload as store_upload,
)
from email_service import (
    send_audit_report_review_request,
)

router = APIRouter(tags=["audit_reports"])
logger = logging.getLogger(__name__)

# Portal 75 — certification_manager added so the CM can list, download and
# approve audit reports (same access as other CB staff).
CB_ROLES      = {"admin", "planner", "planner_us", "officer", "executive", "gm", "certification_manager"}
UPLOAD_ROLES  = {"auditor", "admin", "planner", "planner_us"}
AUDITOR_ROLES = {"auditor", "admin"}
# (OTP_EXPIRY removed — OTP signing was removed system-wide)

VALID_FORMS = {"FR.231", "FR.231-1", "FR.229", "FR.232"}

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





def _report_dict(
    r: AuditSetAuditReport,
    can_review: bool = False,
    committee_chair: dict | None = None,
    requires_appointed_reviewer: bool | None = None,
) -> dict:
    show_appointed_reviewer = (
        requires_appointed_reviewer
        if requires_appointed_reviewer is not None
        else committee_chair is not None
    )
    chair_id = committee_member_auditor_id(committee_chair) if show_appointed_reviewer else None
    chair_name = committee_member_name(committee_chair) if show_appointed_reviewer else None
    return {
        "id":                     r.id,
        "audit_set_id":           r.audit_set_id,
        "stage_type":             r.stage_type,
        "report_form":            r.report_form,
        "label":                  r.label,
        "file_name":              r.file_name,
        "status":                 r.status,
        "la_signed_at":           r.la_signed_at.isoformat() if r.la_signed_at else None,
        "appointed_reviewer_signed_at": (
            r.appointed_reviewer_signed_at.isoformat()
            if r.appointed_reviewer_signed_at else None
        ),
        "reviewer_signed_at":     r.reviewer_signed_at.isoformat() if r.reviewer_signed_at else None,
        "created_at":             r.created_at.isoformat() if r.created_at else None,
        "can_review":             can_review,
        # The reviewer shown in report lists is the planned committee chair.
        "reviewer_auditor_id":    (chair_id or r.reviewer_auditor_id) if show_appointed_reviewer else None,
        "reviewer_auditor_name":  (chair_name or r.reviewer_auditor_name) if show_appointed_reviewer else None,
        "requires_appointed_reviewer": bool(show_appointed_reviewer),
    }


def _get_committee_reviewer(
    audit_set_id: str, current_user: PlatformUser, db: Session,
) -> AuditSetCommitteeMember | None:
    return db.query(AuditSetCommitteeMember).filter_by(
        audit_set_id=audit_set_id, user_id=current_user.id, role="reviewer",
    ).first()


def _maybe_advance_single_stage_report_review(
    db: Session,
    audit_set: AuditSet | None,
    report: AuditSetAuditReport,
    triggered_by: str,
    effective_ts: datetime,
) -> None:
    """Move surveillance/recertification audits to review after report approval.

    Shared-document uploads already have their own workflow hook, but audit
    reports are stored in AuditSetAuditReport. Without this hook a fully
    approved FR.232 surveillance report can remain stuck at audit_in_progress.
    """
    if not audit_set or audit_set.workflow_status != "audit_in_progress":
        return

    audit_type = (audit_set.audit_type or "").lower()
    stage_type = (report.stage_type or "").lower()
    if not (
        audit_type.startswith("surveillance")
        or audit_type == "recertification"
        or stage_type in {"surveillance", "recertification"}
    ):
        return

    if report.status != "approved":
        return

    audit_set.workflow_status = "under_review"
    db.add(AuditSetStatusEvent(
        audit_set_id=audit_set.id,
        from_status="audit_in_progress",
        to_status="under_review",
        triggered_by=triggered_by,
        triggered_at=effective_ts,
        notes=(
            "Auto-advanced after the single-stage audit report was fully "
            "approved by all required report signers."
        ),
    ))


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
    if report_form == "FR.231-1" and stage_type != "stage_1":
        raise HTTPException(400, "FR.231-1 MDQMS Report is only valid for Stage 1")

    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Audit set not found")
    standards = audit_set.standards or []
    if isinstance(standards, str):
        standards = [standards]
    if report_form == "FR.231-1" and not any(
        marker in str(standard).upper()
        for standard in standards
        for marker in ("MDQMS", "13485")
    ):
        raise HTTPException(
            400,
            "FR.231-1 MDQMS Report requires ISO 13485 in the audit scope",
        )

    safe_name = f"{secrets.token_hex(6)}_{file.filename or 'report'}"
    relative_path = f"audit_reports/{audit_set_id}/{safe_name}"
    content = await file.read()
    file_path = store_upload(relative_path, content)

    record_date = resolve_realtime_action_datetime(auth_db, report_date)
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
    if audit_report_requires_appointed_reviewer(report, audit_set):
        chair = planned_committee_chair(audit_set)
        report.reviewer_auditor_id = committee_member_auditor_id(chair)
        report.reviewer_auditor_name = committee_member_name(chair)
    db.add(report)
    db.commit()
    db.refresh(report)

    return _report_dict(
        report,
        requires_appointed_reviewer=audit_report_requires_appointed_reviewer(report, audit_set),
    )


# ── List and download ─────────────────────────────────────────────────────────

@router.get("/audit-sets/{audit_set_id}/audit-reports")
def list_audit_reports(
    audit_set_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in CB_ROLES | AUDITOR_ROLES:
        raise HTTPException(403, "Not authorized")

    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    chair = planned_committee_chair(audit_set) if audit_set else None

    # FR.231/FR.231-1 are approved by Lead Auditor + Certification Manager.
    # FR.232 is approved by Lead Auditor + appointed committee chairperson.
    is_cm = current_user.role in ("certification_manager", "admin", "executive")

    rows = (
        db.query(AuditSetAuditReport)
        .filter_by(audit_set_id=audit_set_id)
        .order_by(AuditSetAuditReport.created_at)
        .all()
    )

    def _can_review(r: AuditSetAuditReport) -> bool:
        if r.status != "pending_review":
            return False
        if not audit_report_requires_certification_manager(r, audit_set):
            return False
        return is_cm and r.reviewer_signed_at is None

    return [
        _report_dict(
            r,
            can_review=_can_review(r),
            committee_chair=chair,
            requires_appointed_reviewer=audit_report_requires_appointed_reviewer(r, audit_set),
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
    if not report.file_path:
        raise HTTPException(404, "File not found on server")
    try:
        local_path = ensure_local(report.file_path)
    except FileNotFoundError:
        raise HTTPException(404, "File not found on server")

    if has_completed_visual_signatures("audit_report", rid, db):
        try:
            prepare_document(local_path, db)
            pdf_bytes = flatten_document("audit_report", rid, db)
        except Exception as exc:
            logger.exception("Failed to prepare signed audit report %s: %s", rid, exc)
            raise HTTPException(500, "Failed to generate signed PDF") from exc

        base_name = report.file_name or f"{report.report_form}_audit_report"
        safe_name = "".join(c if c.isalnum() or c in " .-" else "_" for c in base_name)[:60]
        if safe_name.lower().endswith(".docx"):
            safe_name = safe_name[:-5]
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{safe_name}_signed.pdf"'
            },
        )

    return FileResponse(
        local_path,
        filename=report.file_name or "audit_report.docx",
        media_type="application/octet-stream",
    )


@router.delete("/audit-sets/{audit_set_id}/audit-reports/{rid}")
def delete_audit_report(
    audit_set_id: str,
    rid: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """Delete an uploaded stage report so the Lead Auditor can replace it."""
    if current_user.role not in {"admin", "planner", "planner_us"}:
        raise HTTPException(403, "Only planners and admins may delete audit reports")

    report = db.query(AuditSetAuditReport).filter_by(
        id=rid,
        audit_set_id=audit_set_id,
    ).first()
    if not report:
        raise HTTPException(404, "Audit report not found")

    db.query(VisualSignaturePlacement).filter_by(
        document_type="audit_report",
        doc_id=rid,
    ).delete()

    if report.file_path:
        docx_key = resolve_docx_key(report.file_path)
        db.query(DocumentSignatureField).filter_by(docx_path=docx_key).delete()
        invalidate_cache(report.file_path)
        try:
            store_delete(report.file_path)
        except Exception as exc:
            logger.warning(
                "Could not delete audit report file %s: %s",
                report.file_path,
                exc,
            )

    db.delete(report)
    db.commit()
    return {"deleted": True, "id": rid}


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
        raise HTTPException(400, "Report already signed by Lead Auditor")
    if report.status not in ("pending_la",):
        raise HTTPException(400, f"Report status is '{report.status}', expected 'pending_la'")

    report.la_user_id   = current_user.id
    report.la_signed_at = resolve_realtime_action_datetime(auth_db, body.signed_date)
    report.la_signed_ip = request.client.host if request.client else None
    report.status       = "pending_review"
    db.commit()

    # Notify assigned reviewer that the report is ready for their signature.
    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    _notify_reviewer(db, report, audit_set)

    db.refresh(report)
    return _report_dict(
        report,
        requires_appointed_reviewer=audit_report_requires_appointed_reviewer(report, audit_set),
    )


# ── Committee Reviewer: approve party 2 ──────────────────────────────────────

def _notify_reviewer(
    db: Session,
    report: AuditSetAuditReport,
    audit_set,
) -> None:
    """Send review-request email to the assigned reviewer (auditor or committee member)."""
    if not audit_report_requires_appointed_reviewer(report, audit_set):
        return

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

    This direct approval path is reserved for report types that still require
    Certification Manager approval. Reports with an appointed committee
    chairperson are approved by the Lead Auditor and chairperson only.
    """
    audit_set = db.query(AuditSet).filter_by(id=report.audit_set_id).first()
    if not audit_report_requires_certification_manager(report, audit_set):
        raise HTTPException(
            400,
            "This report is approved without Certification Manager signing; "
            "Certification Manager signature is not required.",
        )

    # 1. Admin/CM bypass
    if current_user.role in ("admin", "certification_manager", "executive"):
        return

    raise HTTPException(
        403,
        "Only the Certification Manager may give final approval for this report.",
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
    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    signed_dt = resolve_realtime_action_datetime(auth_db, body.signed_date)
    report.reviewer_user_id   = current_user.id
    report.reviewer_signed_at = signed_dt
    report.reviewer_signed_ip = request.client.host if request.client else None
    if audit_report_has_all_required_approvals(report, audit_set):
        report.status = "approved"
        _maybe_advance_single_stage_report_review(
            db,
            audit_set,
            report,
            current_user.id,
            signed_dt,
        )
    else:
        report.status = "pending_review"
    db.commit()

    db.refresh(report)
    return _report_dict(
        report,
        can_review=False,
        requires_appointed_reviewer=audit_report_requires_appointed_reviewer(report, audit_set),
    )


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
    return _report_dict(
        report,
        requires_appointed_reviewer=audit_report_requires_appointed_reviewer(report, audit_set),
    )


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
