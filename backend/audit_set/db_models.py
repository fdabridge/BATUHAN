"""
BATUHAN — Audit Set: SQLAlchemy ORM models.
Tables: audit_sets, audit_set_stages

plan_number is an application-managed sequential integer.
The service layer computes it as:
    COALESCE(MAX(plan_number), 1599) + 1
so the first row ever inserted gets plan_number = 1600,
matching the existing numbering series (1652, 1653 …).

audit_set_stages.lead_auditor_id is a *soft* FK to auditors.auditors.id —
it is stored as a plain String because both tables live in different
SQLite files (audit_sets.db vs auditors.db).  No DB-level constraint is
created; validation happens in the service layer.
"""
from __future__ import annotations
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Float,
    ForeignKey, Integer, String, Text, JSON,
    create_engine,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from config.settings import get_settings

_settings = get_settings()
_connect_args = {"check_same_thread": False} if _settings.database_url.startswith("sqlite") else {}
Base = declarative_base()
engine = create_engine(_settings.database_url, connect_args=_connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _safe_add_column(table: str, col_def: str) -> None:
    """Add a column if it doesn't already exist (Postgres + SQLite safe)."""
    import sqlalchemy as sa
    with engine.connect() as conn:
        try:
            conn.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN {col_def}"))
            conn.commit()
        except Exception:
            pass  # column already exists


def create_tables():
    Base.metadata.create_all(bind=engine)
    # Safe migrations — add columns introduced after initial deployment
    _safe_add_column("audit_sets", "required_scope JSON")
    _safe_add_column("audit_sets", "scope_integration_level VARCHAR")
    _safe_add_column("audit_sets", "audit_language VARCHAR")
    _safe_add_column("audit_sets", "document_language VARCHAR DEFAULT 'turkish'")
    _safe_add_column("audit_sets", "client_reference VARCHAR")
    # Client portal additions
    _safe_add_column("audit_sets", "workflow_status VARCHAR")
    _safe_add_column("audit_sets", "submitted_via_portal BOOLEAN DEFAULT 0")


# ---------------------------------------------------------------------------
# Table 1 — audit_sets
# ---------------------------------------------------------------------------

class AuditSet(Base):
    __tablename__ = "audit_sets"

    id           = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    plan_number  = Column(Integer, unique=True, nullable=False)   # app-managed, starts at 1600
    client_reference = Column(String, nullable=True, index=True)   # user-supplied client/agreement code
    status       = Column(String, default="draft", nullable=False)  # "draft"|"planning"|"complete"

    # ── Company info ──────────────────────────────────────────────────────────
    company_name    = Column(String)
    company_address = Column(String)
    country         = Column(String)
    city            = Column(String)
    phone           = Column(String)
    email           = Column(String)
    website         = Column(String)
    representative  = Column(String)     # contact person name

    # ── Audit config ──────────────────────────────────────────────────────────
    standards          = Column(JSON)    # ["QMS", "EMS", "OHSMS"]
    audit_type         = Column(String)  # "initial"|"surveillance"|"recertification"
    cycle_number       = Column(Integer, default=1)
    accreditation_body = Column(String)  # "UAF"|"TURKAK"

    # ── Scope ─────────────────────────────────────────────────────────────────
    scope_tr               = Column(Text)
    scope_en               = Column(Text)
    non_applicable_clauses = Column(Text)

    # ── Personnel (from FR.217 application form) ───────────────────────────────
    # JSON keys: full_time, part_time, subcontractors, seasonal, unskilled,
    #            shift_count, shift_same_process (bool),
    #            shift_1_count, shift_2_count, shift_3_count,
    #            repetitive_roles: [{activity, employee_count}]
    personnel = Column(JSON)

    # ── Sites ─────────────────────────────────────────────────────────────────
    # JSON list of {address, process, employee_count,
    #               energy_tj, energy_types, seu_count}
    sites = Column(JSON)

    # ── Integration level (8 boolean fields from FR.217 page 3) ──────────────
    # JSON keys: document_management, management_review, internal_audit,
    #            policy_objectives, process_approach, improvement_mechanism,
    #            management_support, risk_based_thinking
    integration_level = Column(JSON)

    # ── Calculated outputs (populated after calculate() runs) ─────────────────
    effective_employees = Column(Integer,  nullable=True)
    risk_category       = Column(String,   nullable=True)  # "HIGH"|"MEDIUM"|"LOW"
    man_day_result      = Column(JSON,     nullable=True)  # full CalculationResult dict

    # ── Fees ──────────────────────────────────────────────────────────────────
    certification_fee  = Column(Float, nullable=True)
    surveillance_fee   = Column(Float, nullable=True)

    # ── Derived required scope (from derive-scope endpoint) ──────────────────
    # JSON dict: {"ISO 22000": {"type": "food", "codes": ["CI", "CIV"]}, ...}
    required_scope            = Column(JSON,   nullable=True)
    # IAF MD 11 integration reduction level: "Low" | "Medium" | "High"
    scope_integration_level   = Column(String, nullable=True)

    # ── EA classification ─────────────────────────────────────────────────────
    ea_code          = Column(String, nullable=True)
    ea_category      = Column(String, nullable=True)
    ea_technical_area= Column(String, nullable=True)

    # ── Languages ─────────────────────────────────────────────────────────────
    # audit_language: spoken language of the audit (defaulted from country).
    # document_language: report language, only meaningful for TURKAK ("turkish"|"english").
    audit_language    = Column(String, nullable=True)
    document_language = Column(String, default="turkish")

    # ── Certificate ───────────────────────────────────────────────────────────
    cert_issued_date = Column(Date, nullable=True)
    cert_expiry_date = Column(Date, nullable=True)   # typically 3 years from issued date
    cert_status      = Column(String, nullable=True)
    # cert_status values: "active" | "approaching_expiry" | "expired" | "suspended"

    # ── Client portal workflow ────────────────────────────────────────────────
    # workflow_status tracks the certification lifecycle for the client portal.
    # Separate from `status` (internal planning status: draft/planning/complete).
    # Valid values:
    #   pending_review    → client submitted application, CB reviewing
    #   in_planning       → CB approved, doing man-days/auditor assignment
    #   quotation_sent    → FR.220 released to client portal
    #   agreement_signed  → FR.220 + FR.221 both signed by client
    #   audit_scheduled   → audit dates confirmed by both sides
    #   audit_in_progress → audit underway
    #   under_review      → auditor uploaded docs, CB technical review
    #   certified         → certificate issued
    # NULL = audit set created internally (not via client portal) — existing rows
    workflow_status      = Column(String, nullable=True)
    submitted_via_portal = Column(Boolean, default=False, nullable=False, server_default="0")

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # ── Relationships ─────────────────────────────────────────────────────────
    stages = relationship(
        "AuditSetStage",
        back_populates="audit_set",
        cascade="all, delete-orphan",
        order_by="AuditSetStage.stage_order",
    )

    def compute_cert_status(self) -> str | None:
        """Compute the current certificate status from cert_expiry_date. Does not save."""
        if not self.cert_expiry_date:
            return None
        today = date.today()
        if self.cert_expiry_date < today:
            return "expired"
        if (self.cert_expiry_date - today).days <= 90:
            return "approaching_expiry"
        return "active"


# ---------------------------------------------------------------------------
# Table 2 — audit_set_stages
# ---------------------------------------------------------------------------

class AuditSetStage(Base):
    __tablename__ = "audit_set_stages"

    id           = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    audit_set_id = Column(String, ForeignKey("audit_sets.id", ondelete="CASCADE"), nullable=False)
    stage_type   = Column(String, nullable=False)  # "stage_1"|"stage_2"|"surveillance"
    stage_order  = Column(Integer, nullable=False)  # 1 or 2 for initial; 1 for surveillance

    # ── Dates ─────────────────────────────────────────────────────────────────
    notification_date = Column(Date, nullable=True)
    audit_date_start  = Column(Date, nullable=True)
    audit_date_end    = Column(Date, nullable=True)

    # ── Auditor assignments (soft references to auditors.auditors) ─────────────
    lead_auditor_id   = Column(String, nullable=True)   # soft FK → auditors.id
    lead_auditor_name = Column(String, nullable=True)   # denormalized for display

    # JSON list of {id, name, ea_code, standard}
    auditors         = Column(JSON, nullable=True)
    technical_experts= Column(JSON, nullable=True)
    observers        = Column(JSON, nullable=True)
    ik_experts       = Column(JSON, nullable=True)
    evaluators       = Column(JSON, nullable=True)

    # ── Audit duration for this stage ─────────────────────────────────────────
    audit_days = Column(Float, nullable=True)

    # ── Status ────────────────────────────────────────────────────────────────
    status = Column(String, default="pending", nullable=False)  # "pending"|"confirmed"|"complete"

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # ── Relationships ─────────────────────────────────────────────────────────
    audit_set = relationship("AuditSet", back_populates="stages")


# ---------------------------------------------------------------------------
# Table 3 — audit_set_status_events
# Log of every workflow_status transition (ISO 17021-1 §9.5 traceability).
# ---------------------------------------------------------------------------

class AuditSetStatusEvent(Base):
    __tablename__ = "audit_set_status_events"

    id             = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    audit_set_id   = Column(String, ForeignKey("audit_sets.id", ondelete="CASCADE"), nullable=False)
    from_status    = Column(String, nullable=True)   # null for initial creation event
    to_status      = Column(String, nullable=False)
    triggered_by   = Column(String, nullable=True)   # user id or "system"
    triggered_at   = Column(DateTime, default=datetime.utcnow, nullable=False)
    notes          = Column(Text, nullable=True)


# ---------------------------------------------------------------------------
# Table 4 — audit_set_messages
# Threaded message log per audit set (ISO 17021-1 §8.4 communication record).
# ---------------------------------------------------------------------------

class AuditSetMessage(Base):
    __tablename__ = "audit_set_messages"

    id             = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    audit_set_id   = Column(String, ForeignKey("audit_sets.id", ondelete="CASCADE"), nullable=False)
    sender_user_id = Column(String, nullable=False)
    sender_name    = Column(String, nullable=False)
    sender_role    = Column(String, nullable=False)   # "client" | "planner" | "auditor" | …
    body           = Column(Text, nullable=False)
    attachment_url = Column(String, nullable=True)    # optional file link
    created_at     = Column(DateTime, default=datetime.utcnow, nullable=False)
    read_by        = Column(JSON, default=list)       # list of user ids who have read this


# ---------------------------------------------------------------------------
# Table 5 — audit_set_shared_documents
# Documents released by CB to the client portal, or uploaded by an auditor.
# OTP signing fields support the in-house e-signature flow (no DocuSign).
# ---------------------------------------------------------------------------

class AuditSetSharedDocument(Base):
    __tablename__ = "audit_set_shared_documents"

    id             = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    audit_set_id   = Column(String, ForeignKey("audit_sets.id", ondelete="CASCADE"), nullable=False)
    label          = Column(String, nullable=False)   # e.g. "Quotation (FR.220)"
    document_type  = Column(String, nullable=False)
    # document_type: "quotation" | "agreement" | "audit_upload" | "certificate"
    file_path      = Column(String, nullable=True)    # server-side path (CB-generated)
    direction      = Column(String, nullable=False, default="cb_to_client")
    # direction: "cb_to_client" | "auditor_to_cb"
    status         = Column(String, nullable=False, default="released")
    # status: "released" | "signed" | "uploaded"
    released_by    = Column(String, nullable=True)    # user id
    released_at    = Column(DateTime, nullable=True)
    signed_by      = Column(String, nullable=True)    # user id (client)
    signed_at      = Column(DateTime, nullable=True)
    signed_ip      = Column(String, nullable=True)
    otp_hash       = Column(String, nullable=True)    # bcrypt hash of OTP
    otp_expires_at = Column(DateTime, nullable=True)
    created_at     = Column(DateTime, default=datetime.utcnow, nullable=False)


# ---------------------------------------------------------------------------
# Table 6 — audit_document_signatures
# Multi-party signature tracking for all document types.
# CB planner signs FR.220/FR.221; future prompts add committee, auditor, guest.
# ---------------------------------------------------------------------------

class AuditDocumentSignature(Base):
    __tablename__ = "audit_document_signatures"

    id               = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    audit_set_id     = Column(String, ForeignKey("audit_sets.id", ondelete="CASCADE"), nullable=False)
    document_id      = Column(String, nullable=True)   # soft FK → audit_set_shared_documents.id
    document_type    = Column(String, nullable=False)   # "quotation" | "agreement" | "FR218" | etc.
    signer_role_label= Column(String, nullable=False)   # "cb_planner" | "cb_cert_manager" | "lead_auditor" | "guest"
    signer_user_id   = Column(String, nullable=True)    # PlatformUser.id; null for guests
    signer_name      = Column(String, nullable=True)    # denormalized
    signer_email     = Column(String, nullable=True)    # for OTP delivery
    required         = Column(Boolean, default=True, nullable=False)
    order_index      = Column(Integer, default=0, nullable=False)
    signed_at        = Column(DateTime, nullable=True)
    signed_ip        = Column(String, nullable=True)
    otp_hash         = Column(String, nullable=True)
    otp_expires_at   = Column(DateTime, nullable=True)
    signing_token    = Column(String, nullable=True)    # for future guest token links
    token_expires_at = Column(DateTime, nullable=True)
    created_at       = Column(DateTime, default=datetime.utcnow, nullable=False)



# ---------------------------------------------------------------------------
# Table 7 — audit_set_committee_members
# Certification committee appointments for ISO 17021-1 review and decision.
# ---------------------------------------------------------------------------

class AuditSetCommitteeMember(Base):
    __tablename__ = "audit_set_committee_members"

    id                      = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    audit_set_id            = Column(String, ForeignKey("audit_sets.id", ondelete="CASCADE"), nullable=False)
    user_id                 = Column(String, nullable=False)   # PlatformUser.id
    user_name               = Column(String, nullable=False)   # denormalized for display
    user_email              = Column(String, nullable=False)   # denormalized for email
    role                    = Column(String, nullable=False)   # "reviewer" | "decision_maker"
    appointed_by            = Column(String, nullable=True)    # PlatformUser.id of the appointing user
    ea_codes_at_appointment = Column(JSON, nullable=True)      # snapshot of EA codes at time of appointment
    appointed_at            = Column(DateTime, default=datetime.utcnow, nullable=False)



# ---------------------------------------------------------------------------
# Table 8 — audit_set_meeting_attendees
# External organization personnel who sign FR.225 opening and closing meetings.
# No Certiva account — signed via tokenized email links.
# ---------------------------------------------------------------------------

class AuditSetMeetingAttendee(Base):
    __tablename__ = "audit_set_meeting_attendees"

    id               = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    audit_set_id     = Column(String, ForeignKey("audit_sets.id", ondelete="CASCADE"), nullable=False)
    stage_type       = Column(String, nullable=False)  # "stage_1" | "stage_2" | "surveillance" | "recertification"
    full_name        = Column(String, nullable=False)
    title            = Column(String, nullable=True)   # e.g. "General Manager", "Quality Engineer"
    email            = Column(String, nullable=False)
    # Token for the signing link — UUID, hard to guess
    token            = Column(String, unique=True, nullable=False,
                              default=lambda: str(uuid.uuid4()))
    token_expires_at = Column(DateTime, nullable=True)  # 72h from creation
    # Opening meeting
    opening_otp_hash    = Column(String, nullable=True)
    opening_otp_expires = Column(DateTime, nullable=True)
    opening_signed_at   = Column(DateTime, nullable=True)
    opening_signed_ip   = Column(String, nullable=True)
    # Closing meeting
    closing_otp_hash    = Column(String, nullable=True)
    closing_otp_expires = Column(DateTime, nullable=True)
    closing_signed_at   = Column(DateTime, nullable=True)
    closing_signed_ip   = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


# ---------------------------------------------------------------------------
# Table 10 — audit_set_nc_forms
# FR.230 — Nonconformity Notification Form.
# Two-party signing: Lead Auditor signs first, then client counter-signs.
# ---------------------------------------------------------------------------

class AuditSetNCForm(Base):
    __tablename__ = "audit_set_nc_forms"

    id           = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    audit_set_id = Column(String, ForeignKey("audit_sets.id", ondelete="CASCADE"), nullable=False)
    stage_type   = Column(String, nullable=False)   # "stage_1" | "stage_2" | "surveillance" etc.
    label        = Column(String, nullable=False)   # NC reference / short description
    file_path    = Column(String, nullable=False)   # disk path, same storage_base_path convention
    file_name    = Column(String, nullable=True)    # original filename for Content-Disposition

    # ── Lead Auditor signature (party 1) ───────────────────────────────────
    la_user_id      = Column(String, nullable=True)  # PlatformUser.id (resolved at sign time)
    la_signed_at    = Column(DateTime, nullable=True)
    la_signed_ip    = Column(String, nullable=True)
    la_otp_hash     = Column(String, nullable=True)
    la_otp_expires  = Column(DateTime, nullable=True)

    # ── Client signature (party 2) ─────────────────────────────────────────
    client_user_id  = Column(String, nullable=True)
    client_signed_at  = Column(DateTime, nullable=True)
    client_signed_ip  = Column(String, nullable=True)
    client_otp_hash   = Column(String, nullable=True)
    client_otp_expires = Column(DateTime, nullable=True)

    # ── Status ─────────────────────────────────────────────────────────────
    # "pending_la"     → awaiting Lead Auditor signature
    # "pending_client" → LA signed; awaiting client counter-signature
    # "complete"       → both signed
    status       = Column(String, default="pending_la", nullable=False)

    created_by   = Column(String, nullable=True)   # CB user who uploaded
    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False)



# ---------------------------------------------------------------------------
# Table 9 — audit_set_auditor_assessments
# FR.211 — Client evaluates each auditor after an audit stage (ISO 17021-1).
# ---------------------------------------------------------------------------

class AuditSetAuditorAssessment(Base):
    __tablename__ = "audit_set_auditor_assessments"

    id              = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    audit_set_id    = Column(String, ForeignKey("audit_sets.id", ondelete="CASCADE"), nullable=False)
    stage_type      = Column(String, nullable=False)  # "stage_1" | "stage_2" | "surveillance"
    stage_order     = Column(Integer, nullable=True)  # disambiguates multiple surveillance stages
    auditor_name    = Column(String, nullable=False)  # denormalized
    auditor_role    = Column(String, nullable=True)   # "Lead Auditor" | "Team Auditor"
    auditor_ref_id  = Column(String, nullable=True)   # soft FK → auditors.auditors.id
    # Client evaluation (filled before signing)
    rating          = Column(Integer, nullable=True)  # 1–5
    comments        = Column(Text, nullable=True)
    # Signature
    signed_by       = Column(String, nullable=True)   # PlatformUser.id
    signed_at       = Column(DateTime, nullable=True)
    signed_ip       = Column(String, nullable=True)
    otp_hash        = Column(String, nullable=True)
    otp_expires_at  = Column(DateTime, nullable=True)

    created_at      = Column(DateTime, default=datetime.utcnow, nullable=False)


# ---------------------------------------------------------------------------
# Table 11 — audit_set_impartiality_declarations
# FR.224 — Impartiality declaration signed by each audit team member.
# One record per person per stage. Seeded by CB; signed by the auditor.
# ---------------------------------------------------------------------------

class AuditSetImpartialityDeclaration(Base):
    __tablename__ = "audit_set_impartiality_declarations"

    id             = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    audit_set_id   = Column(String, ForeignKey("audit_sets.id", ondelete="CASCADE"), nullable=False)
    stage_type     = Column(String, nullable=False)
    stage_order    = Column(Integer, nullable=True)
    member_name    = Column(String, nullable=False)   # denormalized
    member_role    = Column(String, nullable=False)   # "Lead Auditor"|"Team Auditor"|"Technical Expert"|"Observer"
    auditor_ref_id = Column(String, nullable=True)    # soft FK → auditors.id (for self-sign matching)

    # Signature
    signed_by      = Column(String, nullable=True)    # PlatformUser.id
    signed_at      = Column(DateTime, nullable=True)
    signed_ip      = Column(String, nullable=True)
    otp_hash       = Column(String, nullable=True)
    otp_expires_at = Column(DateTime, nullable=True)

    created_at     = Column(DateTime, default=datetime.utcnow, nullable=False)



# ---------------------------------------------------------------------------
# Table 12 — audit_set_audit_reports
# FR.231 / FR.229 / FR.232 — Formal audit reports requiring committee review.
# Two-party signing: Lead Auditor signs first, then Committee Reviewer approves.
# ---------------------------------------------------------------------------

class AuditSetAuditReport(Base):
    __tablename__ = "audit_set_audit_reports"

    id           = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    audit_set_id = Column(String, ForeignKey("audit_sets.id", ondelete="CASCADE"), nullable=False)
    stage_type   = Column(String, nullable=False)   # "stage_1" | "stage_2" | "surveillance" | "recertification"
    report_form  = Column(String, nullable=False)   # "FR.231" | "FR.229" | "FR.232"
    label        = Column(String, nullable=False)   # short description e.g. "Stage 2 Audit Report"
    file_path    = Column(String, nullable=False)
    file_name    = Column(String, nullable=True)

    # ── Lead Auditor signature (party 1) ───────────────────────────────────
    la_user_id      = Column(String, nullable=True)
    la_signed_at    = Column(DateTime, nullable=True)
    la_signed_ip    = Column(String, nullable=True)
    la_otp_hash     = Column(String, nullable=True)
    la_otp_expires  = Column(DateTime, nullable=True)

    # ── Committee Reviewer approval (party 2) ─────────────────────────────
    reviewer_user_id      = Column(String, nullable=True)
    reviewer_signed_at    = Column(DateTime, nullable=True)
    reviewer_signed_ip    = Column(String, nullable=True)
    reviewer_otp_hash     = Column(String, nullable=True)
    reviewer_otp_expires  = Column(DateTime, nullable=True)

    # ── Status ─────────────────────────────────────────────────────────────
    # "pending_la"     → awaiting Lead Auditor signature
    # "pending_review" → LA signed; awaiting committee reviewer approval
    # "approved"       → both signed — report is final
    status       = Column(String, default="pending_la", nullable=False)

    uploaded_by  = Column(String, nullable=True)   # PlatformUser.id of uploader
    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False)


# ---------------------------------------------------------------------------
# Table 13 — document_signature_fields
# Stores bounding-box coordinates of [SIG:KEY] placeholders extracted from PDFs.
# Populated lazily when a document is first opened in the in-portal viewer.
# Keyed by docx_path (absolute) so it's decoupled from document type.
# ---------------------------------------------------------------------------

class DocumentSignatureField(Base):
    __tablename__ = "document_signature_fields"

    id           = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    docx_path    = Column(String, nullable=False, index=True)   # absolute path to source DOCX
    pdf_path     = Column(String, nullable=True)                # absolute path to converted PDF
    sig_key      = Column(String, nullable=False)               # e.g. "CB_PLANNER" | "CLIENT"
    page_number  = Column(Integer, nullable=False)              # 0-indexed
    # Bounding box in PDF points (72 pts/inch), pdfplumber top-left origin
    x0           = Column(Float, nullable=False)
    y0           = Column(Float, nullable=False)
    x1           = Column(Float, nullable=False)
    y1           = Column(Float, nullable=False)
    # Page dimensions (needed by viewer to compute overlay pixel positions)
    page_width   = Column(Float, nullable=False)
    page_height  = Column(Float, nullable=False)
    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False)
