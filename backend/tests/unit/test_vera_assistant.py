from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from audit_set.db_models import (
    Base as AuditBase,
    AuditDocumentSignature,
    AuditSet,
    AuditSetNCDecision,
    AuditSetNCItem,
    AuditSetSharedDocument,
    AuditSetStage,
)
from auth.db_models import Base as AuthBase
from vera.knowledge import page_description
from vera.service import build_case_snapshot, resolve_case, system_instructions


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    AuditBase.metadata.create_all(engine)
    AuthBase.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _user(**overrides):
    values = {
        "id": "user-1",
        "full_name": "Test User",
        "role": "planner",
        "audit_set_id": None,
        "auditor_id": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _case(case_id: str, plan_number: int, **overrides) -> AuditSet:
    values = {
        "id": case_id,
        "plan_number": plan_number,
        "company_name": f"Company {plan_number}",
        "standards": ["QMS"],
        "audit_type": "initial",
        "accreditation_body": "UAF",
        "workflow_version": 2,
        "workflow_status": "fr218_complete",
        "is_transfer": False,
        "submitted_via_portal": True,
    }
    values.update(overrides)
    return AuditSet(**values)


def test_client_cannot_select_another_clients_case(db):
    own = _case("own-case", 1701)
    other = _case("other-case", 1702)
    db.add_all([own, other])
    db.commit()

    client = _user(role="client", audit_set_id=own.id)
    resolved = resolve_case(other.id, client, db)

    assert resolved is not None
    assert resolved.id == own.id


def test_unassigned_auditor_cannot_read_case(db):
    audit_set = _case("case-1", 1703)
    db.add(audit_set)
    db.commit()

    auditor = _user(role="auditor", auditor_id="auditor-1")
    with pytest.raises(HTTPException) as caught:
        resolve_case(audit_set.id, auditor, db)

    assert caught.value.status_code == 403


def test_assigned_trainee_auditor_can_read_case(db):
    audit_set = _case("case-2", 1704)
    stage = AuditSetStage(
        audit_set_id=audit_set.id,
        stage_type="stage_1",
        stage_order=1,
        trainees=[{"id": "auditor-1", "name": "Trainee"}],
    )
    db.add_all([audit_set, stage])
    db.commit()

    auditor = _user(role="auditor", auditor_id="auditor-1")
    assert resolve_case(audit_set.id, auditor, db).id == audit_set.id


def test_snapshot_reports_live_documents_signatures_and_nc_state(db):
    audit_set = _case("case-3", 1705, workflow_status="stage2_complete")
    document = AuditSetSharedDocument(
        id="doc-1",
        audit_set_id=audit_set.id,
        label="FR.233",
        document_type="fr233",
        direction="cb_to_client",
        status="released",
    )
    signature = AuditDocumentSignature(
        audit_set_id=audit_set.id,
        document_id=document.id,
        document_type="fr233",
        signer_role_label="cb_cert_manager",
        required=True,
    )
    decision = AuditSetNCDecision(
        audit_set_id=audit_set.id,
        stage_type="stage_2",
        no_nc=False,
    )
    open_nc = AuditSetNCItem(
        audit_set_id=audit_set.id,
        stage_type="stage_2",
        nc_index=1,
        category="minor",
        description="Example",
        status="open",
    )
    db.add_all([audit_set, document, signature, decision, open_nc])
    db.commit()

    snapshot = build_case_snapshot(audit_set, _user(), db)

    assert snapshot["status_title"] == "Stage 2 complete"
    assert snapshot["visible_documents"]["by_type"] == {"fr233": 1}
    assert snapshot["visible_documents"]["unsigned_required_slots"] == 1
    assert snapshot["nc"]["open"] == 1
    assert snapshot["nc"]["stage_decisions"] == [{"stage": "stage_2", "no_nc": False}]


def test_consultant_snapshot_does_not_bypass_document_visibility(db):
    audit_set = _case("case-4", 1706, consultant_id="consultant-1")
    internal_document = AuditSetSharedDocument(
        id="doc-internal",
        audit_set_id=audit_set.id,
        label="Internal assessment",
        document_type="assessment",
        direction="internal",
        status="uploaded",
    )
    db.add_all([audit_set, internal_document])
    db.commit()

    consultant = _user(id="consultant-1", role="consultant")
    snapshot = build_case_snapshot(audit_set, consultant, db)

    assert snapshot["visible_documents"]["total"] == 0
    assert snapshot["visible_documents"]["by_type"] == {}


def test_system_prompt_enforces_read_only_and_contains_only_authorised_snapshot():
    instructions = system_instructions(
        user=_user(role="client", full_name="Client Person"),
        pathname="/client/overview",
        snapshot={"workflow_status": "quotation_sent", "company": "Allowed Ltd"},
    )

    assert "read-only" in instructions.lower()
    assert "cannot perform" in instructions.lower()
    assert "Allowed Ltd" in instructions
    assert "quotation_sent" in instructions
    assert "API keys" in instructions


def test_page_guidance_routes_ai_report_questions():
    assert page_description("/certivai/reports") == "CertivAI report generation and job history"
    assert page_description("/training/people") == "person-based exam history"
