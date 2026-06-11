"""
Certiva — In-portal document viewer endpoints (Prompt 23).

Two endpoints used by the <CertivaDocumentViewer> React component (Prompt 24):

  GET /viewer/prepare?document_type=shared_doc&doc_id=<id>
    → Converts DOCX → PDF (lazy) + extracts [SIG:...] field coordinates.
    → Returns { fields: [...], document_type, doc_id }
    → Idempotent: safe to call multiple times; results are cached in DB.

  GET /viewer/pdf?document_type=shared_doc&doc_id=<id>
    → Streams the converted PDF bytes with Content-Type: application/pdf.
    → Returns 404 if /viewer/prepare has not been called first.

document_type values:
  "shared_doc"    → AuditSetSharedDocument (quotation, agreement, audit_plan, FR.218, FR.222)
  "audit_report"  → AuditSetAuditReport    (FR.229, FR.231, FR.232)
  "nc_form"       → AuditSetNCForm         (FR.230)
"""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from audit_set.pdf_flattener import flatten_document
from pydantic import BaseModel
from sqlalchemy.orm import Session

from audit_set.db_models import (
    AuditDocumentSignature,
    AuditSet,
    AuditSetAuditReport,
    AuditSetCommitteeMember,
    AuditSetNCForm,
    AuditSetSharedDocument,
    AuditSetStage,
    AuditSetStatusEvent,
    DocumentSignatureField,
    VisualSignaturePlacement,
    get_db,
)
from audit_set.doc_converter import prepare_document
from auth.db_models import PlatformUser, UserSignature, get_db as get_auth_db
from auth.dependencies import get_current_user
from email_service import send_document_released, send_otp_code, send_client_status_update

router = APIRouter(prefix="/viewer", tags=["viewer"])

# ── Constants ─────────────────────────────────────────────────────────────────

OTP_EXPIRY = 10  # minutes

CB_ROLES = {"admin", "planner", "officer", "executive"}

ROLE_TO_SIG: dict[str, str] = {
    "cb_planner":      "CB_PLANNER",
    "cb_cert_manager": "CB_CERT_MANAGER",
    "cb_reviewer":     "CB_REVIEWER",
    "lead_auditor":    "LEAD_AUDITOR",
}
SIG_TO_ROLE: dict[str, str] = {v: k for k, v in ROLE_TO_SIG.items()}


def _hash_otp(otp: str) -> str:
    return hashlib.sha256(otp.encode()).hexdigest()


# ── Pydantic request bodies ───────────────────────────────────────────────────

class SignOtpRequest(BaseModel):
    document_type: str
    doc_id:        str
    sig_key:       str


class SignVerifyRequest(BaseModel):
    document_type: str
    doc_id:        str
    sig_key:       str
    otp:           str


# ── Helper ────────────────────────────────────────────────────────────────────

def _resolve_docx_path(document_type: str, doc_id: str, db: Session) -> str:
    """Map (document_type, doc_id) → absolute DOCX file path."""
    path: str | None = None

    if document_type == "shared_doc":
        doc = db.query(AuditSetSharedDocument).filter_by(id=doc_id).first()
        path = doc.file_path if doc else None
    elif document_type == "audit_report":
        doc = db.query(AuditSetAuditReport).filter_by(id=doc_id).first()
        path = doc.file_path if doc else None
    elif document_type == "nc_form":
        doc = db.query(AuditSetNCForm).filter_by(id=doc_id).first()
        path = doc.file_path if doc else None
    else:
        raise HTTPException(
            400,
            f"Unknown document_type '{document_type}'. "
            "Expected: shared_doc | audit_report | nc_form",
        )

    if not path:
        raise HTTPException(404, "Document not found or has no file.")
    if not os.path.exists(path):
        raise HTTPException(404, "Document file not found on server.")

    return os.path.abspath(path)


# ── Prepare (convert + extract) ───────────────────────────────────────────────

@router.get("/prepare")
def viewer_prepare(
    document_type: str         = Query(..., description="shared_doc | audit_report | nc_form"),
    doc_id:        str         = Query(..., description="UUID of the document record"),
    db:            Session     = Depends(get_db),
    current_user:  PlatformUser = Depends(get_current_user),
):
    """
    Idempotent: converts DOCX → PDF if not already done, extracts [SIG:...] fields
    if not already in DB, returns field coordinates.

    May take 2–5 seconds on first call (LibreOffice). Subsequent calls return
    instantly from the DB cache.
    """
    docx_path = _resolve_docx_path(document_type, doc_id, db)

    try:
        result = prepare_document(docx_path, db)
    except RuntimeError as exc:
        raise HTTPException(500, f"Document preparation failed: {exc}") from exc

    # Filter out the sentinel "__none__" row from the response
    fields = [f for f in result["fields"] if f.get("sig_key") != "__none__"]

    return {
        "document_type": document_type,
        "doc_id":        doc_id,
        "fields":        fields,
    }


# ── Serve PDF ─────────────────────────────────────────────────────────────────

@router.get("/pdf")
def serve_viewer_pdf(
    document_type: str         = Query(...),
    doc_id:        str         = Query(...),
    db:            Session     = Depends(get_db),
    current_user:  PlatformUser = Depends(get_current_user),
):
    """
    Stream the converted PDF to the browser. PDF.js calls this URL directly.
    Returns 404 if /viewer/prepare has not been called first.
    """
    docx_path = _resolve_docx_path(document_type, doc_id, db)
    pdf_path  = os.path.splitext(docx_path)[0] + ".pdf"

    if not os.path.exists(pdf_path):
        raise HTTPException(
            404,
            "PDF not yet generated. Call GET /viewer/prepare first.",
        )

    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=os.path.basename(pdf_path),
    )


# ── Download signed PDF ───────────────────────────────────────────────────────

@router.get("/download-signed")
def download_signed_pdf(
    document_type: str          = Query(...),
    doc_id:        str          = Query(...),
    db:            Session      = Depends(get_db),
    auth_db:       Session      = Depends(get_auth_db),  # noqa: F841
    current_user:  PlatformUser = Depends(get_current_user),
):
    """
    Returns a flattened PDF with all completed VisualSignaturePlacements burned in.
    Falls back to the raw converted PDF if no visual placements exist.

    Requires the document to have been prepared first (/viewer/prepare).
    Accessible by any authenticated user (CB, auditor, client).
    """
    try:
        pdf_bytes = flatten_document(document_type, doc_id, db)
    except FileNotFoundError as exc:
        raise HTTPException(
            404,
            "PDF not ready. Open the document in the viewer first.",
        ) from exc
    except Exception as exc:
        raise HTTPException(500, f"Failed to generate signed PDF: {exc}") from exc

    doc_label = _get_doc_label(document_type, doc_id, db)
    safe_name = "".join(c if c.isalnum() or c in " .-" else "_" for c in doc_label)[:60]
    filename  = f"{safe_name}_signed.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Helper: _get_doc_label ────────────────────────────────────────────────────

def _get_doc_label(document_type: str, doc_id: str, db: Session) -> str:
    """Human-readable label for OTP email subject."""
    try:
        if document_type == "shared_doc":
            doc = db.query(AuditSetSharedDocument).filter_by(id=doc_id).first()
            return doc.label if doc else "Document"
        elif document_type == "audit_report":
            r = db.query(AuditSetAuditReport).filter_by(id=doc_id).first()
            return f"{r.report_form} — {r.label}" if r else "Audit Report"
        elif document_type == "nc_form":
            nc = db.query(AuditSetNCForm).filter_by(id=doc_id).first()
            return f"NC Form: {nc.label}" if nc else "NC Form"
    except Exception:
        pass
    return "Document"


# ── Helper: _assert_can_sign ──────────────────────────────────────────────────

def _assert_can_sign(
    document_type: str,
    doc_id: str,
    sig_key: str,
    current_user: PlatformUser,
    db: Session,
) -> None:
    """Raise HTTPException(403/400) if current_user may not sign sig_key."""

    if document_type == "shared_doc":
        doc = db.query(AuditSetSharedDocument).filter_by(id=doc_id).first()
        if not doc:
            raise HTTPException(404, "Document not found")

        if sig_key == "CLIENT":
            if current_user.role != "client":
                raise HTTPException(403, "Only the client account may sign this field")
            if current_user.audit_set_id != doc.audit_set_id:
                raise HTTPException(403, "This document is not for your audit set")
            if doc.status not in ("released",):
                raise HTTPException(
                    400,
                    f"Document is not available for signing (status: {doc.status}). "
                    "It may still be awaiting the CB planner's signature.",
                )
            if doc.signed_at:
                raise HTTPException(400, "Document already signed")

        else:
            if current_user.role not in CB_ROLES:
                raise HTTPException(403, "CB staff account required to sign this field")
            role_label = SIG_TO_ROLE.get(sig_key)
            if not role_label:
                raise HTTPException(400, f"Unknown sig_key '{sig_key}'")
            sig_record = db.query(AuditDocumentSignature).filter_by(
                document_id=doc_id, signer_role_label=role_label,
            ).first()
            if not sig_record:
                raise HTTPException(
                    400,
                    f"No signature slot for '{sig_key}' found on this document.",
                )
            if sig_record.signed_at:
                raise HTTPException(400, "This field has already been signed")
            if sig_record.signer_user_id is not None and sig_record.signer_user_id != current_user.id:
                raise HTTPException(403, "This signature slot is assigned to a different user")
            if sig_record.signer_user_id is None:
                eligible = (
                    role_label == "cb_cert_manager"
                    and current_user.role in ("admin", "executive")
                )
                if not eligible:
                    raise HTTPException(403, "This signature slot is not assigned to you")

    elif document_type == "audit_report":
        report = db.query(AuditSetAuditReport).filter_by(id=doc_id).first()
        if not report:
            raise HTTPException(404, "Audit report not found")

        if sig_key == "LEAD_AUDITOR":
            if report.la_signed_at:
                raise HTTPException(400, "Lead Auditor has already signed this report")
            if current_user.role == "admin":
                return
            if current_user.role != "auditor":
                raise HTTPException(403, "Auditor role required to sign this field")
            if not current_user.auditor_id:
                raise HTTPException(403, "No auditor profile linked to your account")
            stage = (
                db.query(AuditSetStage)
                .filter_by(audit_set_id=report.audit_set_id, stage_type=report.stage_type)
                .order_by(AuditSetStage.stage_order)
                .first()
            )
            if not stage or stage.lead_auditor_id != current_user.auditor_id:
                raise HTTPException(403, "Only the Lead Auditor for this stage may sign")

        elif sig_key == "CB_REVIEWER":
            if report.reviewer_signed_at:
                raise HTTPException(400, "Committee Reviewer has already signed this report")
            if current_user.role not in CB_ROLES:
                raise HTTPException(403, "CB staff account required")
            if report.status != "pending_review":
                raise HTTPException(
                    400,
                    "The Lead Auditor must sign before the Committee Reviewer can sign",
                )
            member = db.query(AuditSetCommitteeMember).filter_by(
                audit_set_id=report.audit_set_id,
                user_id=current_user.id,
                role="reviewer",
            ).first()
            if not member:
                raise HTTPException(403, "You are not the appointed committee reviewer for this audit set")

        else:
            raise HTTPException(400, f"Unexpected sig_key '{sig_key}' for audit_report")

    elif document_type == "nc_form":
        nc = db.query(AuditSetNCForm).filter_by(id=doc_id).first()
        if not nc:
            raise HTTPException(404, "NC form not found")

        if sig_key == "LEAD_AUDITOR":
            if nc.la_signed_at:
                raise HTTPException(400, "Lead Auditor has already signed this NC form")
            if current_user.role == "admin":
                return
            if current_user.role != "auditor":
                raise HTTPException(403, "Auditor role required")
            if not current_user.auditor_id:
                raise HTTPException(403, "No auditor profile linked")
            stage = (
                db.query(AuditSetStage)
                .filter_by(audit_set_id=nc.audit_set_id, stage_type=nc.stage_type)
                .order_by(AuditSetStage.stage_order)
                .first()
            )
            if not stage or stage.lead_auditor_id != current_user.auditor_id:
                raise HTTPException(403, "Only the Lead Auditor for this stage may sign")

        elif sig_key == "CLIENT":
            if nc.client_signed_at:
                raise HTTPException(400, "Client has already signed this NC form")
            if current_user.role != "client":
                raise HTTPException(403, "Client role required")
            if current_user.audit_set_id != nc.audit_set_id:
                raise HTTPException(403, "This NC form is not for your audit set")
            if nc.status != "pending_client":
                raise HTTPException(400, "The Lead Auditor must sign before the client can sign")

        else:
            raise HTTPException(400, f"Unexpected sig_key '{sig_key}' for nc_form")

    else:
        raise HTTPException(400, f"Unknown document_type '{document_type}'")


# ── Helper: _get_field_status ─────────────────────────────────────────────────

def _get_field_status(
    sig_key: str,
    document_type: str,
    doc_id: str,
    current_user: PlatformUser,
    db: Session,
    auth_db: Session,
) -> dict:
    """Return signing status for one sig_key on one document."""
    vsp = db.query(VisualSignaturePlacement).filter(
        VisualSignaturePlacement.document_type == document_type,
        VisualSignaturePlacement.doc_id == doc_id,
        VisualSignaturePlacement.sig_key == sig_key,
        VisualSignaturePlacement.signed_at.isnot(None),
    ).first()

    def _result(status: str, name: str | None = None, image: str | None = None) -> dict:
        return {"sig_key": sig_key, "status": status, "signer_name": name, "signature_image": image}

    def _user_name(user_id: str | None) -> str | None:
        if not user_id:
            return None
        u = auth_db.query(PlatformUser).filter_by(id=user_id).first()
        return u.full_name if u else None

    if document_type == "shared_doc":
        doc = db.query(AuditSetSharedDocument).filter_by(id=doc_id).first()
        if not doc:
            return _result("pending")

        if sig_key == "CLIENT":
            if doc.signed_at:
                return _result("signed", _user_name(doc.signed_by), vsp.signature_image if vsp else None)
            if (current_user.role == "client"
                    and current_user.audit_set_id == doc.audit_set_id
                    and doc.status == "released"):
                return _result("current_user")
            blocked = doc.status == "pending_cb_signature"
            return _result("blocked" if blocked else "pending")

        role_label = SIG_TO_ROLE.get(sig_key)
        if not role_label:
            return _result("pending")

        sig_record = db.query(AuditDocumentSignature).filter_by(
            document_id=doc_id, signer_role_label=role_label,
        ).first()
        if not sig_record:
            return _result("pending")

        if sig_record.signed_at:
            return _result("signed", sig_record.signer_name, vsp.signature_image if vsp else None)
        if sig_record.signer_user_id == current_user.id:
            return _result("current_user")
        if sig_record.signer_user_id is None:
            can_claim = (role_label == "cb_cert_manager" and current_user.role in ("admin", "executive"))
            if can_claim:
                return _result("current_user")
        return _result("pending")

    elif document_type == "audit_report":
        report = db.query(AuditSetAuditReport).filter_by(id=doc_id).first()
        if not report:
            return _result("pending")

        if sig_key == "LEAD_AUDITOR":
            if report.la_signed_at:
                return _result("signed", _user_name(report.la_user_id), vsp.signature_image if vsp else None)
            is_la = current_user.role == "admin"
            if not is_la and current_user.role == "auditor" and current_user.auditor_id:
                stage = (
                    db.query(AuditSetStage)
                    .filter_by(audit_set_id=report.audit_set_id, stage_type=report.stage_type)
                    .order_by(AuditSetStage.stage_order)
                    .first()
                )
                is_la = stage is not None and stage.lead_auditor_id == current_user.auditor_id
            return _result("current_user" if is_la else "pending")

        elif sig_key == "CB_REVIEWER":
            if report.reviewer_signed_at:
                return _result("signed", _user_name(report.reviewer_user_id), vsp.signature_image if vsp else None)
            if not report.la_signed_at:
                return _result("blocked")
            member = db.query(AuditSetCommitteeMember).filter_by(
                audit_set_id=report.audit_set_id,
                user_id=current_user.id,
                role="reviewer",
            ).first()
            return _result("current_user" if member else "pending")

        return _result("pending")

    elif document_type == "nc_form":
        nc = db.query(AuditSetNCForm).filter_by(id=doc_id).first()
        if not nc:
            return _result("pending")

        if sig_key == "LEAD_AUDITOR":
            if nc.la_signed_at:
                return _result("signed", _user_name(nc.la_user_id), vsp.signature_image if vsp else None)
            is_la = current_user.role == "admin"
            if not is_la and current_user.role == "auditor" and current_user.auditor_id:
                stage = (
                    db.query(AuditSetStage)
                    .filter_by(audit_set_id=nc.audit_set_id, stage_type=nc.stage_type)
                    .order_by(AuditSetStage.stage_order)
                    .first()
                )
                is_la = stage is not None and stage.lead_auditor_id == current_user.auditor_id
            return _result("current_user" if is_la else "pending")

        elif sig_key == "CLIENT":
            if nc.client_signed_at:
                return _result("signed", _user_name(nc.client_user_id), vsp.signature_image if vsp else None)
            if not nc.la_signed_at:
                return _result("blocked")
            if (current_user.role == "client"
                    and current_user.audit_set_id == nc.audit_set_id
                    and nc.status == "pending_client"):
                return _result("current_user")
            return _result("pending")

        return _result("pending")

    return _result("pending")


# ── Helper: _commit_existing_signing_record ────────────────────────────────────

def _commit_existing_signing_record(
    document_type: str,
    doc_id: str,
    sig_key: str,
    current_user: PlatformUser,
    ip: str | None,
    db: Session,
    auth_db: Session,
) -> None:
    """Update existing signing tables so workflow/legal state stays consistent."""
    now = datetime.utcnow()

    if document_type == "shared_doc":
        if sig_key == "CLIENT":
            doc = db.query(AuditSetSharedDocument).filter_by(id=doc_id).first()
            if not doc or doc.signed_at:
                return
            doc.status         = "signed"
            doc.signed_by      = current_user.id
            doc.signed_at      = now
            doc.signed_ip      = ip
            doc.otp_hash       = None
            doc.otp_expires_at = None

            audit_set = db.query(AuditSet).filter_by(id=doc.audit_set_id).first()
            if audit_set and doc.document_type == "agreement":
                if audit_set.workflow_status in ("quotation_sent", "quotation_accepted"):
                    old_status = audit_set.workflow_status
                    audit_set.workflow_status = "agreement_signed"
                    db.add(AuditSetStatusEvent(
                        audit_set_id=doc.audit_set_id,
                        from_status=old_status,
                        to_status="agreement_signed",
                        triggered_by=current_user.id,
                        notes="Agreement signed by client via Certiva viewer",
                    ))
            db.commit()

        else:
            role_label = SIG_TO_ROLE.get(sig_key)
            if not role_label:
                return
            sig_record = db.query(AuditDocumentSignature).filter_by(
                document_id=doc_id, signer_role_label=role_label,
            ).first()
            if not sig_record or sig_record.signed_at:
                return

            if sig_record.signer_user_id is None:
                sig_record.signer_user_id = current_user.id
                sig_record.signer_name    = current_user.full_name
                sig_record.signer_email   = current_user.email

            sig_record.signed_at      = now
            sig_record.signed_ip      = ip
            sig_record.otp_hash       = None
            sig_record.otp_expires_at = None

            # Flush pending ORM changes to the DB (session has autoflush=False)
            # so the count below sees sig_record.signed_at as non-NULL.
            db.flush()

            remaining = (
                db.query(AuditDocumentSignature)
                .filter_by(document_id=doc_id, required=True)
                .filter(AuditDocumentSignature.signed_at.is_(None))
                .count()
            )
            doc = db.query(AuditSetSharedDocument).filter_by(id=doc_id).first()
            if doc and remaining == 0 and doc.status == "pending_cb_signature":
                doc.status = "released"
                audit_set = db.query(AuditSet).filter_by(id=doc.audit_set_id).first()
                if audit_set and doc.document_type == "quotation":
                    if audit_set.workflow_status == "in_planning":
                        audit_set.workflow_status = "quotation_sent"
                        db.add(AuditSetStatusEvent(
                            audit_set_id=doc.audit_set_id,
                            from_status="in_planning",
                            to_status="quotation_sent",
                            triggered_by=current_user.id,
                            notes="Quotation signed by CB planner and released via viewer",
                        ))
                db.commit()

                client_user = auth_db.query(PlatformUser).filter_by(
                    audit_set_id=doc.audit_set_id, role="client",
                ).first()
                if client_user:
                    try:
                        send_document_released(
                            to=client_user.email,
                            full_name=client_user.full_name,
                            document_label=doc.label,
                        )
                    except Exception:
                        pass
            else:
                db.commit()

    elif document_type == "audit_report":
        report = db.query(AuditSetAuditReport).filter_by(id=doc_id).first()
        if not report:
            return

        if sig_key == "LEAD_AUDITOR" and not report.la_signed_at:
            report.la_user_id     = current_user.id
            report.la_signed_at   = now
            report.la_signed_ip   = ip
            report.la_otp_hash    = None
            report.la_otp_expires = None
            report.status         = "pending_review"
            db.commit()

            member = db.query(AuditSetCommitteeMember).filter_by(
                audit_set_id=report.audit_set_id, role="reviewer",
            ).first()
            if member:
                try:
                    send_otp_code(
                        to=member.user_email,
                        full_name=member.user_name,
                        otp="[REVIEW NOTIFICATION]",
                        document_label=(
                            f"{report.report_form} — {report.label} is ready for your review"
                        ),
                    )
                except Exception:
                    pass

        elif sig_key == "CB_REVIEWER" and not report.reviewer_signed_at:
            report.reviewer_user_id     = current_user.id
            report.reviewer_signed_at   = now
            report.reviewer_signed_ip   = ip
            report.reviewer_otp_hash    = None
            report.reviewer_otp_expires = None
            report.status               = "approved"
            db.commit()

            audit_set = db.query(AuditSet).filter_by(id=report.audit_set_id).first()
            if audit_set and audit_set.workflow_status == "under_review":
                audit_set.workflow_status  = "certified"
                audit_set.cert_issued_date = now.date()
                db.add(AuditSetStatusEvent(
                    audit_set_id=report.audit_set_id,
                    from_status="under_review",
                    to_status="certified",
                    triggered_by=current_user.id,
                    notes=(
                        f"Audit report '{report.report_form} — {report.label}' "
                        "approved by committee reviewer via viewer"
                    ),
                ))
                db.commit()
                try:
                    client_user = auth_db.query(PlatformUser).filter_by(
                        audit_set_id=report.audit_set_id, role="client",
                    ).first()
                    if client_user:
                        send_client_status_update(
                            to=client_user.email,
                            full_name=client_user.full_name,
                            new_status="certified",
                            notes=(
                                "Your audit report has been reviewed and approved "
                                "by the certification committee."
                            ),
                        )
                except Exception:
                    pass

    elif document_type == "nc_form":
        nc = db.query(AuditSetNCForm).filter_by(id=doc_id).first()
        if not nc:
            return

        if sig_key == "LEAD_AUDITOR" and not nc.la_signed_at:
            nc.la_user_id     = current_user.id
            nc.la_signed_at   = now
            nc.la_signed_ip   = ip
            nc.la_otp_hash    = None
            nc.la_otp_expires = None
            nc.status         = "pending_client"
            db.commit()

            client_user = auth_db.query(PlatformUser).filter_by(
                audit_set_id=nc.audit_set_id, role="client",
            ).first()
            if client_user:
                try:
                    send_document_released(
                        to=client_user.email,
                        full_name=client_user.full_name,
                        document_label=f"NC Form: {nc.label}",
                    )
                except Exception:
                    pass

        elif sig_key == "CLIENT" and not nc.client_signed_at:
            nc.client_user_id     = current_user.id
            nc.client_signed_at   = now
            nc.client_signed_ip   = ip
            nc.client_otp_hash    = None
            nc.client_otp_expires = None
            nc.status             = "complete"
            db.commit()


# ── New endpoint: GET /viewer/signing-status ──────────────────────────────────

@router.get("/signing-status")
def viewer_signing_status(
    document_type: str          = Query(..., description="shared_doc | audit_report | nc_form"),
    doc_id:        str          = Query(...),
    db:            Session      = Depends(get_db),
    auth_db:       Session      = Depends(get_auth_db),
    current_user:  PlatformUser = Depends(get_current_user),
):
    """
    Returns the signing status for every [SIG:KEY] field in a document.
    Status values: signed | current_user | pending | blocked
    """
    docx_path = _resolve_docx_path(document_type, doc_id, db)

    sig_key_rows = (
        db.query(DocumentSignatureField.sig_key)
        .filter(
            DocumentSignatureField.docx_path == docx_path,
            DocumentSignatureField.sig_key != "__none__",
        )
        .distinct()
        .all()
    )
    sig_keys = [row.sig_key for row in sig_key_rows]

    fields = [
        _get_field_status(sk, document_type, doc_id, current_user, db, auth_db)
        for sk in sig_keys
    ]

    return {
        "document_type": document_type,
        "doc_id":        doc_id,
        "fields":        fields,
    }


# ── New endpoint: POST /viewer/sign/request-otp ───────────────────────────────

@router.post("/sign/request-otp")
def sign_request_otp(
    body:         SignOtpRequest,
    db:           Session      = Depends(get_db),
    auth_db:      Session      = Depends(get_auth_db),  # noqa: F841
    current_user: PlatformUser = Depends(get_current_user),
):
    """
    Validate authorization, create/update a pending VisualSignaturePlacement,
    generate an OTP, and email it to the user.
    """
    _assert_can_sign(body.document_type, body.doc_id, body.sig_key, current_user, db)

    vsp = (
        db.query(VisualSignaturePlacement)
        .filter_by(
            document_type=body.document_type,
            doc_id=body.doc_id,
            sig_key=body.sig_key,
            user_id=current_user.id,
        )
        .filter(VisualSignaturePlacement.signed_at.is_(None))
        .first()
    )
    if not vsp:
        vsp = VisualSignaturePlacement(
            document_type=body.document_type,
            doc_id=body.doc_id,
            sig_key=body.sig_key,
            user_id=current_user.id,
        )
        db.add(vsp)

    otp = f"{secrets.randbelow(900000) + 100000}"
    vsp.otp_hash    = _hash_otp(otp)
    vsp.otp_expires = datetime.utcnow() + timedelta(minutes=OTP_EXPIRY)
    db.commit()

    doc_label = _get_doc_label(body.document_type, body.doc_id, db)
    try:
        send_otp_code(
            to=current_user.email,
            full_name=current_user.full_name,
            otp=otp,
            document_label=doc_label,
        )
    except Exception:
        pass

    return {"message": f"Verification code sent to {current_user.email}. Valid for {OTP_EXPIRY} minutes."}


# ── New endpoint: POST /viewer/sign/verify ────────────────────────────────────

@router.post("/sign/verify")
def sign_verify(
    body:         SignVerifyRequest,
    request:      Request,
    db:           Session      = Depends(get_db),
    auth_db:      Session      = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """
    Verify OTP, record VisualSignaturePlacement with the user's signature image,
    then mirror the signing event into the existing legal/workflow signing tables.
    """
    vsp = (
        db.query(VisualSignaturePlacement)
        .filter_by(
            document_type=body.document_type,
            doc_id=body.doc_id,
            sig_key=body.sig_key,
            user_id=current_user.id,
        )
        .filter(VisualSignaturePlacement.signed_at.is_(None))
        .first()
    )
    if not vsp:
        raise HTTPException(400, "No pending signing session. Please request a verification code first.")
    if not vsp.otp_hash or not vsp.otp_expires:
        raise HTTPException(400, "No verification code is pending. Please request one first.")
    if datetime.utcnow() > vsp.otp_expires:
        raise HTTPException(400, "Verification code expired. Please request a new one.")
    if _hash_otp(body.otp.strip()) != vsp.otp_hash:
        raise HTTPException(400, "Invalid code. Please check and try again.")

    user_sig = auth_db.query(UserSignature).filter_by(user_id=current_user.id).first()

    ip = request.client.host if request.client else None
    vsp.signature_image = user_sig.image_data if user_sig else None
    vsp.otp_hash        = None
    vsp.otp_expires     = None
    vsp.signed_at       = datetime.utcnow()
    vsp.signed_ip       = ip
    db.commit()

    _commit_existing_signing_record(
        body.document_type, body.doc_id, body.sig_key, current_user, ip, db, auth_db,
    )

    return {
        "signed":    True,
        "sig_key":   body.sig_key,
        "signed_at": vsp.signed_at.isoformat(),
    }
