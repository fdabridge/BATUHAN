"""
BATUHAN — Audit Set API Routes.
POST   /audit-sets/              → create a new audit set (201)
GET    /audit-sets/              → list all audit sets (?status=)
GET    /audit-sets/{id}          → get one audit set (404 if not found)
PUT    /audit-sets/{id}/planning → update EA, fees, stage assignments
GET    /audit-sets/{id}/download → ZIP of all filled DOCX templates
DELETE /audit-sets/{id}          → soft-delete: status = "archived" (204)
"""
from __future__ import annotations
import io
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from audit_set.db_models import AuditSet, get_db
from audit_set.packager import build_audit_set_zip
from audit_set.schemas import (
    AuditSetCreateSchema,
    AuditSetUpdatePlanningSchema,
    AuditSetResponse,
    AuditSetSummarySchema,
    NACGenerationResponse,
    QuickCalcSchema,
)
from audit_set.service import (
    create_audit_set,
    get_audit_set,
    list_audit_sets,
    update_planning,
    quick_calculate,
    derive_and_save_scope,
)
from auth.db_models import PlatformUser
from auth.dependencies import require_admin, require_planner, require_any


class FR218ReviewerUpdate(BaseModel):
    fr218_reviewer_id:   Optional[str] = None
    fr218_reviewer_name: Optional[str] = None

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/", response_model=AuditSetResponse, status_code=201)
def create(payload: AuditSetCreateSchema, db: Session = Depends(get_db), _: PlatformUser = Depends(require_planner)):
    """Create a new audit set, run man-day calculation, auto-generate stage rows."""
    audit_set = create_audit_set(db, payload)
    return audit_set


@router.get("/", response_model=list[AuditSetSummarySchema])
def list_all(status: str | None = None, db: Session = Depends(get_db), _: PlatformUser = Depends(require_any)):
    """
    List all audit sets, newest first.
    Pass ?status=draft|planning|complete|archived to filter.
    """
    return list_audit_sets(db, status=status)


@router.get("/{audit_set_id}", response_model=AuditSetResponse)
def get_one(audit_set_id: str, db: Session = Depends(get_db), _: PlatformUser = Depends(require_any)):
    """Return full audit set by ID, including all stage rows."""
    audit_set = get_audit_set(db, audit_set_id)
    if not audit_set:
        raise HTTPException(status_code=404, detail=f"Audit set '{audit_set_id}' not found.")
    return audit_set


@router.put("/{audit_set_id}/planning", response_model=AuditSetResponse)
def planning(
    audit_set_id: str,
    payload: AuditSetUpdatePlanningSchema,
    db: Session = Depends(get_db),
    _: PlatformUser = Depends(require_planner),
):
    """
    Update EA classification, fees, and stage auditor/date assignments.
    Creates missing stage rows; advances status from 'draft' to 'planning'.
    Portal 64: also accepts and validates committee_members (optional).
    """
    # Portal 64 — validate committee before touching the DB
    if payload.committee_members is not None and len(payload.committee_members) > 0:
        audit_set_row = db.query(AuditSet).filter_by(id=audit_set_id).first()
        if not audit_set_row:
            raise HTTPException(status_code=404, detail=f"Audit set '{audit_set_id}' not found.")

        from audit_set.committee_router import (
            _auditor_iso_quals,
            _collect_stage_auditor_ids,
        )
        from audit_set.db_models import AuditSetStage
        from auditors.models import Auditor as AuditorModel

        # Collect all stage-team auditor IDs from BOTH the payload and DB-saved stages
        all_team_ids: set[str] = set()
        for si in payload.stages:
            if si.lead_auditor_id:
                all_team_ids.add(si.lead_auditor_id)
            for group in (si.auditors, si.technical_experts, si.observers, si.ik_experts, si.evaluators):
                for a in group:
                    if a.id:
                        all_team_ids.add(a.id)
        db_stages = db.query(AuditSetStage).filter_by(audit_set_id=audit_set_id).all()
        all_team_ids |= _collect_stage_auditor_ids(db_stages)

        committee_ids = [m["id"] for m in payload.committee_members if m.get("id")]
        if not committee_ids:
            raise HTTPException(status_code=422, detail="Committee must have at least one member (Chairperson)")

        overlap = set(committee_ids) & all_team_ids
        if overlap:
            raise HTTPException(
                status_code=422,
                detail=f"Committee members cannot be on the audit team: {sorted(overlap)}",
            )

        # Look up live auditor data for coverage validation
        auditors = {
            a.id: a for a in
            db.query(AuditorModel)
            .filter(AuditorModel.id.in_(committee_ids))
            .filter(AuditorModel.is_active == True)  # noqa: E712
            .all()
        }
        missing_auditors = [aid for aid in committee_ids if aid not in auditors]
        if missing_auditors:
            raise HTTPException(status_code=400, detail=f"Auditor(s) not found or inactive: {missing_auditors}")

        # Build canonical snapshot: first member = chairperson
        snapshot = []
        for i, mid in enumerate(committee_ids):
            a = auditors[mid]
            snapshot.append({
                "id":       a.id,
                "name":     a.name,
                "email":    a.email,
                "ea_codes": list(a.ea_codes or []),
                "standards": sorted(_auditor_iso_quals(db, mid)),
                "role":     "chairperson" if i == 0 else "member",
            })
        payload.committee_members = snapshot

    audit_set = update_planning(db, audit_set_id, payload)
    if not audit_set:
        raise HTTPException(status_code=404, detail=f"Audit set '{audit_set_id}' not found.")
    return audit_set


@router.get("/{audit_set_id}/download")
def download_zip(audit_set_id: str, db: Session = Depends(get_db), _: PlatformUser = Depends(require_any)):
    """Return a ZIP of all filled IFC DOCX templates for this audit set."""
    audit_set = get_audit_set(db, audit_set_id)
    if not audit_set:
        raise HTTPException(status_code=404, detail=f"Audit set '{audit_set_id}' not found.")

    # Pre-flight: at least one stage must have a lead auditor assigned
    stages_with_lead = [s for s in (audit_set.stages or []) if s.lead_auditor_name]
    if not stages_with_lead:
        raise HTTPException(
            status_code=400,
            detail="Cannot generate audit package: no lead auditor has been assigned to any stage.",
        )

    try:
        zip_bytes = build_audit_set_zip(audit_set, db)
    except Exception as exc:
        logger.exception("[AuditSet] ZIP build failed id=%s", audit_set_id)
        raise HTTPException(status_code=500, detail=f"Failed to build audit set ZIP: {exc}")

    # Advance status to active now that the package has been generated
    if audit_set.status != "active":
        audit_set.status = "active"
        db.commit()

    filename = f"audit_set_{audit_set.plan_number}.zip"
    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{audit_set_id}/quick-calculate", response_model=AuditSetResponse)
def run_quick_calculate(
    audit_set_id: str,
    payload: QuickCalcSchema,
    db: Session = Depends(get_db),
    _: PlatformUser = Depends(require_planner),
):
    """
    (Re-)run the IAF MD 5 calculator for an existing audit set using submitted
    personnel / integration data. Updates man_day_result and stage audit_days.
    Useful for manually-created clients that skipped the form upload step.
    """
    audit_set = quick_calculate(db, audit_set_id, payload)
    if not audit_set:
        raise HTTPException(status_code=404, detail=f"Audit set '{audit_set_id}' not found.")
    return audit_set


@router.post("/{audit_set_id}/derive-scope", response_model=AuditSetResponse)
def run_derive_scope(
    audit_set_id: str,
    db: Session = Depends(get_db),
    _: PlatformUser = Depends(require_planner),
):
    """
    Derive per-standard required scope codes from the client's scope text using
    keyword matching (food chain categories, medical TAs, sector types, energy
    complexity, EA codes).  Saves the result to audit_set.required_scope and
    returns the updated audit set.
    """
    audit_set = derive_and_save_scope(db, audit_set_id)
    if not audit_set:
        raise HTTPException(status_code=404, detail=f"Audit set '{audit_set_id}' not found.")
    return audit_set


@router.post("/{audit_set_id}/generate-nac", response_model=NACGenerationResponse)
def run_generate_nac(
    audit_set_id: str,
    db: Session = Depends(get_db),
    _: PlatformUser = Depends(require_planner),
):
    """
    Ask Claude which clauses are likely non-applicable for this organisation's
    scope + standards.  Returns suggestions only — caller must explicitly save
    the chosen `non_applicable_clauses` via PUT /{id}/planning.
    """
    from audit_set.nac_generator import generate_nac_ai
    audit_set = get_audit_set(db, audit_set_id)
    if not audit_set:
        raise HTTPException(status_code=404, detail=f"Audit set '{audit_set_id}' not found.")
    result = generate_nac_ai(audit_set)
    return NACGenerationResponse(
        non_applicable_clauses=result["nac_text"],
        suggestions=result["suggestions"],
    )


@router.patch("/{audit_set_id}/fr218-reviewer", status_code=200)
def set_fr218_reviewer(
    audit_set_id: str,
    body: FR218ReviewerUpdate,
    db: Session = Depends(get_db),
    _: PlatformUser = Depends(require_planner),
):
    """Set (or clear) the appointed Application Reviewer for FR.218.
    Only applicable when the audit set has FSMS or ISMS standards.
    """
    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(status_code=404, detail="Audit set not found")
    audit_set.fr218_reviewer_id   = body.fr218_reviewer_id
    audit_set.fr218_reviewer_name = body.fr218_reviewer_name
    db.commit()
    return {
        "fr218_reviewer_id":   audit_set.fr218_reviewer_id,
        "fr218_reviewer_name": audit_set.fr218_reviewer_name,
    }


@router.delete("/{audit_set_id}", status_code=204)
def soft_delete(audit_set_id: str, db: Session = Depends(get_db), _: PlatformUser = Depends(require_admin)):
    """Soft-delete: set status to 'archived'. Returns 204 No Content."""
    audit_set = get_audit_set(db, audit_set_id)
    if not audit_set:
        raise HTTPException(status_code=404, detail=f"Audit set '{audit_set_id}' not found.")
    audit_set.status = "archived"
    db.commit()
    logger.info("[AuditSet] Archived id=%s", audit_set_id)
