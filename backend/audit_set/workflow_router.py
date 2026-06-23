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
    AuditDocumentSignature,
    AuditSet,
    AuditSetAuditReport,
    AuditSetSharedDocument,
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
    # ── Surveillance: notification replaces quotation + agreement ─────────────
    ("in_planning",          "notification_sent"):  {"admin", "planner"},
    ("notification_sent",    "audit_scheduled"):    {"admin", "planner"},
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
    # Portal 49b: the team is assigned at planning, so fr218_complete advances
    # directly to stage1_in_progress (gated below). Scheduled statuses are
    # kept for legacy sets only.
    ("fr218_complete",     "stage1_in_progress"): {"admin", "planner"},
    ("fr218_complete",     "stage1_scheduled"):   {"admin", "planner"},  # legacy
    ("agreement_signed",   "stage1_scheduled"):   {"admin", "planner"},  # retroactive / legacy
    ("stage1_scheduled",   "stage1_in_progress"): {"admin", "planner", "auditor"},
    ("stage1_in_progress", "stage1_complete"):    {"admin", "planner", "auditor"},
    # ── Initial certification — Stage 2 ──────────────────────────────────────
    # Portal 49b: CM clicks "Stage 1 appropriate" → stage2_in_progress (gated).
    ("stage1_complete",    "stage2_in_progress"): {"admin", "executive", "certification_manager"},
    ("stage1_complete",    "stage2_scheduled"):   {"admin", "planner"},  # legacy
    ("stage2_scheduled",   "stage2_in_progress"): {"admin", "planner", "auditor"},
    ("stage2_in_progress", "stage2_complete"):    {"admin", "planner", "auditor"},
    ("stage2_in_progress", "under_review"):       {"admin", "planner", "auditor"},  # legacy
    # ── Committee + closing ───────────────────────────────────────────────────
    ("stage2_complete",    "committee_review"):   {"admin", "planner", "certification_manager"},
    ("under_review",       "certified"):          {"admin", "executive"},
}

CB_REVIEW_ROLES = {"admin", "planner", "officer", "executive"}


# ─── Portal 49b: hard entry gates ────────────────────────────────────────────
def _unsigned_required_count(db: Session, doc_id: str) -> int:
    """Number of required signature slots still unsigned on a document."""
    return (
        db.query(AuditDocumentSignature)
        .filter_by(document_id=doc_id, required=True)
        .filter(AuditDocumentSignature.signed_at.is_(None))
        .count()
    )


def _stage_docs(
    db: Session,
    audit_set_id: str,
    document_type: str,
    stage_type: str,
    include_null_stage: bool = False,
) -> list[AuditSetSharedDocument]:
    """Shared documents of a type for one stage (optionally legacy NULL stage)."""
    q = db.query(AuditSetSharedDocument).filter_by(
        audit_set_id=audit_set_id, document_type=document_type,
    )
    if include_null_stage:
        q = q.filter(
            (AuditSetSharedDocument.stage_type == stage_type)
            | (AuditSetSharedDocument.stage_type.is_(None))
        )
    else:
        q = q.filter(AuditSetSharedDocument.stage_type == stage_type)
    return q.all()


def _assert_stage_entry_gate(db: Session, audit_set_id: str, stage: str) -> None:
    """
    Portal 49b gate chain — hard server-side checks before stage1_in_progress
    may start. Stage 2 planning docs (FR.224s, FR.223) are uploaded DURING
    stage2_in_progress, not before it — see _assert_stage1_complete_gate().

    stage1_in_progress requires:
      • FR.222 (audit_programme) fully signed (CB_PLANNER + CB_CERT_MANAGER)
      • ALL Stage 1 FR.224s (team_info) signed by their assigned auditors
      • FR.223 (audit_plan, Stage 1) signed by ORG_REP
    """
    if stage != "stage_1":
        return

    failures: list[str] = []

    programmes = db.query(AuditSetSharedDocument).filter_by(
        audit_set_id=audit_set_id, document_type="audit_programme",
    ).all()
    if not programmes:
        failures.append("FR.222 Audit Programme has not been uploaded")
    elif any(_unsigned_required_count(db, p.id) for p in programmes):
        failures.append("FR.222 Audit Programme is not fully signed (Planner + Cert Manager)")

    team_infos = _stage_docs(
        db, audit_set_id, "team_info", "stage_1", include_null_stage=True,
    )
    if not team_infos:
        failures.append("No FR.224 team-info documents exist for stage_1")
    elif any(_unsigned_required_count(db, t.id) for t in team_infos):
        failures.append("Not all stage_1 FR.224s are signed by their assigned auditors")

    plans = _stage_docs(
        db, audit_set_id, "audit_plan", "stage_1", include_null_stage=True,
    )
    if not plans:
        failures.append("FR.223 Audit Plan for stage_1 has not been uploaded")
    elif any(_unsigned_required_count(db, p.id) for p in plans):
        failures.append("FR.223 Audit Plan (stage_1) is not signed by the organisation representative")

    if failures:
        raise HTTPException(409, "Gate not met: " + "; ".join(failures))


def _assert_stage1_complete_gate(db: Session, audit_set_id: str) -> None:
    """
    Gate for stage1_complete → stage2_in_progress.
    Verifies Stage 1 outcome documents are finished before the CM opens Stage 2.

    Checks:
      • All Stage 1 FR.224 (team_info) documents are fully signed.
      • Stage 1 FR.231 (stage1_report) is uploaded and fully signed.
    """
    failures: list[str] = []

    team_infos = _stage_docs(
        db, audit_set_id, "team_info", "stage_1", include_null_stage=True,
    )
    if team_infos and any(_unsigned_required_count(db, t.id) for t in team_infos):
        failures.append("Not all Stage 1 FR.224s are fully signed by their assigned auditors")

    # FR.231 is stored in AuditSetAuditReport (uploaded via report_router),
    # not in AuditSetSharedDocument — check the correct table.
    stage1_audit_reports = (
        db.query(AuditSetAuditReport)
        .filter_by(audit_set_id=audit_set_id, stage_type="stage_1")
        .filter(AuditSetAuditReport.report_form.in_(["FR.231", "FR.229"]))
        .all()
    )
    if not stage1_audit_reports:
        failures.append("Stage 1 FR.231 Stage Report has not been uploaded")
    elif not any(
        r.la_signed_at is not None and r.reviewer_signed_at is not None
        for r in stage1_audit_reports
    ):
        failures.append("Stage 1 FR.231 Stage Report is not fully signed")

    if failures:
        raise HTTPException(409, "Gate not met: " + "; ".join(failures))


class WorkflowUpdateSchema(BaseModel):
    workflow_status: str
    notes: Optional[str] = None
    effective_date: Optional[date] = None    # override the transition timestamp (retroactive mode)


# The full set of statuses that can be set via the jump endpoint.
VALID_JUMP_STATUSES = {
    "in_planning",
    "notification_sent",
    "quotation_sent",
    "agreement_signed",
    "fr218_in_progress",
    "fr218_complete",
    "stage1_scheduled",
    "stage1_in_progress",
    "stage1_complete",
    "stage2_scheduled",
    "stage2_in_progress",
    "stage2_complete",
    "committee_review",
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

    # Portal 49b — hard gates: Stage 1 cannot start until its planning
    # documents are fully signed (FR.222 / FR.224s / FR.223). Stage 2 has
    # no entry-doc gate (those docs are produced during the stage); instead
    # Portal 57 verifies Stage 1 outcome documents are signed before opening
    # Stage 2.
    if to_status == "stage1_in_progress":
        _assert_stage_entry_gate(db, audit_set_id, "stage_1")
    elif to_status == "stage2_in_progress":
        _assert_stage1_complete_gate(db, audit_set_id)

    audit_set.workflow_status = to_status

    # When a stage is marked complete, close out its AuditSetStage row.
    if to_status in ("stage1_complete", "stage2_complete"):
        stage_type = "stage_1" if to_status == "stage1_complete" else "stage_2"
        stage_row = (
            db.query(AuditSetStage)
            .filter_by(audit_set_id=audit_set_id, stage_type=stage_type)
            .first()
        )
        if stage_row:
            stage_row.status = "complete"

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
