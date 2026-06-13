"""
BATUHAN — Auditor portal API (Prompt 08).
Routes for auditor-role users to view audit sets they are assigned to (as
lead auditor or team member on any stage), read/post messages on those
audit sets, and read the curated detail payload.

Document upload happens through the existing
POST /audit-sets/{id}/documents/upload endpoint (Prompt 07) which already
gates on AUDITOR_UPLOAD_ROLES.
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from audit_set.db_models import (
    AuditSet,
    AuditSetMessage,
    AuditSetStage,
    get_db,
)
from auth.db_models import PlatformUser
from auth.dependencies import get_current_user

router = APIRouter(prefix="/auditor", tags=["auditor-portal"])

# admin is included so an admin can verify the portal end-to-end without
# needing to create an auditor account.
AUDITOR_PORTAL_ROLES = {"auditor", "admin"}


class MessageCreateSchema(BaseModel):
    body: str


def _require_auditor(current_user: PlatformUser) -> PlatformUser:
    if current_user.role not in AUDITOR_PORTAL_ROLES:
        raise HTTPException(403, "Auditor portal access only")
    return current_user


def _stage_matches_auditor(stage: AuditSetStage, auditor_id: str) -> tuple[bool, bool]:
    """Return (is_assigned, is_lead) for this auditor on the given stage.
    Portal 50a fix: checks lead auditor, regular auditors, AND technical experts.
    """
    is_lead = bool(stage.lead_auditor_id) and stage.lead_auditor_id == auditor_id
    all_members = list(stage.auditors or []) + list(stage.technical_experts or [])
    is_team = any(
        isinstance(a, dict) and a.get("id") == auditor_id
        for a in all_members
    )
    return (is_lead or is_team, is_lead)


def _get_auditor_assignments(current_user: PlatformUser, db: Session) -> list[AuditSet]:
    """Find audit sets where this auditor is lead or team member on any stage."""
    if not current_user.auditor_id:
        return []
    auditor_id = current_user.auditor_id

    matching_ids: set[str] = set()
    for stage in db.query(AuditSetStage).all():
        assigned, _ = _stage_matches_auditor(stage, auditor_id)
        if assigned:
            matching_ids.add(stage.audit_set_id)

    if not matching_ids:
        return []
    return (
        db.query(AuditSet)
        .filter(AuditSet.id.in_(matching_ids))
        .order_by(AuditSet.created_at.desc())
        .all()
    )


@router.get("/my-assignments")
def get_my_assignments(
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    _require_auditor(current_user)
    audit_sets = _get_auditor_assignments(current_user, db)
    auditor_id = current_user.auditor_id

    result = []
    for a in audit_sets:
        my_stages = []
        for s in (a.stages or []):
            assigned, is_lead = _stage_matches_auditor(s, auditor_id)
            if not assigned:
                continue
            my_stages.append({
                "stage_type":       s.stage_type,
                "audit_date_start": s.audit_date_start.isoformat() if s.audit_date_start else None,
                "audit_date_end":   s.audit_date_end.isoformat()   if s.audit_date_end   else None,
                "is_lead":          is_lead,
                "status":           s.status,
            })
        result.append({
            "id":              a.id,
            "plan_number":     a.plan_number,
            "company_name":    a.company_name,
            "company_address": a.company_address,
            "standards":       a.standards,
            "audit_type":      a.audit_type,
            "scope_en":        a.scope_en,
            "workflow_status": a.workflow_status,
            "my_stages":       my_stages,
        })
    return result


def _assert_assigned(audit_set_id: str, current_user: PlatformUser, db: Session) -> None:
    assigned_ids = {a.id for a in _get_auditor_assignments(current_user, db)}
    if audit_set_id not in assigned_ids:
        raise HTTPException(403, "Not assigned to this audit set")


@router.get("/my-assignments/{audit_set_id}")
def get_assignment_detail(
    audit_set_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    _require_auditor(current_user)
    _assert_assigned(audit_set_id, current_user, db)

    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Not found")

    stages_out = []
    for s in (audit_set.stages or []):
        stages_out.append({
            "stage_type":        s.stage_type,
            "stage_order":       s.stage_order,
            "audit_date_start":  s.audit_date_start.isoformat() if s.audit_date_start else None,
            "audit_date_end":    s.audit_date_end.isoformat()   if s.audit_date_end   else None,
            "lead_auditor_name": s.lead_auditor_name,
            "audit_days":        s.audit_days,
            "status":            s.status,
        })

    return {
        "id":                     audit_set.id,
        "plan_number":            audit_set.plan_number,
        "client_reference":       audit_set.client_reference,
        "company_name":           audit_set.company_name,
        "company_address":        audit_set.company_address,
        "email":                  audit_set.email,
        "phone":                  audit_set.phone,
        "representative":         audit_set.representative,
        "standards":              audit_set.standards,
        "audit_type":             audit_set.audit_type,
        "scope_en":               audit_set.scope_en,
        "non_applicable_clauses": audit_set.non_applicable_clauses,
        "ea_code":                audit_set.ea_code,
        "ea_category":            audit_set.ea_category,
        "accreditation_body":     audit_set.accreditation_body,
        "workflow_status":        audit_set.workflow_status,
        "stages":                 stages_out,
    }


@router.get("/my-assignments/{audit_set_id}/messages")
def get_assignment_messages(
    audit_set_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    _require_auditor(current_user)
    _assert_assigned(audit_set_id, current_user, db)

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


@router.post("/my-assignments/{audit_set_id}/messages")
def post_assignment_message(
    audit_set_id: str,
    payload: MessageCreateSchema,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    _require_auditor(current_user)
    _assert_assigned(audit_set_id, current_user, db)

    body = (payload.body or "").strip()
    if not body:
        raise HTTPException(400, "Message body cannot be empty")

    msg = AuditSetMessage(
        audit_set_id=audit_set_id,
        sender_user_id=current_user.id,
        sender_name=current_user.full_name,
        sender_role="auditor",
        body=body,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return {
        "id":         msg.id,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }
