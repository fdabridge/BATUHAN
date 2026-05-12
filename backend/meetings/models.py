"""
BATUHAN — Meetings Module: SQLAlchemy Model, Engine, Session, and DB helpers.
Uses the same database_url from settings (SQLite by default).
"""

from __future__ import annotations
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from config.settings import get_settings

settings = get_settings()

# SQLite needs check_same_thread=False for multi-threaded FastAPI usage
_connect_args = (
    {"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {}
)

engine = create_engine(settings.database_url, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


class Meeting(Base):
    __tablename__ = "meetings"

    id               = Column(Integer, primary_key=True, index=True)
    title            = Column(String, nullable=False)
    description      = Column(String, nullable=True)
    start_utc        = Column(DateTime, nullable=False)   # naive UTC always
    duration_minutes = Column(Integer, default=60)
    notified_30min   = Column(Boolean, default=False)
    created_at       = Column(DateTime, default=datetime.utcnow)


def create_tables() -> None:
    """Create meeting tables if they do not exist. Safe to call on every startup."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency: yield a DB session, always close on exit."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
