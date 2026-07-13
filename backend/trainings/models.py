"""
BATUHAN — Trainings Module: SQLAlchemy ORM models.
Tables: training_courses, training_exam_questions, training_assignments

Uses the same database_url from config.settings.
"""
from __future__ import annotations
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Float, Integer, String, UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker

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


class TrainingCourse(Base):
    __tablename__ = "training_courses"

    id              = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    title           = Column(String, nullable=False)
    description     = Column(String, nullable=True)
    file_path              = Column(String, nullable=True)    # R2 storage ref for training material
    material_file_name     = Column(String, nullable=True)   # original filename
    material_content_type  = Column(String, nullable=True)   # stored MIME type
    material_kind          = Column(String, nullable=True)   # pdf | video | office | other
    exam_file_path         = Column(String, nullable=True)   # R2 storage ref for exam display file
    exam_file_name         = Column(String, nullable=True)   # original filename
    exam_content_type      = Column(String, nullable=True)   # stored MIME type
    exam_kind              = Column(String, nullable=True)   # pdf | office | other
    passing_grade          = Column(Integer, default=70)     # percentage
    is_active       = Column(Boolean, default=True)
    created_by      = Column(String, nullable=False)       # user ID of training officer
    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class TrainingExamQuestion(Base):
    __tablename__ = "training_exam_questions"

    id                   = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    course_id            = Column(String, nullable=False)   # soft FK -> training_courses.id
    question_number      = Column(Integer, nullable=False)
    question_text        = Column(String, nullable=False)
    options              = Column(String, nullable=False)    # JSON string - list of option strings
    correct_option_index = Column(Integer, nullable=False)   # 0-based index
    created_at           = Column(DateTime, default=datetime.utcnow)


class TrainingAssignment(Base):
    __tablename__ = "training_assignments"
    __table_args__ = (
        UniqueConstraint('course_id', 'user_id', name='uq_training_assignment_course_user'),
    )

    id                    = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    course_id             = Column(String, nullable=False)   # soft FK -> training_courses.id
    user_id               = Column(String, nullable=False)   # soft FK -> platform_users.id
    assigned_by           = Column(String, nullable=False)    # training officer user ID
    training_completed    = Column(Boolean, default=False)
    training_completed_at = Column(DateTime, nullable=True)
    exam_completed        = Column(Boolean, default=False)
    exam_score            = Column(Float, nullable=True)      # percentage
    exam_passed           = Column(Boolean, nullable=True)
    exam_completed_at     = Column(DateTime, nullable=True)
    exam_answers          = Column(String, nullable=True)    # JSON: submitted answers for audit
    assigned_at           = Column(DateTime, default=datetime.utcnow)


def _safe_add_column(table: str, col_def: str) -> None:
    """Add a column if it doesn't already exist (Postgres + SQLite safe)."""
    import sqlalchemy as sa
    with engine.connect() as conn:
        try:
            conn.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN {col_def}"))
            conn.commit()
        except Exception:
            pass  # column already exists


def _safe_create_unique_assignment_index() -> None:
    """Deduplicate assignments then create unique index. Safe for every startup."""
    import logging as _log
    import sqlalchemy as sa
    _logger = _log.getLogger("batuhan.trainings")
    with engine.connect() as conn:
        # Detect duplicates: keep the row with the most progress (prefer exam > training > latest)
        try:
            dupes = conn.execute(sa.text(
                "SELECT course_id, user_id, COUNT(*) AS cnt "
                "FROM training_assignments "
                "GROUP BY course_id, user_id HAVING cnt > 1"
            )).fetchall()
        except Exception:
            dupes = []
        for row in dupes:
            cid, uid = row[0], row[1]
            # Fetch all assignments for this pair, ordered by progress desc
            rows = conn.execute(sa.text(
                "SELECT id, exam_completed, training_completed, assigned_at "
                "FROM training_assignments "
                "WHERE course_id = :cid AND user_id = :uid "
                "ORDER BY exam_completed DESC, training_completed DESC, assigned_at DESC"
            ), {"cid": cid, "uid": uid}).fetchall()
            if len(rows) > 1:
                keep_id = rows[0][0]
                delete_ids = [r[0] for r in rows[1:]]
                for did in delete_ids:
                    conn.execute(sa.text(
                        "DELETE FROM training_assignments WHERE id = :did"
                    ), {"did": did})
                _logger.warning(
                    "[Trainings] Removed %d duplicate assignment(s) for course=%s user=%s, kept id=%s",
                    len(delete_ids), cid, uid, keep_id,
                )
        if dupes:
            conn.commit()
        # Now create the unique index
        try:
            conn.execute(sa.text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_training_assignment_course_user "
                "ON training_assignments (course_id, user_id)"
            ))
            conn.commit()
        except Exception as exc:
            _logger.warning("[Trainings] Could not create unique assignment index: %s", exc)


def create_tables() -> None:
    """Create training tables if they do not exist. Safe to call on every startup."""
    Base.metadata.create_all(bind=engine, checkfirst=True)
    # Phase 2 — file metadata columns (safe migration for existing deployments)
    for col in (
        "material_file_name VARCHAR",
        "material_content_type VARCHAR",
        "material_kind VARCHAR",
        "exam_file_name VARCHAR",
        "exam_content_type VARCHAR",
        "exam_kind VARCHAR",
    ):
        _safe_add_column("training_courses", col)
    # Phase 4 — exam answers column for auditability
    _safe_add_column("training_assignments", "exam_answers TEXT")
    # Phase 10 — unique constraint on (course_id, user_id)
    _safe_create_unique_assignment_index()
