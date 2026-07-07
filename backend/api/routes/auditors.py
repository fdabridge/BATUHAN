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
import secrets
import string
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
from auth.db_models import PlatformUser, get_db as get_auth_db
from auth.dependencies import require_admin, require_planner, require_auditor, require_any
from auth.service import create_user

logger = logging.getLogger(__name__)
router = APIRouter()

# Standard abbreviation → numeric fragment for cross-matching required_scope keys
# (full ISO names) against stored qualification standard_codes (CB abbreviations).
_STD_ABBR_NORM: dict[str, str] = {
    "isms":  "27001",
    "enms":  "50001",
    "abms":  "37001",
    "cms":   "37301",
    "mdqms": "13485",
    "mdms":  "13485",
}


def _std_norm(s: str) -> str:
    """Normalise a standard code for cross-matching.

    Strips 'ISO ', 'IEC ', slashes and spaces, then maps known CB abbreviations
    to their numeric fragment so that 'ISMS' == 'ISO 27001' == '27001'.
    """
    base = (s or '').lower().replace('iso ', '').replace('iec ', '').replace('/', '').replace(' ', '')
    return _STD_ABBR_NORM.get(base, base)


def _ea_int(code) -> int | None:
    """Normalise 'EA 28', 'EA28', '28', or bare integer 28 → 28.
    Handles integer inputs stored in JSON columns as well as string inputs.
    Returns None if the value cannot be parsed as an EA sector number.
    """
    try:
        if isinstance(code, (int, float)):
            return int(code)
        return int(str(code).strip().upper().replace("EA", "").replace(" ", ""))
    except (ValueError, AttributeError):
        return None


# ── Bulk import helpers ───────────────────────────────────────────────────────

class BulkAuditorEntry(BaseModel):
    """One auditor entry in the JSON bulk import payload."""
    name: str
    role: Optional[str] = None
    field_of_expertise: Optional[str] = None
    ea_codes: Optional[list[str]] = None
    accreditation_bodies: Optional[list[str]] = None
    standard_qualifications: list = []

    username: Optional[str] = None
    password: Optional[str] = None


class BulkAuditorImportPayload(BaseModel):
    auditors: list[BulkAuditorEntry]
    replace_all: bool = False


def _make_username(name: str) -> str:
    """'Ahmet Yakup Boran' -> 'ahmet.boran'"""
    import unicodedata, re  # noqa: F401
    replacements = {'ş': 's', 'ğ': 'g', 'ı': 'i', 'ö': 'o', 'ü': 'u', 'ç': 'c',
                    'Ş': 'S', 'Ğ': 'G', 'İ': 'I', 'Ö': 'O', 'Ü': 'U', 'Ç': 'C'}
    n = name.strip()
    for k, v in replacements.items():
        n = n.replace(k, v)
    n = unicodedata.normalize('NFKD', n).encode('ascii', 'ignore').decode()
    parts = [p.lower() for p in n.split() if p.strip()]
    if len(parts) == 0:
        return 'user'
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]}.{parts[-1]}"


def _gen_password(length: int = 10) -> str:
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


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


@router.post("/bulk-import-json")
def bulk_import_json(
    payload: BulkAuditorImportPayload,
    db: Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    _: PlatformUser = Depends(require_admin),
):
    """
    Import auditors from structured JSON.
    Each entry creates an Auditor profile (with per-standard EA codes) AND
    a PlatformUser account linked to it.

    Set replace_all=true to purge all existing auditor records and their
    linked platform user accounts before importing (clean slate).

    Returns the full credentials list so usernames/passwords can be saved.
    """
    from auditors.schemas import StandardQualificationItem
    from auditors.models import Auditor as AuditorModel
    from auth.db_models import PlatformUser as PU

    # ── Optional purge ──────────────────────────────────────────────────────
    if payload.replace_all:
        from auditors.models import (
            AuditorStandardQualification, AuditorEducation, AuditorLanguage,
            AuditorWorkExperience, AuditorTrainingRecord, AuditorAuditLog,
            AuditorWitnessRecord,
        )
        existing_auditors = db.query(AuditorModel).all()
        auditor_ids = [a.id for a in existing_auditors]

        if auditor_ids:
            # Delete linked PlatformUser accounts first
            auth_db.query(PU).filter(
                PU.auditor_id.in_(auditor_ids)
            ).delete(synchronize_session=False)
            auth_db.commit()

            # Delete all child tables before auditors (bypass ORM cascade for bulk delete)
            for child_model in (
                AuditorStandardQualification, AuditorEducation, AuditorLanguage,
                AuditorWorkExperience, AuditorTrainingRecord, AuditorAuditLog,
                AuditorWitnessRecord,
            ):
                db.query(child_model).filter(
                    child_model.auditor_id.in_(auditor_ids)
                ).delete(synchronize_session=False)
            db.commit()

        # Now delete the auditors themselves
        db.query(AuditorModel).delete(synchronize_session=False)
        db.commit()
        logger.info("[BulkImport] Purged all existing auditors and child records")

    # ── Track used usernames for deduplication ──────────────────────────────
    existing_usernames: set[str] = {
        u.username for u in auth_db.query(PU).all() if u.username
    }

    created: list[dict] = []
    skipped: list[dict] = []
    errors:  list[dict] = []

    for i, entry in enumerate(payload.auditors):
        base_uname = entry.username or _make_username(entry.name)
        uname = base_uname
        suffix = 2
        while uname in existing_usernames:
            uname = f"{base_uname}{suffix}"
            suffix += 1
        existing_usernames.add(uname)

        pw = entry.password or _gen_password()

        sq_items = []
        for sq in entry.standard_qualifications:
            if isinstance(sq, dict):
                sq_items.append(StandardQualificationItem(**sq))
            else:
                sq_items.append(sq)

        create_schema = AuditorCreateSchema(
            name=entry.name,
            role=entry.role,
            field_of_expertise=entry.field_of_expertise,
            ea_codes=entry.ea_codes,
            accreditation_bodies=entry.accreditation_bodies,
            standard_qualifications=sq_items,
        )

        try:
            auditor = create_auditor(db, create_schema)

            email = f"{uname}@certiva.internal"
            user = create_user(
                db=auth_db,
                email=email,
                password=pw,
                full_name=entry.name,
                role="auditor",
                auditor_id=auditor.id,
                username=uname,
            )

            created.append({
                "index":      i,
                "name":       entry.name,
                "username":   uname,
                "password":   pw,
                "email":      email,
                "auditor_id": auditor.id,
                "user_id":    user.id,
            })
            logger.info("[BulkImport] Created auditor %s (username=%s)", entry.name, uname)

        except Exception as exc:
            logger.exception("[BulkImport] Failed for %s: %s", entry.name, exc)
            errors.append({"index": i, "name": entry.name, "reason": str(exc)})

    return {
        "summary": {
            "total":   len(payload.auditors),
            "created": len(created),
            "skipped": len(skipped),
            "errors":  len(errors),
        },
        "credentials": created,
        "errors": errors,
    }


@router.delete("/purge-all")
def purge_all_auditors(
    db: Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    _: PlatformUser = Depends(require_admin),
):
    """
    Delete ALL auditor records and their linked portal accounts.
    Admin-only. Use before a clean re-import.
    """
    from auditors.models import (
        Auditor as AuditorModel,
        AuditorStandardQualification, AuditorEducation, AuditorLanguage,
        AuditorWorkExperience, AuditorTrainingRecord, AuditorAuditLog,
        AuditorWitnessRecord,
    )
    from auth.db_models import PlatformUser as PU

    existing = db.query(AuditorModel).all()
    auditor_ids = [a.id for a in existing]

    deleted_users = 0
    if auditor_ids:
        deleted_users = auth_db.query(PU).filter(
            PU.auditor_id.in_(auditor_ids)
        ).delete(synchronize_session=False)
        auth_db.commit()

        for child_model in (
            AuditorStandardQualification, AuditorEducation, AuditorLanguage,
            AuditorWorkExperience, AuditorTrainingRecord, AuditorAuditLog,
            AuditorWitnessRecord,
        ):
            db.query(child_model).filter(
                child_model.auditor_id.in_(auditor_ids)
            ).delete(synchronize_session=False)
        db.commit()

    deleted_auditors = db.query(AuditorModel).delete(synchronize_session=False)
    db.commit()
    return {
        "deleted_auditors": deleted_auditors,
        "deleted_users": deleted_users,
    }


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
    required_scope: Optional[str] = None,         # JSON-encoded required_scope dict (preferred)
    required_categories: Optional[str] = None,    # legacy alias — same semantics
    db: Session = Depends(get_db),
    _: PlatformUser = Depends(require_any),
):
    """
    Return auditors who are qualified for the given standard/EA code AND have no
    overlapping bookings in the audit_sets DB for the requested date range.

    Query params:
      date_start           — ISO date string YYYY-MM-DD (inclusive)
      date_end             — ISO date string YYYY-MM-DD (inclusive)
      standard_code        — optional; e.g. "ISO 9001" (partial case-insensitive match)
      ea_code              — optional; e.g. "EA 3" (numeric part compared)
      required_scope       — optional; JSON-encoded required_scope dict, e.g.
                             '{"ISO 22000": {"type": "food", "codes": ["CI", "CIV"]}}'
                             When provided, each result includes covered_scope showing
                             which codes from the required set this auditor can cover.
      required_categories  — legacy alias for required_scope (kept for compatibility).

    Returns list sorted: available auditors first, then unavailable.
    """
    import json as _json
    from auditors.models import Auditor
    from audit_set.db_models import get_db as get_sets_db, AuditSetStage, AuditSet

    # Parse required_scope (preferred name) with legacy fallback to required_categories
    raw_scope = required_scope or required_categories
    req_cat: dict = {}
    if raw_scope:
        try:
            req_cat = _json.loads(raw_scope)
        except Exception:
            req_cat = {}

    # 1. Fetch all active auditors
    all_auditors = db.query(Auditor).filter(Auditor.is_active == True).all()

    # 2 & 3. Qualification filter.
    # When required_scope is provided (integrated audit with multiple standards / codes),
    # use it as the single comprehensive filter: include any auditor who covers AT LEAST
    # ONE required (standard, code/category) pair — so the full team can collectively
    # cover everything.  The single ea_code / standard_code params are legacy fallbacks
    # used when required_scope is absent.
    if req_cat:
        _q_std_norm = _std_norm   # use module-level normaliser (maps ISMS→27001 etc.)

        def _auditor_covers_any_required(auditor, req: dict) -> bool:
            for iso_std, entry in req.items():
                scope_type    = entry.get('type', 'ea')
                required_codes: list[str] = entry.get('codes', [])
                std_norm = _q_std_norm(iso_std)
                qual = next(
                    (q for q in auditor.standard_qualifications
                     if q.is_qualified is not False
                     and std_norm in _q_std_norm(q.standard_code or '')),
                    None,
                )
                if not qual:
                    continue
                if not required_codes:
                    # Standard with no code system (ISO 37001 etc.) — qualification alone is enough
                    return True
                if scope_type in ('food', 'medical', 'sector', 'energy'):
                    raw = qual.scope_category or ''
                    auditor_codes = [c.strip() for c in raw.split(',') if c.strip()]
                else:  # ea
                    auditor_codes = qual.ea_codes or []
                # If no EA codes are recorded for this auditor, treat as qualifying for
                # any code. (Common for auditors imported without per-standard EA breakdown.)
                if not auditor_codes:
                    return True
                # EA codes — numeric normalisation so "EA 12", "12", and int 12 all match.
                req_ints = {_ea_int(c) for c in required_codes} - {None}
                if req_ints and any(_ea_int(c) in req_ints for c in auditor_codes):
                    return True
                elif not req_ints and any(c in auditor_codes for c in required_codes):
                    # Non-numeric required codes — fall back to plain string match
                    return True
            return False

        all_auditors = [a for a in all_auditors if _auditor_covers_any_required(a, req_cat)]
    else:
        # Legacy fallback: single standard_code + ea_code filter
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

        # 3. Filter by ea_code — read from AuditorStandardQualification.ea_codes (per-standard),
        #    NOT from Auditor.ea_codes (top-level field is null for bulk-imported auditors).
        if ea_code:
            target_ea = _ea_int(ea_code)
            if target_ea is not None:
                sc_lower = (standard_code or '').lower()
                filtered_by_ea = []
                for a in all_auditors:
                    sq_codes: list[str] = []
                    for q in a.standard_qualifications:
                        if q.is_qualified is not False:
                            if not sc_lower or sc_lower in (q.standard_code or '').lower():
                                sq_codes.extend(q.ea_codes or [])
                    codes_to_check = sq_codes if sq_codes else (a.ea_codes or [])
                    if any(_ea_int(c) == target_ea for c in codes_to_check):
                        filtered_by_ea.append(a)
                all_auditors = filtered_by_ea

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

        def _compute_covered_scope(auditor_qualifications: list, req: dict) -> dict:
            """
            For each required standard/codes, determine which codes this auditor covers.
            Returns {iso_standard: [covered_codes]}.
            'UNSCOPED' is a sentinel meaning "qualified for this standard, no sub-code restriction".
            """
            covered: dict = {}
            for iso_std, entry in req.items():
                scope_type = entry.get("type", "ea")
                required_codes: list[str] = entry.get("codes", [])

                # Qualification lookup comes first — before the codes check.
                std_lower = _std_norm(iso_std)
                qual = next(
                    (q for q in auditor_qualifications
                     if q.is_qualified is not False and std_lower in
                     _std_norm(q.standard_code or "")),
                    None,
                )
                if not qual:
                    continue

                # No specific sub-codes required (e.g. Turkish scope text, no keyword match).
                # Auditor is qualified → mark as unscoped so the committee picker can see them.
                if not required_codes:
                    covered[iso_std] = ["UNSCOPED"]
                    continue

                auditor_codes: list[str] = []
                if scope_type in ("food", "medical", "sector", "energy"):
                    # scope_category is a comma-separated string like "A1.1, A1.3"
                    raw = qual.scope_category or ""
                    auditor_codes = [c.strip() for c in raw.split(",") if c.strip()]
                elif scope_type == "ea":
                    auditor_codes = qual.ea_codes or []

                # If auditor has no recorded codes (any scope type), credit all required codes.
                if not auditor_codes:
                    covered[iso_std] = required_codes
                    continue

                # Intersection — numeric normalisation for EA codes so "EA 12", "12",
                # and bare integer 12 all compare as the same sector number.
                aud_ints = {_ea_int(c) for c in auditor_codes} - {None}
                if aud_ints:
                    matched = [c for c in required_codes if _ea_int(c) in aud_ints]
                else:
                    # No parseable integers — fall back to plain string match
                    matched = [c for c in required_codes if c in auditor_codes]
                if matched:
                    covered[iso_std] = matched

            return covered

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

            covered_scope = _compute_covered_scope(auditor.standard_qualifications, req_cat)

            result.append(AuditorAvailabilityItem(
                id=auditor.id,
                name=auditor.name,
                role=auditor.role,
                ea_codes=auditor.ea_codes or [],
                standard_qualifications=[
                    {
                        "standard_code": q.standard_code,
                        "technical_depth": q.technical_depth,
                        "ea_codes": q.ea_codes or [],
                        "scope_category": q.scope_category,
                    }
                    for q in auditor.standard_qualifications
                    if q.is_qualified is not False
                ],
                available=conflict_detail is None,
                conflict_detail=conflict_detail,
                covered_scope=covered_scope,
            ))
    finally:
        sets_db.close()

    # Sort: available first, then by name
    # (When req_cat was provided, the pre-filter above already ensures every returned
    # auditor covers at least one required code, so no second-pass filtering is needed.)
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
