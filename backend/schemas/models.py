"""
BATUHAN — Core Data Contracts (T3)
All Pydantic schemas for the full pipeline.
"""

from __future__ import annotations
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
from datetime import datetime


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class ISOStandard(str, Enum):
    QMS = "QMS"
    EMS = "EMS"
    OHSMS = "OHSMS"
    FSMS = "FSMS"
    MDQMS = "MDQMS"
    ISMS = "ISMS"
    ABMS = "ABMS"
    ENMS = "ENMS"


class AuditStage(str, Enum):
    STAGE_1 = "Stage 1"
    STAGE_2 = "Stage 2"


class JobState(str, Enum):
    QUEUED = "QUEUED"
    PREPROCESSING = "PREPROCESSING"
    STEP_A = "STEP_A"
    STEP_B = "STEP_B"
    STEP_C = "STEP_C"
    ASSEMBLING = "ASSEMBLING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


# ---------------------------------------------------------------------------
# Upload & Job
# ---------------------------------------------------------------------------

class UploadBundle(BaseModel):
    """Everything submitted by the user to start a job."""
    job_id: str
    standards: list[ISOStandard]   # One or more — integrated audit when len > 1
    stage: AuditStage
    company_document_paths: list[str] = Field(
        description="Paths to uploaded company documents"
    )
    sample_report_paths: list[str] = Field(
        description="Paths to uploaded sample reports (style reference only)"
    )
    template_path: str = Field(
        description="Path to the blank .docx report template"
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)


class JobStatus(BaseModel):
    """Tracks the current state of a processing job."""
    job_id: str
    state: JobState
    current_step: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    step_timestamps: dict[str, datetime] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Parsed Inputs
# ---------------------------------------------------------------------------

class ParsedDocument(BaseModel):
    """A single parsed company document."""
    filename: str
    text: str
    is_ocr_sourced: bool = False
    char_count: int = 0


class TemplateSection(BaseModel):
    """One section from the blank report template."""
    title: str
    original_placeholder: Optional[str] = None
    order_index: int


class TemplateMap(BaseModel):
    """Full ordered section map from the blank template."""
    sections: list[TemplateSection]
    source_path: str


class StyleGuidance(BaseModel):
    """Style/tone/structure extracted from sample reports (no content)."""
    tone_notes: list[str] = Field(default_factory=list)
    structure_notes: list[str] = Field(default_factory=list)
    section_logic_notes: list[str] = Field(default_factory=list)
    blocked_company_names: list[str] = Field(default_factory=list)
    blocked_phrases: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Step A — Evidence Extraction Output
# ---------------------------------------------------------------------------

class EvidenceItem(BaseModel):
    """A single extracted evidence fact."""
    statement: str
    source_filename: Optional[str] = None
    is_weak: bool = False  # True if marked 'Not clearly evidenced'


class ExtractedEvidence(BaseModel):
    """Full structured output of Prompt A."""
    job_id: str
    company_overview: list[EvidenceItem] = Field(default_factory=list)
    scope_of_activities: list[EvidenceItem] = Field(default_factory=list)
    documented_information: list[EvidenceItem] = Field(default_factory=list)
    key_processes_and_functions: list[EvidenceItem] = Field(default_factory=list)
    evidence_of_system_implementation: list[EvidenceItem] = Field(default_factory=list)
    audit_relevant_records: list[EvidenceItem] = Field(default_factory=list)
    identified_gaps: list[EvidenceItem] = Field(default_factory=list)
    raw_output: str = Field(description="Raw Claude response for audit trail")
    extracted_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Step B — Report Generation Output
# ---------------------------------------------------------------------------

class ReportSection(BaseModel):
    """Generated content for one report section."""
    title: str
    content: str
    order_index: int
    has_weak_evidence: bool = False


class GeneratedReport(BaseModel):
    """Full structured output of Prompt B."""
    job_id: str
    standards: list[ISOStandard]   # One or more selected standards
    stage: AuditStage
    sections: list[ReportSection]
    raw_output: str = Field(description="Raw Claude response for audit trail")
    generated_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Step C — Validation & Correction Output
# ---------------------------------------------------------------------------

class CorrectionEntry(BaseModel):
    """A single correction made by Prompt C."""
    section_title: Optional[str] = None
    description: str


class CorrectionLog(BaseModel):
    """Full list of corrections made during Prompt C."""
    job_id: str
    corrections: list[CorrectionEntry] = Field(default_factory=list)
    correction_count: int = 0
    validated_at: datetime = Field(default_factory=datetime.utcnow)


class ValidatedReport(BaseModel):
    """Final corrected report output from Prompt C."""
    job_id: str
    sections: list[ReportSection]
    correction_log: CorrectionLog
    raw_output: str = Field(description="Raw Claude response for audit trail")
    validated_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Final Delivery
# ---------------------------------------------------------------------------

class JobResult(BaseModel):
    """Final deliverables for a completed job."""
    job_id: str
    final_docx_path: str
    correction_log_path: str
    standards: list[ISOStandard]   # One or more selected standards
    stage: AuditStage
    files_used: list[str]
    correction_count: int
    completed_at: datetime = Field(default_factory=datetime.utcnow)

