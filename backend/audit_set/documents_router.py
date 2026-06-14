"""
BATUHAN — Audit set document sharing + visual signing (Prompt 07, Portal 49b).
CB releases generated documents to the client portal; all signatures are
placed visually via the document viewer (/viewer/sign/confirm) — OTP signing
has been removed. Auditors upload completed audit deliverables back to CB
(direction='auditor_to_cb') and clients upload FR.211 auditor assessments
(direction='client_to_cb').
"""
from __future__ import annotations
import os
import secrets
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from audit_set.db_models import (
    AuditDocumentSignature,
    AuditSet,
    AuditSetSharedDocument,
    AuditSetStage,
    AuditSetStatusEvent,
    get_db,
)
from auth.db_models import PlatformUser, get_db as get_auth_db
from auth.dependencies import get_current_user
from config.settings import get_settings
from email_service import send_client_status_update, send_document_released

router = APIRouter(prefix="/audit-sets", tags=["documents"])

CB_ROLES = {"admin", "planner", "officer", "executive", "gm"}
AUDITOR_UPLOAD_ROLES = {"auditor", "admin", "planner"}

# Portal 49b — full document-type vocabulary (Document Type Reference table)
ALLOWED_DOC_TYPES = {
    "quotation",        # FR.220
    "agreement",        # FR.221
    "audit_programme",  # FR.222 — CB only
    "fr218_review",     # FR.218 — Application Review (CB only, file-backed)
    "audit_plan",       # FR.223
    "team_info",        # FR.224 — per-auditor, private
    "meeting_form",     # FR.225
    "nc_form",          # FR.230
    "stage1_report",    # FR.231 / FR.231-1
    "stage2_report",    # FR.232 / FR.229
    "assessment",       # FR.211 — client uploads, auditors never see
    "review_decision",  # FR.233 — CB only
    "certificate",
    "audit_upload",     # legacy auditor uploads
}

# Visibility matrix (Portal 49b "Visibility Enforcement")
AUDITOR_VISIBLE_TYPES = {
    "audit_plan", "meeting_form", "nc_form",
    "stage1_report", "stage2_report", "certificate", "audit_upload",
    "fr218_review",   # visible to the appointed application reviewer (FSMS/ISMS only)
}
CLIENT_VISIBLE_TYPES = {
    "quotation", "agreement", "audit_plan", "meeting_form",
    "nc_form", "assessment", "certificate",
}

# Signature slots seeded per document type, in signing order.
# stage1/stage2 reports get an extra "reviewer" slot when FSMS/ISMS applies.
DOC_SIG_SLOTS: dict[str, list[str]] = {
    "quotation":       ["gm", "client"],
    "agreement":       ["gm", "client"],
    "audit_programme": ["cb_planner", "cb_cert_manager"],
    "fr218_review":    ["cb_planner", "cb_cert_manager"],
    "team_info":       ["assigned_auditor"],
    "audit_plan":      ["org_rep"],
    "nc_form":         ["lead_auditor", "org_rep"],
    "stage1_report":   ["lead_auditor"],
    "stage2_report":   ["lead_auditor"],
}

# Linear order of the initial-certification status machine, used for
# "status X or later" gates.
STATUS_ORDER = [
    "pending_review",
    "in_planning",
    "quotation_sent",
    "agreement_signed",
    "fr218_in_progress",
    "fr218_complete",
    "stage1_scheduled",
    "stage1_in_progress",
    "stage1_complete",
    "stage2_scheduled",
    "stage2_in_progress",
    "stage2_complete",
    "under_review",
    "committee_review",
    "certified",
]

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _status_at_least(current: Optional[str], threshold: str) -> bool:
    """True if `current` is at or past `threshold` in the status machine."""
    try:
        return STATUS_ORDER.index(current or "") >= STATUS_ORDER.index(threshold)
    except ValueError:
        return False


def _needs_reviewer(audit_set: AuditSet) -> bool:
    """FSMS/ISMS audits require a committee reviewer slot on FR.218 and stage reports.

    Standards are stored as codes ("FSMS", "ISMS") or legacy ISO strings ("ISO 22000").
    """
    standards = audit_set.standards or []
    if isinstance(standards, str):
        standards = [standards]
    joined = " ".join(str(s).upper() for s in standards)
    # Match code-style ("FSMS", "ISMS") and legacy ISO-number style ("22000", "27001")
    return any(
        kw in joined
        for kw in ("FSMS", "ISMS", "22000", "27001")
    )


def _doc_to_dict(d: AuditSetSharedDocument, db: Session | None = None) -> dict:
    result = {
        "id":                  d.id,
        "label":               d.label,
        "document_type":       d.document_type,
        "direction":           d.direction,
        "status":              d.status,
        "stage_type":          d.stage_type,
        "assigned_auditor_id": d.assigned_auditor_id,
        "released_at":         d.released_at.isoformat() if d.released_at else None,
        "signed_at":           d.signed_at.isoformat()   if d.signed_at   else None,
        "signed_by":           d.signed_by,
        "cb_sig_status":       None,
        "cb_sig_id":           None,
        "signatures":          [],
    }
    if db is not None:
        sigs = (
            db.query(AuditDocumentSignature)
            .filter(AuditDocumentSignature.document_id == d.id)
            .order_by(AuditDocumentSignature.order_index)
            .all()
        )
        result["signatures"] = [
            {
                "id":                s.id,
                "signer_role_label": s.signer_role_label,
                "order_index":       s.order_index,
                "required":          s.required,
                "signed_at":         s.signed_at.isoformat() if s.signed_at else None,
                "signer_name":       s.signer_name,
            }
            for s in sigs
        ]
        # Backward-compat fields used by older frontend code
        cb_sig = next(
            (s for s in sigs if s.signer_role_label in ("gm", "cb_planner")), None,
        )
        if cb_sig:
            result["cb_sig_status"] = "signed" if cb_sig.signed_at else "pending"
            result["cb_sig_id"] = cb_sig.id
    return result


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

    # Portal 47 — fire phase side effects (e.g. seed FR.218 slots and advance
    # to fr218_in_progress when agreement is signed).
    from audit_set.pipeline_triggers import fire_phase_triggers
    fire_phase_triggers(
        audit_set_id=audit_set.id,
        new_status=to_status,
        triggered_by=triggered_by,
        db=db,
    )

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
    release_date: Optional[date] = Form(None),
    stage_type: Optional[str] = Form(None),           # "stage_1" | "stage_2" | "surveillance"
    assigned_auditor_id: Optional[str] = Form(None),  # required for team_info (FR.224)
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

    # Portal 49b gate: cannot release the agreement (FR.221) until the
    # quotation (FR.220) has been fully signed by GM AND client.
    if document_type == "agreement":
        quotation = (
            db.query(AuditSetSharedDocument)
            .filter_by(audit_set_id=audit_set_id, document_type="quotation")
            .order_by(AuditSetSharedDocument.released_at.desc())
            .first()
        )
        if not quotation:
            raise HTTPException(
                400,
                "Cannot release the agreement before a quotation (FR.220) has been issued.",
            )
        quotation_unsigned = (
            db.query(AuditDocumentSignature)
            .filter_by(document_id=quotation.id, required=True)
            .filter(AuditDocumentSignature.signed_at.is_(None))
            .count()
        )
        if quotation_unsigned > 0:
            raise HTTPException(
                400,
                "Cannot release the agreement: the quotation (FR.220) has not been "
                "fully signed by both GM and client yet.",
            )

    # Portal 49b gates: FR.222 and FR.224 require the application review
    # (FR.218) to be complete before they can be uploaded.
    if document_type in ("audit_programme", "team_info"):
        if not _status_at_least(audit_set.workflow_status, "fr218_complete"):
            raise HTTPException(
                400,
                f"Cannot upload {document_type} before the application review "
                f"(FR.218) is complete.",
            )
    if document_type == "team_info" and not assigned_auditor_id:
        raise HTTPException(400, "team_info (FR.224) requires assigned_auditor_id")

    # Persist the uploaded file alongside auditor uploads, under a sibling folder
    settings = get_settings()
    upload_dir = os.path.join(settings.storage_base_path, "shared_docs", audit_set_id)
    os.makedirs(upload_dir, exist_ok=True)
    safe_name = f"{secrets.token_hex(6)}_{file.filename}"
    file_path = os.path.join(upload_dir, safe_name)
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    # Determine signature slots for this document type. Stage reports gain a
    # reviewer slot when FSMS/ISMS standards apply. FR.218 gains a cb_reviewer
    # slot between cb_planner and cb_cert_manager for FSMS/ISMS audits.
    slot_labels = list(DOC_SIG_SLOTS.get(document_type, []))
    if document_type in ("stage1_report", "stage2_report") and _needs_reviewer(audit_set):
        slot_labels.append("reviewer")
    if document_type == "fr218_review" and _needs_reviewer(audit_set):
        # Insert cb_reviewer between cb_planner (idx 0) and cb_cert_manager (idx 1)
        slot_labels = ["cb_planner", "cb_reviewer", "cb_cert_manager"]

    # Quotation and Agreement stay hidden from the client until the GM has
    # signed (status flips to "released" on GM sign in the viewer). All other
    # documents are visible to their audience immediately.
    requires_cb_sig = document_type in ("quotation", "agreement")
    initial_status  = "pending_cb_signature" if requires_cb_sig else "released"

    released_dt = (
        datetime.combine(release_date, datetime.min.time())
        if release_date else datetime.utcnow()
    )
    doc = AuditSetSharedDocument(
        audit_set_id=audit_set_id,
        label=label,
        document_type=document_type,
        file_path=file_path,
        direction="cb_to_client",
        status=initial_status,
        stage_type=stage_type,
        assigned_auditor_id=assigned_auditor_id,
        released_by=current_user.id,
        released_at=released_dt,
    )
    db.add(doc)
    db.flush()  # populate doc.id before linking signatures

    sig_ids = []
    for idx, role_label in enumerate(slot_labels):
        sig = AuditDocumentSignature(
            audit_set_id=audit_set_id,
            document_id=doc.id,
            document_type=document_type,
            signer_role_label=role_label,
            signer_user_id=None,   # resolved at signing time in viewer_router
            signer_name=None,
            signer_email=None,
            required=True,
            order_index=idx,
        )
        db.add(sig)
        db.flush()
        sig_ids.append(sig.id)

    db.commit()
    db.refresh(doc)

    if requires_cb_sig:
        # Workflow advance + client email are deferred to the client signature.
        return {"id": doc.id, "status": "pending_cb_signature", "signature_ids": sig_ids}

    # Notify the client only for documents they can actually see.
    if document_type in CLIENT_VISIBLE_TYPES:
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

    return {"id": doc.id, "status": "released", "signature_ids": sig_ids}


def _auditor_is_assigned(audit_set_id: str, auditor_id: Optional[str], db: Session) -> bool:
    """True if the auditor is on any stage team (lead, auditor, or TE)."""
    if not auditor_id:
        return False
    stages = db.query(AuditSetStage).filter_by(audit_set_id=audit_set_id).all()
    for stage in stages:
        if stage.lead_auditor_id == auditor_id:
            return True
        members = list(stage.auditors or []) + list(stage.technical_experts or [])
        if any(isinstance(m, dict) and m.get("id") == auditor_id for m in members):
            return True
    return False


def _visible_docs_for_user(
    audit_set_id: str, current_user: PlatformUser, db: Session,
) -> list[AuditSetSharedDocument]:
    """Apply the Portal 49b visibility matrix to the shared-documents query."""
    q = (
        db.query(AuditSetSharedDocument)
        .filter_by(audit_set_id=audit_set_id)
        .order_by(AuditSetSharedDocument.created_at)
    )
    if current_user.role in CB_ROLES:
        return q.all()

    if current_user.role == "auditor":
        if not _auditor_is_assigned(audit_set_id, current_user.auditor_id, db):
            raise HTTPException(403, "Not assigned to this audit set")
        docs = q.filter(
            AuditSetSharedDocument.document_type.in_(
                AUDITOR_VISIBLE_TYPES | {"team_info"}
            )
        ).all()
        return [
            d for d in docs
            if d.document_type != "team_info"
            or (current_user.auditor_id and d.assigned_auditor_id == current_user.auditor_id)
        ]

    if current_user.role == "client":
        return (
            q.filter(AuditSetSharedDocument.document_type.in_(CLIENT_VISIBLE_TYPES))
            .filter(AuditSetSharedDocument.status != "pending_cb_signature")
            .all()
        )

    raise HTTPException(403, "Not authorized")


@router.get("/{audit_set_id}/documents")
def list_documents(
    audit_set_id: str,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role == "client" and current_user.audit_set_id != audit_set_id:
        raise HTTPException(403, "Not your audit set")
    docs = _visible_docs_for_user(audit_set_id, current_user, db)
    return [_doc_to_dict(d, db) for d in docs]


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

    if current_user.role == "client" and current_user.audit_set_id != audit_set_id:
        raise HTTPException(403, "Not your document")
    visible_ids = {d.id for d in _visible_docs_for_user(audit_set_id, current_user, db)}
    if doc.id not in visible_ids:
        raise HTTPException(403, "Not authorized")

    if not doc.file_path or not os.path.exists(doc.file_path):
        raise HTTPException(404, "File not found on server")

    return FileResponse(doc.file_path, filename=os.path.basename(doc.file_path), media_type=DOCX_MIME)


# ── Client: FR.211 auditor assessment uploads (Phase 9.5 / 13.5) ────────────

@router.post("/{audit_set_id}/documents/assessments/upload")
async def upload_assessment(
    audit_set_id: str,
    stage_type: str = Form(...),                # "stage_1" | "stage_2"
    assigned_auditor_id: str = Form(...),       # auditor this FR.211 evaluates
    auditor_name: Optional[str] = Form(None),   # for the document label
    upload_date: Optional[date] = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """Client uploads one filled FR.211 per auditor/TE of a completed stage."""
    if current_user.role != "client":
        raise HTTPException(403, "Assessment upload is for clients only")
    if current_user.audit_set_id != audit_set_id:
        raise HTTPException(403, "Not your audit set")
    if stage_type not in ("stage_1", "stage_2"):
        raise HTTPException(400, "stage_type must be 'stage_1' or 'stage_2'")

    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Audit set not found")

    # Gates: Stage 1 batch opens after stage1_complete; Stage 2 batch after certified.
    threshold = "stage1_complete" if stage_type == "stage_1" else "certified"
    if not _status_at_least(audit_set.workflow_status, threshold):
        raise HTTPException(
            400,
            f"Assessments for {stage_type} open once the audit set reaches '{threshold}'.",
        )

    settings = get_settings()
    upload_dir = os.path.join(settings.storage_base_path, "shared_docs", audit_set_id)
    os.makedirs(upload_dir, exist_ok=True)
    safe_name = f"{secrets.token_hex(6)}_{file.filename}"
    file_path = os.path.join(upload_dir, safe_name)
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    uploaded_dt = (
        datetime.combine(upload_date, datetime.min.time())
        if upload_date else datetime.utcnow()
    )
    label = f"FR.211 Auditor Assessment — {auditor_name or assigned_auditor_id}"
    doc = AuditSetSharedDocument(
        audit_set_id=audit_set_id,
        label=label,
        document_type="assessment",
        file_path=file_path,
        direction="client_to_cb",
        status="uploaded",
        stage_type=stage_type,
        assigned_auditor_id=assigned_auditor_id,
        released_by=current_user.id,
        released_at=uploaded_dt,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return {"id": doc.id, "label": doc.label, "status": "uploaded"}


@router.post("/{audit_set_id}/documents/{doc_id}/assessments/sign")
def sign_assessment(
    audit_set_id: str,
    doc_id: str,
    request: Request,
    signed_date: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """Client signs their own uploaded FR.211 (visual signature on record)."""
    if current_user.role != "client":
        raise HTTPException(403, "Assessment signing is for clients only")
    if current_user.audit_set_id != audit_set_id:
        raise HTTPException(403, "Not your audit set")

    doc = db.query(AuditSetSharedDocument).filter_by(
        id=doc_id, audit_set_id=audit_set_id, document_type="assessment",
    ).first()
    if not doc:
        raise HTTPException(404, "Assessment not found")
    if doc.status == "signed":
        raise HTTPException(400, "Already signed")

    doc.status = "signed"
    doc.signed_by = current_user.id
    doc.signed_at = (
        datetime.combine(signed_date, datetime.min.time())
        if signed_date else datetime.utcnow()
    )
    doc.signed_ip = request.client.host if request.client else None
    db.commit()
    return {"signed": True, "signed_at": doc.signed_at.isoformat()}


# ── Auditor: upload completed audit documents ───────────────────────────────

@router.post("/{audit_set_id}/documents/upload")
async def upload_audit_document(
    audit_set_id: str,
    label: str,
    upload_date: Optional[date] = None,
    document_type: str = "audit_upload",
    stage_type: Optional[str] = None,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if current_user.role not in AUDITOR_UPLOAD_ROLES:
        raise HTTPException(403, "Not authorized to upload audit documents")
    # Auditors may upload their stage deliverables; everything else (quotation,
    # agreement, FR.222, FR.224, certificate…) goes through /documents/release.
    auditor_types = {"audit_upload", "audit_plan", "meeting_form", "nc_form",
                     "stage1_report", "stage2_report"}
    if document_type not in auditor_types:
        raise HTTPException(400, f"Invalid document_type. Expected one of: {sorted(auditor_types)}")

    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Audit set not found")

    settings = get_settings()
    upload_dir = os.path.join(settings.storage_base_path, "audit_uploads", audit_set_id)
    os.makedirs(upload_dir, exist_ok=True)

    safe_name = f"{secrets.token_hex(6)}_{file.filename}"
    file_path = os.path.join(upload_dir, safe_name)

    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    uploaded_dt = (
        datetime.combine(upload_date, datetime.min.time())
        if upload_date else datetime.utcnow()
    )
    doc = AuditSetSharedDocument(
        audit_set_id=audit_set_id,
        label=label or (file.filename or "upload"),
        document_type=document_type,
        file_path=file_path,
        direction="auditor_to_cb",
        status="uploaded",
        stage_type=stage_type,
        released_by=current_user.id,
        released_at=uploaded_dt,
    )
    db.add(doc)
    db.flush()

    # Seed visual-signature slots for typed deliverables (FR.223/225/230/231/232).
    slot_labels = list(DOC_SIG_SLOTS.get(document_type, []))
    if document_type in ("stage1_report", "stage2_report") and _needs_reviewer(audit_set):
        slot_labels.append("reviewer")
    for idx, role_label in enumerate(slot_labels):
        db.add(AuditDocumentSignature(
            audit_set_id=audit_set_id,
            document_id=doc.id,
            document_type=document_type,
            signer_role_label=role_label,
            signer_user_id=None,
            signer_name=None,
            signer_email=None,
            required=True,
            order_index=idx,
        ))
    db.commit()

    # Auto-advance: auditor upload moves audit_in_progress → under_review
    # (surveillance / recertification single-audit path only)
    _auto_advance_workflow(
        db, auth_db, audit_set,
        expected_from="audit_in_progress",
        to_status="under_review",
        triggered_by=current_user.id,
        notes="Auditor uploaded completed documents",
    )

    return {"id": doc.id, "label": doc.label, "status": "uploaded"}

