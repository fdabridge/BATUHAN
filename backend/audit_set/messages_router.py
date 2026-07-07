"""
BATUHAN — Audit set messaging API (CB-side, Prompt 06).
CB users (admin / planner / officer / executive / auditor) can read and post
messages on any audit set. Each post notifies the linked client user by email.
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from audit_set.db_models import AuditSet, AuditSetMessage, get_db
from auth.db_models import PlatformUser, get_db as get_auth_db
from auth.dependencies import get_current_user
from email_service import send_new_message_notification

router = APIRouter(prefix="/audit-sets", tags=["messages"])

CB_ROLES = {"admin", "planner", "planner_us", "officer", "executive", "auditor"}


class MessageCreateSchema(BaseModel):
    body: str


@router.get("/{audit_set_id}/messages")
def get_messages(
    audit_set_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "Not authorized")
    msgs = (
        db.query(AuditSetMessage)
        .filter_by(audit_set_id=audit_set_id)
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


@router.post("/{audit_set_id}/messages")
def post_message(
    audit_set_id: str,
    payload: MessageCreateSchema,
    db: Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "Not authorized")
    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Audit set not found")
    body = (payload.body or "").strip()
    if not body:
        raise HTTPException(400, "Message body cannot be empty")

    msg = AuditSetMessage(
        audit_set_id=audit_set_id,
        sender_user_id=current_user.id,
        sender_name=current_user.full_name,
        sender_role=current_user.role,
        body=body,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    # Notify the client user if one is linked. Email failures don't roll back.
    client_user = auth_db.query(PlatformUser).filter_by(
        audit_set_id=audit_set_id, role="client"
    ).first()
    if client_user:
        try:
            send_new_message_notification(
                to=client_user.email,
                full_name=client_user.full_name,
                sender_name=current_user.full_name,
            )
        except Exception:
            pass

    return {
        "id":         msg.id,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }
