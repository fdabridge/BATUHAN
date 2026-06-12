"""
BATUHAN — Certification Committee appointment (Prompt 14).

Endpoints under /audit-sets:
  GET    /audit-sets/{id}/committee
  GET    /audit-sets/{id}/committee/eligible-users
  POST   /audit-sets/{id}/committee/appoint
  DELETE /audit-sets/{id}/committee/{member_id}
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from audit_set.db_models import (
    AuditSet, AuditSetCommitteeMember, AuditSetStage,
    AuditDocumentSignature, get_db,
)
from auth.db_models import PlatformUser, get_db as get_auth_db
from auth.dependencies import get_current_user

router = APIRouter(prefix="/audit-sets", tags=["committee"])

CB_ROLES = {"admin", "planner", "officer", "executive", "gm"}


def _collect_stage_auditor_ids(stages: list) -> set[str]:
    """Return the set of auditors.auditors.id values assigned to any stage."""
    ids: set[str] = set()
    for s in stages:
        if s.lead_auditor_id:
            ids.add(s.lead_auditor_id)
        for group in (s.auditors or [], s.technical_experts or [],
                      s.observers or [], s.ik_experts or [], s.evaluators or []):
            for p in group:
                if isinstance(p, dict) and p.get("id"):
                    ids.add(p["id"])
    return ids


@router.get("/{audit_set_id}/committee")
def get_committee(
    audit_set_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "Not authorized")

    members = (
        db.query(AuditSetCommitteeMember)
        .filter_by(audit_set_id=audit_set_id)
        .order_by(AuditSetCommitteeMember.appointed_at)
        .all()
    )
    reviewer_sigs = {
        s.signer_user_id: s
        for s in db.query(AuditDocumentSignature).filter_by(
            audit_set_id=audit_set_id,
            signer_role_label="cb_reviewer",
        ).all()
        if s.signer_user_id
    }
    return [
        {
            "id":                      m.id,
            "user_id":                 m.user_id,
            "user_name":               m.user_name,
            "user_email":              m.user_email,
            "role":                    m.role,
            "appointed_by":            m.appointed_by,
            "ea_codes_at_appointment": m.ea_codes_at_appointment,
            "appointed_at":            m.appointed_at.isoformat() if m.appointed_at else None,
            "has_signed_fr218":        (
                reviewer_sigs.get(m.user_id) is not None
                and reviewer_sigs[m.user_id].signed_at is not None
            ),
        }
        for m in members
    ]


@router.get("/{audit_set_id}/committee/eligible-users")
def get_eligible_users(
    audit_set_id: str,
    db: Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "Not authorized")

    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Audit set not found")

    stages = db.query(AuditSetStage).filter_by(audit_set_id=audit_set_id).all()
    stage_auditor_ids = _collect_stage_auditor_ids(stages)

    already_appointed_user_ids = {
        m.user_id for m in
        db.query(AuditSetCommitteeMember).filter_by(audit_set_id=audit_set_id).all()
    }

    cb_users = (
        auth_db.query(PlatformUser)
        .filter(
            PlatformUser.role.in_(CB_ROLES),
            PlatformUser.is_active == True,  # noqa: E712
        )
        .all()
    )

    from auditors.models import Auditor as AuditorModel

    plan_ea_code = (audit_set.ea_code or "").strip()

    results = []
    for u in cb_users:
        if u.id in already_appointed_user_ids:
            continue

        ea_codes: list[str] = []
        on_audit_team = False

        if u.auditor_id:
            if u.auditor_id in stage_auditor_ids:
                on_audit_team = True
            auditor = db.query(AuditorModel).filter_by(id=u.auditor_id).first()
            if auditor:
                ea_codes = auditor.ea_codes or []

        if on_audit_team:
            continue

        if ea_codes:
            ea_match = (not plan_ea_code) or (plan_ea_code in ea_codes)
        else:
            ea_match = True

        results.append({
            "user_id":              u.id,
            "full_name":            u.full_name,
            "email":                u.email,
            "role":                 u.role,
            "ea_codes":             ea_codes,
            "ea_match":             ea_match,
            "has_auditor_profile":  bool(u.auditor_id),
            "eligible_as_reviewer": ea_match,
        })

    results.sort(key=lambda x: (not x["eligible_as_reviewer"], x["full_name"]))
    return results


class AppointRequest(BaseModel):
    user_id: str
    role: str  # "reviewer" | "decision_maker"


@router.post("/{audit_set_id}/committee/appoint")
def appoint_committee_member(
    audit_set_id: str,
    body: AppointRequest,
    db: Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in {"admin", "planner"}:
        raise HTTPException(403, "Only admin or planner can appoint committee members")

    if body.role not in ("reviewer", "decision_maker"):
        raise HTTPException(400, "role must be 'reviewer' or 'decision_maker'")

    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Audit set not found")

    user = auth_db.query(PlatformUser).filter_by(id=body.user_id).first()
    if not user or user.role not in CB_ROLES:
        raise HTTPException(400, "User not found or not a CB user")

    already = db.query(AuditSetCommitteeMember).filter_by(
        audit_set_id=audit_set_id, user_id=body.user_id
    ).first()
    if already:
        raise HTTPException(409, "User is already a committee member for this audit set")

    from auditors.models import Auditor as AuditorModel
    ea_codes_snapshot: list[str] = []
    if user.auditor_id:
        auditor = db.query(AuditorModel).filter_by(id=user.auditor_id).first()
        if auditor:
            ea_codes_snapshot = auditor.ea_codes or []

    member = AuditSetCommitteeMember(
        audit_set_id=audit_set_id,
        user_id=user.id,
        user_name=user.full_name,
        user_email=user.email,
        role=body.role,
        appointed_by=current_user.id,
        ea_codes_at_appointment=ea_codes_snapshot,
    )
    db.add(member)

    if body.role == "reviewer":
        sig = (
            db.query(AuditDocumentSignature)
            .filter_by(
                audit_set_id=audit_set_id,
                document_type="FR218",
                signer_role_label="cb_reviewer",
            )
            .first()
        )
        if sig and not sig.signed_at:
            sig.signer_user_id = user.id
            sig.signer_name    = user.full_name
            sig.signer_email   = user.email

    db.commit()
    return {
        "appointed": True,
        "user_id":   user.id,
        "user_name": user.full_name,
        "role":      body.role,
    }


@router.delete("/{audit_set_id}/committee/{member_id}")
def remove_committee_member(
    audit_set_id: str,
    member_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in {"admin", "planner"}:
        raise HTTPException(403, "Not authorized")

    member = db.query(AuditSetCommitteeMember).filter_by(
        id=member_id, audit_set_id=audit_set_id
    ).first()
    if not member:
        raise HTTPException(404, "Committee member not found")

    has_signed = (
        db.query(AuditDocumentSignature)
        .filter_by(audit_set_id=audit_set_id, signer_user_id=member.user_id)
        .filter(AuditDocumentSignature.signed_at.isnot(None))
        .count()
    ) > 0
    if has_signed:
        raise HTTPException(
            409, "Cannot remove a committee member who has already signed documents"
        )

    if member.role == "reviewer":
        sig = (
            db.query(AuditDocumentSignature)
            .filter_by(
                audit_set_id=audit_set_id,
                document_type="FR218",
                signer_role_label="cb_reviewer",
                signer_user_id=member.user_id,
            )
            .first()
        )
        if sig:
            sig.signer_user_id = None
            sig.signer_name    = None
            sig.signer_email   = None

    db.delete(member)
    db.commit()
    return {"removed": True}
