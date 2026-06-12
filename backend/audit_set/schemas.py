"""
BATUHAN — Audit Set: Pydantic v2 schemas.
Input schemas (API receives) and output schemas (API returns).
"""
from __future__ import annotations
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel


# ── Nested input types ─────────────────────────────────────────────────────

class RepetitiveRole(BaseModel):
    activity: str
    employee_count: int


class PersonnelData(BaseModel):
    full_time: int = 0
    part_time: int = 0
    subcontractors: int = 0
    seasonal: int = 0
    unskilled: int = 0
    shift_count: int = 1
    shift_same_process: bool = False
    shift_1_count: int = 0
    shift_2_count: int = 0
    shift_3_count: int = 0
    repetitive_roles: list[RepetitiveRole] = []


class SiteData(BaseModel):
    address: str
    process: str = ""
    employee_count: int = 0
    energy_tj: Optional[float] = None
    energy_types: Optional[int] = None
    seu_count: Optional[int] = None


class IntegrationLevel(BaseModel):
    document_management: bool = False
    management_review: bool = False
    internal_audit: bool = False
    policy_objectives: bool = False
    process_approach: bool = False
    improvement_mechanism: bool = False
    management_support: bool = False
    risk_based_thinking: bool = False


class AuditorAssignment(BaseModel):
    id: Optional[str] = None
    name: str
    ea_code: Optional[str] = None
    standard: Optional[str] = None


class StageInput(BaseModel):
    stage_type: str        # "stage_1" | "stage_2" | "surveillance"
    stage_order: int
    notification_date: Optional[date] = None
    audit_date_start: Optional[date] = None
    audit_date_end: Optional[date] = None
    lead_auditor_id: Optional[str] = None
    lead_auditor_name: Optional[str] = None
    auditors: list[AuditorAssignment] = []
    technical_experts: list[AuditorAssignment] = []
    observers: list[AuditorAssignment] = []
    ik_experts: list[AuditorAssignment] = []
    evaluators: list[AuditorAssignment] = []
    audit_days: Optional[float] = None
    status: str = "pending"


class ApplicationDataSchema(BaseModel):
    """Standard-specific inputs collected at application time.
    Stored as JSON in audit_sets.application_data.
    """
    # ISO 50001 — EnMS energy profile (used for K-factor → complexity level)
    enms_annual_energy_tj: Optional[float] = None       # annual energy consumption in TJ
    enms_num_energy_types: Optional[int] = None         # number of distinct energy sources
    enms_num_seus: Optional[int] = None                 # number of Significant Energy Uses

    # ISO 22000 / FSSC 22000 — FSMS
    fsms_food_chain_categories: list[str] = []          # e.g. ["CI", "CIV"] per ISO 22003-1:2022
    fsms_haccp_studies: Optional[int] = None            # number of HACCP / food safety studies
    fsms_offsite_storage_count: int = 0                 # off-site storage facilities in scope
    fsms_separate_head_office: bool = False             # head office separate from production site
    fsms_fssc22000: bool = False                        # FSSC 22000 add-on scheme requested
    fsms_seasonal_production: bool = False              # seasonal production / seasonal workforce

    # ISO 27001 — ISMS
    isms_technical_area: Optional[str] = None           # "A" | "B" | "C" | "D" per ISO 27006-1
    isms_data_role: Optional[str] = None                # "Controller" | "Processor" | "Both"
    isms_it_complexity: Optional[str] = None            # "Low" | "Medium" | "High"
    isms_business_complexity: Optional[str] = None      # "Low" | "Medium" | "High"

    # ISO 13485 — MDQMS
    mdqms_device_classes: list[str] = []                # e.g. ["Class I", "Class IIa", "Class IIb"]
    mdqms_regulatory_territories: list[str] = []        # e.g. ["EU MDR 2017/745", "FDA 21 CFR 820"]

    # Personnel — IAF MD5 FTE conversion
    part_time_fte_factor: float = 0.5                   # fraction to multiply part-time count (default 0.5)
    subcontractors_in_scope: bool = True                # whether subcontractors are counted in EPS


# ── Create / Update input schemas ──────────────────────────────────────────

class AuditSetCreateSchema(BaseModel):
    company_name: str
    client_reference: Optional[str] = None   # user-supplied agreement/quotation number
    company_address: str = ""
    country: str = ""
    city: str = ""
    phone: str = ""
    email: str = ""
    website: str = ""
    representative: str = ""
    standards: list[str]           # e.g. ["QMS", "EMS", "OHSMS"]
    audit_type: str                # "initial" | "surveillance" | "recertification"
    cycle_number: int = 1
    accreditation_body: str = "UAF"
    scope_tr: str = ""
    scope_en: str = ""
    non_applicable_clauses: str = ""
    personnel: PersonnelData = PersonnelData()
    sites: list[SiteData] = []
    integration_level: IntegrationLevel = IntegrationLevel()
    certification_fee: Optional[float] = None
    surveillance_fee: Optional[float] = None
    ea_code: Optional[str] = None
    ea_category: Optional[str] = None
    ea_technical_area: Optional[str] = None
    audit_language: Optional[str] = None
    document_language: Optional[str] = "turkish"
    application_data: Optional[ApplicationDataSchema] = None   # ← ADD


class AuditSetUpdatePlanningSchema(BaseModel):
    ea_code: Optional[str] = None
    ea_category: Optional[str] = None
    ea_technical_area: Optional[str] = None
    representative: Optional[str] = None
    non_applicable_clauses: Optional[str] = None
    client_reference: Optional[str] = None
    certification_fee: Optional[float] = None
    surveillance_fee: Optional[float] = None
    required_scope: Optional[dict] = None           # persisted from derive-scope
    scope_integration_level: Optional[str] = None  # "Low" | "Medium" | "High"
    audit_language: Optional[str] = None
    document_language: Optional[str] = None
    application_date: Optional[date] = None          # retroactive override — when the client actually applied
    application_data: Optional[ApplicationDataSchema] = None   # ← ADD
    stages: list[StageInput] = []


class QuickCalcSchema(BaseModel):
    """Payload for POST /{id}/quick-calculate.
    Allows manually-created clients to (re)run the IAF MD 5 calculator
    with updated personnel / integration data without a full form re-upload.
    If personnel is all zeros, the service will use the existing stored personnel.
    """
    personnel: PersonnelData = PersonnelData()
    integration_level: IntegrationLevel = IntegrationLevel()
    ea_code: Optional[str] = None
    ea_category: Optional[str] = None
    scope_integration_level: Optional[str] = None   # "Low" | "Medium" | "High"


# ── Output schemas ─────────────────────────────────────────────────────────

class StageResponse(BaseModel):
    id: str
    stage_type: str
    stage_order: int
    notification_date: Optional[date]
    audit_date_start: Optional[date]
    audit_date_end: Optional[date]
    lead_auditor_id: Optional[str] = None
    lead_auditor_name: Optional[str]
    auditors: Optional[list]
    technical_experts: Optional[list]
    observers: Optional[list]
    audit_days: Optional[float]
    status: str

    class Config:
        from_attributes = True


class AuditSetResponse(BaseModel):
    id: str
    plan_number: int
    client_reference: Optional[str] = None
    status: str
    company_name: str
    company_address: Optional[str]
    standards: Optional[list]
    audit_type: str
    cycle_number: int
    accreditation_body: Optional[str]
    scope_tr: Optional[str]
    scope_en: Optional[str]
    effective_employees: Optional[int]
    man_day_result: Optional[dict]
    ea_code: Optional[str]
    ea_category: Optional[str]
    non_applicable_clauses: Optional[str] = None
    certification_fee: Optional[float]
    surveillance_fee: Optional[float]
    required_scope: Optional[dict] = None            # per-standard derived scope codes
    scope_integration_level: Optional[str] = None   # "Low" | "Medium" | "High"
    personnel: Optional[dict] = None                # {full_time, part_time, subcontractors, seasonal, unskilled}
    application_data: Optional[dict] = None          # standard-specific inputs (JSON column returns dict, not model)
    audit_language: Optional[str] = None
    document_language: Optional[str] = None
    workflow_status: Optional[str] = None
    submitted_via_portal: bool = False
    application_date: Optional[date] = None          # retroactive override
    stages: list[StageResponse]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AuditSetSummarySchema(BaseModel):
    id: str
    plan_number: int
    client_reference: Optional[str] = None
    company_name: str
    standards: Optional[list]
    audit_type: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


# ── Certificate & Dashboard schemas ────────────────────────────────────────

class AuditSetCertUpdateSchema(BaseModel):
    cert_issued_date: date | None = None
    cert_expiry_date: date | None = None


class NACGenerationResponse(BaseModel):
    """Result of POST /audit-sets/{id}/generate-nac — suggestions only, not saved."""
    non_applicable_clauses: str
    suggestions: list[dict]


class DashboardStatsSchema(BaseModel):
    total_plans: int
    active_certificates: int
    approaching_expiry: int     # expiry within 90 days, not yet expired
    expired: int
    open_jobs: int              # pipeline jobs not yet COMPLETE or FAILED
    pending_reviews: int        # review jobs not yet COMPLETE or FAILED


class ClientSummarySchema(BaseModel):
    id: str
    plan_number: int
    client_reference: str | None = None
    company_name: str
    company_address: str
    standards: list[str]
    audit_type: str
    status: str
    cert_issued_date: date | None
    cert_expiry_date: date | None
    cert_status: str | None
    stage_1_date: date | None       # audit_date_start of stage_type == "stage_1"
    stage_2_date: date | None       # audit_date_start of stage_type == "stage_2"
    lead_auditor_name: str | None   # stage_2 preferred, then stage_1
    created_at: datetime

    class Config:
        from_attributes = True
