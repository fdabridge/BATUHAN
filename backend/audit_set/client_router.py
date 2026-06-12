"""
BATUHAN — Client portal API (Prompt 05).
Routes for client-role users to view their own audit set.

Only exposes a curated subset of AuditSet fields — fees, internal notes, and
other CB-only data are intentionally omitted from the response payload.
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from pydantic import BaseModel

from audit_set.db_models import (
    AuditSet,
    AuditSetMessage,
    AuditSetSharedDocument,
    AuditSetStatusEvent,
    get_db,
)
from auth.db_models import PlatformUser
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
        # Team roster (id + name only) — the client needs it for FR.211
        # auditor-assessment uploads. Names are already known to the client
        # via FR.223, so this leaks nothing new.
        team = []
        seen_ids: set[str] = set()

        def _push(member_id, member_name, member_role):
            if not member_id or member_id in seen_ids:
                return
            seen_ids.add(member_id)
            team.append({"id": member_id, "name": member_name or member_id, "role": member_role})

        _push(s.lead_auditor_id, s.lead_auditor_name, "Lead Auditor")
        for m in (s.auditors or []):
            if isinstance(m, dict):
                _push(m.get("id"), m.get("name"), "Auditor")
        for m in (s.technical_experts or []):
            if isinstance(m, dict):
                _push(m.get("id"), m.get("name"), "Technical Expert")

        stages_out.append({
            "stage_type":        s.stage_type,
            "stage_order":       s.stage_order,
            "audit_date_start":  s.audit_date_start.isoformat() if s.audit_date_start else None,
            "audit_date_end":    s.audit_date_end.isoformat()   if s.audit_date_end   else None,
            "lead_auditor_name": s.lead_auditor_name,
            "status":            s.status,
            "team":              team,
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



# ── Documents (client-scoped shortcuts; signing happens in the viewer) ───────

@router.get("/my-audit-set/documents")
def get_my_documents(
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    from audit_set.documents_router import _doc_to_dict, _visible_docs_for_user

    audit_set = _get_client_audit_set(current_user, db)
    docs = _visible_docs_for_user(audit_set.id, current_user, db)
    return [_doc_to_dict(d, db) for d in docs]


@router.get("/my-audit-set/documents/{doc_id}/download")
def download_my_document(
    doc_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    from fastapi.responses import FileResponse
    import os

    from audit_set.documents_router import _visible_docs_for_user

    audit_set = _get_client_audit_set(current_user, db)
    visible_ids = {d.id for d in _visible_docs_for_user(audit_set.id, current_user, db)}
    doc = db.query(AuditSetSharedDocument).filter_by(
        id=doc_id, audit_set_id=audit_set.id
    ).first()
    if not doc or doc.id not in visible_ids or not doc.file_path or not os.path.exists(doc.file_path):
        raise HTTPException(404, "Document not found")
    return FileResponse(
        doc.file_path,
        filename=os.path.basename(doc.file_path),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
