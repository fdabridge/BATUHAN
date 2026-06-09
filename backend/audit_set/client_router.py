"""
BATUHAN — Client portal API (Prompt 05).
Routes for client-role users to view their own audit set.

Only exposes a curated subset of AuditSet fields — fees, internal notes, and
other CB-only data are intentionally omitted from the response payload.
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from pydantic import BaseModel

from audit_set.db_models import (
    AuditSet,
    AuditSetMessage,
    AuditSetSharedDocument,
    AuditSetStatusEvent,
    get_db,
)
from auth.db_models import PlatformUser, get_db as get_auth_db
from auth.dependencies import get_current_user

router = APIRouter(prefix="/client", tags=["client-portal"])


class MessageCreateSchema(BaseModel):
    body: str


def _get_client_audit_set(current_user: PlatformUser, db: Session) -> AuditSet:
    """Resolve the audit set belonging to the current client user."""
    if current_user.role != "client":
        raise HTTPException(403, "Client portal access only")
    if not current_user.audit_set_id:
        raise HTTPException(404, "No audit set linked to this account")
    audit_set = db.query(AuditSet).filter_by(id=current_user.audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Audit set not found")
    return audit_set


@router.get("/my-audit-set")
def get_my_audit_set(
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """Returns the client's audit set — filtered to fields safe for client view."""
    audit_set = _get_client_audit_set(current_user, db)

    stages_out = []
    for s in (audit_set.stages or []):
        stages_out.append({
            "stage_type":        s.stage_type,
            "stage_order":       s.stage_order,
            "audit_date_start":  s.audit_date_start.isoformat() if s.audit_date_start else None,
            "audit_date_end":    s.audit_date_end.isoformat()   if s.audit_date_end   else None,
            "lead_auditor_name": s.lead_auditor_name,
            "status":            s.status,
        })

    return {
        "id":                 audit_set.id,
        "plan_number":        audit_set.plan_number,
        "client_reference":   audit_set.client_reference,
        "company_name":       audit_set.company_name,
        "company_address":    audit_set.company_address,
        "standards":          audit_set.standards,
        "audit_type":         audit_set.audit_type,
        "accreditation_body": audit_set.accreditation_body,
        "scope_en":           audit_set.scope_en,
        "workflow_status":    audit_set.workflow_status,
        "cert_issued_date":   audit_set.cert_issued_date.isoformat() if audit_set.cert_issued_date else None,
        "cert_expiry_date":   audit_set.cert_expiry_date.isoformat() if audit_set.cert_expiry_date else None,
        "cert_status":        audit_set.cert_status,
        "stages":             stages_out,
        "created_at":         audit_set.created_at.isoformat() if audit_set.created_at else None,
    }


@router.get("/my-audit-set/status-history")
def get_my_status_history(
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    audit_set = _get_client_audit_set(current_user, db)
    events = (
        db.query(AuditSetStatusEvent)
        .filter_by(audit_set_id=audit_set.id)
        .order_by(AuditSetStatusEvent.triggered_at)
        .all()
    )
    return [
        {
            "to_status":    e.to_status,
            "triggered_at": e.triggered_at.isoformat() if e.triggered_at else None,
            "notes":        e.notes,
        }
        for e in events
    ]


# ── Messages ─────────────────────────────────────────────────────────────────

@router.get("/my-audit-set/messages")
def get_my_messages(
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    audit_set = _get_client_audit_set(current_user, db)
    msgs = (
        db.query(AuditSetMessage)
        .filter_by(audit_set_id=audit_set.id)
        .order_by(AuditSetMessage.created_at)
        .all()
    )
    return [
        {
            "id":          m.id,
            "sender_name": m.sender_name,
            "sender_role": m.sender_role,
            "body":        m.body,
            "created_at":  m.created_at.isoformat() if m.created_at else None,
            "is_mine":     m.sender_user_id == current_user.id,
        }
        for m in msgs
    ]


@router.post("/my-audit-set/messages")
def post_my_message(
    payload: MessageCreateSchema,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    audit_set = _get_client_audit_set(current_user, db)
    body = (payload.body or "").strip()
    if not body:
        raise HTTPException(400, "Message body cannot be empty")
    msg = AuditSetMessage(
        audit_set_id=audit_set.id,
        sender_user_id=current_user.id,
        sender_name=current_user.full_name,
        sender_role=current_user.role,
        body=body,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return {
        "id":         msg.id,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }



# ── Documents (client-scoped shortcuts; delegate signing to documents_router) ─

@router.get("/my-audit-set/documents")
def get_my_documents(
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    audit_set = _get_client_audit_set(current_user, db)
    docs = (
        db.query(AuditSetSharedDocument)
        .filter_by(audit_set_id=audit_set.id, direction="cb_to_client")
        .order_by(AuditSetSharedDocument.created_at)
        .all()
    )
    return [
        {
            "id":            d.id,
            "label":         d.label,
            "document_type": d.document_type,
            "status":        d.status,
            "released_at":   d.released_at.isoformat() if d.released_at else None,
            "signed_at":     d.signed_at.isoformat()   if d.signed_at   else None,
        }
        for d in docs
    ]


@router.get("/my-audit-set/documents/{doc_id}/download")
def download_my_document(
    doc_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    from fastapi.responses import FileResponse
    import os

    audit_set = _get_client_audit_set(current_user, db)
    doc = db.query(AuditSetSharedDocument).filter_by(
        id=doc_id, audit_set_id=audit_set.id, direction="cb_to_client"
    ).first()
    if not doc or not doc.file_path or not os.path.exists(doc.file_path):
        raise HTTPException(404, "Document not found")
    return FileResponse(
        doc.file_path,
        filename=os.path.basename(doc.file_path),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@router.post("/my-audit-set/documents/{doc_id}/sign/request-otp")
def client_request_otp(
    doc_id: str,
    db: Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    from audit_set.documents_router import request_sign_otp
    audit_set = _get_client_audit_set(current_user, db)
    return request_sign_otp(audit_set.id, doc_id, db, auth_db, current_user)


@router.post("/my-audit-set/documents/{doc_id}/sign/verify")
def client_verify_otp(
    doc_id: str,
    otp: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    from audit_set.documents_router import verify_sign_otp
    audit_set = _get_client_audit_set(current_user, db)
    return verify_sign_otp(audit_set.id, doc_id, request, otp, db, current_user)
