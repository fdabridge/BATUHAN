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
import os
import secrets
from datetime import datetime, timedelta, date
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from storage.document_store import upload as store_upload, ensure_local
from audit_set.db_models import (
    AuditSet, AuditSetImpartialityDeclaration, AuditSetStage, get_db,
)
from auth.db_models import PlatformUser, get_db as get_auth_db
from auth.dependencies import get_current_user
from email_service import send_impartiality_declaration_request, send_otp_code

router = APIRouter(tags=["declarations"])

CB_ROLES      = {"admin", "planner", "planner_us", "officer", "executive", "gm"}
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
        "file_path":      d.file_path,
        "file_name":      d.file_name,
        "created_at":     d.created_at.isoformat() if d.created_at else None,
    }


@router.post("/audit-sets/{audit_set_id}/declarations/create-for-stage")
def create_declarations_for_stage(
    audit_set_id: str,
    stage_type:   str,
    db:       Session = Depends(get_db),
    auth_db:  Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """Seed one declaration record per team member for this stage. Idempotent."""
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
        raise HTTPException(404, f"No stage of type '{stage_type}' found")

    entries: list[dict] = []
    if stage.lead_auditor_name:
        entries.append({"name": stage.lead_auditor_name, "role": "Lead Auditor", "ref_id": stage.lead_auditor_id})
    for a in (stage.auditors or []):
        if isinstance(a, dict) and a.get("name"):
            entries.append({"name": a["name"], "role": "Team Auditor", "ref_id": a.get("id")})
    for te in (stage.technical_experts or []):
        if isinstance(te, dict) and te.get("name"):
            entries.append({"name": te["name"], "role": "Technical Expert", "ref_id": te.get("id")})
    for obs in (stage.observers or []):
        if isinstance(obs, dict) and obs.get("name"):
            entries.append({"name": obs["name"], "role": "Observer", "ref_id": obs.get("id")})

    if not entries:
        raise HTTPException(
            422,
            "No team members assigned to this stage — assign the audit team before creating declarations",
        )

    existing = {
        (d.member_name, d.stage_type)
        for d in db.query(AuditSetImpartialityDeclaration)
                   .filter_by(audit_set_id=audit_set_id, stage_type=stage_type)
                   .all()
    }

    created = 0
    for entry in entries:
        if (entry["name"], stage_type) in existing:
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


@router.get("/audit-sets/{audit_set_id}/declarations")
def list_declarations(
    audit_set_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """CB sees all; auditors see all (to know team status), but can only sign their own."""
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

    otp = f"{secrets.randbelow(900000) + 100000}"
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


class SignDeclarationOTPBody(BaseModel):
    signed_date: Optional[date] = None


@router.post("/audit-sets/{audit_set_id}/declarations/{did}/sign/verify")
def declaration_verify_otp(
    audit_set_id: str,
    did: str,
    otp: str,
    request: Request,
    body:    SignDeclarationOTPBody = Body(default_factory=SignDeclarationOTPBody),
    db:      Session = Depends(get_db),
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
    decl.signed_at      = (
        datetime.combine(body.signed_date, datetime.min.time())
        if body.signed_date else datetime.utcnow()
    )
    decl.signed_ip      = request.client.host if request.client else None
    decl.otp_hash       = None
    decl.otp_expires_at = None
    db.commit()

    return {"signed": True, "signed_at": decl.signed_at.isoformat()}


# ── Direct-sign (no OTP) ─────────────────────────────────────────────────────

class SignDeclarationDirectBody(BaseModel):
    signed_date: Optional[date] = None  # user-selected signing date; defaults to today


@router.post("/audit-sets/{audit_set_id}/declarations/{did}/sign/direct")
def sign_declaration_direct(
    audit_set_id: str,
    did: str,
    body:         SignDeclarationDirectBody = Body(default_factory=SignDeclarationDirectBody),
    db:           Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    decl = db.query(AuditSetImpartialityDeclaration).filter_by(
        id=did, audit_set_id=audit_set_id
    ).first()
    if not decl:
        raise HTTPException(404, "Declaration not found")
    if decl.signed_at:
        raise HTTPException(400, "Declaration already signed")

    # Authorization: admin bypass; auditors may only sign their own declaration
    if current_user.role != "admin":
        if not current_user.auditor_id or decl.auditor_ref_id != current_user.auditor_id:
            raise HTTPException(403, "You may only sign your own declaration")

    decl.signed_by = current_user.id
    decl.signed_at = (
        datetime.combine(body.signed_date, datetime.min.time())
        if body.signed_date else datetime.utcnow()
    )
    db.commit()
    db.refresh(decl)

    # Generate PDF signing certificate (Portal 50b)
    try:
        from audit_set.declaration_pdf import generate_declaration_pdf

        audit_set  = db.query(AuditSet).filter_by(id=audit_set_id).first()
        sig_image: Optional[str] = current_user.signature_image if hasattr(current_user, "signature_image") else None

        import tempfile as _tempfile
        _tmp_dir = _tempfile.mkdtemp(prefix="fr215_")
        _tmp_path = os.path.join(_tmp_dir, f"FR215_declaration_{decl.id}.pdf")
        generate_declaration_pdf(
            member_name=decl.member_name,
            member_role=decl.member_role,
            stage_type=decl.stage_type,
            audit_plan_number=audit_set.plan_number if audit_set else None,
            company_name=audit_set.company_name if audit_set else "",
            signed_at=decl.signed_at,
            signature_image_b64=sig_image,
            output_path=_tmp_path,
        )
        with open(_tmp_path, "rb") as _f:
            _pdf_bytes = _f.read()
        relative_path = f"{audit_set_id}/declarations/FR215_declaration_{decl.id}.pdf"
        out_path = store_upload(relative_path, _pdf_bytes, content_type="application/pdf")
        import shutil as _shutil
        _shutil.rmtree(_tmp_dir, ignore_errors=True)
        decl.file_path = out_path
        decl.file_name = f"FR215_declaration_{decl.member_name.replace(' ', '_')}.pdf"
        db.commit()
    except Exception:
        pass  # PDF generation failure must never break the signing flow

    return _decl_dict(decl)


@router.get("/audit-sets/{audit_set_id}/declarations/{did}/download-certificate")
def download_declaration_certificate(
    audit_set_id: str,
    did:          str,
    db:           Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """Download the signed PDF certificate for a declaration."""
    decl = db.query(AuditSetImpartialityDeclaration).filter_by(
        id=did, audit_set_id=audit_set_id
    ).first()
    if not decl:
        raise HTTPException(404, "Declaration not found")
    if not decl.signed_at:
        raise HTTPException(400, "Not yet signed")
    if not decl.file_path:
        raise HTTPException(404, "Signing certificate PDF not found")
    try:
        local_path = ensure_local(decl.file_path)
    except FileNotFoundError:
        raise HTTPException(404, "Signing certificate PDF not found")
    return FileResponse(
        local_path,
        media_type="application/pdf",
        filename=decl.file_name or f"FR215_declaration_{did}.pdf",
    )
