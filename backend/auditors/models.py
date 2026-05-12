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

DATABASE_URL = "sqlite:///./auditors.db"
Base = declarative_base()
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables():
    Base.metadata.create_all(bind=engine)


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
    id              = Column(Integer, primary_key=True, autoincrement=True)
    auditor_id      = Column(String, ForeignKey("auditors.id"), nullable=False)
    standard_code   = Column(String)   # e.g. "ISO 9001", "ISO 27001"
    technical_depth = Column(String)   # e.g. "Lead Auditor", "Team Auditor", "Technical Expert"
    experience_years= Column(Integer)
    auditor         = relationship("Auditor", back_populates="standard_qualifications")


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
