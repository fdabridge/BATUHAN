from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, LargeBinary, String
from sqlalchemy.orm import declarative_base, relationship

from auth.db_models import engine, SessionLocal


Base = declarative_base()


class SalesQuotationCase(Base):
    __tablename__ = "sales_quotation_cases"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_user_id = Column(String, nullable=False, index=True)
    company_name = Column(String, nullable=False, index=True)
    representative_name = Column(String, nullable=False, default="")
    representative_email = Column(String, nullable=False, default="")
    status = Column(String, nullable=False, default="draft", index=True)
    application_data = Column(JSON, nullable=False)
    calculation_result = Column(JSON, nullable=True)
    day_breakdown = Column(JSON, nullable=True)
    commercial_details = Column(JSON, nullable=True)
    pricing = Column(JSON, nullable=True)
    quotation_revision = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    documents = relationship(
        "SalesQuotationDocument",
        back_populates="case",
        cascade="all, delete-orphan",
        order_by="SalesQuotationDocument.created_at",
    )


class SalesQuotationDocument(Base):
    __tablename__ = "sales_quotation_documents"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id = Column(String, ForeignKey("sales_quotation_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String, nullable=False)  # quotation | agreement
    revision = Column(Integer, nullable=False, default=1)
    file_name = Column(String, nullable=False)
    content_type = Column(String, nullable=False, default="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    content = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    case = relationship("SalesQuotationCase", back_populates="documents")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables() -> None:
    Base.metadata.create_all(bind=engine, checkfirst=True)
