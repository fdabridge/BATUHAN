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


def _serialize(document: AuditSetCompanyDocument) -> dict:
    return {
        "id": document.id,
        "file_name": document.file_name,
        "file_type": document.file_type,
        "file_size": document.file_size,
        "uploaded_at": document.uploaded_at.isoformat() if document.uploaded_at else None,
        "uploader_name": document.uploader_name,
        "uploader_role": document.uploader_role,
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
    return [_serialize(document) for document in documents]


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

    document = (
        db.query(AuditSetCompanyDocument)
        .filter_by(id=document_id, audit_set_id=audit_set_id)
        .first()
    )
    if not document:
        raise HTTPException(404, "Company document not found")

    try:
        local_path = ensure_local(document.file_path)
    except (FileNotFoundError, OSError):
        raise HTTPException(404, "Stored company document is unavailable")
    if not os.path.isfile(local_path):
        raise HTTPException(404, "Stored company document is unavailable")

    disposition = "attachment" if download else "inline"
    return FileResponse(
        local_path,
        media_type=document.file_type,
        filename=document.file_name,
        content_disposition_type=disposition,
    )
