"""
BATUHAN — FR.230 NC Form (Portal 49b).

All signing is now done via the visual document viewer (POST /viewer/sign/confirm).
OTP and direct-sign endpoints have been removed.

Routes (kept for backward compat with legacy AuditSetNCForm records):
  POST /audit-sets/{id}/nc-forms/upload          (CB admin/planner — multipart)
  GET  /audit-sets/{id}/nc-forms                 (CB + auditor — list all for this audit set)
  GET  /audit-sets/{id}/nc-forms/{nid}/download  (CB + auditor)
  GET  /client/my-audit-set/nc-forms             (client only)
  GET  /client/my-audit-set/nc-forms/{nid}/download  (client only, pending_client+)

New NC forms should be uploaded via POST /audit-sets/{id}/documents/upload
with document_type="nc_form" and signed via the visual viewer.
"""
from __future__ import annotations
import os
import secrets


from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from audit_set.db_models import AuditSet, AuditSetNCForm, AuditSetStage, get_db
from auth.db_models import PlatformUser, get_db as get_auth_db
from auth.dependencies import get_current_user
from config.settings import get_settings
from storage.document_store import upload as store_upload, ensure_local
from email_service import send_nc_form_la_request

router = APIRouter(tags=["nc_forms"])

CB_ROLES = {"admin", "planner", "planner_us", "officer", "executive", "gm"}


def _nc_dict(n: AuditSetNCForm) -> dict:
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
    if current_user.role not in {"admin", "planner", "planner_us"}:
        raise HTTPException(403, "Not authorized")

    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Audit set not found")

    safe_name = f"{secrets.token_hex(6)}_{file.filename or 'nc_form'}"
    relative_path = f"nc_forms/{audit_set_id}/{safe_name}"
    content = await file.read()
    file_path = store_upload(relative_path, content)

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

    if not nc.file_path:
        raise HTTPException(404, "File not found on server")
    try:
        local_path = ensure_local(nc.file_path)
    except FileNotFoundError:
        raise HTTPException(404, "File not found on server")
    return FileResponse(
        local_path,
        filename=nc.file_name or "nc_form.docx",
        media_type="application/octet-stream",
    )


# ── Client: view and download ─────────────────────────────────────────────────

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
    if not nc.file_path:
        raise HTTPException(404, "File not found on server")
    try:
        local_path = ensure_local(nc.file_path)
    except FileNotFoundError:
        raise HTTPException(404, "File not found on server")
    return FileResponse(
        local_path,
        filename=nc.file_name or "nc_form.docx",
        media_type="application/octet-stream",
    )



