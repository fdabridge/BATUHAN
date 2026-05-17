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
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auditors.models import get_db

from auditors.schemas import (
    AuditorCreateSchema, AuditorResponseSchema, AuditorSummarySchema,
    EligibilityCheckSchema, EligibilityResultSchema,
    WitnessRecordCreateSchema, WitnessStatusSchema, WitnessRecordItem,
    AuditorAvailabilityItem,
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


@router.get("/witness-summary", response_model=list[WitnessStatusSchema])
def witness_summary(
    db: Session = Depends(get_db),
    _: PlatformUser = Depends(require_any),
):
    """Return witness compliance status for every active auditor."""
    from auditors.models import Auditor, AuditorWitnessRecord
    from datetime import date

    auditors = db.query(Auditor).filter(Auditor.is_active == True).all()
    result = []
    for auditor in auditors:
        records = db.query(AuditorWitnessRecord).filter(
            AuditorWitnessRecord.auditor_id == auditor.id
        ).order_by(AuditorWitnessRecord.witness_date.desc()).all()

        last_witness_date = records[0].witness_date if records else None
        days_since = None
        witness_overdue = True

        if last_witness_date:
            last_dt = date.fromisoformat(last_witness_date)
            days_since = (date.today() - last_dt).days
            witness_overdue = days_since > (3 * 365)

        created = auditor.created_at.date() if auditor.created_at else date.today()
        new_auditor_unwitnessed = (len(records) == 0) and ((date.today() - created).days > 365)

        result.append(WitnessStatusSchema(
            auditor_id=auditor.id,
            auditor_name=auditor.name,
            last_witness_date=last_witness_date,
            days_since_last_witness=days_since,
            witness_overdue=witness_overdue,
            new_auditor_unwitnessed=new_auditor_unwitnessed,
            total_witness_count=len(records),
            records=[],  # omit full records in summary view
        ))
    return result


@router.get("/available", response_model=list[AuditorAvailabilityItem])
def get_available_auditors(
    date_start: str,
    date_end: str,
    standard_code: Optional[str] = None,
    ea_code: Optional[str] = None,
    db: Session = Depends(get_db),
    _: PlatformUser = Depends(require_any),
):
    """
    Return auditors who are qualified for the given standard/EA code AND have no
    overlapping bookings in the audit_sets DB for the requested date range.

    Query params:
      date_start    — ISO date string YYYY-MM-DD (inclusive)
      date_end      — ISO date string YYYY-MM-DD (inclusive)
      standard_code — optional; e.g. "ISO 9001" (partial case-insensitive match)
      ea_code       — optional; e.g. "EA 3" (numeric part compared)

    Returns list sorted: available auditors first, then unavailable.
    """
    from auditors.models import Auditor
    from audit_set.db_models import get_db as get_sets_db, AuditSetStage, AuditSet

    # 1. Fetch all active auditors
    all_auditors = db.query(Auditor).filter(Auditor.is_active == True).all()

    # 2. Filter by standard_code (partial, case-insensitive)
    if standard_code:
        sc_lower = standard_code.lower()
        all_auditors = [
            a for a in all_auditors
            if any(
                q.is_qualified is not False and sc_lower in (q.standard_code or '').lower()
                for q in a.standard_qualifications
            )
        ]

    # 3. Filter by ea_code (normalize to integer)
    if ea_code:
        def _ea_int(code: str) -> Optional[int]:
            try:
                return int(code.strip().upper().replace('EA', '').replace(' ', ''))
            except (ValueError, AttributeError):
                return None
        target_ea = _ea_int(ea_code)
        if target_ea is not None:
            all_auditors = [
                a for a in all_auditors
                if any(_ea_int(c) == target_ea for c in (a.ea_codes or []))
            ]

    # 4. Check bookings in audit_sets DB
    sets_db_gen = get_sets_db()
    sets_db = next(sets_db_gen)
    result: list[AuditorAvailabilityItem] = []
    try:
        # Find all stages that overlap the requested date range and are not cancelled
        overlapping_stages = (
            sets_db.query(AuditSetStage, AuditSet.company_name)
            .join(AuditSet, AuditSetStage.audit_set_id == AuditSet.id)
            .filter(
                AuditSetStage.audit_date_start != None,
                AuditSetStage.audit_date_end != None,
                AuditSetStage.audit_date_start <= date_end,
                AuditSetStage.audit_date_end >= date_start,
                AuditSetStage.status != "cancelled",
            )
            .all()
        )

        for auditor in all_auditors:
            conflict_detail: Optional[str] = None
            for stage, company_name in overlapping_stages:
                # Check if this auditor is the lead or in the auditors JSON list
                is_lead = stage.lead_auditor_id == auditor.id
                stage_auditors = stage.auditors or []
                is_team = any(str(a.get("id", "")) == auditor.id for a in stage_auditors)
                if is_lead or is_team:
                    start_str = str(stage.audit_date_start)
                    end_str   = str(stage.audit_date_end)
                    client    = company_name or "a client"
                    conflict_detail = f"Booked {start_str} to {end_str} ({client})"
                    break

            result.append(AuditorAvailabilityItem(
                id=auditor.id,
                name=auditor.name,
                role=auditor.role,
                ea_codes=auditor.ea_codes or [],
                standard_qualifications=[
                    {"standard_code": q.standard_code, "technical_depth": q.technical_depth}
                    for q in auditor.standard_qualifications
                    if q.is_qualified is not False
                ],
                available=conflict_detail is None,
                conflict_detail=conflict_detail,
            ))
    finally:
        sets_db.close()

    # Sort: available first, then by name
    result.sort(key=lambda a: (0 if a.available else 1, a.name))
    return result


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


@router.get("/{auditor_id}/witness", response_model=WitnessStatusSchema)
def get_witness_status(
    auditor_id: str,
    db: Session = Depends(get_db),
    _: PlatformUser = Depends(require_any),
):
    """Return all witness records + computed compliance status for one auditor."""
    from auditors.models import Auditor, AuditorWitnessRecord
    from datetime import date

    auditor = db.query(Auditor).filter(Auditor.id == auditor_id).first()
    if not auditor:
        raise HTTPException(status_code=404, detail="Auditor not found")

    records = db.query(AuditorWitnessRecord).filter(
        AuditorWitnessRecord.auditor_id == auditor_id
    ).order_by(AuditorWitnessRecord.witness_date.desc()).all()

    last_witness_date = records[0].witness_date if records else None
    days_since = None
    witness_overdue = True

    if last_witness_date:
        last_dt = date.fromisoformat(last_witness_date)
        days_since = (date.today() - last_dt).days
        witness_overdue = days_since > (3 * 365)

    created = auditor.created_at.date() if auditor.created_at else date.today()
    new_auditor_unwitnessed = (len(records) == 0) and ((date.today() - created).days > 365)

    return WitnessStatusSchema(
        auditor_id=auditor_id,
        auditor_name=auditor.name,
        last_witness_date=last_witness_date,
        days_since_last_witness=days_since,
        witness_overdue=witness_overdue,
        new_auditor_unwitnessed=new_auditor_unwitnessed,
        total_witness_count=len(records),
        records=[WitnessRecordItem(
            id=r.id,
            witness_date=r.witness_date,
            client_name=r.client_name,
            standard_code=r.standard_code,
            ea_code=r.ea_code,
            role_witnessed=r.role_witnessed,
            observer_name=r.observer_name,
            outcome=r.outcome,
            notes=r.notes,
        ) for r in records],
    )


@router.post("/{auditor_id}/witness", status_code=201)
def add_witness_record(
    auditor_id: str,
    payload: WitnessRecordCreateSchema,
    db: Session = Depends(get_db),
    _: PlatformUser = Depends(require_admin),
):
    """Log a new witness audit record for an auditor."""
    from auditors.models import Auditor, AuditorWitnessRecord

    auditor = db.query(Auditor).filter(Auditor.id == auditor_id).first()
    if not auditor:
        raise HTTPException(status_code=404, detail="Auditor not found")

    record = AuditorWitnessRecord(
        auditor_id=auditor_id,
        **payload.model_dump(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return {"id": record.id, "status": "created"}


@router.delete("/{auditor_id}/witness/{record_id}", status_code=204)
def delete_witness_record(
    auditor_id: str,
    record_id: int,
    db: Session = Depends(get_db),
    _: PlatformUser = Depends(require_admin),
):
    """Remove a witness record."""
    from auditors.models import AuditorWitnessRecord

    rec = db.query(AuditorWitnessRecord).filter(
        AuditorWitnessRecord.id == record_id,
        AuditorWitnessRecord.auditor_id == auditor_id,
    ).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Record not found")
    db.delete(rec)
    db.commit()
