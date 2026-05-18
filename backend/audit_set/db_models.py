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
    Column, Date, DateTime, Float,
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


# ---------------------------------------------------------------------------
# Table 1 — audit_sets
# ---------------------------------------------------------------------------

class AuditSet(Base):
    __tablename__ = "audit_sets"

    id           = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    plan_number  = Column(Integer, unique=True, nullable=False)   # app-managed, starts at 1600
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

    # ── Certificate ───────────────────────────────────────────────────────────
    cert_issued_date = Column(Date, nullable=True)
    cert_expiry_date = Column(Date, nullable=True)   # typically 3 years from issued date
    cert_status      = Column(String, nullable=True)
    # cert_status values: "active" | "approaching_expiry" | "expired" | "suspended"

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
