"""Advanced standalone audit-time calculator.

This module is intentionally independent from AuditSet persistence.  It powers
only the sidebar calculator and does not modify application/client planning.
"""
from __future__ import annotations

import math
import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .engine import _lookup_standard, _round_audit
from .models import ExtractedFormData, StandardClassification


STANDARD_NAMES: dict[str, str] = {
    "QMS": "ISO 9001",
    "EMS": "ISO 14001",
    "OHSMS": "ISO 45001",
    "FSMS": "ISO 22000",
    "ISMS": "ISO 27001",
    "MDQMS": "ISO 13485",
    "ABMS": "ISO 37001",
    "ENMS": "ISO 50001",
}

EA_CODE_NAMES: dict[int, str] = {
    1: "Agriculture, forestry and fishing",
    2: "Mining and quarrying",
    3: "Food products, beverages and tobacco",
    4: "Textiles and textile products",
    5: "Leather and leather products",
    6: "Wood and wood products",
    7: "Pulp, paper and paper products",
    8: "Publishing companies",
    9: "Printing companies",
    10: "Coke and refined petroleum products",
    11: "Nuclear fuel",
    12: "Chemicals, chemical products and fibres",
    13: "Pharmaceuticals",
    14: "Rubber and plastic products",
    15: "Non-metallic mineral products",
    16: "Concrete, cement, lime and plaster",
    17: "Basic metals and fabricated metal products",
    18: "Machinery and equipment",
    19: "Electrical and optical equipment",
    20: "Shipbuilding",
    21: "Aerospace",
    22: "Other transport equipment",
    23: "Manufacturing not elsewhere classified",
    24: "Recycling",
    25: "Electricity supply",
    26: "Gas supply",
    27: "Water supply",
    28: "Construction",
    29: "Wholesale and retail trade",
    30: "Hotels and restaurants",
    31: "Transport, storage and communication",
    32: "Financial intermediation, real estate and renting",
    33: "Information technology",
    34: "Engineering services",
    35: "Other services",
    36: "Public administration",
    37: "Education",
    38: "Health and social work",
    39: "Other social services",
}

_EA_KEYWORDS: dict[int, tuple[str, ...]] = {
    1: ("agriculture", "farming", "forestry", "fishery", "aquaculture", "livestock"),
    2: ("mining", "quarrying", "mineral extraction", "coal extraction"),
    3: ("food", "beverage", "bakery", "dairy", "meat", "tobacco", "confectionery"),
    4: ("textile", "garment", "clothing", "fabric", "weaving", "knitting"),
    5: ("leather", "tanning", "footwear"),
    6: ("wood", "timber", "sawmill", "carpentry", "joinery"),
    7: ("paper", "pulp", "cardboard", "paperboard"),
    8: ("publishing", "book publisher", "journal publisher"),
    9: ("printing", "print shop", "flexography", "gravure"),
    10: ("petroleum refinery", "oil refinery", "coke production", "fuel refining"),
    11: ("nuclear fuel", "uranium", "radioactive"),
    12: ("chemical", "petrochemical", "fertilizer", "paint", "detergent", "resin"),
    13: ("pharmaceutical", "medicine", "drug manufacturing", "vaccine"),
    14: ("rubber", "plastic", "polymer", "injection moulding"),
    15: ("glass", "ceramic", "tile", "brick", "mineral product"),
    16: ("concrete", "cement", "lime", "plaster", "mortar", "precast"),
    17: ("steel", "aluminium", "aluminum", "foundry", "forging", "metal fabrication"),
    18: ("machinery", "industrial equipment", "pump", "compressor", "machine tool"),
    19: ("electrical", "electronics", "semiconductor", "optical equipment", "switchgear"),
    20: ("shipbuilding", "ship repair", "marine vessel", "yacht"),
    21: ("aerospace", "aircraft", "aviation", "spacecraft", "satellite"),
    22: ("automotive", "vehicle", "locomotive", "rail vehicle", "motorcycle"),
    23: ("furniture manufacturing", "jewellery", "toy manufacturing", "musical instrument"),
    24: ("recycling", "material recovery", "scrap processing"),
    25: ("electricity generation", "power plant", "solar power", "wind power"),
    26: ("gas supply", "gas distribution", "natural gas network"),
    27: ("water supply", "water treatment", "water distribution"),
    28: ("construction", "civil engineering", "building contractor", "infrastructure"),
    29: ("wholesale", "retail", "trade", "distribution", "import", "export"),
    30: ("hotel", "restaurant", "catering", "hospitality", "accommodation"),
    31: ("transport", "logistics", "freight", "warehousing", "courier", "telecommunication"),
    32: ("financial", "banking", "insurance", "real estate", "leasing"),
    33: ("information technology", "software", "cloud", "cybersecurity", "data centre", "saas"),
    34: ("engineering services", "testing laboratory", "research and development", "architectural"),
    35: ("consulting", "legal services", "accounting", "facility management", "cleaning"),
    36: ("public administration", "government agency", "ministry", "public authority"),
    37: ("education", "training", "school", "university", "academy"),
    38: ("healthcare", "hospital", "clinic", "medical services", "social work", "dental"),
    39: ("waste collection", "sewage", "remediation", "media production", "recreation"),
}

_QMS_HIGH = {1, 2, 3, 10, 11, 12, 13, 14, 16, 18, 19, 20, 21, 24, 25, 26, 28, 38}
_QMS_LOW = {4, 5, 7, 8, 29, 30, 32, 33, 35, 37}
_EMS_HIGH = {2, 5, 7, 9, 10, 12, 13, 15, 16, 17, 20, 24, 25, 26, 28, 39}
_EMS_LOW = {8, 29, 30, 33, 34, 35, 37, 38}
_EMS_LIMITED = {32, 36}
_OHS_HIGH = {1, 2, 10, 12, 13, 17, 20, 24, 25, 28, 39}
_OHS_LOW = {8, 29, 30, 32, 33, 35, 36, 37}

_FOOD_KEYWORDS: dict[str, tuple[str, ...]] = {
    "AI": ("animal farming", "livestock farming", "cattle farm", "poultry farm"),
    "AII": ("fish farming", "farming of fish", "aquaculture", "seafood farming", "farming of seafood"),
    "BI": ("plant handling", "harvesting fruit", "harvesting vegetable"),
    "BII": ("grain handling", "pulse handling", "grain storage"),
    "CI": ("meat processing", "meat product", "poultry processing", "fish processing", "seafood processing",
           "dairy processing", "milk processing", "yogurt production", "cheese production", "egg processing",
           "döner", "doner", "kebap", "kebab"),
    "CII": ("fresh produce", "fresh fruit", "fresh vegetable", "fresh juice"),
    "CIII": ("ready meal", "sandwich", "prepared food", "ready-to-eat", "hazır yemek", "hazır gıda", "hazır tüketim"),
    "CIV": ("bakery", "bread", "confectionery", "snack", "canned", "pasta", "beverage"),
    "D": ("animal feed", "pet food", "feedstuff"),
    "E": ("catering", "restaurant", "canteen", "food service"),
    "FI": ("food retail", "supermarket", "food wholesale"),
    "FII": ("food broker", "food trader", "food distribution"),
    "G": ("food storage", "cold chain", "food logistics", "food warehousing"),
    "H": ("food service support", "food transport service", "transport support"),
    "I": ("food packaging", "packaging material", "food contact material"),
    "J": ("food equipment", "processing equipment", "vending machine"),
    "K": ("food chemical", "food additive", "food enzyme", "ingredient manufacture"),
    "BIII": ("plant pre-process", "sorting plant", "packing whole plant"),
    "C0": ("slaughter", "slaughterhouse", "abattoir"),
}

_MEDICAL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Active medical devices": ("medical device", "diagnostic device", "monitor", "imaging"),
    "Non-active medical devices": ("implant", "surgical instrument", "catheter", "prosthesis"),
    "In-vitro diagnostic devices": ("in-vitro", "ivd", "laboratory reagent", "diagnostic kit"),
    "Sterilization services": ("sterilization", "sterile", "ethylene oxide"),
}

_ISMS_KEYWORDS: dict[str, tuple[str, ...]] = {
    "A": ("software", "cloud", "data centre", "cybersecurity", "telecommunication"),
    "B": ("bank", "financial", "insurance", "payment"),
    "C": ("healthcare", "hospital", "government", "critical infrastructure"),
    "D": ("outsourcing", "managed service", "shared service", "business process"),
}

_MD11_MATRIX: dict[int, dict[int, int]] = {
    20: {20: 0, 40: 0, 60: 0, 80: 0, 100: 0},
    40: {20: 0, 40: 5, 60: 5, 80: 5, 100: 5},
    60: {20: 0, 40: 5, 60: 10, 80: 10, 100: 10},
    80: {20: 0, 40: 5, 60: 10, 80: 15, 100: 15},
    100: {20: 0, 40: 5, 60: 10, 80: 15, 100: 20},
}


class AdvancedSiteInput(BaseModel):
    id: str
    name: str = ""
    address: str = ""
    process_description: str = ""
    employee_count: int = Field(default=0, ge=0)
    site_type: Literal["permanent", "temporary"] = "permanent"
    sampling_eligible: bool = True


class MultiSiteEligibility(BaseModel):
    single_management_system: bool = False
    central_function_identified: bool = False
    centralized_management_review: bool = False
    centralized_internal_audit: bool = False
    similar_processes: bool = False

    @property
    def satisfied(self) -> bool:
        return all(self.model_dump().values())


class IntegrationProfile(BaseModel):
    enabled: bool = False
    integrated_documentation: bool = False
    integrated_management_review: bool = False
    integrated_internal_audits: bool = False
    integrated_policy_objectives: bool = False
    integrated_processes: bool = False
    integrated_improvement: bool = False
    integrated_responsibilities: bool = False
    combined_audit_capability_pct: int = Field(default=20, ge=0, le=100)

    @property
    def integration_pct(self) -> int:
        flags = [
            self.integrated_documentation,
            self.integrated_management_review,
            self.integrated_internal_audits,
            self.integrated_policy_objectives,
            self.integrated_processes,
            self.integrated_improvement,
            self.integrated_responsibilities,
        ]
        return round(sum(flags) / len(flags) * 100)


class AdvancedCalculationRequest(BaseModel):
    organization_name: str = ""
    scope: str = Field(min_length=5)
    standards: list[str] = Field(min_length=1)
    audit_type: Literal["initial", "surveillance", "recertification"] = "initial"
    accreditation_body: Literal["UAF", "TURKAK"] = "UAF"

    full_time_personnel: int = Field(default=1, ge=0)
    part_time_personnel: int = Field(default=0, ge=0)
    part_time_hours_per_day: float = Field(default=4, ge=0, le=24)
    normal_hours_per_day: float = Field(default=8, gt=0, le=24)
    subcontractors: int = Field(default=0, ge=0)
    subcontractors_in_scope: bool = True
    seasonal_temporary_personnel: int = Field(default=0, ge=0)
    office_personnel: int = Field(default=0, ge=0)
    repetitive_personnel: int = Field(default=0, ge=0)
    shift_count: int = Field(default=1, ge=1)
    same_process_all_shifts: bool = True

    sites: list[AdvancedSiteInput] = Field(default_factory=list)
    multi_site_sampling_requested: bool = False
    multi_site_eligibility: MultiSiteEligibility = Field(default_factory=MultiSiteEligibility)
    mature_management_system: bool = False
    sampled_site_reduction_pct: float = Field(default=0, ge=0, le=50)
    sampled_site_reduction_justification: str = ""

    manual_ea_codes: list[str] = Field(default_factory=list)
    category_overrides: dict[str, Literal["High", "Medium", "Low", "Limited"]] = Field(
        default_factory=dict,
    )

    integration: IntegrationProfile = Field(default_factory=IntegrationProfile)
    md5_adjustment_pct: float = Field(default=0, ge=-30, le=100)
    adjustment_justification: str = ""
    increase_factors: list[str] = Field(default_factory=list)
    decrease_factors: list[str] = Field(default_factory=list)
    remote_audit_pct: float = Field(default=0, ge=0, le=20)

    food_chain_categories: list[str] = Field(default_factory=list)
    fsms_haccp_studies: int | None = Field(default=None, ge=1)
    fsms_offsite_storage_count: int = Field(default=0, ge=0)
    fsms_separate_head_office: bool = False
    fsms_fssc22000: bool = False
    annual_energy_tj: float | None = Field(default=None, ge=0)
    num_energy_types: int | None = Field(default=None, ge=0)
    num_seus: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_justifications(self):
        if self.part_time_hours_per_day > self.normal_hours_per_day:
            raise ValueError("Part-time hours cannot exceed normal daily hours.")
        if self.md5_adjustment_pct and len(self.adjustment_justification.strip()) < 10:
            raise ValueError("A documented justification is required for an MD 5 adjustment.")
        if (
            self.sampled_site_reduction_pct
            and len(self.sampled_site_reduction_justification.strip()) < 10
        ):
            raise ValueError("A justification is required for sampled-site time reduction.")
        return self


class ScopeClassificationResult(BaseModel):
    standard: str
    scope_type: str
    codes: list[str]
    code_names: list[str]
    category: str
    source: str


class AdvancedStandardResult(BaseModel):
    standard: str
    category: str
    eps: float
    central_time: float
    additional_site_time: float
    subtotal: float
    stage_1: float | None = None
    stage_2: float | None = None


class MultiSitePlanResult(BaseModel):
    sampling_requested: bool
    sampling_permitted: bool
    eligible_sites: int
    required_sample_size: int
    audited_additional_sites: int
    sampled_site_ids: list[str]
    excluded_site_ids: list[str]
    minimum_random_sites: int
    formula: str


class AdvancedCalculationResult(BaseModel):
    organization_name: str
    scope: str
    audit_type: str
    accreditation_body: str
    effective_personnel: int
    part_time_fte: float
    classifications: list[ScopeClassificationResult]
    standard_results: list[AdvancedStandardResult]
    multi_site_plan: MultiSitePlanResult
    base_time: float
    md5_adjustment_pct: float
    md5_adjustment_days: float
    after_md5_adjustment: float
    integration_level_pct: int
    combined_audit_capability_pct: int
    md11_reduction_pct: int
    md11_reduction_days: float
    final_audit_time: float
    stage_1_time: float | None
    stage_2_time: float | None
    on_site_time: float
    remote_time: float
    warnings: list[str]
    compliance_notes: list[str]


def _normalise_ea_codes(values: list[str]) -> list[int]:
    result: list[int] = []
    for value in values:
        for token in re.findall(r"\d{1,2}", str(value)):
            code = int(token)
            if code in EA_CODE_NAMES and code not in result:
                result.append(code)
    return result


def _infer_ea_codes(scope: str) -> list[int]:
    text = scope.casefold()
    scored: list[tuple[int, int]] = []
    for code, keywords in _EA_KEYWORDS.items():
        score = sum(1 for keyword in keywords if keyword in text)
        if score:
            scored.append((score, code))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [code for _, code in scored[:5]]


def _highest_category(categories: list[str], *, allow_limited: bool) -> str:
    order = {"Limited": 0, "Low": 1, "Medium": 2, "High": 3}
    if not categories:
        return "Medium"
    selected = max(categories, key=lambda value: order.get(value, 2))
    if selected == "Limited" and not allow_limited:
        return "Low"
    return selected


def _category_for_standard(standard: str, codes: list[int], scope: str) -> str:
    text = scope.casefold()
    if standard == "QMS":
        values = ["High" if c in _QMS_HIGH else "Low" if c in _QMS_LOW else "Medium" for c in codes]
        if any(word in text for word in ("nuclear", "pharmaceutical", "high-rise", "load-bearing")):
            values.append("High")
        return _highest_category(values, allow_limited=False)
    if standard == "EMS":
        values = [
            "High" if c in _EMS_HIGH else "Limited" if c in _EMS_LIMITED
            else "Low" if c in _EMS_LOW else "Medium"
            for c in codes
        ]
        if any(word in text for word in ("tanning", "hazardous waste", "wastewater", "smelting")):
            values.append("High")
        return _highest_category(values, allow_limited=True)
    if standard == "OHSMS":
        values = ["High" if c in _OHS_HIGH else "Low" if c in _OHS_LOW else "Medium" for c in codes]
        if any(word in text for word in ("tanning", "dyeing", "explosive", "major accident")):
            values.append("High")
        return _highest_category(values, allow_limited=False)
    return "Medium"


def _keyword_codes(scope: str, mapping: dict[str, tuple[str, ...]]) -> list[str]:
    text = scope.casefold()
    return [code for code, keywords in mapping.items() if any(keyword in text for keyword in keywords)]


def _classify_scope(data: AdvancedCalculationRequest) -> list[ScopeClassificationResult]:
    manual_codes = _normalise_ea_codes(data.manual_ea_codes)
    inferred_codes = _infer_ea_codes(data.scope)
    ea_codes = manual_codes or inferred_codes
    results: list[ScopeClassificationResult] = []

    for standard in data.standards:
        full_name = STANDARD_NAMES[standard]
        if standard in {"QMS", "EMS", "OHSMS"}:
            override = data.category_overrides.get(standard)
            category = override or _category_for_standard(standard, ea_codes, data.scope)
            source = "manual category override" if override else (
                "manual EA code" if manual_codes else "scope analysis"
            )
            results.append(ScopeClassificationResult(
                standard=full_name,
                scope_type="EA",
                codes=[f"EA {code}" for code in ea_codes],
                code_names=[EA_CODE_NAMES[code] for code in ea_codes],
                category=category,
                source=source,
            ))
        elif standard == "FSMS":
            codes = data.food_chain_categories or _keyword_codes(data.scope, _FOOD_KEYWORDS)
            results.append(ScopeClassificationResult(
                standard=full_name,
                scope_type="Food chain",
                codes=codes,
                code_names=codes,
                category="Scheme-specific",
                source="manual category" if data.food_chain_categories else "scope analysis",
            ))
        elif standard == "MDQMS":
            codes = _keyword_codes(data.scope, _MEDICAL_KEYWORDS)
            results.append(ScopeClassificationResult(
                standard=full_name,
                scope_type="Medical technical area",
                codes=codes,
                code_names=codes,
                category="Scheme-specific",
                source="scope analysis",
            ))
        elif standard == "ISMS":
            codes = _keyword_codes(data.scope, _ISMS_KEYWORDS)
            results.append(ScopeClassificationResult(
                standard=full_name,
                scope_type="ISMS technical area",
                codes=codes,
                code_names=codes,
                category="Scheme-specific",
                source="scope analysis",
            ))
        elif standard == "ENMS":
            results.append(ScopeClassificationResult(
                standard=full_name,
                scope_type="Energy complexity",
                codes=[],
                code_names=[],
                category="Calculated from energy data",
                source="energy inputs",
            ))
        else:
            results.append(ScopeClassificationResult(
                standard=full_name,
                scope_type="Sector",
                codes=["Private sector"],
                code_names=["Private sector"],
                category="CB methodology",
                source="scope analysis",
            ))
    return results


def _sample_plan(data: AdvancedCalculationRequest) -> tuple[MultiSitePlanResult, list[AdvancedSiteInput]]:
    eligible = [
        site for site in data.sites
        if site.site_type == "permanent" and site.sampling_eligible
    ]
    non_sampled_pool = [site for site in data.sites if site not in eligible]
    permitted = (
        data.multi_site_sampling_requested
        and data.multi_site_eligibility.satisfied
        and bool(eligible)
    )

    if permitted:
        x = len(eligible)
        if data.audit_type == "surveillance":
            sample_size = math.ceil(0.6 * math.sqrt(x))
            formula = "ceil(0.6 × √eligible sites)"
        elif data.audit_type == "recertification" and data.mature_management_system:
            sample_size = math.ceil(0.8 * math.sqrt(x))
            formula = "ceil(0.8 × √eligible sites)"
        else:
            sample_size = math.ceil(math.sqrt(x))
            formula = "ceil(√eligible sites)"
        # Conservative time estimate: use the largest sites. Actual audit
        # selection must still include the MD 1 random/selective requirements.
        selected = sorted(eligible, key=lambda site: site.employee_count, reverse=True)[:sample_size]
        excluded = [site for site in eligible if site not in selected]
    else:
        selected = eligible
        excluded = []
        sample_size = len(eligible)
        formula = "All sites audited"

    audited = non_sampled_pool + selected
    minimum_random = math.ceil(sample_size * 0.25) if permitted else 0
    return MultiSitePlanResult(
        sampling_requested=data.multi_site_sampling_requested,
        sampling_permitted=permitted,
        eligible_sites=len(eligible),
        required_sample_size=sample_size,
        audited_additional_sites=len(audited),
        sampled_site_ids=[site.id for site in selected],
        excluded_site_ids=[site.id for site in excluded],
        minimum_random_sites=minimum_random,
        formula=formula,
    ), audited


def _audit_time_for_type(result, audit_type: str) -> float:
    if audit_type == "surveillance":
        return result.base_surv
    if audit_type == "recertification":
        return result.base_recert
    return result.base_init


def _md11_bucket(value: int) -> int:
    if value < 20:
        return 20
    return min(100, int(value // 20) * 20)


def calculate_advanced(data: AdvancedCalculationRequest) -> AdvancedCalculationResult:
    unsupported = [standard for standard in data.standards if standard not in STANDARD_NAMES]
    if unsupported:
        raise ValueError(f"Unsupported standards: {', '.join(unsupported)}")

    classifications = _classify_scope(data)
    classification_by_standard = {item.standard: item for item in classifications}

    pt_fte = (
        data.part_time_personnel
        * data.part_time_hours_per_day
        / data.normal_hours_per_day
    )
    effective_personnel = math.ceil(
        data.full_time_personnel
        + pt_fte
        + data.seasonal_temporary_personnel
        + (data.subcontractors if data.subcontractors_in_scope else 0)
    )
    effective_personnel = max(1, effective_personnel)
    office = min(data.office_personnel, effective_personnel)
    repetitive = min(data.repetitive_personnel, max(0, effective_personnel - office))

    engine_classifications = [
        StandardClassification(
            standard=STANDARD_NAMES[standard],
            sector_name=", ".join(classification_by_standard[STANDARD_NAMES[standard]].code_names)
            or "Unclassified",
            category=(
                classification_by_standard[STANDARD_NAMES[standard]].category
                if standard in {"QMS", "EMS", "OHSMS"}
                else "Medium"
            ),
        )
        for standard in data.standards
    ]
    form_data = ExtractedFormData(
        org_name=data.organization_name,
        standards=[STANDARD_NAMES[standard] for standard in data.standards],
        audit_type=data.audit_type,
        scope=data.scope,
        total_employees=effective_personnel,
        office_employees=office,
        repetitive_employees=repetitive,
        classifications=engine_classifications,
        annual_energy_tj=data.annual_energy_tj,
        num_energy_types=data.num_energy_types,
        num_seus=data.num_seus,
        food_chain_categories=(
            data.food_chain_categories
            or next((
                item.codes for item in classifications if item.scope_type == "Food chain"
            ), [])
        ),
        haccp_studies=data.fsms_haccp_studies,
        fsms_offsite_storage_count=data.fsms_offsite_storage_count,
        fsms_separate_head_office=data.fsms_separate_head_office,
        fsms_fssc22000=data.fsms_fssc22000,
    )

    multi_site_plan, audited_sites = _sample_plan(data)
    standard_results: list[AdvancedStandardResult] = []
    phase_one_weight = 0.0
    total_weight = 0.0

    for standard in data.standards:
        full_name = STANDARD_NAMES[standard]
        central = _lookup_standard(form_data, full_name)
        central_time = _audit_time_for_type(central, data.audit_type)
        site_time = 0.0

        for site in audited_sites:
            if site.employee_count <= 0:
                continue
            site_data = form_data.model_copy(update={
                "total_employees": site.employee_count,
                "office_employees": site.employee_count,
                "repetitive_employees": 0,
            })
            site_result = _lookup_standard(site_data, full_name)
            site_base = _audit_time_for_type(site_result, data.audit_type)
            site_time += site_base * (1 - data.sampled_site_reduction_pct / 100)

        subtotal = central_time + site_time
        stage_1 = central.base_ph1 if data.audit_type == "initial" else (
            central.base_recert_ph1 if data.audit_type == "recertification" else None
        )
        stage_2 = central.base_ph2 if data.audit_type == "initial" else (
            central.base_recert_ph2 if data.audit_type == "recertification" else None
        )
        standard_results.append(AdvancedStandardResult(
            standard=full_name,
            category=central.category,
            eps=central.eps,
            central_time=round(central_time, 2),
            additional_site_time=round(site_time, 2),
            subtotal=round(subtotal, 2),
            stage_1=stage_1,
            stage_2=stage_2,
        ))
        if stage_1 is not None and central_time > 0:
            phase_one_weight += (stage_1 / central_time) * subtotal
        total_weight += subtotal

    base_time = round(sum(item.subtotal for item in standard_results), 2)
    md5_adjustment_days = round(base_time * data.md5_adjustment_pct / 100, 2)
    after_md5 = max(0.5, base_time + md5_adjustment_days)

    integration_level = data.integration.integration_pct if data.integration.enabled else 0
    capability = data.integration.combined_audit_capability_pct if data.integration.enabled else 0
    md11_pct = 0
    if data.integration.enabled and len(data.standards) >= 2:
        md11_pct = _MD11_MATRIX[_md11_bucket(integration_level)][_md11_bucket(capability)]
    md11_days = round(after_md5 * md11_pct / 100, 2)
    final_time = max(0.5, _round_audit(after_md5 - md11_days))

    stage_1_time: float | None = None
    stage_2_time: float | None = None
    if data.audit_type in {"initial", "recertification"} and total_weight > 0:
        ratio = min(1.0, max(0.0, phase_one_weight / total_weight))
        stage_1_time = _round_audit(final_time * ratio)
        stage_2_time = _round_audit(final_time - stage_1_time)

    remote_time = round(final_time * data.remote_audit_pct / 100, 2)
    on_site_time = round(final_time - remote_time, 2)

    warnings: list[str] = []
    if any(
        not item.codes
        for item in classifications
        if item.scope_type in {"EA", "Food chain", "Medical technical area", "ISMS technical area"}
    ):
        warnings.append(
            "One or more scope classifications could not be determined. Review and enter the applicable code manually.",
        )
    if len(_normalise_ea_codes(data.manual_ea_codes) or _infer_ea_codes(data.scope)) > 1:
        warnings.append(
            "Multiple EA sectors were identified; the highest applicable risk/complexity category was used.",
        )
    if data.multi_site_sampling_requested and not multi_site_plan.sampling_permitted:
        warnings.append(
            "MD 1 sampling was requested but the eligibility conditions were not all confirmed, so every site was included.",
        )
    if multi_site_plan.sampling_permitted:
        warnings.append(
            "The named sample is a conservative time estimate. The final sample must be partly selective and at least 25% random.",
        )
    if data.shift_count > 1:
        warnings.append(
            "Shift coverage must be planned and justified separately; the calculator does not automatically reduce time for similar shifts.",
        )
    if data.md5_adjustment_pct and not (data.increase_factors or data.decrease_factors):
        warnings.append(
            "An adjustment percentage was entered without selecting the factors that support it.",
        )
    if "ABMS" in data.standards:
        warnings.append(
            "ISO 37001 has no dedicated IAF MD 5 table here; the result uses the documented CB ISO 9001-medium proxy and requires approval.",
        )

    return AdvancedCalculationResult(
        organization_name=data.organization_name,
        scope=data.scope,
        audit_type=data.audit_type,
        accreditation_body=data.accreditation_body,
        effective_personnel=effective_personnel,
        part_time_fte=round(pt_fte, 2),
        classifications=classifications,
        standard_results=standard_results,
        multi_site_plan=multi_site_plan,
        base_time=base_time,
        md5_adjustment_pct=data.md5_adjustment_pct,
        md5_adjustment_days=md5_adjustment_days,
        after_md5_adjustment=round(after_md5, 2),
        integration_level_pct=integration_level,
        combined_audit_capability_pct=capability,
        md11_reduction_pct=md11_pct,
        md11_reduction_days=md11_days,
        final_audit_time=final_time,
        stage_1_time=stage_1_time,
        stage_2_time=stage_2_time,
        on_site_time=on_site_time,
        remote_time=remote_time,
        warnings=warnings,
        compliance_notes=[
            "IAF MD 5: effective personnel, risk/complexity, shifts, temporary sites and documented adjustments considered.",
            "IAF MD 1: sampling is conditional, formula-based, and central-function/site requirements remain mandatory.",
            "IAF MD 11: each standard is calculated separately before a matrix-based integration reduction capped at 20%.",
            "No automatic reporting deduction is applied. Any reduction must be supported by a recorded factor and justification.",
        ],
    )
