# Augment Implementation Prompt — Filler + Calculator Extensions

## Context

You are working on the Certiva backend (FastAPI + SQLAlchemy + PostgreSQL). The system manages ISO certification audits. Audit sets hold all company and audit configuration data. Each audit set has stages (Stage 1, Stage 2, Surveillance). At download time, the system generates a ZIP of .docx files pre-filled with data via the `docxtpl` library (Jinja2 for Word). You are implementing the full render pipeline for this ZIP generation, plus extending the calculator model with missing output fields.

Read these files before starting — they are your complete specification:
- `PENDING_CHANGES_after_documents.md` — every field that must exist, why it's needed, and how to compute it
- `TEMPLATE_AUDIT_REPORT.md` — the full placeholder audit, shows which Word document uses which variable

The relevant existing models are:

**`backend/audit_set/db_models.py`** — `AuditSet` has: `id`, `plan_number`, `company_name`, `company_address`, `country`, `phone`, `email`, `website`, `representative`, `standards` (JSON list of codes: "QMS", "EMS", etc.), `audit_type` (VARCHAR: "initial", "surveillance_1", "surveillance_2", "recertification"), `accreditation_body`, `scope_en`, `non_applicable_clauses`, `personnel` (JSON), `sites` (JSON list), `integration_level` (JSON with 8 boolean keys), `effective_employees`, `risk_category`, `man_day_result` (JSON — serialized `CalculationResult`), `certification_fee`, `surveillance_fee`, `scope_integration_level`, `ea_code`, `ea_category`, `ea_technical_area`. `AuditSetStage` has: `stage_type` ("stage_1", "stage_2", "surveillance"), `stage_order`, `notification_date`, `audit_date_start`, `audit_date_end`, `lead_auditor_id`, `lead_auditor_name`, `auditors` (JSON list), `technical_experts` (JSON list), `observers` (JSON list), `audit_days`.

**`backend/calculator/models.py`** — `CalculationResult` (Pydantic): `standard_results` (list[`StandardAuditResult`]), `combined_base`, `integration_reduction`, `reporting_reduction`, `final_total`, `final_ph1`, `final_ph2`, `final_surv1`, `final_surv2`, `final_recert`, `final_recert_ph1`, `final_recert_ph2`, `total_employees`, `office_employees`, `repetitive_employees`, `eps`, `enms_k`, `enms_complexity`, `scope_integration_level`, `md11_floor_applied`, `md11_floor_value`, `fssc_reporting_surcharge`, `warning`. `StandardAuditResult` (Pydantic): `standard`, `category`, `eps`, `base_init`, `base_ph1`, `base_ph2`, `base_surv`, `base_recert`, `base_recert_ph1`, `base_recert_ph2`, `site_addition`. `ExtractedFormData`: has `office_employees`, `repetitive_employees`, `haccp_studies`, `annual_energy_tj`, `num_energy_types`, `num_seus`.

**`backend/calculator/service.py`** — Runs the calculator, saves `CalculationResult` as JSON to `AuditSet.man_day_result`. This is where you add the write-back of `office_employees` / `repetitive_employees` to `audit_set.personnel`.

**Standard code → full name mapping** (hardcode this dict in filler.py):
```python
STANDARD_NAMES = {
    "QMS":   "ISO 9001:2015",
    "EMS":   "ISO 14001:2015",
    "OHSMS": "ISO 45001:2018",
    "FSMS":  "ISO 22000:2018",
    "ISMS":  "ISO/IEC 27001:2022",
    "MDQMS": "ISO 13485:2016",
    "ABMS":  "ISO 37001:2016",
    "ENMS":  "ISO 50001:2018",
}
```

---

## Task 1 — DB Migration: New columns on audit_sets

Add two columns to `audit_sets`. Write an Alembic migration and update the SQLAlchemy model.

```sql
ALTER TABLE audit_sets ADD COLUMN audit_language VARCHAR;
ALTER TABLE audit_sets ADD COLUMN document_language VARCHAR DEFAULT 'turkish';
```

In `db_models.py` add to `AuditSet`:
```python
audit_language = Column(String, nullable=True)
document_language = Column(String, default="turkish")
```

In `schemas.py` add to `AuditSetCreate`, `AuditSetUpdate`, `AuditSetResponse`:
```python
audit_language: Optional[str] = None
document_language: Optional[str] = "turkish"
```

---

## Task 2 — Backend: audit_language default at creation

In `backend/audit_set/service.py`, in the `create_audit_set` function, after receiving the create payload, compute a default `audit_language` if not supplied:

```python
COUNTRY_LANGUAGE = {
    "Turkey": "Turkish", "Türkiye": "Turkish",
    "Russia": "Russian", "Bangladesh": "Bengali",
    "United States": "English", "United Kingdom": "English",
    "Germany": "German", "France": "French",
    # Add more as needed
}

if not data.audit_language:
    data.audit_language = COUNTRY_LANGUAGE.get(data.country, "English")
```

---

## Task 3 — Backend: Allow "special" as audit_type

Wherever `audit_type` is validated (schema enum or service check), add `"special"` as a valid value alongside `"initial"`, `"surveillance_1"`, `"surveillance_2"`, `"recertification"`. No migration needed — `audit_type` is already VARCHAR.

---

## Task 4 — Calculator model extensions

### 4a. Add to `CalculationResult` in `backend/calculator/models.py`:
```python
# EnMS detail fields (only populated when ENMS is in standards)
enms_range_ec: Optional[str] = None    # e.g. "≥ 10 TJ and < 100 TJ"
enms_range_et: Optional[str] = None    # e.g. "≥ 3 and < 6 energy types"
enms_range_seu: Optional[str] = None   # e.g. "≥ 5 and < 10 SEUs"
enms_fec: Optional[float] = None       # Complexity factor for energy consumption
enms_fet: Optional[float] = None       # Complexity factor for energy types
enms_fseu: Optional[float] = None      # Complexity factor for SEUs
isms_business_score: Optional[int] = None
isms_it_score: Optional[int] = None
```

### 4b. Add to `StandardAuditResult`:
```python
haccp_addition: Optional[float] = None  # Extra person-days for HACCP studies (FSMS only)
```

### 4c. Populate these in `backend/calculator/service.py`:
- In the EnMS calculation branch: compute the IAF range labels and factor values from the input energy metrics (`annual_energy_tj`, `num_energy_types`, `num_seus`) using the IAF MD 6 lookup tables. Store them in the result.
- In the FSMS branch: after computing the HACCP extra days from `haccp_studies`, store the addition amount in `StandardAuditResult.haccp_addition`.
- In the ISMS branch: store the intermediate business and IT complexity scores in `CalculationResult.isms_business_score` and `isms_it_score`.

### 4d. Write back to AuditSet.personnel after calculator saves:
In `backend/calculator/service.py`, after persisting `CalculationResult` to `AuditSet.man_day_result`, also merge `office_employees` and `repetitive_employees` back into `AuditSet.personnel`:

```python
audit_set.personnel = {
    **audit_set.personnel,
    "office_employees": calculation_result.office_employees,
    "repetitive_employees": calculation_result.repetitive_employees,
}
# then flag the JSON column as modified for SQLAlchemy
from sqlalchemy.orm.attributes import flag_modified
flag_modified(audit_set, "personnel")
```

---

## Task 5 — Frontend: Audit set creation form additions

### 5a. Add `audit_language` field
- Add a text input labeled "Audit Language" to the audit set creation form
- On load (or when the country field changes), pre-populate it with the country→language suggestion. Either:
  - Call a new GET `/audit-sets/suggest-audit-language?country=Turkey` endpoint that returns `{"audit_language": "Turkish"}`, or
  - Hardcode the same `COUNTRY_LANGUAGE` dict client-side (simpler)
- The coordinator can freely edit the pre-filled value before saving
- Pass the value in the create/update payload as `audit_language`

### 5b. Add `document_language` selector (TÜRKAK only)
- Already specified — show a "Document Language" radio group (Turkish / English) only when `accreditation_body === "TURKAK"` or `"TÜRKAK"`
- Default: "turkish"
- Pass as `document_language` in the payload

### 5c. Add "Special Audit" to audit type dropdown
- The existing Audit Type dropdown has: Initial Certification, Surveillance 1, Surveillance 2, Recertification
- Add a fourth option: "Special Audit" with value `"special"`
- No other UI changes needed

---

## Task 6 — New file: `backend/audit_set/filler.py`

This is the most important task. Create `backend/audit_set/filler.py` with the following structure.

### 6a. Constants

```python
from datetime import date, timedelta
from typing import Optional
import calendar

STANDARD_NAMES = {
    "QMS": "ISO 9001:2015", "EMS": "ISO 14001:2015",
    "OHSMS": "ISO 45001:2018", "FSMS": "ISO 22000:2018",
    "ISMS": "ISO/IEC 27001:2022", "MDQMS": "ISO 13485:2016",
    "ABMS": "ISO 37001:2016", "ENMS": "ISO 50001:2018",
}

AUDIT_TYPE_DISPLAY = {
    "initial": "Initial Certification",
    "surveillance_1": "Surveillance",
    "surveillance_2": "Surveillance",
    "recertification": "Recertification",
    "special": "Special Audit",
}

STAGE_CLAUSES = {
    # ISO 9001:2015
    ("ISO 9001:2015", "stage_1"):      "4.1-4.2-4.3-4.4 / 5.2-5.3 / 6.1-6.2 / 7.1-7.2-7.3-7.4-7.5 / 8.1 / 9.2 / 9.3 / 10.1",
    ("ISO 9001:2015", "stage_2"):      "4.1-4.2-4.3-4.4 / 5.1-5.2-5.3 / 6.1-6.2-6.3 / 7.1-7.2-7.3-7.4-7.5 / 8.1-8.2-8.3-8.4-8.5-8.6-8.7 / 9.1-9.2-9.3 / 10.1-10.2-10.3",
    ("ISO 9001:2015", "surveillance"): "4.1-4.2-4.3 / 5.1-5.2-5.3 / 6.1-6.2-6.3 / 7.1-7.3-7.5 / 8.2-8.4-8.5-8.6-8.7 / 9.1-9.2-9.3 / 10.1-10.2-10.3",
    # ISO 14001:2015
    ("ISO 14001:2015", "stage_1"):      "4.1-4.2-4.3-4.4 / 5.2-5.3 / 6.1-6.2 / 7.1-7.2-7.3-7.4-7.5 / 8.1 / 9.2 / 9.3 / 10.1",
    ("ISO 14001:2015", "stage_2"):      "4.1-4.2-4.3-4.4 / 5.1-5.2-5.3 / 6.1-6.2-6.3 / 7.1-7.2-7.3-7.4-7.5 / 8.1-8.2-8.3 / 9.1-9.2-9.3 / 10.1-10.2",
    ("ISO 14001:2015", "surveillance"): "4.1-4.2-4.3 / 5.1-5.2-5.3 / 6.1-6.2-6.3 / 7.1-7.3-7.5 / 8.1-8.2 / 9.1-9.2-9.3 / 10.1-10.2",
    # ISO 45001:2018
    ("ISO 45001:2018", "stage_1"):      "4.1-4.2-4.3-4.4 / 5.2-5.3-5.4 / 6.1-6.2 / 7.1-7.2-7.3-7.4-7.5 / 8.1 / 9.2 / 9.3 / 10.1",
    ("ISO 45001:2018", "stage_2"):      "4.1-4.2-4.3-4.4 / 5.1-5.2-5.3-5.4 / 6.1-6.2-6.3 / 7.1-7.2-7.3-7.4-7.5 / 8.1-8.2 / 9.1-9.2-9.3 / 10.1-10.2-10.3",
    ("ISO 45001:2018", "surveillance"): "4.1-4.2-4.3 / 5.1-5.2-5.4 / 6.1-6.2-6.3 / 7.1-7.3-7.5 / 8.1-8.2 / 9.1-9.2-9.3 / 10.1-10.2-10.3",
    # ISO 22000:2018
    ("ISO 22000:2018", "stage_1"):      "4.1-4.2-4.3-4.4 / 5.2-5.3 / 6.1-6.2 / 7.1-7.2-7.3-7.4-7.5 / 8.1-8.2 / 9.2 / 9.3 / 10.1",
    ("ISO 22000:2018", "stage_2"):      "4.1-4.2-4.3-4.4 / 5.1-5.2-5.3 / 6.1-6.2-6.3 / 7.1-7.2-7.3-7.4-7.5 / 8.1-8.2-8.3-8.4-8.5-8.6-8.7-8.8-8.9 / 9.1-9.2-9.3 / 10.1-10.2-10.3",
    ("ISO 22000:2018", "surveillance"): "4.1-4.2 / 5.1-5.2-5.3 / 6.1 / 7.1-7.3-7.5 / 8.2-8.5-8.8-8.9 / 9.1-9.2-9.3 / 10.1-10.2-10.3",
    # ISO/IEC 27001:2022
    ("ISO/IEC 27001:2022", "stage_1"):      "4.1-4.2-4.3-4.4 / 5.2-5.3 / 6.1-6.2-6.3 / 7.1-7.2-7.3-7.4-7.5 / 8.1-8.2-8.3 / 9.2 / 9.3 / 10.1",
    ("ISO/IEC 27001:2022", "stage_2"):      "4.1-4.2-4.3-4.4 / 5.1-5.2-5.3 / 6.1-6.2-6.3 / 7.1-7.2-7.3-7.4-7.5 / 8.1-8.2-8.3 / 9.1-9.2-9.3 / 10.1-10.2",
    ("ISO/IEC 27001:2022", "surveillance"): "4.1-4.2-4.3 / 5.1-5.2-5.3 / 6.1-6.2-6.3 / 7.1-7.3-7.5 / 8.1-8.2-8.3 / 9.1-9.2-9.3 / 10.1-10.2",
    # ISO 50001:2018
    ("ISO 50001:2018", "stage_1"):      "4.1-4.2-4.3 / 5.2-5.3 / 6.1-6.2-6.3 / 7.1-7.2-7.3-7.4-7.5 / 8.1-8.2 / 9.2 / 9.3 / 10.1",
    ("ISO 50001:2018", "stage_2"):      "4.1-4.2-4.3 / 5.1-5.2-5.3 / 6.1-6.2-6.3 / 7.1-7.2-7.3-7.4-7.5 / 8.1-8.2-8.3-8.4-8.5-8.6 / 9.1-9.2-9.3 / 10.1-10.2-10.3",
    ("ISO 50001:2018", "surveillance"): "4.1-4.2-4.3 / 5.1-5.2-5.3 / 6.1-6.2-6.3 / 7.1-7.3-7.5 / 8.1-8.2-8.3-8.4 / 9.1-9.2-9.3 / 10.1-10.2-10.3",
    # ISO 13485:2016
    ("ISO 13485:2016", "stage_1"):      "4.1-4.2 / 5.1-5.2-5.3-5.4-5.5-5.6 / 6.1-6.2 / 7.1-7.2-7.3-7.4-7.5-7.6 / 8.1-8.2 / 9.2 / 10.1",
    ("ISO 13485:2016", "stage_2"):      "4.1-4.2 / 5.1-5.2-5.3-5.4-5.5-5.6 / 6.1-6.2-6.3 / 7.1-7.2-7.3-7.4-7.5-7.6 / 8.1-8.2-8.3-8.4-8.5 / 9.1-9.2-9.3 / 10.1-10.2",
    ("ISO 13485:2016", "surveillance"): "4.1-4.2 / 5.1-5.5-5.6 / 6.1-6.2 / 7.1-7.2-7.4-7.5-7.6 / 8.1-8.2-8.3-8.4-8.5 / 9.1-9.2 / 10.1-10.2",
    # ISO 37001:2016
    ("ISO 37001:2016", "stage_1"):      "4.1-4.2-4.3-4.4-4.5 / 5.1-5.2-5.3-5.4 / 6.1-6.2 / 7.1-7.2-7.3-7.4-7.5 / 8.1-8.2-8.3-8.4-8.5-8.6-8.7-8.8-8.9-8.10 / 9.2 / 9.3 / 10.1",
    ("ISO 37001:2016", "stage_2"):      "4.1-4.2-4.3-4.4-4.5 / 5.1-5.2-5.3-5.4 / 6.1-6.2 / 7.1-7.2-7.3-7.4-7.5 / 8.1-8.2-8.3-8.4-8.5-8.6-8.7-8.8-8.9-8.10 / 9.1-9.2-9.3 / 10.1-10.2",
    ("ISO 37001:2016", "surveillance"): "4.1-4.2-4.4-4.5 / 5.1-5.2-5.4 / 6.1 / 7.1-7.3-7.5 / 8.1-8.2-8.6-8.7-8.10 / 9.1-9.2-9.3 / 10.1-10.2",
}
```

**Note:** The clause strings above are approximate — verify them against the pre-printed rows in FR.222 (the Word template). FR.222 has these strings already correct. Use those as the authoritative source and update this dict to match exactly.

---

### 6b. Helper functions

```python
def format_date(d) -> str:
    """Format a date object as DD/MM/YYYY."""
    if d is None:
        return ""
    return d.strftime("%d/%m/%Y")

def format_date_range(start, end) -> str:
    """Format a date range. Same month: '10–12 June 2026'. Different: '28 Jan – 3 Feb 2026'."""
    if not start or not end:
        return ""
    if start.month == end.month and start.year == end.year:
        return f"{start.day}–{end.day} {start.strftime('%B %Y')}"
    return f"{start.strftime('%-d %b')} – {end.strftime('%-d %b %Y')}"

def add_working_days(d: date, days: int) -> date:
    """Subtract `days` working days (Mon–Fri) from date d."""
    # For negative days (subtracting): iterate backwards
    step = -1 if days > 0 else 1
    count = 0
    current = d
    while count < abs(days):
        current += timedelta(days=step)
        if current.weekday() < 5:  # Mon=0, Fri=4
            count += 1
    return current

def subtract_months(d: date, months: int) -> date:
    """Subtract calendar months from a date."""
    month = d.month - months
    year = d.year
    while month <= 0:
        month += 12
        year -= 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)

def add_years_minus_one_day(d: date, years: int = 1) -> date:
    """Add years then subtract 1 day (for cycle end dates)."""
    try:
        result = d.replace(year=d.year + years)
    except ValueError:  # Feb 29 → Feb 28
        result = d.replace(year=d.year + years, day=28)
    return result - timedelta(days=1)
```

---

### 6c. build_base_context() — the core function

```python
def build_base_context(audit_set, stage) -> dict:
    """
    Build the complete Jinja2 render context for one stage render.
    `audit_set` is an AuditSet ORM object.
    `stage` is an AuditSetStage ORM object.
    Returns a dict passed directly to docxtpl Document.render().
    """
    man_day = audit_set.man_day_result or {}
    personnel = audit_set.personnel or {}
    sites = audit_set.sites or []
    integration_level = audit_set.integration_level or {}
    audit_type = audit_set.audit_type or ""
    standards_codes = audit_set.standards or []  # e.g. ["QMS", "EMS"]
    standards_full = [STANDARD_NAMES[c] for c in standards_codes if c in STANDARD_NAMES]

    # --- Audit type booleans ---
    is_initial = audit_type == "initial"
    is_surveillance = audit_type.startswith("surveillance")
    is_recertification = audit_type == "recertification"
    is_special = audit_type == "special"

    # --- Stage lookups (for FR.222 estimated dates and FR.221 audit days) ---
    all_stages = {s.stage_type: s for s in audit_set.stages}
    stage1 = all_stages.get("stage_1")
    stage2 = all_stages.get("stage_2")
    surv_stage = all_stages.get(stage.stage_type) if is_surveillance else None

    # --- Estimated cycle dates (only for initial/recert/surv1) ---
    surv1_estimated_date = surv2_estimated_date = recert_estimated_date = None
    if (is_initial or is_recertification) and stage2 and stage2.audit_date_end:
        surv1_estimated_date = add_years_minus_one_day(stage2.audit_date_end)
        surv2_estimated_date = add_years_minus_one_day(surv1_estimated_date)
        recert_estimated_date = add_years_minus_one_day(surv2_estimated_date)
    elif audit_type == "surveillance_1" and stage.audit_date_end:
        surv2_estimated_date = add_years_minus_one_day(stage.audit_date_end)
        recert_estimated_date = add_years_minus_one_day(surv2_estimated_date)

    # --- Opening/closing meeting dates ---
    if is_initial or is_recertification:
        opening_meeting_date = stage1.audit_date_start if stage1 else None
        closing_meeting_date = stage2.audit_date_end if stage2 else None
    else:
        opening_meeting_date = stage.audit_date_start
        closing_meeting_date = stage.audit_date_end

    # --- Per-standard man-day result objects ---
    standard_results_by_name = {}
    for sr in (man_day.get("standard_results") or []):
        standard_results_by_name[sr["standard"]] = sr

    def get_std(full_name):
        return standard_results_by_name.get(full_name)

    # --- Personnel flattening ---
    total_employees = (
        personnel.get("full_time", 0)
        + personnel.get("part_time", 0)
        + personnel.get("unskilled", 0)
    )

    # --- Site aggregations for EnMS ---
    enms_energy_tj = sum(s.get("energy_tj", 0) for s in sites)
    enms_energy_types = max((s.get("energy_types", 0) for s in sites), default=0)
    enms_seu_count = sum(s.get("seu_count", 0) for s in sites)

    # --- Integration percentage ---
    true_count = sum(1 for v in integration_level.values() if v)
    integration_pct = round(true_count / 8 * 100) if integration_level else 0

    return {
        # Company info (passed through directly)
        "company_name":          audit_set.company_name,
        "company_address":       audit_set.company_address,
        "phone":                 audit_set.phone,
        "email":                 audit_set.email,
        "website":               audit_set.website,
        "representative":        audit_set.representative,
        "scope_en":              audit_set.scope_en,
        "non_applicable_clauses": audit_set.non_applicable_clauses,
        "ea_code":               audit_set.ea_code,
        "ea_category":           audit_set.ea_category,
        "ea_technical_area":     audit_set.ea_technical_area,
        "effective_employees":   audit_set.effective_employees,
        "plan_number":           audit_set.plan_number,
        "certification_fee":     audit_set.certification_fee,
        "initial_fee":           audit_set.certification_fee,   # alias for FR.220/221
        "surveillance_fee":      audit_set.surveillance_fee,
        "scope_integration_level": audit_set.scope_integration_level,
        "risk_category":         audit_set.risk_category,
        "audit_language":        audit_set.audit_language,

        # Standards
        "standards":             standards_codes,
        "standards_str":         ", ".join(standards_full),

        # Audit type
        "audit_type":            audit_type,
        "audit_type_display":    AUDIT_TYPE_DISPLAY.get(audit_type, audit_type),
        "is_initial":            is_initial,
        "is_surveillance":       is_surveillance,
        "is_recertification":    is_recertification,
        "is_special":            is_special,

        # Stage dates
        "today":                 format_date(date.today()),
        "audit_dates":           format_date_range(stage.audit_date_start, stage.audit_date_end),
        "audit_date_end":        format_date(stage.audit_date_end),
        "report_date":           format_date(stage.audit_date_end + timedelta(days=1)) if stage.audit_date_end else "",
        "plan_date":             format_date(add_working_days(stage.audit_date_start, 5)) if stage.audit_date_start else "",
        "notification_date":     format_date(subtract_months(stage.audit_date_start, 2)) if stage.audit_date_start else "",
        "opening_meeting_date":  format_date(opening_meeting_date),
        "closing_meeting_date":  format_date(closing_meeting_date),
        "stage1_dates":          format_date_range(stage1.audit_date_start, stage1.audit_date_end) if stage1 else "",
        "stage2_dates":          format_date_range(stage2.audit_date_start, stage2.audit_date_end) if stage2 else "",
        "stage2_start_date":     format_date(stage2.audit_date_start) if stage2 else "",
        "surv1_estimated_date":  format_date(surv1_estimated_date),
        "surv2_estimated_date":  format_date(surv2_estimated_date),
        "recert_estimated_date": format_date(recert_estimated_date),

        # Audit team
        "lead_auditor_name":     stage.lead_auditor_name,
        "auditors":              stage.auditors or [],
        "technical_experts":     stage.technical_experts or [],
        "observers":             stage.observers or [],
        # lead_auditor_codes + auditors[n].covered_codes_display:
        # populated separately by build_auditor_scope_strings(stage) — see 6d

        # Personnel
        "personnel":             personnel,
        "total_employees":       total_employees,
        "subcontractors":        personnel.get("subcontractors", 0),
        "shift_count":           personnel.get("shift_count", 1),
        "office_employees":      personnel.get("office_employees", 0),
        "repetitive_employees":  personnel.get("repetitive_employees", 0),

        # Sites
        "sites":                 sites,
        "site_addresses":        "\n".join(s.get("address", "") for s in sites),

        # EnMS site aggregates
        "enms_energy_tj":        enms_energy_tj,
        "enms_energy_types":     enms_energy_types,
        "enms_seu_count":        enms_seu_count,

        # Integration
        "integration_level":     integration_level,
        "integration_pct":       integration_pct,

        # Man-day result (full object for templates that iterate it)
        "man_day_result":        man_day,

        # Per-standard results (None if standard not in scope)
        "man_day_result_qms":    get_std("ISO 9001:2015"),
        "man_day_result_ems":    get_std("ISO 14001:2015"),
        "man_day_result_ohsms":  get_std("ISO 45001:2018"),
        "man_day_result_fsms":   get_std("ISO 22000:2018"),
        "man_day_result_isms":   get_std("ISO/IEC 27001:2022"),
        "man_day_result_mdqms":  get_std("ISO 13485:2016"),
        "man_day_result_abms":   get_std("ISO 37001:2016"),
        "man_day_result_enms":   get_std("ISO 50001:2018"),

        # EnMS CalculationResult fields (only set when ENMS in scope)
        "enms_range_ec":         man_day.get("enms_range_ec", ""),
        "enms_range_et":         man_day.get("enms_range_et", ""),
        "enms_range_seu":        man_day.get("enms_range_seu", ""),
        "enms_fec":              man_day.get("enms_fec", ""),
        "enms_fet":              man_day.get("enms_fet", ""),
        "enms_fseu":             man_day.get("enms_fseu", ""),

        # ISMS scores
        "isms_business_score":   man_day.get("isms_business_score", ""),
        "isms_it_score":         man_day.get("isms_it_score", ""),

        # Audit duration (FR.221)
        "stage_1_days":          stage1.audit_days if stage1 else "",
        "stage_2_days":          stage2.audit_days if stage2 else "",
        "surv_days":             man_day.get("final_surv1", ""),

        # Complexity (FR.222 risk/complexity rows)
        "complexity_category":   _extract_complexity_category(man_day, standards_codes),
    }

def _extract_complexity_category(man_day: dict, standards_codes: list) -> str:
    """Extract Low/Medium/High complexity for EMS/OHSMS from man_day_result."""
    # Only relevant when EMS or OHSMS is in scope
    for sr in (man_day.get("standard_results") or []):
        if sr.get("standard") in ("ISO 14001:2015", "ISO 45001:2018"):
            return sr.get("category", "")
    return ""
```

---

### 6d. Auditor scope string builder

```python
def build_auditor_scope_strings(stage, auditor_db_lookup: dict) -> dict:
    """
    Build covered_codes_display strings for every team member.
    `auditor_db_lookup`: dict mapping auditor_id → auditor ORM object (with covered_scope field).
    Returns a dict of additional context variables to merge into the base context.
    """
    def codes_display(auditor_obj) -> str:
        if not auditor_obj or not auditor_obj.covered_scope:
            return ""
        # covered_scope is a dict: {standard_full_name: [code1, code2, ...]}
        parts = []
        for std_name, codes in auditor_obj.covered_scope.items():
            parts.append(f"{' '.join(codes)} ({std_name})")
        return " | ".join(parts)

    lead = auditor_db_lookup.get(stage.lead_auditor_id)
    lead_codes = codes_display(lead)

    enriched_auditors = []
    for aud in (stage.auditors or []):
        aud_obj = auditor_db_lookup.get(aud.get("id"))
        enriched_auditors.append({
            **aud,
            "covered_codes_display": codes_display(aud_obj),
        })

    enriched_tes = []
    for te in (stage.technical_experts or []):
        te_obj = auditor_db_lookup.get(te.get("id"))
        enriched_tes.append({
            **te,
            "covered_codes_display": codes_display(te_obj),
        })

    return {
        "lead_auditor_codes": lead_codes,
        "auditors":           enriched_auditors,     # replaces base context auditors
        "technical_experts":  enriched_tes,          # replaces base context technical_experts
    }
```

---

### 6e. Per-person rendering (FR.224 and FR.211)

```python
def render_per_person_documents(audit_set, stage, base_context: dict, template_dir: str, output_dir: str):
    """
    Render one copy of FR.224 and one copy of FR.211 per team member.
    Writes files to output_dir/FR.224_PersonName.docx etc.
    """
    from docxtpl import DocxTemplate
    import os

    stage_type_key = stage.stage_type  # "stage_1", "stage_2", or "surveillance"
    # Normalize for STAGE_CLAUSES lookup
    clause_stage_key = stage_type_key if stage_type_key != "surveillance" else "surveillance"

    standards_codes = audit_set.standards or []

    team_members = []
    if stage.lead_auditor_name:
        team_members.append({
            "name": stage.lead_auditor_name,
            "covered_standards": _get_person_standards(stage.lead_auditor_id, standards_codes),
        })
    for aud in (stage.auditors or []):
        team_members.append({
            "name": aud.get("name", ""),
            "covered_standards": _get_person_standards(aud.get("id"), standards_codes),
        })
    for te in (stage.technical_experts or []):
        team_members.append({
            "name": te.get("name", ""),
            "covered_standards": _get_person_standards(te.get("id"), standards_codes),
        })

    for person in team_members:
        person_standards = person["covered_standards"]
        person_clauses = [
            STAGE_CLAUSES.get((std, clause_stage_key), "")
            for std in person_standards
        ]
        person_context = {
            **base_context,
            "assessed_person_name": person["name"],
            "person_standards":     person_standards,
            "person_clauses":       person_clauses,
        }

        safe_name = person["name"].replace(" ", "_").replace("/", "-")

        for form_code in ["FR.224", "FR.211"]:
            tpl_path = os.path.join(template_dir, f"{form_code}.docx")
            if not os.path.exists(tpl_path):
                continue
            doc = DocxTemplate(tpl_path)
            doc.render(person_context)
            doc.save(os.path.join(output_dir, f"{form_code}_{safe_name}.docx"))


def _get_person_standards(person_id, all_standards_codes: list) -> list:
    """
    Placeholder: query the auditor profile for this person's covered standards.
    Returns a list of full standard names (e.g. ["ISO 9001:2015"]).
    If auditor profile not found, fall back to all standards in scope.
    """
    # TODO: implement actual auditor DB lookup
    return [STANDARD_NAMES[c] for c in all_standards_codes if c in STANDARD_NAMES]
```

---

### 6f. Main ZIP builder

```python
def build_audit_set_zip(audit_set, stage, template_dir: str) -> bytes:
    """
    Build the full ZIP for one stage.
    Returns ZIP bytes to stream to the HTTP response.
    """
    import io, os, zipfile, tempfile
    from docxtpl import DocxTemplate

    # 1. Build base context
    ctx = build_base_context(audit_set, stage)

    # 2. Enrich with auditor scope strings (requires DB lookup — wire up in calling code)
    # auditor_lookup = {a.id: a for a in db.query(Auditor).filter(...)}
    # ctx.update(build_auditor_scope_strings(stage, auditor_lookup))

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        with tempfile.TemporaryDirectory() as tmpdir:

            # Per-person documents (FR.224 and FR.211)
            render_per_person_documents(audit_set, stage, ctx, template_dir, tmpdir)

            # All other documents — render once per stage
            single_render_forms = [
                "FR.218", "FR.220", "FR.221", "FR.222", "FR.223",
                "FR.225", "FR.229", "FR.230", "FR.231", "FR.231-1",
                "FR.232", "FR.232-1", "FR.234",
            ]
            for form_code in single_render_forms:
                tpl_path = os.path.join(template_dir, f"{form_code}.docx")
                if not os.path.exists(tpl_path):
                    continue
                doc = DocxTemplate(tpl_path)
                doc.render(ctx)
                out_path = os.path.join(tmpdir, f"{form_code}.docx")
                doc.save(out_path)

            # Add all files to ZIP
            for fname in os.listdir(tmpdir):
                zf.write(os.path.join(tmpdir, fname), fname)

    zip_buffer.seek(0)
    return zip_buffer.read()
```

---

## Task 7 — Wire filler into the download endpoint

In `backend/api/routes/audit_sets.py`, replace the existing `build_audit_set_zip` call with the new filler:

```python
from backend.audit_set.filler import build_audit_set_zip

@router.get("/{audit_set_id}/stages/{stage_id}/download")
def download_stage_documents(audit_set_id: int, stage_id: int, db: Session = Depends(get_db)):
    audit_set = db.query(AuditSet).filter(AuditSet.id == audit_set_id).first()
    stage = db.query(AuditSetStage).filter(AuditSetStage.id == stage_id).first()

    # Select template directory based on accreditation body and document language
    # (TÜRKAK Turkish vs TÜRKAK English vs UAF)
    template_dir = resolve_template_dir(audit_set)

    zip_bytes = build_audit_set_zip(audit_set, stage, template_dir)

    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=Stage_{stage.stage_type}.zip"}
    )
```

---

## Notes for Augment

- The `STAGE_CLAUSES` dict has approximate clause strings — before finalizing, compare them against the exact strings pre-printed in FR.222's table rows (those are authoritative).
- `build_auditor_scope_strings` needs a real Auditor DB query wired in — the function signature accepts a pre-fetched `auditor_db_lookup` dict to avoid N+1 queries.
- `_get_person_standards` currently falls back to all standards — replace with actual auditor profile lookup once the covered_standards field structure is confirmed.
- The `template_dir` resolution logic (UAF vs TÜRKAK-Turkish vs TÜRKAK-English) should be a separate helper that looks at `audit_set.accreditation_body` and `audit_set.document_language`.
- For the EnMS range bracket labels and factor values (Task 4c), implement the IAF MD 6 lookup tables. The thresholds are: energy consumption (TJ): < 10, 10–100, > 100; energy types: 1–2, 3–5, ≥ 6; SEUs: < 5, 5–10, > 10. The actual factor values depend on which bracket each metric falls into.
