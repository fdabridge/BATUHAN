"""
BATUHAN — Auditor Profile: Pydantic v2 schemas.
"""
from __future__ import annotations
from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel, ConfigDict


# ── Nested child schemas ───────────────────────────────────────

class EducationItem(BaseModel):
    degree: Optional[str] = None
    institution: Optional[str] = None
    year: Optional[str] = None

class LanguageItem(BaseModel):
    language: Optional[str] = None
    level: Optional[str] = None     # Native, C1, B2 …

class StandardQualificationItem(BaseModel):
    standard_code: Optional[str] = None
    technical_depth: Optional[str] = None   # Lead Auditor, Team Auditor …
    experience_years: Optional[int] = None
    is_qualified: Optional[bool] = True
    last_training_date: Optional[str] = None  # "YYYY-MM-DD"
    last_verified_date: Optional[str] = None  # "YYYY-MM-DD" — TURKAK annual check

class WorkExperienceItem(BaseModel):
    employer: Optional[str] = None
    position: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    description: Optional[str] = None

class TrainingRecordItem(BaseModel):
    training_date: Optional[str] = None
    institution: Optional[str] = None
    subject: Optional[str] = None
    duration_days: Optional[int] = None
    standard_code: Optional[str] = None
    certificate_available: Optional[bool] = False

class AuditLogItem(BaseModel):
    audit_date: Optional[str] = None
    client_name: Optional[str] = None
    standard_code: Optional[str] = None
    role: Optional[str] = None      # Lead Auditor / Team Auditor / Witness
    notes: Optional[str] = None


# ── Create / Update ────────────────────────────────────────────

class AuditorCreateSchema(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    role: Optional[str] = None
    field_of_expertise: Optional[str] = None
    ea_codes: Optional[list[str]] = None
    accreditation_bodies: Optional[list[str]] = None

    education: list[EducationItem] = []
    languages: list[LanguageItem] = []
    standard_qualifications: list[StandardQualificationItem] = []
    work_experience: list[WorkExperienceItem] = []
    training_records: list[TrainingRecordItem] = []
    audit_log: list[AuditLogItem] = []


# ── Witness audit records ──────────────────────────────────────

class WitnessRecordItem(BaseModel):
    id: Optional[int] = None
    witness_date: str
    client_name: Optional[str] = None
    standard_code: Optional[str] = None
    ea_code: Optional[str] = None
    role_witnessed: Optional[str] = None
    observer_name: Optional[str] = None
    outcome: Optional[str] = None   # "Satisfactory" | "Needs Improvement" | "Unsatisfactory"
    notes: Optional[str] = None

class WitnessRecordCreateSchema(BaseModel):
    witness_date: str
    client_name: Optional[str] = None
    standard_code: Optional[str] = None
    ea_code: Optional[str] = None
    role_witnessed: Optional[str] = None
    observer_name: Optional[str] = None
    outcome: Optional[str] = None
    notes: Optional[str] = None

class WitnessStatusSchema(BaseModel):
    """Computed witness compliance status for one auditor."""
    auditor_id: str
    auditor_name: str
    last_witness_date: Optional[str]
    days_since_last_witness: Optional[int]
    witness_overdue: bool
    new_auditor_unwitnessed: bool
    total_witness_count: int
    records: list[WitnessRecordItem]


# ── Full response ──────────────────────────────────────────────

class AuditorResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    role: Optional[str] = None
    field_of_expertise: Optional[str] = None
    ea_codes: Optional[list[str]] = None
    accreditation_bodies: Optional[list[str]] = None
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    education: list[EducationItem] = []
    languages: list[LanguageItem] = []
    standard_qualifications: list[StandardQualificationItem] = []
    work_experience: list[WorkExperienceItem] = []
    training_records: list[TrainingRecordItem] = []
    audit_log: list[AuditLogItem] = []
    witness_records: list[WitnessRecordItem] = []


# ── Eligibility ───────────────────────────────────────────────

class EligibilityCheckSchema(BaseModel):
    standard_code: str
    company_ea_code: str
    accreditation_body: str
    role: str   # "lead_auditor" | "team_auditor" | "technical_expert"

class EligibilityResultSchema(BaseModel):
    eligible: bool
    blocking_reasons: list[str]
    warnings: list[str]


# ── Dashboard ──────────────────────────────────────────────────

class QualificationSummary(BaseModel):
    standard_code: str
    is_qualified: bool
    technical_depth: str | None
    experience_years: int | None
    last_training_date: date | None
    last_verified_date: date | None
    training_expiry_warning: bool   # True if last_training_date older than 3 years
    verification_warning: bool      # True if last_verified_date older than 1 year


class AuditorDashboardEntry(BaseModel):
    auditor_id: str
    name: str
    email: str | None
    role: str | None
    is_active: bool
    ea_codes: list[str]
    accreditation_bodies: list[str]
    qualifications: list[QualificationSummary]
    total_audits: int
    last_audit_date: date | None
    days_since_last_audit: int | None

    class Config:
        from_attributes = True


# ── Summary (list endpoint) ────────────────────────────────────

class AuditorSummarySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    email: Optional[str] = None
    role: Optional[str] = None
    field_of_expertise: Optional[str] = None
    ea_codes: Optional[list[str]] = None
    accreditation_bodies: Optional[list[str]] = None
    is_active: bool
    created_at: Optional[datetime] = None
