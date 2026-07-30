import asyncio
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from audit_set import apply_router
from audit_set.application_documents_router import _require_document_access
from audit_set.apply_router import (
    ClientApplicationSchema,
    CompanyDocumentUpload,
    _read_company_documents,
    _submit_application,
)
from audit_set.db_models import (
    AuditSet,
    AuditSetCompanyDocument,
    Base as AuditBase,
)
from auth.db_models import Base as AuthBase, PlatformUser


@pytest.fixture
def application_sessions():
    audit_engine = create_engine("sqlite:///:memory:")
    auth_engine = create_engine("sqlite:///:memory:")
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
    assert audit_set.workflow_status == "pending_review"
    assert document.audit_set_id == audit_set.id
    assert document.file_name == "Company Registration.pdf"
    assert document.file_type == "application/pdf"
    assert document.file_size == len(b"%PDF-company-evidence")
    assert document.uploader_user_id == user.id
    assert document.uploader_name == "Client User"
    assert uploaded["path"].startswith(f"company_documents/{audit_set.id}/")


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
