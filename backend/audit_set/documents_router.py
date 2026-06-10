"""
BATUHAN — Audit set document sharing + OTP signing (Prompt 07).
CB releases generated documents to the client portal; client signs them with
an emailed 6-digit OTP. Auditor uploads completed audit deliverables back
to CB via the same table (direction='auditor_to_cb').
"""
from __future__ import annotations
import hashlib
import os
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from audit_set.db_models import AuditSet, AuditSetSharedDocument, AuditSetStatusEvent, get_db
from auth.db_models import PlatformUser, get_db as get_auth_db
from auth.dependencies import get_current_user
from config.settings import get_settings
from email_service import send_client_status_update, send_document_released, send_otp_code

router = APIRouter(prefix="/audit-sets", tags=["documents"])

CB_ROLES = {"admin", "planner", "officer", "executive"}
AUDITOR_UPLOAD_ROLES = {"auditor", "admin", "planner"}
ALLOWED_DOC_TYPES = {"quotation", "agreement", "certificate"}

OTP_EXPIRY_MINUTES = 10
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _hash_otp(otp: str) -> str:
    return hashlib.sha256(otp.encode()).hexdigest()


def _doc_to_dict(d: AuditSetSharedDocument) -> dict:
    return {
        "id":            d.id,
        "label":         d.label,
        "document_type": d.document_type,
        "direction":     d.direction,
        "status":        d.status,
        "released_at":   d.released_at.isoformat() if d.released_at else None,
        "signed_at":     d.signed_at.isoformat()   if d.signed_at   else None,
        "signed_by":     d.signed_by,
    }


def _auto_advance_workflow(
    db: Session,
    auth_db: Session,
    audit_set: AuditSet,
    expected_from: str,
    to_status: str,
    triggered_by: str,
    notes: str,
) -> None:
    """
    Document-event-driven workflow advance.
    No-op unless audit_set.workflow_status matches expected_from — keeps
    the transition idempotent if the same document action runs twice
    (e.g. CB releases a second quotation after status already moved on).

    Writes the status event in the same transaction as the workflow_status
    update. The client notification email is best-effort (swallowed) so a
    Resend outage cannot roll back the status change.
    """
    if audit_set.workflow_status != expected_from:
        return

    audit_set.workflow_status = to_status
    db.add(AuditSetStatusEvent(
        audit_set_id=audit_set.id,
        from_status=expected_from,
        to_status=to_status,
        triggered_by=triggered_by,
        notes=notes,
    ))
    db.commit()

    client_user = auth_db.query(PlatformUser).filter_by(
        audit_set_id=audit_set.id, role="client",
    ).first()
    if client_user:
        try:
            send_client_status_update(
                to=client_user.email,
                full_name=client_user.full_name,
                new_status=to_status,
                notes=notes,
            )
        except Exception:
            pass


# ── CB: release a document to the client ────────────────────────────────────

@router.post("/{audit_set_id}/documents/release")
async def release_document(
    audit_set_id: str,
    label: str = Form(...),
    document_type: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "Not authorized")
    if document_type not in ALLOWED_DOC_TYPES:
        raise HTTPException(400, f"Invalid document_type. Expected one of: {sorted(ALLOWED_DOC_TYPES)}")
    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Audit set not found")

    # Persist the uploaded file alongside auditor uploads, under a sibling folder
    settings = get_settings()
    upload_dir = os.path.join(settings.storage_base_path, "shared_docs", audit_set_id)
    os.makedirs(upload_dir, exist_ok=True)
    safe_name = f"{secrets.token_hex(6)}_{file.filename}"
    file_path = os.path.join(upload_dir, safe_name)
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    doc = AuditSetSharedDocument(
        audit_set_id=audit_set_id,
        label=label,
        document_type=document_type,
        file_path=file_path,
        direction="cb_to_client",
        status="released",
        released_by=current_user.id,
        released_at=datetime.utcnow(),
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    client_user = auth_db.query(PlatformUser).filter_by(
        audit_set_id=audit_set_id, role="client"
    ).first()
    if client_user:
        try:
            send_document_released(
                to=client_user.email,
                full_name=client_user.full_name,
                document_label=label,
            )
        except Exception:
            pass

    # Auto-advance: releasing the quotation moves planning → quotation_sent
    if document_type == "quotation":
        _auto_advance_workflow(
            db, auth_db, audit_set,
            expected_from="in_planning",
            to_status="quotation_sent",
            triggered_by=current_user.id,
            notes="Quotation document released",
        )

    return {"id": doc.id, "status": "released"}


@router.get("/{audit_set_id}/documents")
def list_documents(
    audit_set_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in CB_ROLES:
        raise HTTPException(403, "Not authorized")
    docs = (
        db.query(AuditSetSharedDocument)
        .filter_by(audit_set_id=audit_set_id)
        .order_by(AuditSetSharedDocument.created_at)
        .all()
    )
    return [_doc_to_dict(d) for d in docs]


@router.get("/{audit_set_id}/documents/{doc_id}/download")
def download_document(
    audit_set_id: str,
    doc_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    doc = db.query(AuditSetSharedDocument).filter_by(
        id=doc_id, audit_set_id=audit_set_id
    ).first()
    if not doc:
        raise HTTPException(404, "Document not found")

    if current_user.role == "client":
        if current_user.audit_set_id != audit_set_id:
            raise HTTPException(403, "Not your document")
        if doc.direction != "cb_to_client":
            raise HTTPException(403, "Not authorized")
    elif current_user.role not in CB_ROLES and current_user.role != "auditor":
        raise HTTPException(403, "Not authorized")

    if not doc.file_path or not os.path.exists(doc.file_path):
        raise HTTPException(404, "File not found on server")

    return FileResponse(doc.file_path, filename=os.path.basename(doc.file_path), media_type=DOCX_MIME)


# ── Client: OTP signing flow ────────────────────────────────────────────────

@router.post("/{audit_set_id}/documents/{doc_id}/sign/request-otp")
def request_sign_otp(
    audit_set_id: str,
    doc_id: str,
    db: Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role != "client":
        raise HTTPException(403, "Signing is for clients only")
    if current_user.audit_set_id != audit_set_id:
        raise HTTPException(403, "Not your document")

    doc = db.query(AuditSetSharedDocument).filter_by(
        id=doc_id, audit_set_id=audit_set_id, direction="cb_to_client"
    ).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    if doc.status == "signed":
        raise HTTPException(400, "Document already signed")

    otp = f"{secrets.randbelow(900000) + 100000}"
    doc.otp_hash = _hash_otp(otp)
    doc.otp_expires_at = datetime.utcnow() + timedelta(minutes=OTP_EXPIRY_MINUTES)
    db.commit()

    try:
        send_otp_code(
            to=current_user.email,
            full_name=current_user.full_name,
            otp=otp,
            document_label=doc.label,
        )
    except Exception:
        pass

    return {"message": f"OTP sent to {current_user.email}. Valid for {OTP_EXPIRY_MINUTES} minutes."}


@router.post("/{audit_set_id}/documents/{doc_id}/sign/verify")
def verify_sign_otp(
    audit_set_id: str,
    doc_id: str,
    request: Request,
    otp: str,
    db: Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role != "client":
        raise HTTPException(403, "Signing is for clients only")
    if current_user.audit_set_id != audit_set_id:
        raise HTTPException(403, "Not your document")

    doc = db.query(AuditSetSharedDocument).filter_by(
        id=doc_id, audit_set_id=audit_set_id
    ).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    if doc.status == "signed":
        raise HTTPException(400, "Already signed")
    if not doc.otp_hash or not doc.otp_expires_at:
        raise HTTPException(400, "No pending OTP. Request one first.")
    if datetime.utcnow() > doc.otp_expires_at:
        raise HTTPException(400, "OTP expired. Please request a new one.")
    if _hash_otp(otp.strip()) != doc.otp_hash:
        raise HTTPException(400, "Invalid OTP code.")

    doc.status = "signed"
    doc.signed_by = current_user.id
    doc.signed_at = datetime.utcnow()
    doc.signed_ip = request.client.host if request.client else None
    doc.otp_hash = None
    doc.otp_expires_at = None
    db.commit()

    # Auto-advance: client signing the quotation moves quotation_sent → agreement_signed
    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if audit_set:
        _auto_advance_workflow(
            db, auth_db, audit_set,
            expected_from="quotation_sent",
            to_status="agreement_signed",
            triggered_by=current_user.id,
            notes="Agreement signed by client",
        )

    return {"signed": True, "signed_at": doc.signed_at.isoformat()}


# ── Auditor: upload completed audit documents ───────────────────────────────

@router.post("/{audit_set_id}/documents/upload")
async def upload_audit_document(
    audit_set_id: str,
    label: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in AUDITOR_UPLOAD_ROLES:
        raise HTTPException(403, "Not authorized to upload audit documents")

    settings = get_settings()
    upload_dir = os.path.join(settings.storage_base_path, "audit_uploads", audit_set_id)
    os.makedirs(upload_dir, exist_ok=True)

    safe_name = f"{secrets.token_hex(6)}_{file.filename}"
    file_path = os.path.join(upload_dir, safe_name)

    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    doc = AuditSetSharedDocument(
        audit_set_id=audit_set_id,
        label=label or (file.filename or "upload"),
        document_type="audit_upload",
        file_path=file_path,
        direction="auditor_to_cb",
        status="uploaded",
        released_by=current_user.id,
        released_at=datetime.utcnow(),
    )
    db.add(doc)
    db.commit()

    # Auto-advance: auditor upload moves audit_in_progress → under_review
    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if audit_set:
        _auto_advance_workflow(
            db, auth_db, audit_set,
            expected_from="audit_in_progress",
            to_status="under_review",
            triggered_by=current_user.id,
            notes="Auditor uploaded completed documents",
        )

    return {"id": doc.id, "label": doc.label, "status": "uploaded"}

