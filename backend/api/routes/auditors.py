"""
BATUHAN — Auditor Profile: FastAPI router.
Registered in main.py at prefix="/auditors".

Routes:
  POST /auditors/ingest          — extract fields from PDF/DOCX (preview, no DB save)
  POST /auditors/                — create auditor from JSON body
  GET  /auditors/                — list auditors (?active_only=true)
  GET  /auditors/{auditor_id}    — get single auditor
  PUT  /auditors/{auditor_id}    — full replace update
"""
from __future__ import annotations
import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auditors.models import get_db
from auditors.schemas import (
    AuditorCreateSchema, AuditorResponseSchema, AuditorSummarySchema,
    EligibilityCheckSchema, EligibilityResultSchema,
)
from auditors.service import (
    create_auditor, get_auditor, list_auditors, update_auditor, delete_auditor,
    get_dashboard,
)
from auditors.schemas import AuditorDashboardEntry
from auditors.extractor import extract_auditor_from_document
from auditors.eligibility import check_eligibility
from auditors.clause_assignment import suggest_clause_assignment, ClauseAssignmentRequest
from auditors.audit_plan import generate_audit_plan, AuditPlanInput
from auth.db_models import PlatformUser
from auth.dependencies import require_admin, require_planner, require_auditor, require_any

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/ingest")
async def ingest_document(
    file: UploadFile = File(...),
    _: PlatformUser = Depends(require_planner),
):
    """
    Upload a PDF or DOCX auditor CV / FR.201 form.
    Returns the Claude-extracted profile as JSON — nothing is saved to the DB.
    Use POST / afterwards to persist the (possibly corrected) data.
    """
    file_bytes = await file.read()
    result = extract_auditor_from_document(file_bytes, file.filename or "upload")

    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])

    logger.info("[Auditors/API] Ingested document '%s'", file.filename)
    return result


@router.post("/", response_model=AuditorResponseSchema, status_code=201)
def create(
    payload: AuditorCreateSchema,
    db: Session = Depends(get_db),
    _: PlatformUser = Depends(require_admin),
):
    """Create a new auditor profile from a JSON body."""
    auditor = create_auditor(db, payload)
    return auditor


@router.get("/", response_model=list[AuditorSummarySchema])
def list_all(active_only: bool = True, db: Session = Depends(get_db), _: PlatformUser = Depends(require_any)):
    """List auditors. Pass ?active_only=false to include soft-deleted."""
    return list_auditors(db, active_only=active_only)


@router.get("/dashboard", response_model=list[AuditorDashboardEntry])
def dashboard(active_only: bool = True, db: Session = Depends(get_db), _: PlatformUser = Depends(require_any)):
    """
    Return a rich summary of every auditor in the pool.

    Each entry includes qualification warning flags (training expiry, TURKAK
    annual verification) and audit history stats (total audits, last audit date,
    days since last audit).

    Pass ?active_only=false to include soft-deleted auditors.
    Always returns HTTP 200; returns [] when no auditors exist.
    """
    return get_dashboard(db, active_only=active_only)


@router.post("/assign-clauses")
def assign_clauses(body: ClauseAssignmentRequest, db: Session = Depends(get_db), _: PlatformUser = Depends(require_planner)):
    """
    Suggest which auditor covers which clauses for a given standard.

    Auditors are ranked by role seniority, technical depth, and experience years.
    Higher-ranked auditors receive the operationally complex sections (8.x, 9.x, 10.x).

    Returns HTTP 200 always when valid. Never persists anything.
    HTTP 404 — one or more auditor_ids not found in the DB.
    HTTP 422 — no clause config exists for the given standard_code.
    """
    missing = [aid for aid in body.auditor_ids if not get_auditor(db, aid)]
    if missing:
        raise HTTPException(
            status_code=404,
            detail=f"Auditor(s) not found: {missing}",
        )

    try:
        return suggest_clause_assignment(db, body.auditor_ids, body.standard_code)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"No clause config found for standard '{body.standard_code}': {exc}",
        )


class AuditPlanRequest(BaseModel):
    company_name: str
    company_address: str
    standard_code: str
    accreditation_body: str
    stage: int
    audit_date: str
    lead_auditor_name: str
    assignments: list[dict]
    opening_time: str = "09:00"
    closing_time: str = "17:00"
    document_ref: str = "FR.223"


@router.post("/generate-audit-plan")
def generate_audit_plan_endpoint(body: AuditPlanRequest, _: PlatformUser = Depends(require_auditor)):
    """
    Generate a filled FR.223 Audit Plan DOCX from auditor clause assignments.

    Accepts the same assignments list produced by POST /auditors/assign-clauses.
    Returns a ready-to-download .docx file — nothing is saved to the DB.

    HTTP 422 — stage is not 1 or 2.
    """
    if body.stage not in (1, 2):
        raise HTTPException(status_code=422, detail="stage must be 1 or 2.")

    plan_bytes = generate_audit_plan(
        AuditPlanInput(
            company_name=body.company_name,
            company_address=body.company_address,
            standard_code=body.standard_code,
            accreditation_body=body.accreditation_body,
            stage=body.stage,
            audit_date=body.audit_date,
            lead_auditor_name=body.lead_auditor_name,
            assignments=body.assignments,
            opening_time=body.opening_time,
            closing_time=body.closing_time,
            document_ref=body.document_ref,
        )
    )

    return StreamingResponse(
        iter([plan_bytes]),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": 'attachment; filename="FR223_Audit_Plan.docx"'},
    )


@router.get("/{auditor_id}", response_model=AuditorResponseSchema)
def get_one(auditor_id: str, db: Session = Depends(get_db), _: PlatformUser = Depends(require_any)):
    """Return full auditor profile by ID."""
    auditor = get_auditor(db, auditor_id)
    if not auditor:
        raise HTTPException(status_code=404, detail=f"Auditor '{auditor_id}' not found.")
    return auditor


@router.put("/{auditor_id}", response_model=AuditorResponseSchema)
def update(auditor_id: str, payload: AuditorCreateSchema, db: Session = Depends(get_db), _: PlatformUser = Depends(require_admin)):
    """
    Full replace update. All child rows (EA codes, qualifications, training, etc.)
    are deleted and re-inserted from the request body.
    """
    auditor = update_auditor(db, auditor_id, payload)
    if not auditor:
        raise HTTPException(status_code=404, detail=f"Auditor '{auditor_id}' not found.")
    return auditor


@router.delete("/{auditor_id}", status_code=204)
def soft_delete(auditor_id: str, db: Session = Depends(get_db), _: PlatformUser = Depends(require_admin)):
    """Soft-delete an auditor (sets is_active=False)."""
    found = delete_auditor(db, auditor_id)
    if not found:
        raise HTTPException(status_code=404, detail=f"Auditor '{auditor_id}' not found.")


@router.post("/{auditor_id}/check-eligibility", response_model=EligibilityResultSchema)
def eligibility_check(
    auditor_id: str,
    body: EligibilityCheckSchema,
    db: Session = Depends(get_db),
    _: PlatformUser = Depends(require_planner),
):
    """
    Evaluate whether an auditor is eligible to conduct an audit.

    Returns HTTP 200 always — an ineligible result is NOT an HTTP error.
    HTTP 404 only when the auditor row itself does not exist.

    eligible=True  → no hard blocks found
    eligible=False → blocking_reasons contains IAF/accreditation body violations
    warnings       → items that must be manually verified before signing off
    """
    if not get_auditor(db, auditor_id):
        raise HTTPException(status_code=404, detail=f"Auditor '{auditor_id}' not found.")

    return check_eligibility(
        db=db,
        auditor_id=auditor_id,
        standard_code=body.standard_code,
        company_ea_code=body.company_ea_code,
        accreditation_body=body.accreditation_body,
        role=body.role,
    )
