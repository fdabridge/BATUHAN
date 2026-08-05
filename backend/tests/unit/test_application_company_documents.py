import asyncio
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from audit_set import apply_router
from audit_set.application_documents_router import (
    _require_document_access,
    list_company_documents,
)
from audit_set.apply_router import (
    ClientApplicationSchema,
    CompanyDocumentUpload,
    _read_company_documents,
    _submit_application,
    submit_application_with_documents,
)
from audit_set.db_models import (
    AuditSet,
    AuditSetCompanyDocument,
    Base as AuditBase,
    get_db as get_audit_db,
)
from auth.db_models import Base as AuthBase, PlatformUser, get_db as get_auth_db


@pytest.fixture
def application_sessions():
    engine_options = {
        "connect_args": {"check_same_thread": False},
        "poolclass": StaticPool,
    }
    audit_engine = create_engine("sqlite:///:memory:", **engine_options)
    auth_engine = create_engine("sqlite:///:memory:", **engine_options)
    AuditBase.metadata.create_all(audit_engine)
    AuthBase.metadata.create_all(auth_engine)
    audit_session = sessionmaker(bind=audit_engine)()
    auth_session = sessionmaker(bind=auth_engine)()
    try:
        yield audit_session, auth_session
    finally:
        audit_session.close()
        auth_session.close()


def _payload(email: str = "client@example.com") -> ClientApplicationSchema:
    return ClientApplicationSchema(
        company_name="Example Manufacturing",
        company_address="1 Example Road",
        representative_name="Client User",
        representative_email=email,
        standards=["QMS"],
        audit_type="initial",
        scope_description="Manufacturing",
    )


def test_submission_persists_document_and_uploader_metadata(
    application_sessions,
    monkeypatch,
):
    audit_db, auth_db = application_sessions
    uploaded = {}
    monkeypatch.setattr(apply_router, "policy_enabled", lambda *_: False)
    monkeypatch.setattr(apply_router, "send_client_welcome", lambda **_: None)
    monkeypatch.setattr(
        apply_router,
        "store_upload",
        lambda path, content, content_type: uploaded.update(
            path=path,
            content=content,
            content_type=content_type,
        ) or path,
    )

    result = _submit_application(
        _payload(),
        audit_db,
        auth_db,
        [
            CompanyDocumentUpload(
                file_name="Company Registration.pdf",
                content_type="application/pdf",
                content=b"%PDF-company-evidence",
            ),
        ],
    )

    audit_set = audit_db.query(AuditSet).one()
    document = audit_db.query(AuditSetCompanyDocument).one()
    user = auth_db.query(PlatformUser).one()
    assert result["success"] is True
    assert result["company_documents_received"] == 1
    assert audit_set.workflow_status == "pending_review"
    assert document.audit_set_id == audit_set.id
    assert document.file_name == "Company Registration.pdf"
    assert document.file_type == "application/pdf"
    assert document.file_size == len(b"%PDF-company-evidence")
    assert document.uploader_user_id == user.id
    assert document.uploader_name == "Client User"
    assert uploaded["path"].startswith(f"company_documents/{audit_set.id}/")


def test_all_selected_documents_are_persisted_and_visible_to_planner(
    application_sessions,
    monkeypatch,
):
    audit_db, auth_db = application_sessions
    uploaded_paths = []
    monkeypatch.setattr(apply_router, "policy_enabled", lambda *_: False)
    monkeypatch.setattr(apply_router, "send_client_welcome", lambda **_: None)
    monkeypatch.setattr(
        apply_router,
        "store_upload",
        lambda path, _content, content_type: uploaded_paths.append((path, content_type)) or path,
    )

    result = _submit_application(
        _payload(),
        audit_db,
        auth_db,
        [
            CompanyDocumentUpload("Registration.pdf", "application/pdf", b"registration"),
            CompanyDocumentUpload(
                "Tax Certificate.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                b"tax-certificate",
            ),
        ],
    )

    audit_set = audit_db.query(AuditSet).one()
    planner = SimpleNamespace(role="planner", audit_set_id=None, auditor_id=None)
    planner_documents = list_company_documents(audit_set.id, audit_db, planner)

    assert result["company_documents_received"] == 2
    assert len(uploaded_paths) == 2
    assert {document["file_name"] for document in planner_documents} == {
        "Registration.pdf",
        "Tax Certificate.docx",
    }


def test_multipart_manifest_mismatch_is_rejected_before_application_creation(
    application_sessions,
):
    audit_db, auth_db = application_sessions
    upload = UploadFile(filename="Registration.pdf", file=BytesIO(b"registration"))

    with pytest.raises(HTTPException, match="Not all selected"):
        asyncio.run(submit_application_with_documents(
            application=_payload().model_dump_json(),
            company_documents=[upload],
            company_document_count=2,
            audit_db=audit_db,
            auth_db=auth_db,
        ))

    assert audit_db.query(AuditSet).count() == 0
    assert auth_db.query(PlatformUser).count() == 0


def test_multipart_endpoint_receives_every_repeated_file_field(
    application_sessions,
    monkeypatch,
):
    audit_db, auth_db = application_sessions
    monkeypatch.setattr(apply_router, "policy_enabled", lambda *_: False)
    monkeypatch.setattr(apply_router, "send_client_welcome", lambda **_: None)
    monkeypatch.setattr(
        apply_router,
        "store_upload",
        lambda path, _content, content_type: path,
    )

    app = FastAPI()
    app.include_router(apply_router.router)
    app.dependency_overrides[get_audit_db] = lambda: audit_db
    app.dependency_overrides[get_auth_db] = lambda: auth_db

    response = TestClient(app).post(
        "/apply/with-documents",
        data={
            "application": _payload().model_dump_json(),
            "company_document_count": "2",
        },
        files=[
            ("company_documents", ("Registration.pdf", b"registration", "application/pdf")),
            ("company_documents", ("Tax Certificate.pdf", b"tax", "application/pdf")),
        ],
    )

    assert response.status_code == 200
    assert response.json()["company_documents_received"] == 2
    assert audit_db.query(AuditSetCompanyDocument).count() == 2


def test_document_storage_failure_does_not_submit_application(
    application_sessions,
    monkeypatch,
):
    audit_db, auth_db = application_sessions
    monkeypatch.setattr(apply_router, "policy_enabled", lambda *_: False)
    monkeypatch.setattr(
        apply_router,
        "store_upload",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("storage down")),
    )

    with pytest.raises(HTTPException, match="documents could not be stored"):
        _submit_application(
            _payload(),
            audit_db,
            auth_db,
            [
                CompanyDocumentUpload(
                    file_name="Registration.pdf",
                    content_type="application/pdf",
                    content=b"%PDF-evidence",
                ),
            ],
        )

    assert audit_db.query(AuditSet).count() == 0
    assert auth_db.query(PlatformUser).count() == 0


def test_company_document_validation_rejects_unsafe_and_oversized_files(monkeypatch):
    unsafe = UploadFile(filename="malware.exe", file=BytesIO(b"payload"))
    with pytest.raises(HTTPException, match="Unsupported"):
        asyncio.run(_read_company_documents([unsafe]))

    monkeypatch.setattr(apply_router, "MAX_COMPANY_DOCUMENT_BYTES", 3)
    oversized = UploadFile(filename="evidence.pdf", file=BytesIO(b"1234"))
    with pytest.raises(HTTPException, match="25 MB"):
        asyncio.run(_read_company_documents([oversized]))


def test_company_document_type_is_derived_from_allowed_extension():
    upload = UploadFile(
        filename=r"C:\fakepath\company-registration.pdf",
        file=BytesIO(b"%PDF-evidence"),
    )
    documents = asyncio.run(_read_company_documents([upload]))

    assert documents[0].file_name == "company-registration.pdf"
    assert documents[0].content_type == "application/pdf"


def test_access_is_status_independent_and_scoped_to_application_owner():
    audit_set = SimpleNamespace(id="application-1", workflow_status="pending_review")
    planner = SimpleNamespace(role="planner", audit_set_id=None, auditor_id=None)
    owner = SimpleNamespace(role="client", audit_set_id="application-1", auditor_id=None)
    other_client = SimpleNamespace(role="client", audit_set_id="application-2", auditor_id=None)

    _require_document_access(audit_set, planner, None)
    _require_document_access(audit_set, owner, None)
    with pytest.raises(HTTPException, match="Not authorized"):
        _require_document_access(audit_set, other_client, None)

    audit_set.workflow_status = "certified"
    _require_document_access(audit_set, planner, None)
