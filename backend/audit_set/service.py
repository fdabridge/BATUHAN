"""
BATUHAN — Audit Set: Service layer (CRUD + calculation bridge).
"""
from __future__ import annotations
import json
import uuid
import logging
from datetime import date
from pathlib import Path

from sqlalchemy import cast, func, String
from sqlalchemy.orm import Session, selectinload

from audit_set.db_models import AuditSet, AuditSetStage
from audit_set.schemas import (
    AuditSetCertUpdateSchema,
    AuditSetCreateSchema,
    AuditSetUpdatePlanningSchema,
    QuickCalcSchema,
)

logger = logging.getLogger(__name__)

# Standard code → full ISO name understood by calculator/engine.py
_CODE_TO_ISO: dict[str, str] = {
    "QMS":        "ISO 9001",
    "EMS":        "ISO 14001",
    "OHSMS":      "ISO 45001",
    "FSMS":       "ISO 22000",
    "FSSC 22000": "FSSC 22000",
    "MDQMS":      "ISO 13485",
    "MDMS":       "ISO 13485",
    "ISMS":       "ISO 27001",
    "ENMS":       "ISO 50001",
    "EnMS":       "ISO 50001",
    "ABMS":       "ISO 37001",
    "CMS":        "ISO 37301",
}

# ── Scope-derivation keyword maps ──────────────────────────────────────────
_FOOD_CHAIN_KW: dict[str, tuple[str, ...]] = {
    "CI":   ("meat", "poultry", "fish", "seafood", "dairy", "milk", "yogurt", "cheese", "ice cream", "egg"),
    "CII":  ("fresh juice", "cut vegetable", "fresh produce", "perishable plant", "fresh fruit"),
    "CIII": ("ready meal", "sandwich", "mixed perishable", "prepared food", "ready-to-eat"),
    "CIV":  ("confection", "chocolate", "candy", "biscuit", "cookie", "snack", "chip", "cracker",
             "canned", "ambient", "dried", "cereal", "flour", "rice", "pasta", "edible oil",
             "sauce", "condiment", "frozen", "beverage", "juice in carton", "soft drink", "bottled water",
             "coffee", "tea", "cake", "tortilla", "bread", "bakery", "pastry", "wrap", "gluten",
             "noodle", "wafer"),
    "D":    ("animal feed", "pet food", "feedstuff"),
    "E":    ("catering", "restaurant", "canteen", "food service", "hospitality kitchen"),
    "FI":   ("food retail", "food wholesale", "supermarket", "grocer"),
    "FII":  ("food broker", "food distribution", "food trader"),
    "G":    ("food storage", "cold chain", "food logistics", "food warehousing"),
    "I":    ("food packaging", "packaging material", "food contact material"),
    "K":    ("food chemical", "food additive", "ingredient manufacture", "food enzyme", "vitamin"),
    "BIII": ("plant pre-process", "cleaning of plant", "sorting plant", "packing whole plant"),
    "C0":   ("slaughter", "slaughterhouse", "abattoir", "animal primary"),
}

_MEDICAL_TA_KW: dict[str, tuple[str, ...]] = {
    "A1.1": ("bandage", "wound care", "catheter", "surgical instrument", "syringe"),
    "A1.2": ("hip replacement", "dental implant", "non-active implant", "orthopaedic"),
    "A1.3": ("imaging equipment", "monitoring equipment", "ventilator"),
    "A1.4": ("pacemaker", "active implant", "defibrillator"),
    "A1.5": ("sterilization", "sterilisation", "ethylene oxide", "gamma steriliz"),
    "A1.6": ("software as medical device", "samd", "medical software", "ai medical"),
    "A1.7": ("medical device component", "medical parts supplier"),
    "A2.1": ("in-vitro diagnostic", "ivd reagent"),
    "A2.2": ("ivd self-test", "self-testing diagnostic"),
    "A2.3": ("ivd professional", "professional diagnostic"),
    "A2.4": ("companion diagnostic",),
}

_SECTOR_KW: dict[str, tuple[str, ...]] = {
    "Public":           ("government", "ministry", "municipality", "public authority", "state-owned", "public sector"),
    "Third sector/NGO": ("ngo", "non-profit", "nonprofit", "charity", "foundation", "association", "third sector"),
}

_ENERGY_HIGH_KW = ("chemical", "steel", "cement", "refinery", "petrochemical", "mining", "smelting")
_ENERGY_MED_KW  = ("manufacturing", "production", "industrial", "plant", "factory", "assembly")

# Scope text → EA code keyword map (IAF EA 1–39)
_SCOPE_TO_EA_KW: dict[str, tuple[str, ...]] = {
    "EA 1":  ("agriculture", "farming", "horticulture", "fishery", "aquaculture", "forestry", "livestock"),
    "EA 3":  ("food", "beverage", "tobacco", "bakery", "confectionery", "dairy", "meat processing",
              "cake", "tortilla", "snack", "sandwich", "pastry", "bread", "milling", "brewing",
              "gluten", "biscuit", "cookie", "cracker", "noodle", "pasta production"),
    "EA 4":  ("textile", "clothing", "apparel", "garment", "leather", "footwear", "fabric"),
    "EA 5":  ("wood", "furniture", "paper", "pulp", "printing", "packaging material"),
    "EA 6":  ("chemical", "petrochemical", "pharmaceutical", "cosmetic", "paint", "coating", "adhesive"),
    "EA 7":  ("metal", "steel", "aluminium", "foundry", "forging", "casting", "metallurgy", "welding"),
    "EA 8":  ("machinery", "equipment manufacturing", "pump", "compressor", "valve", "industrial equipment"),
    "EA 9":  ("electrical", "electronics", "semiconductor", "circuit board", "pcb", "electronic component"),
    "EA 10": ("shipbuilding", "marine", "aerospace", "aircraft", "defence", "military equipment"),
    "EA 11": ("automotive", "vehicle", "car", "truck", "bus", "motorcycle", "spare part", "auto component"),
    "EA 13": ("rubber", "plastic", "polymer", "composite"),
    "EA 14": ("glass", "ceramic", "stone", "mineral", "tile", "brick"),
    "EA 15": ("concrete", "cement", "construction material", "aggregate"),
    "EA 16": ("construction", "building", "civil engineering", "infrastructure", "contractor", "installation"),
    "EA 17": ("wholesale", "retail", "trade", "distribution", "import", "export", "commerce"),
    "EA 18": ("hotel", "restaurant", "catering", "hospitality", "tourism", "accommodation"),
    "EA 19": ("transport", "logistics", "freight", "courier", "shipping", "warehousing", "supply chain"),
    "EA 20": ("mining", "quarrying", "extraction", "oil", "gas", "refinery", "petroleum"),
    "EA 21": ("water treatment", "waste management", "recycling", "environmental services", "sewage"),
    "EA 22": ("electricity generation", "power plant", "gas supply", "energy utility", "grid"),
    "EA 23": ("education", "training", "school", "university", "academy", "e-learning"),
    "EA 24": ("healthcare", "hospital", "clinic", "medical services", "diagnostic laboratory"),
    "EA 26": ("financial", "banking", "insurance", "investment", "fintech", "audit firm"),
    "EA 27": ("information technology", "it services", "data centre", "cloud", "managed services"),
    "EA 28": ("telecom", "telecommunication", "internet service provider", "isp"),
    "EA 29": ("engineering services", "technical consulting", "testing laboratory", "inspection"),
    "EA 33": ("software development", "software house", "it consulting", "technology consulting", "saas"),
    "EA 34": ("management consulting", "business services", "legal services", "advisory"),
    "EA 35": ("public administration", "government services", "municipality"),
    "EA 37": ("media", "publishing", "broadcasting", "advertising"),
    "EA 39": ("beauty", "cleaning services", "laundry", "personal services"),
}

# Risk level keywords for ISO 9001 / 45001 (affects table lookup in the engine)
_RISK_HIGH_KW: tuple[str, ...] = (
    "food", "pharmaceutical", "medical", "aerospace", "nuclear", "defence",
    "chemical", "petrochemical", "construction", "mining", "oil", "gas",
    "cake", "tortilla", "snack", "sandwich", "dairy", "meat", "bakery",
    "implant", "surgical", "explosive",
)
_RISK_LOW_KW: tuple[str, ...] = (
    "software development", "it consulting", "consultancy", "training",
    "education", "media", "publishing", "financial services", "insurance",
)


def derive_required_scope(
    standards: list[str],
    scope_tr: str | None,
    scope_en: str | None,
    ea_code: str | None,
) -> dict:
    """
    Derive per-standard required scope codes from the client's scope text.

    Returns a dict keyed by the ISO standard name:
      {"ISO 22000": {"type": "food", "codes": ["CI", "CIV"]}, ...}
    """
    haystack = f"{scope_tr or ''} {scope_en or ''}".lower()
    result: dict = {}

    for abbr in (standards or []):
        iso = _CODE_TO_ISO.get(abbr, abbr)
        norm = iso.lower().replace("iso ", "").replace(" ", "")

        if "22000" in norm or "fssc" in norm:
            codes = [c for c, kws in _FOOD_CHAIN_KW.items() if any(kw in haystack for kw in kws)]
            result[iso] = {"type": "food", "codes": codes}

        elif "13485" in norm:
            codes = [c for c, kws in _MEDICAL_TA_KW.items() if any(kw in haystack for kw in kws)]
            result[iso] = {"type": "medical", "codes": codes}

        elif "37001" in norm or "37301" in norm:
            sector = "Private"
            for s, kws in _SECTOR_KW.items():
                if any(kw in haystack for kw in kws):
                    sector = s
                    break
            result[iso] = {"type": "sector", "codes": [sector]}

        elif "50001" in norm:
            if any(kw in haystack for kw in _ENERGY_HIGH_KW):
                complexity = "High"
            elif any(kw in haystack for kw in _ENERGY_MED_KW):
                complexity = "Medium"
            else:
                complexity = "Low"
            result[iso] = {"type": "energy", "codes": [complexity]}

        elif any(n in norm for n in ("9001", "14001", "45001", "27001")):
            # Use stored ea_code if available, otherwise infer from scope text
            if ea_code:
                codes = [ea_code]
            else:
                codes = [
                    ea for ea, kws in _SCOPE_TO_EA_KW.items()
                    if any(kw in haystack for kw in kws)
                ]
            # Derive risk level for ISO 9001 and 45001
            if any(kw in haystack for kw in _RISK_HIGH_KW):
                risk = "High"
            elif any(kw in haystack for kw in _RISK_LOW_KW):
                risk = "Low"
            else:
                risk = "Medium"
            result[iso] = {"type": "ea", "codes": codes, "risk": risk}

    logger.info("[AuditSet] derive_required_scope → %s", result)
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _next_plan_number(db: Session) -> int:
    """Return COALESCE(MAX(plan_number), 1599) + 1 — first call yields 1600."""
    result = db.query(func.coalesce(func.max(AuditSet.plan_number), 1599)).scalar()
    return int(result) + 1


def _run_calculation(audit_set: AuditSet) -> dict | None:
    """
    Bridge: map AuditSet fields → ExtractedFormData → calculate() → dict.
    Returns the full CalculationResult as a plain dict, or None on failure.
    """
    try:
        from calculator.engine import calculate
        from calculator.models import ExtractedFormData, SiteInfo, StandardClassification

        standards = [_CODE_TO_ISO.get(s, s) for s in (audit_set.standards or [])]
        if not standards:
            return None

        # ── Personnel ─────────────────────────────────────────────────────
        p = audit_set.personnel or {}
        full_time     = p.get("full_time", 0)
        part_time     = p.get("part_time", 0)
        subcontractors= p.get("subcontractors", 0)
        seasonal      = p.get("seasonal", 0)
        unskilled     = p.get("unskilled", 0)

        total_employees     = full_time + part_time + subcontractors + seasonal + unskilled
        repetitive_roles    = p.get("repetitive_roles", [])
        repetitive_employees= sum(r.get("employee_count", 0) for r in repetitive_roles)
        office_employees    = max(0, total_employees - repetitive_employees)

        # ── Integration level (count YES booleans) ────────────────────────
        il = audit_set.integration_level or {}
        integration_yes_count = sum(1 for v in il.values() if v)

        # ── Sites → SiteInfo list (for the engine's multi-site logic) ─────
        sites_raw = audit_set.sites or []
        sites = [
            SiteInfo(
                address=s.get("address", ""),
                process_description=s.get("process", ""),
                employee_count=s.get("employee_count", 0),
            )
            for s in sites_raw
            if s.get("employee_count", 0) > 0
        ]

        # ── EnMS energy data (ISO 50001) — first site that supplies it ────
        annual_energy_tj = num_energy_types = num_seus = None
        for s in sites_raw:
            if s.get("energy_tj") is not None:
                annual_energy_tj  = float(s["energy_tj"])
                num_energy_types  = s.get("energy_types")
                num_seus          = s.get("seu_count")
                break

        # ── Default sector classifications (Medium) ───────────────────────
        classifications = [
            StandardClassification(
                standard=iso_name,
                sector_name="Unknown",
                category="Medium",
            )
            for iso_name in standards
        ]

        form_data = ExtractedFormData(
            org_name=audit_set.company_name or "",
            standards=standards,
            audit_type=audit_set.audit_type or "Initial",
            scope=audit_set.scope_en or audit_set.scope_tr or "",
            total_employees=total_employees,
            office_employees=office_employees,
            repetitive_employees=repetitive_employees,
            subcontractors=subcontractors,
            seasonal_employees=seasonal,
            sites=sites,
            integration_yes_count=integration_yes_count,
            classifications=classifications,
            annual_energy_tj=annual_energy_tj,
            num_energy_types=num_energy_types,
            num_seus=num_seus,
            scope_integration_level=getattr(audit_set, "scope_integration_level", None),
        )

        result = calculate(form_data)
        return result.model_dump()

    except Exception as exc:
        logger.warning("[AuditSet] Calculation failed for id=%s: %s", getattr(audit_set, "id", "?"), exc)
        return None


def _create_auto_stages(db: Session, audit_set: AuditSet, result: dict | None) -> None:
    """Insert auto-generated AuditSetStage rows based on audit_type."""
    audit_type = (audit_set.audit_type or "initial").lower()

    if audit_type == "initial":
        stage_defs = [
            ("stage_1", 1, result.get("final_ph1") if result else None),
            ("stage_2", 2, result.get("final_ph2") if result else None),
        ]
    elif audit_type == "surveillance":
        stage_defs = [
            ("surveillance", 1, result.get("final_surv1") if result else None),
        ]
    else:  # recertification, transfer, scope_extension — use recert phase split
        stage_defs = [
            ("stage_1", 1, result.get("final_recert_ph1") if result else None),
            ("stage_2", 2, result.get("final_recert_ph2") if result else None),
        ]

    for stage_type, order, audit_days in stage_defs:
        db.add(AuditSetStage(
            id=str(uuid.uuid4()),
            audit_set_id=audit_set.id,
            stage_type=stage_type,
            stage_order=order,
            audit_days=audit_days,
        ))


# ---------------------------------------------------------------------------
# Public CRUD functions
# ---------------------------------------------------------------------------

def create_audit_set(db: Session, data: AuditSetCreateSchema) -> AuditSet:
    """Create a new AuditSet, run the calculator, auto-create stages. Returns persisted row."""
    audit_set = AuditSet(
        id=str(uuid.uuid4()),
        plan_number=_next_plan_number(db),
        status="draft",
        company_name=data.company_name,
        company_address=data.company_address,
        country=data.country,
        city=data.city,
        phone=data.phone,
        email=data.email,
        website=data.website,
        representative=data.representative,
        standards=data.standards,
        audit_type=data.audit_type,
        cycle_number=data.cycle_number,
        accreditation_body=data.accreditation_body,
        scope_tr=data.scope_tr,
        scope_en=data.scope_en,
        non_applicable_clauses=data.non_applicable_clauses,
        personnel=data.personnel.model_dump(),
        sites=[s.model_dump() for s in data.sites],
        integration_level=data.integration_level.model_dump(),
        certification_fee=data.certification_fee,
        surveillance_fee=data.surveillance_fee,
        ea_code=data.ea_code,
        ea_category=data.ea_category,
        ea_technical_area=data.ea_technical_area,
    )
    db.add(audit_set)
    db.flush()  # populate audit_set.id before child rows

    result = _run_calculation(audit_set)
    if result:
        audit_set.man_day_result = result
        audit_set.effective_employees = int(round(result.get("eps", 0)))
        audit_set.risk_category = (
            result["standard_results"][0].get("category", "").upper()
            if result.get("standard_results") else None
        )

    # Always derive required scope from scope text — no manual button needed
    audit_set.required_scope = derive_required_scope(
        standards=audit_set.standards or [],
        scope_tr=audit_set.scope_tr,
        scope_en=audit_set.scope_en,
        ea_code=audit_set.ea_code,
    )

    _create_auto_stages(db, audit_set, result)
    db.commit()
    db.refresh(audit_set)
    logger.info("[AuditSet] Created id=%s plan_number=%s", audit_set.id, audit_set.plan_number)
    return audit_set


def get_audit_set(db: Session, audit_set_id: str) -> AuditSet | None:
    """Return AuditSet by ID (including archived), or None."""
    return db.query(AuditSet).filter(AuditSet.id == audit_set_id).first()


def quick_calculate(db: Session, audit_set_id: str, data: QuickCalcSchema) -> AuditSet | None:
    """
    Re-run the IAF MD 5 calculator for an audit set with updated personnel /
    integration data. Persists new man_day_result and updates existing stage
    audit_days. Returns the refreshed AuditSet, or None if not found.
    """
    audit_set = get_audit_set(db, audit_set_id)
    if not audit_set:
        return None

    # Patch the audit set with submitted data (in-memory only, not persisted directly)
    submitted_personnel = data.personnel.model_dump()
    total_submitted = sum(
        submitted_personnel.get(k, 0)
        for k in ("full_time", "part_time", "subcontractors", "seasonal", "unskilled")
    )
    if total_submitted > 0:
        # Only overwrite stored personnel when the caller explicitly supplies counts
        audit_set.personnel = submitted_personnel
        audit_set.integration_level = data.integration_level.model_dump()
    # else: use the existing stored personnel (integration level change, scope level change, etc.)

    if data.ea_code is not None:
        audit_set.ea_code = data.ea_code
    if data.ea_category is not None:
        audit_set.ea_category = data.ea_category
    if data.scope_integration_level is not None:
        audit_set.scope_integration_level = data.scope_integration_level

    result = _run_calculation(audit_set)
    if not result:
        logger.warning("[AuditSet] quick_calculate: engine returned None for id=%s", audit_set_id)
        return audit_set  # return as-is without crashing

    audit_set.man_day_result = result
    audit_set.effective_employees = int(round(result.get("eps", 0)))
    audit_set.risk_category = (
        result["standard_results"][0].get("category", "").upper()
        if result.get("standard_results") else None
    )

    # Update stage audit_days to match new recommended days
    audit_type = (audit_set.audit_type or "initial").lower()
    stage_day_map: dict[str, float | None] = {}
    if audit_type == "initial":
        stage_day_map = {"stage_1": result.get("final_ph1"), "stage_2": result.get("final_ph2")}
    elif audit_type == "surveillance":
        stage_day_map = {"surveillance": result.get("final_surv1")}
    else:
        stage_day_map = {"stage_1": result.get("final_recert_ph1"), "stage_2": result.get("final_recert_ph2")}

    for stage in audit_set.stages:
        new_days = stage_day_map.get(stage.stage_type)
        if new_days is not None:
            stage.audit_days = new_days

    db.commit()
    db.refresh(audit_set)
    logger.info("[AuditSet] quick_calculate done for id=%s final_total=%s", audit_set_id, result.get("final_total"))
    return audit_set


def list_audit_sets(db: Session, status: str | None = None) -> list[AuditSet]:
    """Return all audit sets, newest first. Optionally filter by status."""
    q = db.query(AuditSet)
    if status:
        q = q.filter(AuditSet.status == status)
    return q.order_by(AuditSet.created_at.desc()).all()


def update_planning(
    db: Session,
    audit_set_id: str,
    data: AuditSetUpdatePlanningSchema,
) -> AuditSet | None:
    """
    Update EA classification, fees, and stage assignments.
    Creates a stage row if no matching stage_type + stage_order exists.
    Advances status from "draft" to "planning" on first call.
    Returns None if audit_set_id is not found.
    """
    audit_set = get_audit_set(db, audit_set_id)
    if not audit_set:
        return None

    # Update top-level fields (full replace — PUT semantics)
    audit_set.ea_code               = data.ea_code
    audit_set.ea_category           = data.ea_category
    audit_set.ea_technical_area     = data.ea_technical_area
    audit_set.certification_fee     = data.certification_fee
    audit_set.surveillance_fee      = data.surveillance_fee
    # Persist derived scope only when the caller provides it (don't wipe on stage-only saves)
    if data.required_scope is not None:
        audit_set.required_scope = data.required_scope
    if data.scope_integration_level is not None:
        audit_set.scope_integration_level = data.scope_integration_level

    # Upsert stages
    for stage_input in data.stages:
        existing = next(
            (s for s in audit_set.stages
             if s.stage_type == stage_input.stage_type
             and s.stage_order == stage_input.stage_order),
            None,
        )
        payload = dict(
            notification_date=stage_input.notification_date,
            audit_date_start=stage_input.audit_date_start,
            audit_date_end=stage_input.audit_date_end,
            lead_auditor_id=stage_input.lead_auditor_id,
            lead_auditor_name=stage_input.lead_auditor_name,
            auditors=[a.model_dump() for a in stage_input.auditors],
            technical_experts=[a.model_dump() for a in stage_input.technical_experts],
            observers=[a.model_dump() for a in stage_input.observers],
            ik_experts=[a.model_dump() for a in stage_input.ik_experts],
            evaluators=[a.model_dump() for a in stage_input.evaluators],
            audit_days=stage_input.audit_days,
            status=stage_input.status,
        )
        if existing:
            for k, v in payload.items():
                setattr(existing, k, v)
        else:
            db.add(AuditSetStage(
                id=str(uuid.uuid4()),
                audit_set_id=audit_set.id,
                stage_type=stage_input.stage_type,
                stage_order=stage_input.stage_order,
                **payload,
            ))

    if audit_set.status == "draft":
        audit_set.status = "planning"

    db.commit()
    db.refresh(audit_set)
    logger.info("[AuditSet] Planning updated id=%s", audit_set.id)
    return audit_set


def derive_and_save_scope(
    db: Session,
    audit_set_id: str,
) -> AuditSet | None:
    """
    Run keyword-based scope derivation against the stored scope text and
    save the result to audit_set.required_scope.  Returns None if not found.
    """
    audit_set = get_audit_set(db, audit_set_id)
    if not audit_set:
        return None

    scoped = derive_required_scope(
        standards=audit_set.standards or [],
        scope_tr=audit_set.scope_tr,
        scope_en=audit_set.scope_en,
        ea_code=audit_set.ea_code,
    )
    audit_set.required_scope = scoped
    db.commit()
    db.refresh(audit_set)
    logger.info("[AuditSet] Scope derived and saved id=%s → %s", audit_set.id, scoped)
    return audit_set


# ---------------------------------------------------------------------------
# Certificate management
# ---------------------------------------------------------------------------

def update_cert_dates(
    db: Session,
    audit_set_id: str,
    data: AuditSetCertUpdateSchema,
) -> AuditSet | None:
    """
    Update certificate issued/expiry dates and recompute cert_status.
    If cert_expiry_date is omitted but cert_issued_date is provided,
    auto-sets expiry to exactly 3 calendar years after issue.
    """
    audit_set = get_audit_set(db, audit_set_id)
    if not audit_set:
        return None

    if data.cert_issued_date is not None:
        audit_set.cert_issued_date = data.cert_issued_date

    if data.cert_expiry_date is not None:
        audit_set.cert_expiry_date = data.cert_expiry_date
    elif data.cert_issued_date is not None and audit_set.cert_expiry_date is None:
        # Auto-set to 3 calendar years from issue date
        issued = data.cert_issued_date
        try:
            audit_set.cert_expiry_date = issued.replace(year=issued.year + 3)
        except ValueError:
            # Feb 29 on a non-leap year → use Feb 28
            audit_set.cert_expiry_date = issued.replace(year=issued.year + 3, day=28)

    audit_set.cert_status = audit_set.compute_cert_status()
    db.commit()
    db.refresh(audit_set)
    logger.info("[AuditSet] Cert dates updated id=%s status=%s", audit_set.id, audit_set.cert_status)
    return audit_set


# ---------------------------------------------------------------------------
# Dashboard helpers
# ---------------------------------------------------------------------------

def _count_file_jobs(filename: str) -> int:
    """Count job directories containing `filename` whose state is not terminal."""
    from config.settings import get_settings
    base = Path(get_settings().storage_base_path)
    if not base.exists():
        return 0
    count = 0
    for job_dir in base.iterdir():
        if not job_dir.is_dir():
            continue
        status_file = job_dir / filename
        if not status_file.exists():
            continue
        try:
            data = json.loads(status_file.read_text(encoding="utf-8"))
            if data.get("state") not in ("COMPLETE", "FAILED"):
                count += 1
        except Exception:
            pass
    return count


def get_dashboard_stats(db: Session) -> dict:
    """Return aggregate counts for the dashboard stats cards."""
    total_plans = (
        db.query(func.count(AuditSet.id))
        .filter(AuditSet.status != "archived")
        .scalar() or 0
    )
    active_certs = (
        db.query(func.count(AuditSet.id))
        .filter(AuditSet.cert_status == "active")
        .scalar() or 0
    )
    approaching = (
        db.query(func.count(AuditSet.id))
        .filter(AuditSet.cert_status == "approaching_expiry")
        .scalar() or 0
    )
    expired = (
        db.query(func.count(AuditSet.id))
        .filter(AuditSet.cert_status == "expired")
        .scalar() or 0
    )
    open_jobs       = _count_file_jobs("status.json")
    pending_reviews = _count_file_jobs("review_status.json")

    return {
        "total_plans":          total_plans,
        "active_certificates":  active_certs,
        "approaching_expiry":   approaching,
        "expired":              expired,
        "open_jobs":            open_jobs,
        "pending_reviews":      pending_reviews,
    }


def list_clients(
    db: Session,
    search: str | None = None,
    standard: str | None = None,
    cert_status: str | None = None,
    audit_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[AuditSet]:
    """
    Return audit sets with stages eagerly loaded, ordered newest-first.
    Excludes archived records. Applies AND filters for every non-None param.
    """
    q = (
        db.query(AuditSet)
        .options(selectinload(AuditSet.stages))
        .filter(AuditSet.status != "archived")
    )
    if search:
        q = q.filter(AuditSet.company_name.ilike(f"%{search}%"))
    if standard:
        # standards is stored as JSON text in SQLite; match the quoted value
        q = q.filter(cast(AuditSet.standards, String).like(f'%"{standard}"%'))
    if cert_status:
        q = q.filter(AuditSet.cert_status == cert_status)
    if audit_type:
        q = q.filter(AuditSet.audit_type == audit_type)
    return q.order_by(AuditSet.created_at.desc()).limit(limit).offset(offset).all()
