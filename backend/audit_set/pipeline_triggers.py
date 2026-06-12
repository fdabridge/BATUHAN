"""
BATUHAN — Pipeline state-machine triggers (Portal 47).

Centralises the auto side-effects that fire when an AuditSet enters a new
workflow_status. Called from update_workflow_status (workflow_router) and
from document-event paths (viewer_router agreement-sign, signatures_router
sign-direct for FR.218 completion).

All helpers take an open Session and mutate the DB without committing —
callers commit. The single exception is fire_phase_triggers itself, which
commits at the end so the side effects are durable even if the caller
forgets.
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from audit_set.db_models import (
    AuditDocumentSignature,
    AuditSet,
    AuditSetAuditorAssessment,
    AuditSetImpartialityDeclaration,
    AuditSetStage,
    AuditSetStatusEvent,
)

# Standards that require an independent reviewer slot on FR.218.
FSMS_ISMS_STANDARDS = {"FSMS", "ISMS", "ISO 22000", "ISO 27001", "FSSC 22000"}


# ── FR.218 phase ──────────────────────────────────────────────────────────────

def seed_fr218_slots(audit_set: AuditSet, triggered_by: str, db: Session) -> int:
    """Create FR.218 signature slots (cb_planner, optional cb_reviewer, cb_cert_manager).
    Idempotent: returns 0 if any FR218 slot already exists for this set."""
    existing = (
        db.query(AuditDocumentSignature)
        .filter_by(audit_set_id=audit_set.id, document_type="FR218")
        .first()
    )
    if existing:
        return 0

    db.add(AuditDocumentSignature(
        audit_set_id=audit_set.id,
        document_id=None,
        document_type="FR218",
        signer_role_label="cb_planner",
        signer_user_id=None,
        signer_name=None,
        signer_email=None,
        required=True,
        order_index=0,
    ))
    standards = set(audit_set.standards or [])
    if standards & FSMS_ISMS_STANDARDS:
        db.add(AuditDocumentSignature(
            audit_set_id=audit_set.id,
            document_id=None,
            document_type="FR218",
            signer_role_label="cb_reviewer",
            signer_user_id=None,
            signer_name=None,
            signer_email=None,
            required=True,
            order_index=1,
        ))
    db.add(AuditDocumentSignature(
        audit_set_id=audit_set.id,
        document_id=None,
        document_type="FR218",
        signer_role_label="cb_cert_manager",
        signer_user_id=None,
        signer_name=None,
        signer_email=None,
        required=True,
        order_index=2,
    ))
    return 1


def _trigger_fr218_phase(
    audit_set: AuditSet, triggered_by: str, db: Session,
    effective_ts: Optional[datetime] = None,
) -> None:
    """Auto-advance agreement_signed → fr218_in_progress and seed FR.218 slots."""
    if audit_set.workflow_status != "agreement_signed":
        return

    from_status = audit_set.workflow_status
    audit_set.workflow_status = "fr218_in_progress"
    seed_fr218_slots(audit_set, triggered_by, db)
    db.add(AuditSetStatusEvent(
        audit_set_id=audit_set.id,
        from_status=from_status,
        to_status="fr218_in_progress",
        triggered_by=triggered_by,
        triggered_at=effective_ts or datetime.utcnow(),
        notes="Auto-advanced: agreement signed → FR.218 application review opened",
    ))


def _all_fr218_signed(audit_set_id: str, db: Session) -> bool:
    unsigned = (
        db.query(AuditDocumentSignature)
        .filter_by(audit_set_id=audit_set_id, document_type="FR218", required=True)
        .filter(AuditDocumentSignature.signed_at.is_(None))
        .count()
    )
    total = (
        db.query(AuditDocumentSignature)
        .filter_by(audit_set_id=audit_set_id, document_type="FR218", required=True)
        .count()
    )
    return total > 0 and unsigned == 0


def check_fr218_completion(
    audit_set_id: str, triggered_by: str, db: Session,
    effective_ts: Optional[datetime] = None,
) -> bool:
    """If all FR.218 slots are signed and we are in fr218_in_progress, advance to fr218_complete."""
    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set or audit_set.workflow_status != "fr218_in_progress":
        return False
    if not _all_fr218_signed(audit_set_id, db):
        return False

    audit_set.workflow_status = "fr218_complete"
    db.add(AuditSetStatusEvent(
        audit_set_id=audit_set_id,
        from_status="fr218_in_progress",
        to_status="fr218_complete",
        triggered_by=triggered_by,
        triggered_at=effective_ts or datetime.utcnow(),
        notes="Auto-advanced: FR.218 fully signed by all required parties",
    ))
    db.commit()
    return True


# ── Stage entry triggers ──────────────────────────────────────────────────────

def _stage_team_entries(stage: AuditSetStage) -> list[dict]:
    entries: list[dict] = []
    if stage.lead_auditor_name:
        entries.append({
            "name": stage.lead_auditor_name,
            "role": "Lead Auditor",
            "ref_id": stage.lead_auditor_id,
        })
    for a in (stage.auditors or []):
        if isinstance(a, dict) and a.get("name"):
            entries.append({"name": a["name"], "role": "Team Auditor", "ref_id": a.get("id")})
    for te in (stage.technical_experts or []):
        if isinstance(te, dict) and te.get("name"):
            entries.append({"name": te["name"], "role": "Technical Expert", "ref_id": te.get("id")})
    for obs in (stage.observers or []):
        if isinstance(obs, dict) and obs.get("name"):
            entries.append({"name": obs["name"], "role": "Observer", "ref_id": obs.get("id")})
    return entries


def _seed_stage_declarations_and_assessments(
    audit_set: AuditSet, stage_type: str, db: Session,
) -> tuple[int, int]:
    """Create per-team-member FR.224 declarations + FR.211 assessments. Idempotent."""
    stage = (
        db.query(AuditSetStage)
        .filter_by(audit_set_id=audit_set.id, stage_type=stage_type)
        .order_by(AuditSetStage.stage_order)
        .first()
    )
    if not stage:
        return (0, 0)
    entries = _stage_team_entries(stage)
    if not entries:
        return (0, 0)

    decl_existing = {
        (d.member_name, d.stage_type)
        for d in db.query(AuditSetImpartialityDeclaration)
                   .filter_by(audit_set_id=audit_set.id, stage_type=stage_type)
                   .all()
    }
    decl_created = 0
    for entry in entries:
        if (entry["name"], stage_type) in decl_existing:
            continue
        db.add(AuditSetImpartialityDeclaration(
            audit_set_id=audit_set.id,
            stage_type=stage_type,
            stage_order=stage.stage_order,
            member_name=entry["name"],
            member_role=entry["role"],
            auditor_ref_id=entry["ref_id"],
        ))
        decl_created += 1

    # FR.211 — only for auditors + TEs (observers are not assessed by the client)
    assessable = [e for e in entries if e["role"] != "Observer"]
    asmt_existing = {
        (a.auditor_name, a.stage_type)
        for a in db.query(AuditSetAuditorAssessment)
                   .filter_by(audit_set_id=audit_set.id, stage_type=stage_type)
                   .all()
    }
    asmt_created = 0
    for entry in assessable:
        if (entry["name"], stage_type) in asmt_existing:
            continue
        db.add(AuditSetAuditorAssessment(
            audit_set_id=audit_set.id,
            stage_type=stage_type,
            stage_order=stage.stage_order,
            auditor_name=entry["name"],
            auditor_role=entry["role"],
            auditor_ref_id=entry["ref_id"],
        ))
        asmt_created += 1

    return (decl_created, asmt_created)


def _trigger_stage_start(audit_set: AuditSet, stage_number: int, db: Session) -> None:
    stage_type = f"stage_{stage_number}"
    _seed_stage_declarations_and_assessments(audit_set, stage_type, db)


# ── Public orchestrator ───────────────────────────────────────────────────────

def fire_phase_triggers(
    audit_set_id: str, new_status: str, triggered_by: str, db: Session,
    effective_ts: Optional[datetime] = None,
) -> None:
    """Run automatic side effects when an audit set enters new_status."""
    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        return

    if new_status == "agreement_signed":
        _trigger_fr218_phase(audit_set, triggered_by, db, effective_ts)

    elif new_status == "stage1_scheduled":
        _trigger_stage_start(audit_set, stage_number=1, db=db)

    elif new_status == "stage2_scheduled":
        _trigger_stage_start(audit_set, stage_number=2, db=db)

    db.commit()
