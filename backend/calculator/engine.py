"""
BATUHAN — Audit Time Calculator: Calculation Engine
Implements all EPS calculation methods, table lookups, deductions, rounding,
and phase-split derivation for each ISO standard.

Execution order (per spec Part 4):
  1. EPS per standard
  2. Base time lookup (HQ)
  3. Additional site time additions
  4. Sum → integration reduction (20%, only if 2+ standards)
  5. Reporting reduction (20%, always, same base)
  6. Final total
  7. Rounding
  8. Phase split for outputs
"""

from __future__ import annotations
import math
import logging
from .models import ExtractedFormData, StandardAuditResult, CalculationResult
from .tables import (
    ISO9001_TABLES, ISO14001_TABLES, ISO45001_TABLES,
    ISO13485, ISO27001, ISO50001_A3, ISO50001_A4,
    lookup_eps,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rounding rule (per spec §Part 4 step 7)
# x.1–x.2 → floor, x.3–x.7 → x.5, x.8–x.9 → ceil
# ---------------------------------------------------------------------------

def _round_audit(value: float) -> float:
    """Apply IAF rounding: .1-.2→ floor, .3-.7→ .5, .8-.9→ ceil."""
    integer_part = math.floor(value)
    fraction = round(value - integer_part, 2)
    if fraction <= 0.2:
        return float(integer_part)
    elif fraction <= 0.7:
        return integer_part + 0.5
    else:
        return float(math.ceil(value))


# ---------------------------------------------------------------------------
# EnMS complexity factor K
# ---------------------------------------------------------------------------

def _enms_k(annual_tj: float, num_energy_types: int, num_seus: int) -> tuple[float, str]:
    """Compute K factor and complexity level for ISO 50001."""
    # FEC score
    if annual_tj <= 20:
        fec = 1.0
    elif annual_tj <= 200:
        fec = 1.2
    elif annual_tj <= 2000:
        fec = 1.4
    else:
        fec = 1.6

    # NET score
    if num_energy_types <= 2:
        net = 1.0
    elif num_energy_types == 3:
        net = 1.2
    else:
        net = 1.4

    # FSEU score
    if num_seus <= 3:
        fseu = 1.0
    elif num_seus <= 6:
        fseu = 1.2
    elif num_seus <= 10:
        fseu = 1.3
    elif num_seus <= 15:
        fseu = 1.4
    else:
        fseu = 1.6

    k = round(0.25 * fec + 0.25 * net + 0.50 * fseu, 4)

    if k > 1.35:
        level = "High"
    elif k >= 1.15:
        level = "Medium"
    else:
        level = "Low"

    return k, level


# ---------------------------------------------------------------------------
# EPS calculation per standard
# ---------------------------------------------------------------------------

def _eps_standard(data: ExtractedFormData, standard: str) -> float:
    """
    Compute effective person count for a given standard.
    ISO 9001/14001/45001/13485: percentage-table method.
    ISO 27001: square-root method for repetitive workers.
    ISO 50001: no repetitive reduction (energy personnel count direct).
    """
    # Risk/complexity category for repetitive reduction rate
    category = "Medium"
    for cls in data.classifications:
        if _std_match(cls.standard, standard):
            category = cls.category
            break

    repetitive = data.repetitive_employees
    office = data.office_employees
    total = data.total_employees

    if _std_match(standard, "ISO 27001"):
        # Square root method
        non_repetitive = office  # includes management etc.
        other = max(0, total - repetitive - office)
        eps = math.ceil(math.sqrt(repetitive)) + non_repetitive + other

    elif _std_match(standard, "ISO 50001"):
        # All personnel affecting energy performance — no repetitive reduction
        eps = total  # no reduction; part-time FTE conversion assumed via form data

    else:
        # Percentage-table method
        rate_map = {"High": 0.20, "Medium": 0.15, "Low": 0.10, "Limited": 0.05}
        rate = rate_map.get(category, 0.15)
        other = max(0, total - repetitive - office)
        eps = math.ceil(office + (repetitive * rate) + other)

    return float(max(eps, 1))


def _std_match(a: str, b: str) -> bool:
    """Case-insensitive partial match for standard names."""
    return b.strip().lower() in a.strip().lower() or a.strip().lower() in b.strip().lower()


# ---------------------------------------------------------------------------
# Per-standard base time lookup
# Returns StandardAuditResult (pre-deduction values)
# ---------------------------------------------------------------------------

def _lookup_standard(data: ExtractedFormData, standard: str) -> StandardAuditResult:
    """Look up audit time table values for one standard and return pre-deduction result."""
    eps = _eps_standard(data, standard)
    category = "Medium"
    for cls in data.classifications:
        if _std_match(cls.standard, standard):
            category = cls.category
            break

    # Select the right table and look up
    if _std_match(standard, "ISO 9001"):
        table = ISO9001_TABLES.get(category, ISO9001_TABLES["Medium"])
        row = lookup_eps(table, eps)
        if not row:
            raise ValueError(f"EPS {eps} out of range for ISO 9001")
        _, _, init_t, ph1, ph2, surv, recert_t, r_ph1, r_ph2 = row
        return StandardAuditResult(
            standard=standard, category=f"{category} Risk", eps=eps,
            base_init=init_t, base_ph1=ph1, base_ph2=ph2,
            base_surv=surv, base_recert=recert_t,
            base_recert_ph1=r_ph1, base_recert_ph2=r_ph2,
        )

    elif _std_match(standard, "ISO 14001") or _std_match(standard, "ISO 45001"):
        tbl = ISO14001_TABLES if _std_match(standard, "ISO 14001") else ISO45001_TABLES
        table = tbl.get(category, tbl["Medium"])
        row = lookup_eps(table, eps)
        if not row:
            raise ValueError(f"EPS {eps} out of range for {standard}")
        _, _, init_t, ph1, ph2, surv, recert_t, r_ph1, r_ph2 = row
        return StandardAuditResult(
            standard=standard, category=f"{category} Complexity", eps=eps,
            base_init=init_t, base_ph1=ph1, base_ph2=ph2,
            base_surv=surv, base_recert=recert_t,
            base_recert_ph1=r_ph1, base_recert_ph2=r_ph2,
        )

    elif _std_match(standard, "ISO 13485"):
        row = lookup_eps(ISO13485, eps)
        if not row:
            raise ValueError(f"EPS {eps} out of range for ISO 13485")
        _, _, init_t = row
        surv = max(round(init_t / 3 * 2) / 2, 1.0)   # 1/3, min 1
        recert_t = max(round(init_t * 2 / 3 * 2) / 2, 1.0)  # 2/3, min 1
        ph1 = round(init_t / 3 * 2) / 2
        ph2 = init_t - ph1
        r_ph1 = round(recert_t / 3 * 2) / 2
        r_ph2 = recert_t - r_ph1
        return StandardAuditResult(
            standard=standard, category="N/A", eps=eps,
            base_init=init_t, base_ph1=ph1, base_ph2=ph2,
            base_surv=surv, base_recert=recert_t,
            base_recert_ph1=r_ph1, base_recert_ph2=r_ph2,
        )

    elif _std_match(standard, "ISO 27001"):
        row = lookup_eps(ISO27001, eps)
        if not row:
            raise ValueError(f"EPS {eps} out of range for ISO 27001")
        _, _, total, ph1, ph2 = row
        surv = max(round(total / 3 * 2) / 2, 1.0)
        recert_t = max(round(total * 2 / 3 * 2) / 2, 1.0)
        r_ph1 = round(recert_t / 3 * 2) / 2
        r_ph2 = recert_t - r_ph1
        return StandardAuditResult(
            standard=standard, category="ISMS", eps=eps,
            base_init=total, base_ph1=ph1, base_ph2=ph2,
            base_surv=surv, base_recert=recert_t,
            base_recert_ph1=r_ph1, base_recert_ph2=r_ph2,
        )

    elif _std_match(standard, "ISO 50001"):
        if data.annual_energy_tj is None or data.num_energy_types is None or data.num_seus is None:
            raise ValueError("ISO 50001 requires EnMS energy data (missing from form)")
        k, level = _enms_k(data.annual_energy_tj, data.num_energy_types, data.num_seus)
        col_map = {"Low": 2, "Medium": 3, "High": 4}
        col = col_map[level]
        row_a3 = lookup_eps(ISO50001_A3, eps)
        row_a4 = lookup_eps(ISO50001_A4, eps)
        if not row_a3 or not row_a4:
            raise ValueError(f"EPS {eps} out of range for ISO 50001")
        init_t = row_a3[col]
        ph1 = round(init_t / 3 * 2) / 2
        ph2 = init_t - ph1
        surv_col = {2: 2, 3: 4, 4: 6}[col]
        recert_col = {2: 3, 3: 5, 4: 7}[col]
        surv = row_a4[surv_col]
        recert_t = row_a4[recert_col]
        r_ph1 = round(recert_t / 3 * 2) / 2
        r_ph2 = recert_t - r_ph1
        return StandardAuditResult(
            standard=standard, category=f"{level} Complexity (K={k})", eps=eps,
            base_init=init_t, base_ph1=ph1, base_ph2=ph2,
            base_surv=surv, base_recert=recert_t,
            base_recert_ph1=r_ph1, base_recert_ph2=r_ph2,
        )

    else:
        raise ValueError(f"Unsupported standard: {standard}")


# ---------------------------------------------------------------------------
# Site addition
# ---------------------------------------------------------------------------

def _add_site_time(data: ExtractedFormData, standard: str, base_table_fn) -> float:
    """Compute the total site time addition: sum of (site_time / 2) for each extra site."""
    total_site_add = 0.0
    for site in data.sites:
        if site.employee_count <= 0:
            continue
        try:
            site_result = base_table_fn(site.employee_count, standard, data)
            total_site_add += site_result.base_init / 2
        except Exception as e:
            logger.warning(f"Site time calculation failed for site '{site.address}': {e}")
    return total_site_add


def _lookup_for_eps(eps: float, standard: str, data: ExtractedFormData) -> StandardAuditResult:
    """Helper to look up table using an explicit EPS (used for site calculations)."""
    # Temporarily override total with just the site's employee count
    dummy = data.model_copy(update={"total_employees": int(eps), "repetitive_employees": 0, "office_employees": int(eps)})
    return _lookup_standard(dummy, standard)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def calculate(data: ExtractedFormData) -> CalculationResult:
    """
    Run the complete audit time calculation for all selected standards and
    return a CalculationResult with all phase splits and surveillance values.
    """
    if not data.standards:
        raise ValueError("No ISO standards selected on the application form.")

    # --- Step 1-2: Per-standard base time lookup ---
    standard_results: list[StandardAuditResult] = []
    enms_k: float | None = None
    enms_complexity: str | None = None

    for std in data.standards:
        result = _lookup_standard(data, std)
        # --- Step 3: Site additions ---
        site_add = 0.0
        for site in data.sites:
            if site.employee_count > 0:
                try:
                    site_res = _lookup_for_eps(float(site.employee_count), std, data)
                    site_add += site_res.base_init / 2
                except Exception as e:
                    logger.warning(f"Site addition failed for {std}: {e}")
        result = result.model_copy(update={"site_addition": site_add})
        standard_results.append(result)

        # Capture EnMS K value for display
        if _std_match(std, "ISO 50001") and data.annual_energy_tj is not None:
            k, level = _enms_k(data.annual_energy_tj, data.num_energy_types or 1, data.num_seus or 1)
            enms_k = k
            enms_complexity = level

    # --- Step 4: Combined base (HQ + sites) ---
    combined_base = sum(r.base_init + r.site_addition for r in standard_results)

    # --- Step 5: Integration reduction (20% if 2+ standards) ---
    integration_reduction = round(combined_base * 0.20, 2) if len(data.standards) >= 2 else 0.0

    # --- Step 6: Reporting deduction (always 20% of combined_base) ---
    reporting_reduction = round(combined_base * 0.20, 2)

    # --- Step 7: Final total ---
    raw_total = combined_base - integration_reduction - reporting_reduction
    final_total = _round_audit(raw_total)

    # --- Step 8: Phase split — weighted average of per-standard pre-split values ---
    # Weight each standard's Ph1/Ph2 by its share of combined_base
    total_weight = sum(r.base_init + r.site_addition for r in standard_results)

    if total_weight > 0:
        ph1_ratio = sum((r.base_ph1 / (r.base_init)) * (r.base_init + r.site_addition)
                        for r in standard_results if r.base_init > 0) / total_weight
    else:
        ph1_ratio = 1 / 3

    final_ph1 = _round_audit(final_total * ph1_ratio)
    final_ph2 = _round_audit(final_total * (1 - ph1_ratio))

    # Surveillance: weighted average of per-standard surv, scaled by deduction ratio
    deduction_ratio = final_total / combined_base if combined_base > 0 else 1.0
    raw_surv = sum((r.base_surv + r.site_addition / 2) * (r.base_init + r.site_addition) / total_weight
                   for r in standard_results) if total_weight > 0 else 1.0
    final_surv = max(_round_audit(raw_surv * deduction_ratio), 1.0)

    # Recertification: weighted average, scaled
    raw_recert = sum((r.base_recert + r.site_addition / 2) * (r.base_init + r.site_addition) / total_weight
                     for r in standard_results) if total_weight > 0 else 1.0
    final_recert = max(_round_audit(raw_recert * deduction_ratio), 1.0)

    # Recert phase split — weighted ratio of r_ph1/r_ph2
    if total_weight > 0:
        recert_ph1_ratio = sum(
            (r.base_recert_ph1 / r.base_recert if r.base_recert > 0 else 1/3)
            * (r.base_init + r.site_addition)
            for r in standard_results
        ) / total_weight
    else:
        recert_ph1_ratio = 1 / 3

    final_recert_ph1 = _round_audit(final_recert * recert_ph1_ratio)
    final_recert_ph2 = _round_audit(final_recert * (1 - recert_ph1_ratio))

    eps_display = _eps_standard(data, data.standards[0]) if data.standards else 0.0

    return CalculationResult(
        org_name=data.org_name,
        standards=data.standards,
        audit_type=data.audit_type,
        scope=data.scope,
        standard_results=standard_results,
        combined_base=round(combined_base, 2),
        integration_reduction=integration_reduction,
        reporting_reduction=reporting_reduction,
        final_total=final_total,
        final_ph1=final_ph1,
        final_ph2=final_ph2,
        final_surv1=final_surv,
        final_surv2=final_surv,
        final_recert=final_recert,
        final_recert_ph1=final_recert_ph1,
        final_recert_ph2=final_recert_ph2,
        total_employees=data.total_employees,
        office_employees=data.office_employees,
        repetitive_employees=data.repetitive_employees,
        eps=eps_display,
        enms_k=enms_k,
        enms_complexity=enms_complexity,
    )

