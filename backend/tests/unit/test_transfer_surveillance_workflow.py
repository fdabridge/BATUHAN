from __future__ import annotations

from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from audit_set.db_models import Base, AuditDocumentSignature, AuditSetSharedDocument
from audit_set.workflow_router import _assert_stage_entry_gate


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _signed_document(db, *, document_type: str, stage_type: str | None, role: str):
    document = AuditSetSharedDocument(
        audit_set_id="transfer-surveillance",
        label=document_type,
        document_type=document_type,
        stage_type=stage_type,
        direction="cb_to_client",
        status="signed",
    )
    db.add(document)
    db.flush()
    db.add(AuditDocumentSignature(
        audit_set_id="transfer-surveillance",
        document_id=document.id,
        document_type=document_type,
        signer_role_label=role,
        required=True,
        signed_at=datetime(2026, 10, 8, 12, 0, 0),
    ))
    db.flush()
    return document


def test_transfer_surveillance_entry_gate_reports_all_missing_documents(db):
    with pytest.raises(HTTPException) as exc:
        _assert_stage_entry_gate(db, "transfer-surveillance", "surveillance")

    assert exc.value.status_code == 409
    assert "FR.222" in exc.value.detail
    assert "FR.224" in exc.value.detail
    assert "FR.223" in exc.value.detail
    assert "Surveillance" in exc.value.detail


def test_transfer_surveillance_entry_gate_accepts_fully_signed_documents(db):
    programme = _signed_document(
        db,
        document_type="audit_programme",
        stage_type=None,
        role="cb_planner",
    )
    db.add(AuditDocumentSignature(
        audit_set_id="transfer-surveillance",
        document_id=programme.id,
        document_type="audit_programme",
        signer_role_label="cb_cert_manager",
        required=True,
        signed_at=datetime(2026, 10, 8, 12, 5, 0),
    ))
    _signed_document(
        db,
        document_type="team_info",
        stage_type="surveillance",
        role="assigned_auditor",
    )
    _signed_document(
        db,
        document_type="audit_plan",
        stage_type="surveillance",
        role="org_rep",
    )
    db.commit()

    _assert_stage_entry_gate(db, "transfer-surveillance", "surveillance")


def test_transfer_surveillance_entry_gate_rejects_unsigned_plan(db):
    programme = _signed_document(
        db,
        document_type="audit_programme",
        stage_type=None,
        role="cb_planner",
    )
    db.add(AuditDocumentSignature(
        audit_set_id="transfer-surveillance",
        document_id=programme.id,
        document_type="audit_programme",
        signer_role_label="cb_cert_manager",
        required=True,
        signed_at=datetime(2026, 10, 8, 12, 5, 0),
    ))
    _signed_document(
        db,
        document_type="team_info",
        stage_type="surveillance",
        role="assigned_auditor",
    )
    plan = _signed_document(
        db,
        document_type="audit_plan",
        stage_type="surveillance",
        role="org_rep",
    )
    signature = db.query(AuditDocumentSignature).filter_by(document_id=plan.id).one()
    signature.signed_at = None
    db.commit()

    with pytest.raises(HTTPException) as exc:
        _assert_stage_entry_gate(db, "transfer-surveillance", "surveillance")

    assert "FR.223 Audit Plan (Surveillance) is not signed" in exc.value.detail
