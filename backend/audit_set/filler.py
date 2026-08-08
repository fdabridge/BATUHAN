"""
BATUHAN — Audit Set: docxtpl (Jinja2-for-Word) context builder + renderer.

The IFC blank-set DOCX templates now carry Jinja2 placeholders
({{ var }} and {% if %} blocks).  This module:

  * builds the render context from an AuditSet + AuditSetStage,
  * renders a single template to bytes via docxtpl,
  * provides the per-person context for the FR.224 (Audit Team Information)
    and FR.211 (Auditor Assessment) forms, which are rendered once per
    team member.

Auditor scope coverage (`covered_scope`) is computed on the fly from each
auditor's `standard_qualifications` against the audit set's `required_scope`
— mirroring the logic in the /auditors/available endpoint.
"""
from __future__ import annotations

import calendar
import io
from datetime import date, timedelta

from docxtpl import DocxTemplate

from audit_set.committee_slots import committee_member_name, planned_committee_chair
from audit_set.report_signature_rules import audit_set_has_stage1_extra_review
from audit_set.scope_fields import effective_ea_code
from auditors.qualification_scope import (
    normalize_scope_code,
    normalize_scope_type,
)

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
STANDARD_NAMES = {
    "QMS": "ISO 9001:2015", "EMS": "ISO 14001:2015",
    "OHSMS": "ISO 45001:2018", "FSMS": "ISO 22000:2018",
    "ISMS": "ISO/IEC 27001:2022", "MDQMS": "ISO 13485:2016",
    "ABMS": "ISO 37001:2016", "ENMS": "ISO 50001:2018",
}

AUDIT_TYPE_DISPLAY = {
    "initial": "Initial Certification",
    "surveillance": "Surveillance",
    "surveillance_1": "Surveillance",
    "surveillance_2": "Surveillance",
    "recertification": "Recertification",
    "special": "Special Audit",
}

# FR-numbers rendered once per team member (all other forms render once).
PER_PERSON_FORMS = {"FR.224", "FR.211"}

# Per-standard clause coverage by stage. The Stage 1 entries mirror the
# authoritative pre-printed FR.222 table; these strings feed FR.211/FR.224.
STAGE_CLAUSES = {
    ("ISO 9001:2015", "stage_1"):      "4.1-4.2-4.3-4.4 / 5.2-5.3 / 6.1-6.2 / 7.1-7.2-7.3-7.5 / 8.1-8.2-8.5 / 9.1-9.2-9.3",
    ("ISO 9001:2015", "stage_2"):      "4.1-4.2-4.3-4.4 / 5.1-5.2-5.3 / 6.1-6.2-6.3 / 7.1-7.2-7.3-7.4-7.5 / 8.1-8.2-8.3-8.4-8.5-8.6-8.7 / 9.1-9.2-9.3 / 10.1-10.2-10.3",
    ("ISO 9001:2015", "surveillance"): "4.1-4.2-4.3 / 5.1-5.2-5.3 / 6.1-6.2-6.3 / 7.1-7.3-7.5 / 8.2-8.4-8.5-8.6-8.7 / 9.1-9.2-9.3 / 10.1-10.2-10.3",
    ("ISO 14001:2015", "stage_1"):      "4.1-4.2-4.3-4.4 / 5.2-5.3 / 6.1-6.2 / 7.1-7.2-7.3-7.5 / 8.1 / 9.1-9.2-9.3",
    ("ISO 14001:2015", "stage_2"):      "4.1-4.2-4.3-4.4 / 5.1-5.2-5.3 / 6.1-6.2-6.3 / 7.1-7.2-7.3-7.4-7.5 / 8.1-8.2-8.3 / 9.1-9.2-9.3 / 10.1-10.2",
    ("ISO 14001:2015", "surveillance"): "4.1-4.2-4.3 / 5.1-5.2-5.3 / 6.1-6.2-6.3 / 7.1-7.3-7.5 / 8.1-8.2 / 9.1-9.2-9.3 / 10.1-10.2",
    ("ISO 45001:2018", "stage_1"):      "4.1-4.2-4.3-4.4 / 5.1-5.2-5.3-5.4 / 6.1-6.2 / 7.1-7.2-7.3-7.5 / 8.2 / 9.1-9.2-9.3 / 10.1",
    ("ISO 45001:2018", "stage_2"):      "4.1-4.2-4.3-4.4 / 5.1-5.2-5.3-5.4 / 6.1-6.2-6.3 / 7.1-7.2-7.3-7.4-7.5 / 8.1-8.2 / 9.1-9.2-9.3 / 10.1-10.2-10.3",
    ("ISO 45001:2018", "surveillance"): "4.1-4.2-4.3 / 5.1-5.2-5.4 / 6.1-6.2-6.3 / 7.1-7.3-7.5 / 8.1-8.2 / 9.1-9.2-9.3 / 10.1-10.2-10.3",
    ("ISO 22000:2018", "stage_1"):      "4.1-4.2-4.3-4.4 / 5.2-5.3 / 6.1-6.2 / 7.1-7.2-7.3-7.5 / 8.1-8.2-8.5-8.7-8.8 / 9.2-9.3",
    ("ISO 22000:2018", "stage_2"):      "4.1-4.2-4.3-4.4 / 5.1-5.2-5.3 / 6.1-6.2-6.3 / 7.1-7.2-7.3-7.4-7.5 / 8.1-8.2-8.3-8.4-8.5-8.6-8.7-8.8-8.9 / 9.1-9.2-9.3 / 10.1-10.2-10.3",
    ("ISO 22000:2018", "surveillance"): "4.1-4.2 / 5.1-5.2-5.3 / 6.1 / 7.1-7.3-7.5 / 8.2-8.5-8.8-8.9 / 9.1-9.2-9.3 / 10.1-10.2-10.3",
    ("ISO/IEC 27001:2022", "stage_1"):      "4.1-4.2-4.3-4.4 / 5.1-5.2-5.3 / 6.1-6.2 / 7.1-7.2-7.3-7.4-7.5 / 8.1-8.2-8.3 / 9.1-9.2-9.3 / 10.1-10.2 / Annex A: 5-6-7-8",
    ("ISO/IEC 27001:2022", "stage_2"):      "4.1-4.2-4.3-4.4 / 5.1-5.2-5.3 / 6.1-6.2-6.3 / 7.1-7.2-7.3-7.4-7.5 / 8.1-8.2-8.3 / 9.1-9.2-9.3 / 10.1-10.2",
    ("ISO/IEC 27001:2022", "surveillance"): "4.1-4.2-4.3 / 5.1-5.2-5.3 / 6.1-6.2-6.3 / 7.1-7.3-7.5 / 8.1-8.2-8.3 / 9.1-9.2-9.3 / 10.1-10.2",
    ("ISO 50001:2018", "stage_1"):      "4.1-4.2-4.3-4.4 / 5.1-5.2-5.3 / 6.1-6.2-6.3-6.4-6.5-6.6 / 7.2-7.3-7.5 / 8.2-8.3 / 9.1-9.2-9.3 / 10.1-10.2-10.3",
    ("ISO 50001:2018", "stage_2"):      "4.1-4.2-4.3 / 5.1-5.2-5.3 / 6.1-6.2-6.3 / 7.1-7.2-7.3-7.4-7.5 / 8.1-8.2-8.3-8.4-8.5-8.6 / 9.1-9.2-9.3 / 10.1-10.2-10.3",
    ("ISO 50001:2018", "surveillance"): "4.1-4.2-4.3 / 5.1-5.2-5.3 / 6.1-6.2-6.3 / 7.1-7.3-7.5 / 8.1-8.2-8.3-8.4 / 9.1-9.2-9.3 / 10.1-10.2-10.3",
    ("ISO 13485:2016", "stage_1"):      "4.1-4.2 / 5.1-5.2-5.3-5.4-5.5-5.6 / 6.1-6.2-6.3-6.4 / 7.1-7.2-7.3-7.4-7.5-7.6 / 8.1-8.2-8.3-8.4-8.5",
    ("ISO 13485:2016", "stage_2"):      "4.1-4.2 / 5.1-5.2-5.3-5.4-5.5-5.6 / 6.1-6.2-6.3 / 7.1-7.2-7.3-7.4-7.5-7.6 / 8.1-8.2-8.3-8.4-8.5 / 9.1-9.2-9.3 / 10.1-10.2",
    ("ISO 13485:2016", "surveillance"): "4.1-4.2 / 5.1-5.5-5.6 / 6.1-6.2 / 7.1-7.2-7.4-7.5-7.6 / 8.1-8.2-8.3-8.4-8.5 / 9.1-9.2 / 10.1-10.2",
    ("ISO 37001:2016", "stage_1"):      "4.1-4.2-4.3-4.4-4.5 / 5.2-5.3 / 6.1-6.2 / 7.2-7.3-7.5 / 8.1 / 9.1-9.2-9.3",
    ("ISO 37001:2016", "stage_2"):      "4.1-4.2-4.3-4.4-4.5 / 5.1-5.2-5.3-5.4 / 6.1-6.2 / 7.1-7.2-7.3-7.4-7.5 / 8.1-8.2-8.3-8.4-8.5-8.6-8.7-8.8-8.9-8.10 / 9.1-9.2-9.3 / 10.1-10.2",
    ("ISO 37001:2016", "surveillance"): "4.1-4.2-4.4-4.5 / 5.1-5.2-5.4 / 6.1 / 7.1-7.3-7.5 / 8.1-8.2-8.6-8.7-8.10 / 9.1-9.2-9.3 / 10.1-10.2",
}

for (_std, _stage), _clauses in list(STAGE_CLAUSES.items()):
    if _stage == "stage_2":
        STAGE_CLAUSES[(_std, "recertification")] = _clauses


# --------------------------------------------------------------------------- #
# Date helpers
# --------------------------------------------------------------------------- #
def format_date(d) -> str:
    """Format a date object as DD/MM/YYYY."""
    if d is None:
        return ""
    return d.strftime("%d/%m/%Y")


def format_date_range(start, end) -> str:
    """Format a date range. Same month: '10–12 June 2026'. Cross-month: '28 Jan – 3 Feb 2026'."""
    if not start:
        return ""
    if not end or end == start:
        return start.strftime("%-d %B %Y")
    if start.month == end.month and start.year == end.year:
        return f"{start.day}–{end.day} {start.strftime('%B %Y')}"
    return f"{start.strftime('%-d %b')} – {end.strftime('%-d %b %Y')}"


def add_working_days(d: date, days: int) -> date:
    """Move `days` working days (Mon–Fri) from date d; positive = backwards."""
    step = -1 if days > 0 else 1
    count = 0
    current = d
    while count < abs(days):
        current += timedelta(days=step)
        if current.weekday() < 5:  # Mon=0 … Fri=4
            count += 1
    return current


def subtract_months(d: date, months: int) -> date:
    """Subtract calendar months from a date, clamping the day to month length."""
    month = d.month - months
    year = d.year
    while month <= 0:
        month += 12
        year -= 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def add_years_minus_one_day(d: date, years: int = 1) -> date:
    """Add `years` then subtract 1 day (certification-cycle end dates)."""
    try:
        result = d.replace(year=d.year + years)
    except ValueError:  # Feb 29 → Feb 28
        result = d.replace(year=d.year + years, day=28)
    return result - timedelta(days=1)


_CURRENCY_SYMBOLS: dict[str, str] = {
    "USD": "$",
    "EUR": "€",
    "TRY": "₺",
}


def _fmt_fee(val, currency: str = "USD") -> str:
    """Format a fee value with the correct currency symbol.

    Formats as '<symbol>X,XXX' (no decimal places — fees are always whole units).
    Falls back to '$' if an unrecognised currency code is passed.
    Returns '' when val is None or empty.
    """
    if val is None or val == "":
        return ""
    try:
        symbol = _CURRENCY_SYMBOLS.get(currency or "USD", "$")
        return f"{symbol}{float(val):,.0f}"
    except (TypeError, ValueError):
        return str(val)


# --------------------------------------------------------------------------- #
# Auditor scope-coverage helpers
# --------------------------------------------------------------------------- #
def _norm_std(name: str) -> str:
    """Normalise a standard name for matching: lowercase, drop ':YYYY' suffix."""
    base = (name or "").split(":")[0]
    return base.replace(" ", "").lower()


def _std_match(a: str, b: str) -> bool:
    na, nb = _norm_std(a), _norm_std(b)
    return bool(na) and (na == nb or na in nb or nb in na)


def _compute_covered_scope(qualifications, required_scope: dict) -> dict:
    """
    For each required standard/codes, determine which codes this auditor covers.
    Mirrors /auditors/available._compute_covered_scope.
    Returns {iso_standard: [covered_codes]} keyed by the required_scope key.
    """
    covered: dict = {}
    for iso_std, entry in (required_scope or {}).items():
        scope_type = normalize_scope_type(entry.get("type", "ea"))
        required_codes = entry.get("codes", []) or []
        if not required_codes:
            continue
        qual = next(
            (q for q in (qualifications or [])
             if q.is_qualified is not False and _std_match(iso_std, q.standard_code or "")),
            None,
        )
        if qual is None:
            continue
        if scope_type in ("food", "medical", "isms", "sector", "energy"):
            raw = qual.scope_category or ""
            auditor_codes = [c.strip() for c in raw.split(",") if c.strip()]
        else:  # "ea"
            auditor_codes = qual.ea_codes or []
        auditor_keys = {normalize_scope_code(c, scope_type) for c in auditor_codes}
        matched = [
            c for c in required_codes
            if normalize_scope_code(c, scope_type) in auditor_keys
        ]
        if matched:
            covered[iso_std] = matched
    return covered


def _covered_codes_display(covered: dict) -> str:
    """Render a covered_scope dict as 'EA 3 (ISO 9001) | CI CIV (ISO 22000)'."""
    if not covered:
        return ""
    parts = [f"{' '.join(codes)} ({std})" for std, codes in covered.items() if codes]
    return " | ".join(parts)


# --------------------------------------------------------------------------- #
# Base context
# --------------------------------------------------------------------------- #
def _extract_complexity_category(man_day: dict) -> str:
    """Low/Medium/High complexity for EMS/OHSMS, read from man_day_result."""
    for sr in (man_day.get("standard_results") or []):
        if sr.get("standard") in ("ISO 14001:2015", "ISO 45001:2018"):
            return sr.get("category", "") or ""
    return ""


def _normalize_site(s: dict) -> dict:
    """Add all field aliases so every template variant works regardless of naming."""
    d = dict(s)
    # The DB stores 'process' (from SiteData schema). Add all aliases for template compat.
    process_val = d.get("process") or d.get("process_description") or d.get("scope") or ""
    d.setdefault("process", process_val)
    d.setdefault("process_description", process_val)   # some old templates use this
    d.setdefault("scope", process_val)                 # FR.222 sites[0] uses 'scope'
    d.setdefault("employee_count", d.get("employees", 0))
    d.setdefault("employees", d.get("employee_count", 0))   # FR.222 sites[0] uses 'employees'
    d.setdefault("audit_days", "")                     # per-site days don't exist
    d.setdefault("address", "")
    return d


def build_base_context(audit_set, stage, org_attendees: list | None = None) -> dict:
    """Build the complete Jinja2 render context for one stage render.

    `org_attendees` (Portal 49a) is an optional list of dicts shaped as
    ``{"name": str, "role": str, "sig_key": str}`` used by the FR.225
    organisation-personnel docxtpl loop. Callers that have access to a DB
    session resolve this from the client's ClientOrgEmployee roster; tests
    and other paths can leave it as None (renders as an empty loop).
    """
    man_day = audit_set.man_day_result or {}
    personnel = audit_set.personnel or {}
    sites_raw = audit_set.sites or []
    if not sites_raw:
        # Fallback: synthesise one site from the top-level address so templates
        # that access sites[0] don't crash when no sites were configured.
        sites_raw = [{
            "address": audit_set.company_address or "",
            "process": audit_set.scope_en or "",
            "employee_count": audit_set.effective_employees or 0,
        }]
    sites = [_normalize_site(s) for s in sites_raw]
    integration_level = audit_set.integration_level or {}
    audit_type = audit_set.audit_type or ""
    standards_codes = audit_set.standards or []
    standards_full = [STANDARD_NAMES[c] for c in standards_codes if c in STANDARD_NAMES]

    is_initial = audit_type == "initial"
    is_surveillance = audit_type.startswith("surveillance")
    is_recertification = audit_type == "recertification"
    is_special = audit_type == "special"

    all_stages = {s.stage_type: s for s in (audit_set.stages or [])}
    stage1 = all_stages.get("stage_1")
    stage2 = all_stages.get("stage_2")
    recert_stage = all_stages.get("recertification") or stage2 or stage1

    # Estimated certification-cycle dates.
    surv1_estimated = surv2_estimated = recert_estimated = None
    if is_initial and stage2 and stage2.audit_date_end:
        surv1_estimated = add_years_minus_one_day(stage2.audit_date_end)
        surv2_estimated = add_years_minus_one_day(surv1_estimated)
        recert_estimated = add_years_minus_one_day(surv2_estimated)
    elif is_recertification and recert_stage and recert_stage.audit_date_end:
        surv1_estimated = add_years_minus_one_day(recert_stage.audit_date_end)
        surv2_estimated = add_years_minus_one_day(surv1_estimated)
        recert_estimated = add_years_minus_one_day(surv2_estimated)
    elif audit_type == "surveillance_1" and stage.audit_date_end:
        surv2_estimated = add_years_minus_one_day(stage.audit_date_end)
        recert_estimated = add_years_minus_one_day(surv2_estimated)

    opening_meeting_date = stage.audit_date_start
    closing_meeting_date = stage.audit_date_end

    # Per-standard rows enriched with template-friendly column names.
    # Engine stores `standard` as the bare name ("ISO 9001"), but templates
    # reference the full label ("ISO 9001:2015") — normalise the key so both
    # forms resolve to the same entry.
    _combined_base = man_day.get("combined_base") or 0
    _int_reduction_total = man_day.get("integration_reduction") or 0
    _report_reduction_total = man_day.get("reporting_reduction") or 0

    standard_results_rows: list[dict] = []
    standard_results_by_name: dict[str, dict] = {}
    for sr in (man_day.get("standard_results") or []):
        base_init   = sr.get("base_init", 0) or 0
        base_ph1    = sr.get("base_ph1", 0) or 0
        base_ph2    = sr.get("base_ph2", 0) or 0
        base_surv   = sr.get("base_surv", 0) or 0
        base_recert = sr.get("base_recert", 0) or 0
        site_add    = sr.get("site_addition", 0) or 0

        # Proportional share of the total integration / reporting reductions,
        # weighted by this standard's contribution to combined_base.
        weight = ((base_init + site_add) / _combined_base) if _combined_base else 0
        per_std_intg = round(_int_reduction_total * weight, 2)
        per_std_report = round(_report_reduction_total * weight, 2)

        ad = base_init + site_add
        enriched = {
            **sr,
            # Template-friendly column names used by FR.218 per-standard rows.
            "ad":               round(ad, 2) if ad else "",
            "inc_dec_ad":       round(site_add, 2) if site_add else "",
            "intg_reduction":   per_std_intg if per_std_intg else "",
            "report_reduction": per_std_report if per_std_report else "",
            "stage_1":          round(base_ph1, 2) if base_ph1 else "",
            "stage_2":          round(base_ph2, 2) if base_ph2 else "",
            "surv":             round(base_surv, 2) if base_surv else "",
            "rec":              round(base_recert, 2) if base_recert else "",
        }
        standard_results_rows.append(enriched)
        standard_results_by_name[_norm_std(sr.get("standard", ""))] = enriched

    def get_std(full_name):
        return standard_results_by_name.get(_norm_std(full_name))

    total_employees = (
        personnel.get("full_time", 0)
        + personnel.get("part_time", 0)
        + personnel.get("unskilled", 0)
    )

    enms_energy_tj = sum(s.get("energy_tj", 0) for s in sites)
    enms_energy_types = max((s.get("energy_types", 0) for s in sites), default=0)
    enms_seu_count = sum(s.get("seu_count", 0) for s in sites)

    true_count = sum(1 for v in integration_level.values() if v)
    integration_pct = round(true_count / 8 * 100) if integration_level else 0

    end = stage.audit_date_end
    start = stage.audit_date_start

    # Audit-days fallback: derive from man_day_result when not explicitly set on the stage.
    _stage_type = stage.stage_type  # "stage_1" | "stage_2" | "surveillance" | "recertification"
    if _stage_type == "stage_1":
        _audit_days_fallback = man_day.get("final_ph1", "")
    elif _stage_type == "stage_2":
        _audit_days_fallback = man_day.get("final_ph2", "")
    elif _stage_type == "recertification":
        _audit_days_fallback = man_day.get("final_recert", "")
    else:  # surveillance
        _audit_days_fallback = man_day.get("final_surv1", "")

    decision_committee_chair_name = committee_member_name(planned_committee_chair(audit_set)) or ""

    stage1_dates_value = format_date_range(stage1.audit_date_start, stage1.audit_date_end) if stage1 else ""
    stage2_dates_value = format_date_range(stage2.audit_date_start, stage2.audit_date_end) if stage2 else ""
    recertification_dates_value = (
        format_date_range(recert_stage.audit_date_start, recert_stage.audit_date_end)
        if is_recertification and recert_stage
        else ""
    )
    stage2_date_value = (
        stage2_dates_value
        if stage2
        else (format_date_range(start, end) if (is_surveillance or is_recertification) else "")
    )
    surveillance_date_value = format_date_range(start, end) if is_surveillance else ""
    recertification_date_value = format_date_range(start, end) if is_recertification else ""
    stage2_start_date_value = format_date(stage2.audit_date_start) if stage2 else ""
    surv1_estimated_date_value = format_date(surv1_estimated)
    surv2_estimated_date_value = format_date(surv2_estimated)
    recert_estimated_date_value = format_date(recert_estimated)

    fr222_date_aliases: dict[str, str] = {}
    for suffix in ("qms", "ems", "ohsms", "fsms", "isms", "enms", "mdqms", "abms"):
        fr222_date_aliases.update(
            {
                f"stage_1_date_{suffix}": stage1_dates_value,
                f"stage_2_date_{suffix}": stage2_dates_value,
                f"surveillance_date_{suffix}": surv1_estimated_date_value,
                f"surveillance_1_date_{suffix}": surv1_estimated_date_value,
                f"surveillance_2_date_{suffix}": surv2_estimated_date_value,
                f"recertification_date_{suffix}": recert_estimated_date_value,
            }
        )

    return {
        # Company
        "company_name": audit_set.company_name,
        "company_address": audit_set.company_address,
        "phone": audit_set.phone or "",
        "email": audit_set.email or "",
        "website": audit_set.website or "",
        "representative": audit_set.representative or "",
        "scope_en": audit_set.scope_en or "",
        "scope_tr": audit_set.scope_tr or "",
        "non_applicable_clauses": audit_set.non_applicable_clauses or "",
        # required_scope is revised during application review; prefer it over
        # the legacy top-level value so regenerated plans never show stale EA.
        "ea_code": effective_ea_code(
            getattr(audit_set, "required_scope", None),
            audit_set.ea_code,
        ),
        "ea_category": audit_set.ea_category or "",
        "ea_technical_area": audit_set.ea_technical_area or "",
        "effective_employees": audit_set.effective_employees,
        # `plan_number` in documents shows the client_reference if the user set one,
        # otherwise the system-assigned sequential number. `plan_number_internal`
        # keeps the raw DB id available for any template that needs it.
        "plan_number": getattr(audit_set, "client_reference", None) or audit_set.plan_number,
        "plan_number_internal": audit_set.plan_number,
        "agreement_number": getattr(audit_set, "client_reference", None) or str(audit_set.plan_number),
        "client_reference": getattr(audit_set, "client_reference", None) or "",
        "certification_fee": _fmt_fee(audit_set.certification_fee, getattr(audit_set, "currency", None) or "USD"),
        "initial_fee":       _fmt_fee(audit_set.certification_fee, getattr(audit_set, "currency", None) or "USD"),
        "surveillance_fee":  _fmt_fee(audit_set.surveillance_fee, getattr(audit_set, "currency", None) or "USD"),
        "currency":          getattr(audit_set, "currency", None) or "USD",
        "currency_symbol":   _CURRENCY_SYMBOLS.get(getattr(audit_set, "currency", None) or "USD", "$"),
        "currency_code":     getattr(audit_set, "currency", None) or "USD",
        "scope_integration_level": audit_set.scope_integration_level,
        "risk_category": audit_set.risk_category,
        "audit_language": audit_set.audit_language,
        "document_language": audit_set.document_language,
        # Standards
        "standards": standards_codes,
        "standards_str": ", ".join(standards_full),
        "standards_full": standards_full,
        "qms_selected":   "QMS" in standards_codes,
        "ems_selected":   "EMS" in standards_codes,
        "ohsms_selected": "OHSMS" in standards_codes,
        "fsms_selected":  "FSMS" in standards_codes,
        "isms_selected":  "ISMS" in standards_codes,
        "mdqms_selected": "MDQMS" in standards_codes,
        "abms_selected":  "ABMS" in standards_codes,
        "enms_selected":  "ENMS" in standards_codes,
        "needs_stage1_appointed_reviewer": audit_set_has_stage1_extra_review(audit_set),
        # Audit type
        "audit_type": audit_type,
        "audit_type_display": AUDIT_TYPE_DISPLAY.get(audit_type, audit_type),
        # Alias used by FR.223 / FR.224 / FR.225 field maps (must match audit_type_display).
        "audit_type_str": AUDIT_TYPE_DISPLAY.get(audit_type, audit_type),
        "is_initial": is_initial,
        "is_surveillance": is_surveillance,
        "is_recertification": is_recertification,
        "is_special": is_special,
        # Dates
        "today": format_date(date.today()),
        "audit_dates": format_date_range(start, end),
        "audit_date_end": format_date(end),
        "report_date": format_date(end + timedelta(days=1)) if end else "",
        "plan_date": format_date(add_working_days(start, 5)) if start else "",
        "notification_date": format_date(subtract_months(start, 2)) if start else "",
        "opening_meeting_date": format_date(opening_meeting_date),
        "closing_meeting_date": format_date(closing_meeting_date),
        "stage1_dates": stage1_dates_value,
        "stage2_dates": stage2_dates_value,
        "recertification_dates": recertification_dates_value,
        # Underscore-named aliases used by FR.233, FR.232, FR.231, FR.211 field maps.
        "stage_1_date": stage1_dates_value,
        "stage_2_date": stage2_date_value,
        "surveillance_date": surveillance_date_value,
        "recertification_date": recertification_date_value,
        "stage2_start_date": stage2_start_date_value,
        "surv1_estimated_date": surv1_estimated_date_value,
        "surv2_estimated_date": surv2_estimated_date_value,
        "recert_estimated_date": recert_estimated_date_value,
        **fr222_date_aliases,
        # Team (auditor scope strings merged in by build_auditor_scope_strings)
        "lead_auditor_name": stage.lead_auditor_name,
        "decision_committee_chair_name": decision_committee_chair_name,
        "auditors": stage.auditors or [],
        "technical_experts": stage.technical_experts or [],
        "observers": stage.observers or [],
        "trainees": getattr(stage, "trainees", None) or [],
        "evaluators": getattr(stage, "evaluators", None) or [],
        # Portal 49a — FR.225 org attendees (rendered via {%tr for emp in org_attendees %})
        "org_attendees": org_attendees or [],
        # Personnel
        "personnel": personnel,
        "total_employees": total_employees,
        "subcontractors": personnel.get("subcontractors", 0),
        "shift_count": personnel.get("shift_count", 1),
        "office_employees": personnel.get("office_employees", 0),
        "repetitive_employees": personnel.get("repetitive_employees", 0),
        # Sites
        "sites": sites,
        "site_addresses": "\n".join(s.get("address", "") for s in sites) or (audit_set.company_address or ""),
        # Portal 78 — per-site template variables (site_1_* … site_5_*)
        "additional_sites_count": len(sites_raw) if (audit_set.sites or []) else 0,
        **{
            k: v
            for i, s in enumerate((audit_set.sites or [])[:5], start=1)
            for k, v in {
                f"site_{i}_name":      s.get("name", f"Site {i}"),
                f"site_{i}_address":   s.get("address", ""),
                f"site_{i}_employees": s.get("employee_count", "") or "",
                f"site_{i}_process":   s.get("process", ""),
            }.items()
        },
        **{k: "" for k in (
            f"site_{i}_{field}"
            for i in range(len(audit_set.sites or []) + 1, 6)
            for field in ("name", "address", "employees", "process")
        )},
        "additional_sites_summary": (
            "\n".join(
                " — ".join(filter(None, [
                    s.get("name") or f"Site {i}",
                    s.get("address") or None,
                    (f"{s['employee_count']} emp." if s.get("employee_count") else None),
                    s.get("process") or None,
                ]))
                for i, s in enumerate(audit_set.sites or [], start=1)
            ) or "None"
        ),
        "enms_energy_tj": enms_energy_tj,
        "enms_energy_types": enms_energy_types,
        "enms_seu_count": enms_seu_count,
        # Integration
        "integration_level": integration_level,
        "integration_pct": integration_pct,
        # Man-day results
        "man_day_result": man_day,
        "standard_results_rows": standard_results_rows,
        "integration_reduction": man_day.get("integration_reduction", ""),
        "reporting_reduction":   man_day.get("reporting_reduction", ""),
        "combined_base":         man_day.get("combined_base", ""),
        "final_total":           man_day.get("final_total", ""),
        "man_day_result_qms": get_std("ISO 9001:2015"),
        "man_day_result_ems": get_std("ISO 14001:2015"),
        "man_day_result_ohsms": get_std("ISO 45001:2018"),
        "man_day_result_fsms": get_std("ISO 22000:2018"),
        "man_day_result_isms": get_std("ISO/IEC 27001:2022"),
        "man_day_result_mdqms": get_std("ISO 13485:2016"),
        "man_day_result_abms": get_std("ISO 37001:2016"),
        "man_day_result_enms": get_std("ISO 50001:2018"),
        # EnMS detail
        "enms_range_ec": man_day.get("enms_range_ec", ""),
        "enms_range_et": man_day.get("enms_range_et", ""),
        "enms_range_seu": man_day.get("enms_range_seu", ""),
        "enms_fec": man_day.get("enms_fec", ""),
        "enms_fet": man_day.get("enms_fet", ""),
        "enms_fseu": man_day.get("enms_fseu", ""),
        # ISMS scores
        "isms_business_score": man_day.get("isms_business_score", ""),
        "isms_it_score": man_day.get("isms_it_score", ""),
        # Audit duration
        "stage_1_days": (stage1.audit_days if stage1 and stage1.audit_days is not None
                         else man_day.get("final_ph1", "")) if stage1 else "",
        "stage_2_days": (stage2.audit_days if stage2 and stage2.audit_days is not None
                         else man_day.get("final_ph2", "")) if stage2 else "",
        "surv_days": man_day.get("final_surv1", ""),
        "audit_days": stage.audit_days if stage.audit_days is not None else (_audit_days_fallback or ""),
        "complexity_category": _extract_complexity_category(man_day),
    }


# --------------------------------------------------------------------------- #
# Auditor team enrichment + per-person context
# --------------------------------------------------------------------------- #
def build_auditor_scope_strings(stage, auditor_lookup: dict, required_scope: dict) -> dict:
    """
    Build `covered_codes_display` strings for the lead, auditors and technical
    experts. `auditor_lookup` maps auditor_id → Auditor ORM object.

    Falls back to the assignment-level `ea_code` field on each entry when the
    computed scope is empty or the auditor profile is unavailable, so the
    EA/IAF Code column in FR.223/FR.224 always shows something the coordinator
    explicitly assigned.

    Returns a dict to merge into the base context (overrides auditors / TEs).
    """
    def disp(aud, assignment: dict | None = None) -> str:
        fallback = (assignment or {}).get("ea_code") or ""
        if not aud:
            return fallback
        computed = _covered_codes_display(
            _compute_covered_scope(aud.standard_qualifications, required_scope)
        )
        if computed:
            return computed
        # Second fallback: auditor's own top-level ea_codes list (Auditor.ea_codes)
        # covers the case where required_scope is empty or the per-qualification
        # ea_codes column has not been filled in yet.
        if aud.ea_codes:
            return " ".join(str(c) for c in aud.ea_codes)
        return fallback

    def _enrich(member: dict) -> dict:
        """Return the member dict with ea_code, covered_codes_display, and standard
        guaranteed to be strings (never Python None, which docxtpl renders as 'None').

        `standard` is the comma-joined list of ISO standard names from required_scope
        that this auditor is qualified for, e.g. 'ISO 13485' or 'ISO 9001:2015, ISO 14001:2015'.
        Falls back to all required_scope keys when the profile is unavailable or no
        qualifications match the scope entries.
        """
        member_id = member.get("id")
        aud = auditor_lookup.get(member_id)
        codes = disp(aud, member)

        # Derive standard string from auditor qualifications matched to required_scope.
        if aud and aud.standard_qualifications:
            # Primary: use the keys from _compute_covered_scope (auditor has matching codes).
            covered_stds = list(
                _compute_covered_scope(aud.standard_qualifications, required_scope).keys()
            )
            # Secondary fallback: auditor is qualified for the standard but required_scope
            # has no specific codes to match (e.g. medical scope with empty codes list).
            if not covered_stds:
                quals = [q for q in aud.standard_qualifications if q.is_qualified is not False]
                covered_stds = [
                    iso for iso in (required_scope or {}).keys()
                    if any(_std_match(iso, q.standard_code or "") for q in quals)
                ]
            standard_str = ", ".join(covered_stds) if covered_stds else ", ".join((required_scope or {}).keys())
        else:
            # No auditor profile found — list all audit standards.
            standard_str = ", ".join((required_scope or {}).keys())

        return {
            **member,
            "ea_code": codes or (member.get("ea_code") or ""),
            "covered_codes_display": codes,
            "standard": standard_str,
        }

    enriched_auditors = [_enrich(a) for a in (stage.auditors or [])]
    enriched_tes = [_enrich(te) for te in (stage.technical_experts or [])]

    # Compute lead auditor standard string using the same logic as _enrich.
    _lead_aud = auditor_lookup.get(stage.lead_auditor_id)
    if _lead_aud and _lead_aud.standard_qualifications:
        _lead_covered = list(
            _compute_covered_scope(_lead_aud.standard_qualifications, required_scope).keys()
        )
        if not _lead_covered:
            _lead_quals = [q for q in _lead_aud.standard_qualifications if q.is_qualified is not False]
            _lead_covered = [
                iso for iso in (required_scope or {}).keys()
                if any(_std_match(iso, q.standard_code or "") for q in _lead_quals)
            ]
        _lead_standard = ", ".join(_lead_covered) if _lead_covered else ", ".join((required_scope or {}).keys())
    else:
        _lead_standard = ", ".join((required_scope or {}).keys())

    return {
        "lead_auditor_codes": disp(auditor_lookup.get(stage.lead_auditor_id)),
        "lead_auditor_standard": _lead_standard,
        "auditors": enriched_auditors,
        "technical_experts": enriched_tes,
    }


def _get_person_standards(person_id, auditor_lookup: dict, standards_codes: list) -> list:
    """Full standard names this person is qualified for, within the audit scope.
    Falls back to all in-scope standards when the auditor profile is unknown."""
    standards_full = [STANDARD_NAMES[c] for c in standards_codes if c in STANDARD_NAMES]
    aud = auditor_lookup.get(person_id)
    if not aud:
        return standards_full
    quals = [q for q in (aud.standard_qualifications or []) if q.is_qualified is not False]
    matched = [
        full for full in standards_full
        if any(_std_match(full, q.standard_code or "") for q in quals)
    ]
    return matched or standards_full


def build_team_members(stage, auditor_lookup: dict, standards_codes: list) -> list:
    """Per-person context blocks (FR.224 / FR.211): one per team member."""
    clause_key = stage.stage_type  # "stage_1" | "stage_2" | "surveillance"
    members: list[dict] = []
    if stage.lead_auditor_name:
        members.append({"id": stage.lead_auditor_id, "name": stage.lead_auditor_name})
    for a in (stage.auditors or []):
        members.append({"id": a.get("id"), "name": a.get("name", "")})
    for te in (stage.technical_experts or []):
        members.append({"id": te.get("id"), "name": te.get("name", "")})

    result: list[dict] = []
    seen: set = set()
    for m in members:
        if not m["name"] or m["name"] in seen:
            continue
        seen.add(m["name"])
        person_standards = _get_person_standards(m["id"], auditor_lookup, standards_codes)
        person_clauses = [STAGE_CLAUSES.get((std, clause_key), "") for std in person_standards]
        result.append({
            "name": m["name"],
            "person_standards": person_standards,
            "person_clauses": person_clauses,
        })
    return result


# --------------------------------------------------------------------------- #
# Renderer
# --------------------------------------------------------------------------- #
def render_docx(template_path, context: dict) -> bytes:
    """Render one docxtpl template with `context`; return DOCX bytes."""
    doc = DocxTemplate(str(template_path))
    doc.render(context, autoescape=True)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
