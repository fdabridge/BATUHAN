import uuid
from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.orm import declarative_base
from auth.db_models import engine

Base = declarative_base()


class TrackerRecord(Base):
    __tablename__ = "standalone_tracker_records"
    id = Column(String(100), primary_key=True)
    kind = Column(String(20), nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    payload = Column(Text, nullable=False)


class TrackerHistory(Base):
    __tablename__ = "standalone_tracker_history"
    id = Column(String(100), primary_key=True, default=lambda: str(uuid.uuid4()))
    record_id = Column(String(100), nullable=False, index=True)
    actor = Column(String(320), nullable=False)
    saved_at = Column(String(40), nullable=False)
    action = Column(String(40), nullable=False)
    before_payload = Column(Text, nullable=False)
    after_payload = Column(Text, nullable=False)


class TrackerMetadata(Base):
    __tablename__ = "standalone_tracker_metadata"
    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=False)


def create_tables():
    Base.metadata.create_all(bind=engine)
