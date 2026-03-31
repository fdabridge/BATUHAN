"""
BATUHAN — Audit Time Calculator: Pydantic Models
Data contracts for extracted form data and calculation results.
"""

from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Extracted form data (output of Claude extraction step)
# ---------------------------------------------------------------------------

class SiteInfo(BaseModel):
    """A single additional site on the application form."""
    address: str
    process_description: str = ""
    employee_count: int = 0


class StandardClassification(BaseModel):
    """Claude's sector classification for one ISO standard."""
    standard: str            # e.g. "ISO 9001"
    sector_name: str         # e.g. "Food/beverages/tobacco"
    category: str            # "High" | "Medium" | "Low" | "Limited"


class ExtractedFormData(BaseModel):
    """Everything Claude extracts from the uploaded application form(s)."""
    org_name: str = ""
    standards: list[str] = Field(default_factory=list)   # e.g. ["ISO 9001", "ISO 14001"]
    audit_type: str = "Initial"   # Initial | Transfer | Scope Extension | Recertification
    scope: str = ""

    # Employee data
    total_employees: int = 0
    office_employees: int = 0
    repetitive_employees: int = 0
    subcontractors: int = 0
    seasonal_employees: int = 0
    employees_per_shift: Optional[int] = None

    # Sites (additional beyond HQ)
    sites: list[SiteInfo] = Field(default_factory=list)

    # Standard-specific
    haccp_studies: Optional[int] = None        # ISO 22000
    integration_yes_count: int = 0            # 0-8 (page 3 ticked YES boxes)

    # Sector classification per standard (Claude determines these)
    classifications: list[StandardClassification] = Field(default_factory=list)

    # ISO 50001 / EnMS — from additional form
    annual_energy_tj: Optional[float] = None
    num_energy_types: Optional[int] = None
    num_seus: Optional[int] = None             # Significant Energy Uses (covering 80% consumption)

    # Raw Claude response for traceability
    raw_extraction: str = ""


# ---------------------------------------------------------------------------
# Per-standard calculation result
# ---------------------------------------------------------------------------

class StandardAuditResult(BaseModel):
    """Audit time figures for one ISO standard."""
    standard: str
    category: str           # e.g. "High Risk" / "Medium Complexity"
    eps: float              # Effective Person count used for table lookup

    # Base (pre-deduction) values from table
    base_init: float        # Initial total
    base_ph1: float         # Stage 1 from table
    base_ph2: float         # Stage 2 from table
    base_surv: float        # Surveillance from table
    base_recert: float      # Recertification total from table
    base_recert_ph1: float  # Recertification Ph1
    base_recert_ph2: float  # Recertification Ph2

    # Site addition (pre-deduction)
    site_addition: float = 0.0


# ---------------------------------------------------------------------------
# Final combined calculation result
# ---------------------------------------------------------------------------

class CalculationResult(BaseModel):
    """Complete audit time calculation result — displayed to the user."""
    org_name: str
    standards: list[str]
    audit_type: str
    scope: str

    # Per-standard breakdown
    standard_results: list[StandardAuditResult]

    # Aggregation
    combined_base: float        # Sum of all standards' base times (incl. sites)
    integration_reduction: float   # 20% off if 2+ standards; 0 if single
    reporting_reduction: float     # Always 20% off combined_base

    final_total: float          # After both deductions + rounding

    # Phase split for INITIAL CERTIFICATION
    final_ph1: float
    final_ph2: float

    # Surveillance (two identical visits)
    final_surv1: float
    final_surv2: float

    # Recertification
    final_recert: float
    final_recert_ph1: float
    final_recert_ph2: float

    # Employee breakdown (shown in UI)
    total_employees: int
    office_employees: int
    repetitive_employees: int
    eps: float

    # EnMS complexity (ISO 50001 only)
    enms_k: Optional[float] = None
    enms_complexity: Optional[str] = None

    # Error / warning message (e.g. missing EnMS form)
    warning: Optional[str] = None

