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
import os
import secrets
from datetime import date, datetime, timedelta
from typing import Optional

from docxtpl import DocxTemplate
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from audit_set.db_models import (
    AuditSet, AuditSetAuditorAssessment, AuditSetSharedDocument, AuditSetStage, get_db,
)
from auth.db_models import PlatformUser, get_db as get_auth_db
from auth.dependencies import get_current_user
from config.settings import get_settings
from email_service import send_otp_code

router = APIRouter(tags=["assessments"])

CB_ROLES   = {"admin", "planner", "planner_us", "officer", "executive", "gm"}
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
    if current_user.role not in {"admin", "planner", "planner_us"}:
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


class SignAssessmentOTPBody(BaseModel):
    signed_date: Optional[date] = None


@router.post("/client/my-audit-set/assessments/{aid}/sign/verify")
def verify_assessment_signature(
    aid: str,
    otp: str,
    request: Request,
    body:         SignAssessmentOTPBody = Body(default_factory=SignAssessmentOTPBody),
    db:           Session = Depends(get_db),
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

    signed_dt = (
        datetime.combine(body.signed_date, datetime.min.time())
        if body.signed_date else datetime.utcnow()
    )
    a.signed_by      = current_user.id
    a.signed_at      = signed_dt
    a.signed_ip      = request.client.host if request.client else None
    a.otp_hash       = None
    a.otp_expires_at = None
    db.commit()

    return {"signed": True, "signed_at": a.signed_at.isoformat()}


class SignAssessmentDirectBody(BaseModel):
    signed_date: Optional[date] = None


# ── CB: generate FR.211 DOCX per team member ─────────────────────────────────

@router.post("/audit-sets/{audit_set_id}/assessments/generate-fr211")
def generate_fr211_forms(
    audit_set_id: str,
    stage_type:   str = Query(...),   # "stage_1" | "stage_2" | "surveillance"
    db:           Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """
    Generate one FR.211 DOCX per team member (lead + auditors + TEs) for
    the given stage and store each as an AuditSetSharedDocument
    (document_type "assessment") available for the client to sign.
    Idempotent: skips members who already have an FR.211 doc for this stage.
    """
    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "Not authorized")

    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Audit set not found")

    stage = (
        db.query(AuditSetStage)
        .filter_by(audit_set_id=audit_set_id, stage_type=stage_type)
        .order_by(AuditSetStage.stage_order.desc())
        .first()
    )
    if not stage:
        raise HTTPException(404, f"No stage found for stage_type={stage_type}")

    # Collect team members (lead + auditors + TEs, not observers)
    members: list[dict] = []
    if stage.lead_auditor_name:
        members.append({
            "id":   stage.lead_auditor_id,
            "name": stage.lead_auditor_name,
            "role": "Lead Auditor",
        })
    for a in (stage.auditors or []):
        if isinstance(a, dict):
            members.append({"id": a.get("id"), "name": a.get("name", ""), "role": "Auditor"})
    for te in (stage.technical_experts or []):
        if isinstance(te, dict):
            members.append({"id": te.get("id"), "name": te.get("name", ""), "role": "Technical Expert"})

    if not members:
        raise HTTPException(409, "No team members assigned to this stage yet.")

    # Locate FR.211 DOCX template
    settings = get_settings()
    sub = (audit_set.accreditation_body or "base").lower()
    template_path = os.path.join(settings.blank_set_path, sub, "FR.211.docx")
    if not os.path.exists(template_path):
        template_path = os.path.join(settings.blank_set_path, "base", "FR.211.docx")
    if not os.path.exists(template_path):
        template_path = os.path.join(settings.blank_set_path, "FR.211.docx")
    if not os.path.exists(template_path):
        raise HTTPException(500, "FR.211 template not found on server.")

    # Build shared date string for the stage
    from audit_set.filler import format_date_range
    audit_dates = format_date_range(stage.audit_date_start, stage.audit_date_end)
    standards_str = ", ".join(audit_set.standards or [])

    # Output directory
    upload_dir = os.path.join(settings.storage_base_path, "shared_docs", audit_set_id)
    os.makedirs(upload_dir, exist_ok=True)

    created = []
    for member in members:
        auditor_key = member["id"] or member["name"]
        # Idempotency: skip if already generated for this auditor + stage
        existing = db.query(AuditSetSharedDocument).filter_by(
            audit_set_id=audit_set_id,
            document_type="assessment",
            stage_type=stage_type,
            assigned_auditor_id=auditor_key,
        ).first()
        if existing:
            created.append({"id": existing.id, "skipped": True})
            continue

        # Fill FR.211 template
        tpl = DocxTemplate(template_path)
        context = {
            "lead_auditor_name": member["name"],
            "audit_dates":       audit_dates,
            "company_name":      audit_set.company_name or "",
            "standards_str":     standards_str,
        }
        tpl.render(context)

        # Save DOCX
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in member["name"])
        file_name = f"FR.211_{stage_type}_{safe_name}.docx"
        file_path = os.path.join(upload_dir, file_name)
        tpl.save(file_path)

        # Create shared document record
        doc = AuditSetSharedDocument(
            audit_set_id        = audit_set_id,
            label               = f"Auditor Assessment — {member['name']} ({stage_type.replace('_', ' ').title()}) (FR.211)",
            document_type       = "assessment",
            stage_type          = stage_type,
            assigned_auditor_id = auditor_key,
            file_path           = file_path,
            direction           = "cb_to_client",
            status              = "released",
            released_by         = current_user.id,
            released_at         = datetime.utcnow(),
        )
        db.add(doc)
        db.flush()
        created.append({"id": doc.id, "auditor": member["name"], "skipped": False})

    db.commit()
    return {
        "generated": len([c for c in created if not c.get("skipped")]),
        "skipped":   len([c for c in created if c.get("skipped")]),
        "documents": created,
    }


# ── Client: direct-sign (no OTP) ─────────────────────────────────────────────

@router.post("/client/my-audit-set/assessments/{aid}/sign/direct")
def sign_assessment_direct(
    aid: str,
    body:         SignAssessmentDirectBody = Body(default_factory=SignAssessmentDirectBody),
    db:           Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    a = _get_client_assessment(aid, current_user, db)
    if a.signed_at:
        raise HTTPException(400, "Assessment already signed")
    if not a.rating:
        raise HTTPException(400, "Rating must be set before signing — save a draft first")

    a.signed_by = current_user.id
    a.signed_at = (
        datetime.combine(body.signed_date, datetime.min.time())
        if body.signed_date else datetime.utcnow()
    )
    db.commit()
    db.refresh(a)
    return _assessment_dict(a)
