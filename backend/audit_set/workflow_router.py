"""
BATUHAN — Audit Set workflow status transitions.
Manages the client portal certification lifecycle (Prompt 04).

Endpoints (all under /audit-sets, all auth-gated via get_current_user):
    GET   /audit-sets/pending-applications      → CB queue of submitted applications
    GET   /audit-sets/{id}/status-history       → audit_set_status_events for one set
    PATCH /audit-sets/{id}/workflow-status      → validated transition + client notify

The transition matrix is enforced server-side: only listed (from, to) pairs are
allowed, and only listed roles may trigger each. Every transition is recorded
in audit_set_status_events for ISO 17021-1 §9.5 traceability and (if a client
account is linked) a templated email is fired via email_service.
"""
from __future__ import annotations
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from audit_set.db_models import (
    AuditSet,
    AuditSetStage,
    AuditSetStatusEvent,
    get_db as get_audit_db,
)
from audit_set.pipeline_triggers import fire_phase_triggers
from auth.db_models import PlatformUser, get_db as get_auth_db
from auth.dependencies import get_current_user
from email_service import send_client_status_update

router = APIRouter(prefix="/audit-sets", tags=["workflow"])


# (from_status_or_None, to_status) → set of roles allowed to trigger
VALID_TRANSITIONS: dict[tuple[Optional[str], str], set[str]] = {
    (None,                "pending_review"):    {"system"},
    ("pending_review",    "in_planning"):       {"admin", "planner"},
    ("in_planning",       "quotation_sent"):    {"admin", "planner"},
    ("quotation_sent",    "agreement_signed"):  {"admin", "planner", "client"},
    # ── Surveillance / Recertification path (single-audit) ───────────────────
    ("agreement_signed",  "audit_scheduled"):   {"admin", "planner"},
    ("audit_scheduled",   "audit_in_progress"): {"admin", "planner", "auditor"},
    ("audit_in_progress", "under_review"):      {"admin", "planner", "auditor"},
    # ── Initial certification — FR.218 Application Review (Portal 47) ────────
    # These two are auto-fired by the backend (agreement signing + FR.218
    # completion). Keeping them in VALID_TRANSITIONS lets jump/manual
    # corrections by admin still go through the normal endpoint.
    ("agreement_signed",  "fr218_in_progress"): {"admin"},
    ("fr218_in_progress", "fr218_complete"):    {"admin"},
    # ── Initial certification — Stage 1 ──────────────────────────────────────
    ("fr218_complete",     "stage1_scheduled"):   {"admin", "planner"},
    ("agreement_signed",   "stage1_scheduled"):   {"admin", "planner"},  # retroactive / legacy
    ("stage1_scheduled",   "stage1_in_progress"): {"admin", "planner", "auditor"},
    ("stage1_in_progress", "stage1_complete"):    {"admin", "planner", "auditor"},
    # ── Initial certification — Stage 2 ──────────────────────────────────────
    ("stage1_complete",    "stage2_scheduled"):   {"admin", "planner"},
    ("stage2_scheduled",   "stage2_in_progress"): {"admin", "planner", "auditor"},
    ("stage2_in_progress", "under_review"):       {"admin", "planner", "auditor"},
    # ── Shared closing ────────────────────────────────────────────────────────
    ("under_review",       "certified"):          {"admin", "executive"},
}

CB_REVIEW_ROLES = {"admin", "planner", "officer", "executive"}


class WorkflowUpdateSchema(BaseModel):
    workflow_status: str
    notes: Optional[str] = None
    effective_date: Optional[date] = None    # override the transition timestamp (retroactive mode)


# The full set of statuses that can be set via the jump endpoint.
VALID_JUMP_STATUSES = {
    "in_planning",
    "quotation_sent",
    "agreement_signed",
    "fr218_in_progress",
    "fr218_complete",
    "stage1_scheduled",
    "stage1_in_progress",
    "stage1_complete",
    "stage2_scheduled",
    "stage2_in_progress",
    "audit_scheduled",
    "audit_in_progress",
    "under_review",
    "certified",
}


class WorkflowJumpSchema(BaseModel):
    target_status: str
    effective_date: Optional[date] = None   # defaults to now if omitted


@router.get("/pending-applications")
def list_pending_applications(
    db: Session = Depends(get_audit_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """CB-only: list audit sets submitted via portal that are pending review."""
    if current_user.role not in CB_REVIEW_ROLES:
        raise HTTPException(403, "Not authorized")

    results = (
        db.query(AuditSet)
        .filter(AuditSet.submitted_via_portal == True)  # noqa: E712
        .filter(AuditSet.workflow_status == "pending_review")
        .order_by(AuditSet.created_at.desc())
        .all()
    )
    return [
        {
            "id": a.id,
            "plan_number": a.plan_number,
            "company_name": a.company_name,
            "company_address": a.company_address,
            "email": a.email,
            "phone": a.phone,
            "standards": a.standards,
            "audit_type": a.audit_type,
            "scope_en": a.scope_en,
            "workflow_status": a.workflow_status,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in results
    ]


@router.get("/{audit_set_id}/status-history")
def get_status_history(
    audit_set_id: str,
    db: Session = Depends(get_audit_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    events = (
        db.query(AuditSetStatusEvent)
        .filter_by(audit_set_id=audit_set_id)
        .order_by(AuditSetStatusEvent.triggered_at)
        .all()
    )
    return [
        {
            "from_status": e.from_status,
            "to_status": e.to_status,
            "triggered_by": e.triggered_by,
            "triggered_at": e.triggered_at.isoformat() if e.triggered_at else None,
            "notes": e.notes,
        }
        for e in events
    ]


@router.patch("/{audit_set_id}/workflow-status")
def update_workflow_status(
    audit_set_id: str,
    payload: WorkflowUpdateSchema,
    db: Session = Depends(get_audit_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Audit set not found")

    from_status = audit_set.workflow_status
    to_status = payload.workflow_status

    allowed_roles = VALID_TRANSITIONS.get((from_status, to_status))
    if allowed_roles is None:
        raise HTTPException(400, f"Invalid transition: {from_status} → {to_status}")
    if current_user.role not in allowed_roles:
        raise HTTPException(403, f"Role '{current_user.role}' cannot make this transition")

    audit_set.workflow_status = to_status

    # When Stage 1 is marked complete, close out the Stage 1 AuditSetStage row.
    if to_status == "stage1_complete":
        stage1_row = (
            db.query(AuditSetStage)
            .filter_by(audit_set_id=audit_set_id, stage_type="stage_1")
            .first()
        )
        if stage1_row:
            stage1_row.status = "complete"

    # Retroactive mode: use caller-supplied date if provided, else record now.
    if payload.effective_date:
        effective_ts = datetime(
            payload.effective_date.year,
            payload.effective_date.month,
            payload.effective_date.day,
        )
    else:
        effective_ts = datetime.utcnow()

    event = AuditSetStatusEvent(
        audit_set_id=audit_set_id,
        from_status=from_status,
        to_status=to_status,
        triggered_by=current_user.id,
        triggered_at=effective_ts,
        notes=payload.notes,
    )
    db.add(event)
    db.commit()

    # Portal 47 — fire phase side effects (FR.218 seeding on agreement_signed,
    # per-auditor FR.224 + FR.211 on stage_X_scheduled, etc.). The function
    # commits internally.
    fire_phase_triggers(
        audit_set_id=audit_set_id,
        new_status=to_status,
        triggered_by=current_user.id,
        db=db,
        effective_ts=effective_ts,
    )

    # Notify linked client account (silent failure — email is best-effort)
    client_user = auth_db.query(PlatformUser).filter_by(
        audit_set_id=audit_set_id, role="client",
    ).first()
    if client_user:
        send_client_status_update(
            to=client_user.email,
            full_name=client_user.full_name,
            new_status=to_status,
            notes=payload.notes or "",
        )

    return {"workflow_status": to_status, "updated": True}


@router.post("/{audit_set_id}/workflow-status/jump")
def jump_workflow_status(
    audit_set_id: str,
    payload: WorkflowJumpSchema,
    db: Session = Depends(get_audit_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """
    Retroactive operation: set workflow_status directly, bypassing transition rules.
    Admin and planner only. Creates a single status event with the supplied date.
    Does NOT fire the side effects of normal transitions (FR.218 seeding, etc.).
    """
    if current_user.role not in {"admin", "planner"}:
        raise HTTPException(403, "Only admin and planner can jump workflow status")

    if payload.target_status not in VALID_JUMP_STATUSES:
        raise HTTPException(400, f"Unknown status: {payload.target_status}")

    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Audit set not found")

    from_status = audit_set.workflow_status
    if from_status == payload.target_status:
        raise HTTPException(400, "Audit set is already at that status")

    audit_set.workflow_status = payload.target_status

    if payload.effective_date:
        effective_ts = datetime(
            payload.effective_date.year,
            payload.effective_date.month,
            payload.effective_date.day,
        )
    else:
        effective_ts = datetime.utcnow()

    event = AuditSetStatusEvent(
        audit_set_id=audit_set_id,
        from_status=from_status,
        to_status=payload.target_status,
        triggered_by=current_user.id,
        triggered_at=effective_ts,
        notes="Retroactive jump — set by admin",
    )
    db.add(event)
    db.commit()
    db.refresh(audit_set)

    return {"id": audit_set.id, "workflow_status": audit_set.workflow_status}


@router.delete("/{audit_set_id}")
def delete_audit_set(
    audit_set_id: str,
    db: Session = Depends(get_audit_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """
    Hard-delete an AuditSet and its linked client PlatformUser (if any).
    Restricted to admin and planner. Child rows in audit_set_stages,
    audit_set_status_events, audit_set_messages, and audit_set_shared_documents
    are removed by Postgres ON DELETE CASCADE.
    """
    if current_user.role not in {"admin", "planner"}:
        raise HTTPException(403, "Not authorized")

    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Audit set not found")

    # Free the email by removing the linked client account first
    client_user = auth_db.query(PlatformUser).filter_by(
        audit_set_id=audit_set_id, role="client",
    ).first()
    if client_user:
        auth_db.delete(client_user)
        auth_db.commit()

    db.delete(audit_set)
    db.commit()

    return {"deleted": True, "id": audit_set_id}
