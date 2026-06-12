"""
BATUHAN — FR.230 NC Form Two-Party Signing (Prompt 17).

Upload:  CB uploads the NC form file → status=pending_la
Sign 1:  Lead Auditor signs via OTP (auditor portal) → status=pending_client
Sign 2:  Client counter-signs via OTP (client portal) → status=complete

Routes:
  POST /audit-sets/{id}/nc-forms/upload          (CB admin/planner — multipart)
  GET  /audit-sets/{id}/nc-forms                 (CB + auditor — list all for this audit set)
  GET  /audit-sets/{id}/nc-forms/{nid}/download  (CB + auditor + client after pending_client)
  POST /audit-sets/{id}/nc-forms/{nid}/sign/la/request-otp  (auditor only)
  POST /audit-sets/{id}/nc-forms/{nid}/sign/la/verify       (auditor only)
  GET  /client/my-audit-set/nc-forms             (client only)
  GET  /client/my-audit-set/nc-forms/{nid}/download  (client only, pending_client+)
  POST /client/my-audit-set/nc-forms/{nid}/sign/request-otp  (client only)
  POST /client/my-audit-set/nc-forms/{nid}/sign/verify       (client only)
"""
from __future__ import annotations
import hashlib
import os
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from audit_set.db_models import AuditSet, AuditSetNCForm, AuditSetStage, get_db
from auth.db_models import PlatformUser, get_db as get_auth_db
from auth.dependencies import get_current_user
from config.settings import get_settings
from email_service import (
    send_nc_form_la_request,
    send_nc_form_client_ready,
    send_otp_code,
)

router = APIRouter(tags=["nc_forms"])

CB_ROLES     = {"admin", "planner", "officer", "executive", "gm"}
OTP_EXPIRY   = 10  # minutes


def _hash(val: str) -> str:
    return hashlib.sha256(val.encode()).hexdigest()


def _nc_dict(n: AuditSetNCForm, include_paths: bool = False) -> dict:
    return {
        "id":              n.id,
        "audit_set_id":    n.audit_set_id,
        "stage_type":      n.stage_type,
        "label":           n.label,
        "file_name":       n.file_name,
        "status":          n.status,
        "la_signed_at":    n.la_signed_at.isoformat() if n.la_signed_at else None,
        "client_signed_at":n.client_signed_at.isoformat() if n.client_signed_at else None,
        "created_at":      n.created_at.isoformat() if n.created_at else None,
    }


def _get_lead_auditor_user(
    db: Session,
    auth_db: Session,
    audit_set_id: str,
    stage_type: str,
) -> PlatformUser | None:
    """Look up the PlatformUser who is the Lead Auditor for this stage."""
    stage = (
        db.query(AuditSetStage)
        .filter_by(audit_set_id=audit_set_id, stage_type=stage_type)
        .order_by(AuditSetStage.stage_order)
        .first()
    )
    if not stage or not stage.lead_auditor_id:
        return None
    return auth_db.query(PlatformUser).filter_by(auditor_id=stage.lead_auditor_id).first()


# ── CB: upload NC form ────────────────────────────────────────────────────────

@router.post("/audit-sets/{audit_set_id}/nc-forms/upload")
async def upload_nc_form(
    audit_set_id: str,
    stage_type: str = Form(...),
    label:      str = Form(...),
    file: UploadFile = File(...),
    db:       Session = Depends(get_db),
    auth_db:  Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """CB uploads the NC form file. Notifies the Lead Auditor by email."""
    if current_user.role not in {"admin", "planner"}:
        raise HTTPException(403, "Not authorized")

    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Audit set not found")

    settings = get_settings()
    upload_dir = os.path.join(settings.storage_base_path, "nc_forms", audit_set_id)
    os.makedirs(upload_dir, exist_ok=True)

    safe_name = f"{secrets.token_hex(6)}_{file.filename or 'nc_form'}"
    file_path = os.path.join(upload_dir, safe_name)
    content   = await file.read()
    with open(file_path, "wb") as fh:
        fh.write(content)

    nc = AuditSetNCForm(
        audit_set_id=audit_set_id,
        stage_type=stage_type,
        label=label.strip(),
        file_path=file_path,
        file_name=file.filename or safe_name,
        status="pending_la",
        created_by=current_user.id,
    )
    db.add(nc)
    db.commit()
    db.refresh(nc)

    # Notify Lead Auditor
    la_user = _get_lead_auditor_user(db, auth_db, audit_set_id, stage_type)
    if la_user:
        try:
            send_nc_form_la_request(
                to=la_user.email,
                full_name=la_user.full_name,
                company_name=audit_set.company_name,
                stage_label=stage_type.replace("_", " ").title(),
                nc_label=label,
            )
        except Exception:
            pass

    return _nc_dict(nc)


# ── CB + Auditor: list and download ──────────────────────────────────────────

@router.get("/audit-sets/{audit_set_id}/nc-forms")
def list_nc_forms(
    audit_set_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in CB_ROLES | {"auditor"}:
        raise HTTPException(403, "Not authorized")
    rows = (
        db.query(AuditSetNCForm)
        .filter_by(audit_set_id=audit_set_id)
        .order_by(AuditSetNCForm.created_at)
        .all()
    )
    return [_nc_dict(r) for r in rows]


@router.get("/audit-sets/{audit_set_id}/nc-forms/{nid}/download")
def download_nc_form(
    audit_set_id: str,
    nid: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    nc = db.query(AuditSetNCForm).filter_by(id=nid, audit_set_id=audit_set_id).first()
    if not nc:
        raise HTTPException(404, "NC form not found")

    if current_user.role not in CB_ROLES | {"auditor"}:
        raise HTTPException(403, "Not authorized")

    if not nc.file_path or not os.path.exists(nc.file_path):
        raise HTTPException(404, "File not found on server")

    return FileResponse(
        nc.file_path,
        filename=nc.file_name or "nc_form.docx",
        media_type="application/octet-stream",
    )


# ── Auditor (Lead Auditor): sign party 1 ─────────────────────────────────────

def _check_la_authorization(
    nc: AuditSetNCForm,
    current_user: PlatformUser,
    db: Session,
) -> None:
    """Raise 403 if current_user is not the Lead Auditor for nc.stage_type."""
    if current_user.role != "auditor":
        raise HTTPException(403, "Auditor access only")
    if not current_user.auditor_id:
        raise HTTPException(403, "No auditor profile linked to your account")
    stage = (
        db.query(AuditSetStage)
        .filter_by(audit_set_id=nc.audit_set_id, stage_type=nc.stage_type)
        .order_by(AuditSetStage.stage_order)
        .first()
    )
    if not stage:
        raise HTTPException(404, "Stage not found")
    if stage.lead_auditor_id != current_user.auditor_id:
        raise HTTPException(403, "Only the Lead Auditor for this stage may sign the NC form")


@router.post("/audit-sets/{audit_set_id}/nc-forms/{nid}/sign/la/request-otp")
def la_request_otp(
    audit_set_id: str,
    nid: str,
    db:       Session = Depends(get_db),
    auth_db:  Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    nc = db.query(AuditSetNCForm).filter_by(id=nid, audit_set_id=audit_set_id).first()
    if not nc:
        raise HTTPException(404, "NC form not found")
    _check_la_authorization(nc, current_user, db)
    if nc.la_signed_at:
        raise HTTPException(400, "Already signed")

    otp            = f"{secrets.randbelow(900000) + 100000}"
    nc.la_otp_hash    = _hash(otp)
    nc.la_otp_expires = datetime.utcnow() + timedelta(minutes=OTP_EXPIRY)
    db.commit()

    try:
        send_otp_code(
            to=current_user.email,
            full_name=current_user.full_name,
            otp=otp,
            document_label=f"NC Form — {nc.label}",
        )
    except Exception:
        pass

    return {"message": f"Code sent to {current_user.email}. Valid for {OTP_EXPIRY} minutes."}


@router.post("/audit-sets/{audit_set_id}/nc-forms/{nid}/sign/la/verify")
def la_verify_otp(
    audit_set_id: str,
    nid: str,
    otp: str,
    request: Request,
    db:       Session = Depends(get_db),
    auth_db:  Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    nc = db.query(AuditSetNCForm).filter_by(id=nid, audit_set_id=audit_set_id).first()
    if not nc:
        raise HTTPException(404, "NC form not found")
    _check_la_authorization(nc, current_user, db)
    if nc.la_signed_at:
        raise HTTPException(400, "Already signed")
    if not nc.la_otp_hash or not nc.la_otp_expires:
        raise HTTPException(400, "No pending OTP. Request one first.")
    if datetime.utcnow() > nc.la_otp_expires:
        raise HTTPException(400, "OTP expired. Please request a new one.")
    if _hash(otp.strip()) != nc.la_otp_hash:
        raise HTTPException(400, "Invalid code.")

    nc.la_user_id   = current_user.id
    nc.la_signed_at = datetime.utcnow()
    nc.la_signed_ip = request.client.host if request.client else None
    nc.la_otp_hash  = None
    nc.la_otp_expires = None
    nc.status       = "pending_client"
    db.commit()

    # Notify client that NC form is ready for counter-signature
    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    client_user = auth_db.query(PlatformUser).filter_by(
        audit_set_id=audit_set_id, role="client"
    ).first()
    if audit_set and client_user:
        try:
            send_nc_form_client_ready(
                to=client_user.email,
                full_name=client_user.full_name,
                company_name=audit_set.company_name,
                nc_label=nc.label,
            )
        except Exception:
            pass

    return {"signed": True, "status": "pending_client", "la_signed_at": nc.la_signed_at.isoformat()}


# ── Lead Auditor: direct-sign (no OTP) ───────────────────────────────────────

@router.post("/audit-sets/{audit_set_id}/nc-forms/{nid}/sign/la/direct")
def la_sign_direct(
    audit_set_id: str,
    nid: str,
    db:           Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    nc = db.query(AuditSetNCForm).filter_by(id=nid, audit_set_id=audit_set_id).first()
    if not nc:
        raise HTTPException(404, "NC form not found")
    _check_la_authorization(nc, current_user, db)
    if nc.la_signed_at:
        raise HTTPException(400, "Already signed by Lead Auditor")

    nc.la_signed_at = datetime.utcnow()
    nc.status       = "pending_client"
    db.commit()
    db.refresh(nc)
    return _nc_dict(nc)


# ── Client: view, download, counter-sign ─────────────────────────────────────

def _get_client_nc(
    nid: str,
    current_user: PlatformUser,
    db: Session,
) -> AuditSetNCForm:
    if current_user.role != "client" or not current_user.audit_set_id:
        raise HTTPException(403, "Client access only")
    nc = db.query(AuditSetNCForm).filter_by(
        id=nid, audit_set_id=current_user.audit_set_id
    ).first()
    if not nc:
        raise HTTPException(404, "NC form not found")
    if nc.status == "pending_la":
        raise HTTPException(403, "Not yet available — awaiting auditor signature")
    return nc


@router.get("/client/my-audit-set/nc-forms")
def client_list_nc_forms(
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """Client sees NC forms once the Lead Auditor has signed (pending_client or complete)."""
    if current_user.role != "client" or not current_user.audit_set_id:
        raise HTTPException(403, "Client access only")
    rows = (
        db.query(AuditSetNCForm)
        .filter(
            AuditSetNCForm.audit_set_id == current_user.audit_set_id,
            AuditSetNCForm.status != "pending_la",
        )
        .order_by(AuditSetNCForm.created_at)
        .all()
    )
    return [_nc_dict(r) for r in rows]


@router.get("/client/my-audit-set/nc-forms/{nid}/download")
def client_download_nc_form(
    nid: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    nc = _get_client_nc(nid, current_user, db)
    if not nc.file_path or not os.path.exists(nc.file_path):
        raise HTTPException(404, "File not found on server")
    return FileResponse(
        nc.file_path,
        filename=nc.file_name or "nc_form.docx",
        media_type="application/octet-stream",
    )


@router.post("/client/my-audit-set/nc-forms/{nid}/sign/request-otp")
def client_nc_request_otp(
    nid: str,
    db:      Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    nc = _get_client_nc(nid, current_user, db)
    if nc.client_signed_at:
        raise HTTPException(400, "Already signed")

    otp = f"{secrets.randbelow(900000) + 100000}"
    nc.client_otp_hash    = _hash(otp)
    nc.client_otp_expires = datetime.utcnow() + timedelta(minutes=OTP_EXPIRY)
    db.commit()

    try:
        send_otp_code(
            to=current_user.email,
            full_name=current_user.full_name,
            otp=otp,
            document_label=f"NC Form — {nc.label}",
        )
    except Exception:
        pass

    return {"message": f"Code sent to {current_user.email}. Valid for {OTP_EXPIRY} minutes."}


@router.post("/client/my-audit-set/nc-forms/{nid}/sign/verify")
def client_nc_verify_otp(
    nid: str,
    otp: str,
    request: Request,
    db:      Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    nc = _get_client_nc(nid, current_user, db)
    if nc.client_signed_at:
        raise HTTPException(400, "Already signed")
    if not nc.client_otp_hash or not nc.client_otp_expires:
        raise HTTPException(400, "No pending OTP. Request one first.")
    if datetime.utcnow() > nc.client_otp_expires:
        raise HTTPException(400, "OTP expired. Please request a new one.")
    if _hash(otp.strip()) != nc.client_otp_hash:
        raise HTTPException(400, "Invalid code.")

    nc.client_user_id    = current_user.id
    nc.client_signed_at  = datetime.utcnow()
    nc.client_signed_ip  = request.client.host if request.client else None
    nc.client_otp_hash   = None
    nc.client_otp_expires = None
    nc.status            = "complete"
    db.commit()

    return {"signed": True, "status": "complete", "client_signed_at": nc.client_signed_at.isoformat()}


# ── Client: direct-sign (no OTP) ─────────────────────────────────────────────

@router.post("/client/my-audit-set/nc-forms/{nid}/sign/direct")
def client_sign_direct(
    nid: str,
    db:           Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    nc = _get_client_nc(nid, current_user, db)
    if nc.status not in ("pending_client",):
        raise HTTPException(400, f"NC form status is '{nc.status}', expected 'pending_client'")
    if nc.client_signed_at:
        raise HTTPException(400, "Already signed by client")

    nc.client_signed_at = datetime.utcnow()
    nc.status           = "complete"
    db.commit()
    db.refresh(nc)
    return _nc_dict(nc)
