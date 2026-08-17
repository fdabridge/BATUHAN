"""Role-gated access to company documents submitted with an application."""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from audit_set.db_models import (
    AuditSet,
    AuditSetCompanyDocument,
    AuditSetStage,
    get_db,
)
from auth.db_models import PlatformUser
from auth.dependencies import get_current_user
from storage.document_store import ensure_local

router = APIRouter(prefix="/audit-sets", tags=["application-documents"])

INTERNAL_DOCUMENT_ROLES = {
    "admin",
    "planner",
    "planner_us",
    "officer",
    "executive",
    "gm",
    "certification_manager",
}


def _auditor_is_assigned(db: Session, audit_set_id: str, auditor_id: str | None) -> bool:
    if not auditor_id:
        return False
    stages = db.query(AuditSetStage).filter_by(audit_set_id=audit_set_id).all()
    for stage in stages:
        if stage.lead_auditor_id == auditor_id:
            return True
        groups = (
            stage.auditors or [],
            stage.technical_experts or [],
            stage.observers or [],
            stage.trainees or [],
            stage.ik_experts or [],
            stage.evaluators or [],
        )
        if any(
            isinstance(member, dict) and member.get("id") == auditor_id
            for group in groups
            for member in group
        ):
            return True
    return False


def _require_document_access(
    audit_set: AuditSet,
    current_user: PlatformUser,
    db: Session,
) -> None:
    """Authorize without consulting workflow_status.

    Planner access must work at pending_review, while client access is limited
    to the application linked to that account. Assigned auditors retain access
    later in the certification process.
    """
    if current_user.role in INTERNAL_DOCUMENT_ROLES:
        return
    if current_user.role == "client" and current_user.audit_set_id == audit_set.id:
        return
    if (
        current_user.role == "auditor"
        and _auditor_is_assigned(db, audit_set.id, current_user.auditor_id)
    ):
        return
    raise HTTPException(403, "Not authorized to access these company documents")


def _manifest_documents(audit_set: AuditSet) -> list[dict]:
    """Return validated recovery entries stored on the application itself."""
    application_data = audit_set.application_data or {}
    manifest = application_data.get("company_document_manifest", [])
    if not isinstance(manifest, list):
        return []
    return [
        item
        for item in manifest
        if isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and isinstance(item.get("file_path"), str)
        and isinstance(item.get("file_name"), str)
    ]


def _value(document: AuditSetCompanyDocument | dict, field: str, default=None):
    return document.get(field, default) if isinstance(document, dict) else getattr(document, field, default)


def _serialize(document: AuditSetCompanyDocument | dict) -> dict:
    uploaded_at = _value(document, "uploaded_at")
    return {
        "id": _value(document, "id"),
        "file_name": _value(document, "file_name"),
        "file_type": _value(document, "file_type", "application/octet-stream"),
        "file_size": _value(document, "file_size", 0),
        "uploaded_at": uploaded_at.isoformat() if hasattr(uploaded_at, "isoformat") else uploaded_at,
        "uploader_name": _value(document, "uploader_name", "Client"),
        "uploader_role": _value(document, "uploader_role", "client"),
    }


@router.get("/{audit_set_id}/company-documents")
def list_company_documents(
    audit_set_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Application not found")
    _require_document_access(audit_set, current_user, db)

    documents = (
        db.query(AuditSetCompanyDocument)
        .filter_by(audit_set_id=audit_set_id)
        .order_by(AuditSetCompanyDocument.uploaded_at, AuditSetCompanyDocument.file_name)
        .all()
    )
    # Prefer normalized rows, then recover any missing entries from the
    # application-owned manifest. This is deliberately additive so existing
    # applications without a manifest keep their current behavior.
    known_ids = {document.id for document in documents}
    recovered = [
        document
        for document in _manifest_documents(audit_set)
        if document["id"] not in known_ids
    ]
    return [_serialize(document) for document in [*documents, *recovered]]


@router.get("/{audit_set_id}/company-documents/{document_id}/file")
def get_company_document_file(
    audit_set_id: str,
    document_id: str,
    download: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Application not found")
    _require_document_access(audit_set, current_user, db)

    document: AuditSetCompanyDocument | dict | None = (
        db.query(AuditSetCompanyDocument)
        .filter_by(id=document_id, audit_set_id=audit_set_id)
        .first()
    )
    if not document:
        document = next(
            (
                entry
                for entry in _manifest_documents(audit_set)
                if entry["id"] == document_id
            ),
            None,
        )
    if not document:
        raise HTTPException(404, "Company document not found")

    try:
        local_path = ensure_local(_value(document, "file_path"))
    except (FileNotFoundError, OSError):
        raise HTTPException(404, "Stored company document is unavailable")
    if not os.path.isfile(local_path):
        raise HTTPException(404, "Stored company document is unavailable")

    disposition = "attachment" if download else "inline"
    return FileResponse(
        local_path,
        media_type=_value(document, "file_type", "application/octet-stream"),
        filename=_value(document, "file_name", "company-document"),
        content_disposition_type=disposition,
    )
