"""
BATUHAN — Auditor Profile: Service layer (CRUD).
"""
from __future__ import annotations
import uuid
import logging
from datetime import date, timedelta
from sqlalchemy.orm import Session

from auditors.models import (
    Auditor, AuditorEducation, AuditorLanguage,
    AuditorStandardQualification, AuditorWorkExperience,
    AuditorTrainingRecord, AuditorAuditLog,
)
from auditors.schemas import (
    AuditorCreateSchema, AuditorDashboardEntry, QualificationSummary,
)

logger = logging.getLogger(__name__)


def _attach_children(db: Session, auditor: Auditor, data: AuditorCreateSchema) -> None:
    """Insert all child rows for an Auditor. Caller must commit."""
    for item in (data.education or []):
        db.add(AuditorEducation(auditor_id=auditor.id, **item.model_dump()))

    for item in (data.languages or []):
        db.add(AuditorLanguage(auditor_id=auditor.id, **item.model_dump()))

    for item in (data.standard_qualifications or []):
        db.add(AuditorStandardQualification(auditor_id=auditor.id, **item.model_dump()))

    for item in (data.work_experience or []):
        db.add(AuditorWorkExperience(auditor_id=auditor.id, **item.model_dump()))

    for item in (data.training_records or []):
        db.add(AuditorTrainingRecord(auditor_id=auditor.id, **item.model_dump()))

    for item in (data.audit_log or []):
        db.add(AuditorAuditLog(auditor_id=auditor.id, **item.model_dump()))


def create_auditor(db: Session, data: AuditorCreateSchema) -> Auditor:
    """Create a new Auditor with all child rows. Returns the persisted ORM object."""
    auditor = Auditor(
        id=str(uuid.uuid4()),
        name=data.name,
        email=data.email,
        phone=data.phone,
        mobile=data.mobile,
        role=data.role,
        field_of_expertise=data.field_of_expertise,
        ea_codes=data.ea_codes,
        accreditation_bodies=data.accreditation_bodies,
    )
    db.add(auditor)
    db.flush()  # get auditor.id before inserting children
    _attach_children(db, auditor, data)
    db.commit()
    db.refresh(auditor)
    logger.info("[Auditors] Created auditor id=%s name='%s'", auditor.id, auditor.name)
    return auditor


def get_auditor(db: Session, auditor_id: str) -> Auditor | None:
    """Return Auditor by ID (including inactive), or None."""
    return db.query(Auditor).filter(Auditor.id == auditor_id).first()


def list_auditors(db: Session, active_only: bool = True) -> list[Auditor]:
    """Return all auditors, optionally filtered to active only."""
    q = db.query(Auditor)
    if active_only:
        q = q.filter(Auditor.is_active == True)  # noqa: E712
    return q.order_by(Auditor.name).all()


def update_auditor(db: Session, auditor_id: str, data: AuditorCreateSchema) -> Auditor | None:
    """
    Full replace: update parent fields, delete all child rows, re-insert from data.
    Returns updated Auditor or None if not found.
    """
    auditor = db.query(Auditor).filter(Auditor.id == auditor_id).first()
    if not auditor:
        return None

    # Update scalar fields
    auditor.name                = data.name
    auditor.email               = data.email
    auditor.phone               = data.phone
    auditor.mobile              = data.mobile
    auditor.role                = data.role
    auditor.field_of_expertise  = data.field_of_expertise
    auditor.ea_codes            = data.ea_codes
    auditor.accreditation_bodies= data.accreditation_bodies

    # Delete all existing child rows (cascade would also work, but explicit is safer)
    for child_rel in (
        AuditorEducation, AuditorLanguage, AuditorStandardQualification,
        AuditorWorkExperience, AuditorTrainingRecord, AuditorAuditLog,
    ):
        db.query(child_rel).filter(child_rel.auditor_id == auditor_id).delete()

    db.flush()
    _attach_children(db, auditor, data)
    db.commit()
    db.refresh(auditor)
    logger.info("[Auditors] Updated auditor id=%s name='%s'", auditor.id, auditor.name)
    return auditor


def delete_auditor(db: Session, auditor_id: str) -> bool:
    """Soft-delete: set is_active=False. Returns True if found, False if not."""
    auditor = db.query(Auditor).filter(Auditor.id == auditor_id).first()
    if not auditor:
        return False
    auditor.is_active = False
    db.commit()
    logger.info("[Auditors] Soft-deleted auditor id=%s", auditor_id)
    return True


def get_dashboard(db: Session, active_only: bool = True) -> list[AuditorDashboardEntry]:
    """
    Return a rich summary of every auditor in the pool.
    Computes qualification warning flags and audit history stats in Python
    (dates are stored as ISO strings in the DB, not native date columns).
    """
    _THREE_YEARS = timedelta(days=3 * 365)
    _ONE_YEAR    = timedelta(days=365)
    today = date.today()

    q = db.query(Auditor)
    if active_only:
        q = q.filter(Auditor.is_active == True)  # noqa: E712
    auditors = q.order_by(Auditor.name).all()

    entries: list[AuditorDashboardEntry] = []

    for auditor in auditors:
        # ── Qualifications ────────────────────────────────────────
        qual_rows = (
            db.query(AuditorStandardQualification)
            .filter(AuditorStandardQualification.auditor_id == auditor.id)
            .all()
        )

        qual_summaries: list[QualificationSummary] = []
        for row in qual_rows:
            def _parse(s: str | None) -> date | None:
                if not s:
                    return None
                try:
                    return date.fromisoformat(s)
                except ValueError:
                    return None

            ltd = _parse(row.last_training_date)
            lvd = _parse(row.last_verified_date)

            qual_summaries.append(QualificationSummary(
                standard_code=row.standard_code or "",
                is_qualified=bool(row.is_qualified),
                technical_depth=row.technical_depth,
                experience_years=row.experience_years,
                last_training_date=ltd,
                last_verified_date=lvd,
                training_expiry_warning=(ltd is not None) and (ltd < today - _THREE_YEARS),
                verification_warning=(lvd is None) or (lvd < today - _ONE_YEAR),
            ))

        # ── Audit log ─────────────────────────────────────────────
        log_rows = (
            db.query(AuditorAuditLog)
            .filter(AuditorAuditLog.auditor_id == auditor.id)
            .all()
        )

        parsed_dates: list[date] = []
        for log in log_rows:
            if log.audit_date:
                try:
                    parsed_dates.append(date.fromisoformat(log.audit_date))
                except ValueError:
                    pass

        last_audit_date = max(parsed_dates) if parsed_dates else None
        days_since = (today - last_audit_date).days if last_audit_date else None

        entries.append(AuditorDashboardEntry(
            auditor_id=auditor.id,
            name=auditor.name,
            email=auditor.email,
            role=auditor.role,
            is_active=auditor.is_active,
            ea_codes=auditor.ea_codes or [],
            accreditation_bodies=auditor.accreditation_bodies or [],
            qualifications=qual_summaries,
            total_audits=len(log_rows),
            last_audit_date=last_audit_date,
            days_since_last_audit=days_since,
        ))

    return entries
