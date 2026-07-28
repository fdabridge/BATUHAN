"""
BATUHAN — Auth: SQLAlchemy ORM models.
Table: platform_users

role values: "admin" | "planner" | "auditor" | "officer" | "executive" | "client"

auditor_id is a soft link to auditors.auditors.id — stored as plain String,
no DB-level FK constraint (lives in a separate SQLite file from auditors.db).
audit_set_id is a soft link to audit_sets.id used only for client-role accounts.
"""
from __future__ import annotations
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Integer, String,
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


def _safe_add_column_auth(table: str, col_def: str) -> None:
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
    # Safe migrations — added after initial deployment
    _safe_add_column_auth("platform_users", "audit_set_id VARCHAR")
    _safe_add_column_auth("platform_users", "username VARCHAR")
    _safe_add_column_auth("platform_users", "is_activated BOOLEAN DEFAULT TRUE")
    _safe_add_column_auth("platform_users", "activation_verified_at TIMESTAMP")
    _safe_add_column_auth("platform_users", "activation_email VARCHAR")
    _safe_add_column_auth("platform_users", "activation_otp_hash VARCHAR")
    _safe_add_column_auth("platform_users", "activation_otp_expires_at TIMESTAMP")
    _safe_add_column_auth("platform_users", "activation_otp_attempts INTEGER DEFAULT 0")
    _safe_add_column_auth("platform_users", "activation_verified_ip VARCHAR")
    # Existing accounts remain usable when verification policy is introduced.
    import sqlalchemy as sa
    with engine.begin() as conn:
        conn.execute(sa.text(
            "UPDATE platform_users SET is_activated = TRUE "
            "WHERE is_activated IS NULL"
        ))


class PlatformUser(Base):
    __tablename__ = "platform_users"

    id            = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email         = Column(String, unique=True, nullable=False, index=True)
    username      = Column(String, nullable=True, index=True)
    password_hash = Column(String, nullable=False)
    full_name     = Column(String, nullable=False)
    role          = Column(String, nullable=False)
    # role choices: "admin" | "planner" | "auditor" | "officer" | "executive" | "client"
    is_active     = Column(Boolean, default=True, nullable=False)
    auditor_id    = Column(String, nullable=True)   # soft FK → auditors.auditors.id
    audit_set_id  = Column(String, nullable=True)   # soft FK → audit_sets.id (client role only)
    is_activated  = Column(Boolean, default=True, nullable=False)
    activation_verified_at = Column(DateTime, nullable=True)
    activation_email = Column(String, nullable=True)
    activation_otp_hash = Column(String, nullable=True)
    activation_otp_expires_at = Column(DateTime, nullable=True)
    activation_otp_attempts = Column(Integer, default=0, nullable=False)
    activation_verified_ip = Column(String, nullable=True)
    last_login    = Column(DateTime, nullable=True)
    created_at    = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class UserSignature(Base):
    __tablename__ = "user_signatures"

    id         = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id    = Column(String, nullable=False, unique=True, index=True)  # soft FK → platform_users.id
    image_data = Column(String, nullable=False)  # base64 PNG data URL (data:image/png;base64,...)
    source     = Column(String, nullable=False)  # "drawn" | "uploaded"
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class PlatformPolicy(Base):
    """Runtime-configurable platform policy, one row per stable policy key."""

    __tablename__ = "platform_policies"

    key        = Column(String, primary_key=True)
    enabled    = Column(Boolean, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    updated_by = Column(String, nullable=True)
