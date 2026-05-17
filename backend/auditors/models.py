"""
BATUHAN — Auditor Profile: SQLAlchemy ORM models.
Tables: auditors, auditor_education, auditor_languages,
        auditor_standard_qualifications, auditor_work_experience,
        auditor_training_records, auditor_audit_log
"""
from __future__ import annotations
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey,
    Integer, String, Text, JSON, create_engine,
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
    """Add a column to an existing table if it doesn't already exist (SQLite safe)."""
    with engine.connect() as conn:
        try:
            conn.execute(
                __import__("sqlalchemy").text(f"ALTER TABLE {table} ADD COLUMN {col_def}")
            )
            conn.commit()
        except Exception:
            pass  # column already exists


def create_tables():
    Base.metadata.create_all(bind=engine)
    # Safe migrations: add columns introduced after initial deployment
    _safe_add_column("auditor_standard_qualifications", "accreditation_body TEXT")
    _safe_add_column("auditor_standard_qualifications", "scope_category TEXT")
    _safe_add_column("auditor_standard_qualifications", "ea_codes JSON")


class Auditor(Base):
    __tablename__ = "auditors"

    id                  = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name                = Column(String, nullable=False)
    email               = Column(String)
    phone               = Column(String)
    mobile              = Column(String)
    role                = Column(String)           # e.g. "Lead Auditor", "Technical Expert"
    field_of_expertise  = Column(Text)
    ea_codes            = Column(JSON)             # ["EA 3", "EA 18", ...]
    accreditation_bodies= Column(JSON)             # ["UAF", "TURKAK"]
    is_active           = Column(Boolean, default=True, nullable=False)
    created_at          = Column(DateTime, default=datetime.utcnow)
    updated_at          = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    education               = relationship("AuditorEducation",             back_populates="auditor", cascade="all, delete-orphan")
    languages               = relationship("AuditorLanguage",              back_populates="auditor", cascade="all, delete-orphan")
    standard_qualifications = relationship("AuditorStandardQualification", back_populates="auditor", cascade="all, delete-orphan")
    work_experience         = relationship("AuditorWorkExperience",        back_populates="auditor", cascade="all, delete-orphan")
    training_records        = relationship("AuditorTrainingRecord",        back_populates="auditor", cascade="all, delete-orphan")
    audit_log               = relationship("AuditorAuditLog",              back_populates="auditor", cascade="all, delete-orphan")
    witness_records         = relationship("AuditorWitnessRecord",         back_populates="auditor", cascade="all, delete-orphan")


class AuditorEducation(Base):
    __tablename__ = "auditor_education"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    auditor_id  = Column(String, ForeignKey("auditors.id"), nullable=False)
    degree      = Column(String)
    institution = Column(String)
    year        = Column(String)
    auditor     = relationship("Auditor", back_populates="education")


class AuditorLanguage(Base):
    __tablename__ = "auditor_languages"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    auditor_id  = Column(String, ForeignKey("auditors.id"), nullable=False)
    language    = Column(String)
    level       = Column(String)   # e.g. "Native", "C1", "B2"
    auditor     = relationship("Auditor", back_populates="languages")


class AuditorStandardQualification(Base):
    __tablename__ = "auditor_standard_qualifications"
    id                 = Column(Integer, primary_key=True, autoincrement=True)
    auditor_id         = Column(String, ForeignKey("auditors.id"), nullable=False)
    standard_code      = Column(String)   # e.g. "ISO 9001", "ISO 27001"
    accreditation_body = Column(String)   # e.g. "UAF", "TURKAK" — per-standard accreditation
    scope_category     = Column(String)   # for category-based standards (ISO 22000, FSSC, etc.)
    ea_codes           = Column(JSON)     # per-standard EA codes for ISO 9001/14001/45001/27001, e.g. ["EA 3", "EA 9"]
    technical_depth    = Column(String)   # "Lead Auditor" | "Team Auditor" | "Technical Expert"
    experience_years   = Column(Integer)
    is_qualified       = Column(Boolean, default=True, nullable=False)
    last_training_date = Column(String)   # ISO date "YYYY-MM-DD"
    last_verified_date = Column(String)   # ISO date "YYYY-MM-DD" — used by TURKAK annual check
    auditor            = relationship("Auditor", back_populates="standard_qualifications")


class AuditorWorkExperience(Base):
    __tablename__ = "auditor_work_experience"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    auditor_id  = Column(String, ForeignKey("auditors.id"), nullable=False)
    employer    = Column(String)
    position    = Column(String)
    start_date  = Column(String)
    end_date    = Column(String)
    description = Column(Text)
    auditor     = relationship("Auditor", back_populates="work_experience")


class AuditorTrainingRecord(Base):
    __tablename__ = "auditor_training_records"
    id                   = Column(Integer, primary_key=True, autoincrement=True)
    auditor_id           = Column(String, ForeignKey("auditors.id"), nullable=False)
    training_date        = Column(String)
    institution          = Column(String)
    subject              = Column(String)
    duration_days        = Column(Integer)
    standard_code        = Column(String)
    certificate_available= Column(Boolean, default=False)
    auditor              = relationship("Auditor", back_populates="training_records")


class AuditorAuditLog(Base):
    """History of audits this auditor has personally conducted."""
    __tablename__ = "auditor_audit_log"
    id            = Column(Integer, primary_key=True, autoincrement=True)
    auditor_id    = Column(String, ForeignKey("auditors.id"), nullable=False)
    audit_date    = Column(String)
    client_name   = Column(String)
    standard_code = Column(String)
    role          = Column(String)   # Lead Auditor / Team Auditor / Witness
    notes         = Column(Text)
    auditor       = relationship("Auditor", back_populates="audit_log")


class AuditorWitnessRecord(Base):
    """CB's own witness audit records for its auditors (ISO 17021-1 §7.1)."""
    __tablename__ = "auditor_witness_records"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    auditor_id     = Column(String, ForeignKey("auditors.id"), nullable=False)
    witness_date   = Column(String, nullable=False)   # "YYYY-MM-DD"
    client_name    = Column(String)
    standard_code  = Column(String)                   # e.g. "ISO 9001"
    ea_code        = Column(String)                   # e.g. "EA 3"
    role_witnessed = Column(String)                   # "Lead Auditor" | "Team Auditor"
    observer_name  = Column(String)                   # name of the CB witness observer
    outcome        = Column(String)                   # "Satisfactory" | "Needs Improvement" | "Unsatisfactory"
    notes          = Column(Text)
    created_at     = Column(DateTime, default=datetime.utcnow)

    auditor = relationship("Auditor", back_populates="witness_records")
