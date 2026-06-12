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

import os
import re
from datetime import datetime, date
from typing import Optional

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
    ClientOrgEmployee,
    DocumentSignatureField,
    VisualSignaturePlacement,
    get_db,
)
from audit_set.doc_converter import prepare_document
from auth.db_models import PlatformUser, UserSignature, get_db as get_auth_db
from auth.dependencies import get_current_user
from email_service import send_document_released
router = APIRouter(prefix="/viewer", tags=["viewer"])

# ── Constants ─────────────────────────────────────────────────────────────────

CB_ROLES = {"admin", "planner", "officer", "executive", "gm"}

ROLE_TO_SIG: dict[str, str] = {
    "cb_planner":       "CB_PLANNER",
    "cb_cert_manager":  "CB_CERT_MANAGER",
    "cb_reviewer":      "CB_REVIEWER",
    "lead_auditor":     "LEAD_AUDITOR",
    "gm":               "GM",
    # Portal 49b — pipeline rebuild slots
    "org_rep":          "ORG_REP",
    "assigned_auditor": "ASSIGNED_AUDITOR",
    "reviewer":         "REVIEWER",
}
SIG_TO_ROLE: dict[str, str] = {v: k for k, v in ROLE_TO_SIG.items()}

# Portal 49a Part 2 — FR.225 organisation-personnel signature slots.
# Format: ORG_OPENING_ORG_EMP_<uuid> or ORG_CLOSING_ORG_EMP_<uuid>
ORG_SIG_RE = re.compile(
    r"^ORG_(OPENING|CLOSING)_ORG_EMP_([0-9a-fA-F-]{36})$"
)

# Portal 49a Part 3 — FR.233 certification committee signature slots.
COMMITTEE_SIG_KEYS = {"COMMITTEE_CHAIR", "COMMITTEE_MEMBER_1", "COMMITTEE_MEMBER_2"}
CERT_MANAGER_FR233_KEY = "CERT_MANAGER_FR233"


# ── Pydantic request bodies ───────────────────────────────────────────────────

class SignConfirmRequest(BaseModel):
    document_type: str
    doc_id:        str
    sig_key:       str
    signed_date:   Optional[date] = None  # user-selected signing date; defaults to today


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
    """Human-readable label for downloads and notifications."""
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


# ── Helper: committee sig permission (Portal 49a Part 3) ─────────────────────

def _check_committee_sig(
    sig_key: str, audit_set_id: str, current_user: PlatformUser, db: Session,
) -> None:
    """Raise HTTPException(403) if `current_user` may not sign `sig_key` on FR.233."""
    if sig_key == CERT_MANAGER_FR233_KEY:
        if current_user.role not in ("admin", "executive"):
            raise HTTPException(
                403, "Only the Certification Manager may sign this slot",
            )
        return

    members = (
        db.query(AuditSetCommitteeMember)
        .filter_by(audit_set_id=audit_set_id)
        .order_by(AuditSetCommitteeMember.appointed_at)
        .all()
    )
    chair = next((m for m in members if m.role == "decision_maker"), None)
    non_chairs = [m for m in members if m is not chair]

    expected_user_id: str | None = None
    if sig_key == "COMMITTEE_CHAIR":
        expected_user_id = chair.user_id if chair else None
    elif sig_key == "COMMITTEE_MEMBER_1":
        expected_user_id = non_chairs[0].user_id if len(non_chairs) > 0 else None
    elif sig_key == "COMMITTEE_MEMBER_2":
        expected_user_id = non_chairs[1].user_id if len(non_chairs) > 1 else None

    if expected_user_id is None:
        raise HTTPException(400, f"No committee member assigned for '{sig_key}'")
    if expected_user_id != current_user.id:
        raise HTTPException(403, "This signature slot is assigned to a different committee member")


# ── Helpers: shared-doc slot eligibility + order gating (Portal 49b) ─────────

def _find_stage(db: Session, audit_set_id: str, stage_type: str | None) -> AuditSetStage | None:
    q = db.query(AuditSetStage).filter_by(audit_set_id=audit_set_id)
    if stage_type:
        q = q.filter_by(stage_type=stage_type)
    return q.order_by(AuditSetStage.stage_order).first()


def _shared_slot_eligible(
    role_label: str,
    doc: AuditSetSharedDocument,
    current_user: PlatformUser,
    db: Session,
) -> bool:
    """True if current_user may claim an unassigned shared-doc signature slot."""
    role = current_user.role
    if role_label == "gm":
        return role in ("gm", "admin")
    if role_label == "cb_planner":
        return role in ("planner", "admin")
    if role_label == "cb_cert_manager":
        return role in ("admin", "executive")
    if role_label == "org_rep":
        return role == "client" and current_user.audit_set_id == doc.audit_set_id
    if role_label == "assigned_auditor":
        return (
            role == "auditor"
            and current_user.auditor_id is not None
            and doc.assigned_auditor_id == current_user.auditor_id
        )
    if role_label == "lead_auditor":
        if role == "admin":
            return True
        if role != "auditor" or not current_user.auditor_id:
            return False
        stage = _find_stage(db, doc.audit_set_id, doc.stage_type)
        return stage is not None and stage.lead_auditor_id == current_user.auditor_id
    if role_label == "reviewer":
        member = db.query(AuditSetCommitteeMember).filter_by(
            audit_set_id=doc.audit_set_id, user_id=current_user.id, role="reviewer",
        ).first()
        return member is not None
    return False


def _prior_slots_unsigned(doc_id: str, order_index: int | None, db: Session) -> int:
    """Count required slots earlier in the signing order that are still unsigned."""
    if not order_index:
        return 0
    return (
        db.query(AuditDocumentSignature)
        .filter_by(document_id=doc_id, required=True)
        .filter(AuditDocumentSignature.order_index < order_index)
        .filter(AuditDocumentSignature.signed_at.is_(None))
        .count()
    )


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
                    "It may still be awaiting the General Manager's signature.",
                )
            if doc.signed_at:
                raise HTTPException(400, "Document already signed")

        elif ORG_SIG_RE.match(sig_key):
            # Portal 49a Part 2 — FR.225 organisation-personnel signing.
            # The client user signs on behalf of one of their roster employees;
            # the stored snapshot is the employee's own saved signature image.
            if current_user.role != "client":
                raise HTTPException(403, "Only the client account may sign organisation slots")
            if current_user.audit_set_id != doc.audit_set_id:
                raise HTTPException(403, "This document is not for your audit set")
            employee_id = ORG_SIG_RE.match(sig_key).group(2)
            emp = db.query(ClientOrgEmployee).filter_by(id=employee_id, is_active=True).first()
            if not emp or emp.client_user_id != current_user.id:
                raise HTTPException(404, "Employee not in your roster")
            if not emp.signature_data:
                raise HTTPException(
                    400,
                    f"{emp.full_name} has no signature on file. "
                    "Go to Employees, upload their signature, then try again.",
                )

        elif sig_key in COMMITTEE_SIG_KEYS or sig_key == CERT_MANAGER_FR233_KEY:
            # Portal 49a Part 3 — FR.233 committee signing handled below by
            # _check_committee_sig (needs audit_set_id, computed from doc).
            _check_committee_sig(sig_key, doc.audit_set_id, current_user, db)

        else:
            # Portal 49b — generic slot-based signing (GM, CB_*, ORG_REP,
            # ASSIGNED_AUDITOR, LEAD_AUDITOR, REVIEWER). Eligibility is per
            # role label; order gating is enforced via order_index.
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
            if sig_record.signer_user_id is None and not _shared_slot_eligible(
                role_label, doc, current_user, db,
            ):
                raise HTTPException(403, "This signature slot is not assigned to you")
            if _prior_slots_unsigned(doc_id, sig_record.order_index, db) > 0:
                raise HTTPException(
                    400,
                    "An earlier signature on this document is still pending. "
                    "Signatures must be placed in order.",
                )

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
        if _prior_slots_unsigned(doc_id, sig_record.order_index, db) > 0:
            return _result("blocked")
        if sig_record.signer_user_id == current_user.id:
            return _result("current_user")
        if sig_record.signer_user_id is None and _shared_slot_eligible(
            role_label, doc, current_user, db,
        ):
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
    signed_at: Optional[datetime] = None,
) -> None:
    """Update existing signing tables so workflow/legal state stays consistent."""
    now = signed_at if signed_at is not None else datetime.utcnow()

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

            # Portal 49b — mark the seeded CLIENT slot signed so "fully
            # signed" gates (e.g. FR.221 release requires FR.220 complete)
            # count it.
            client_slot = db.query(AuditDocumentSignature).filter_by(
                document_id=doc_id, signer_role_label="client",
            ).first()
            if client_slot and not client_slot.signed_at:
                client_slot.signer_user_id = current_user.id
                client_slot.signer_name    = current_user.full_name
                client_slot.signer_email   = current_user.email
                client_slot.signed_at      = now
                client_slot.signed_ip      = ip

            audit_set = db.query(AuditSet).filter_by(id=doc.audit_set_id).first()
            advanced_to: str | None = None
            if audit_set and doc.document_type == "quotation":
                # Portal 49b gate chain: quotation_sent fires when the client
                # signs FR.220 (GM signature is enforced upstream by the
                # released-status gate in _assert_can_sign).
                if audit_set.workflow_status == "in_planning":
                    audit_set.workflow_status = "quotation_sent"
                    db.add(AuditSetStatusEvent(
                        audit_set_id=doc.audit_set_id,
                        from_status="in_planning",
                        to_status="quotation_sent",
                        triggered_by=current_user.id,
                        notes="Quotation signed by client via Certiva viewer",
                    ))
                    advanced_to = "quotation_sent"
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
                    advanced_to = "agreement_signed"
            db.commit()

            # Portal 47 — fire phase side effects (e.g. seed FR.218 slots)
            if advanced_to:
                from audit_set.pipeline_triggers import fire_phase_triggers
                fire_phase_triggers(
                    audit_set_id=doc.audit_set_id,
                    new_status=advanced_to,
                    triggered_by=current_user.id,
                    db=db,
                )

        elif ORG_SIG_RE.match(sig_key):
            # Portal 49a Part 2 — placement was already saved in sign_confirm.
            # No workflow status change is associated with org-attendee signing.
            return

        elif sig_key in COMMITTEE_SIG_KEYS or sig_key == CERT_MANAGER_FR233_KEY:
            # Portal 49a Part 3 — FR.233 signing. Placement is already saved.
            # Update AuditSetFR233Record and (for the CM slot) the audit set's
            # workflow status.
            from audit_set.db_models import AuditSetFR233Record
            doc = db.query(AuditSetSharedDocument).filter_by(id=doc_id).first()
            if not doc:
                return
            record = db.query(AuditSetFR233Record).filter_by(
                audit_set_id=doc.audit_set_id,
            ).first()
            if record and record.status == "pending":
                record.status = "signing"

            if sig_key == CERT_MANAGER_FR233_KEY:
                # Require all committee slots signed first.
                committee_signed = (
                    db.query(VisualSignaturePlacement)
                    .filter_by(document_type="shared_doc", doc_id=doc_id)
                    .filter(VisualSignaturePlacement.sig_key.in_(list(COMMITTEE_SIG_KEYS)))
                    .filter(VisualSignaturePlacement.signed_at.isnot(None))
                    .count()
                )
                committee_total = len({
                    row.sig_key for row in (
                        db.query(DocumentSignatureField.sig_key)
                        .filter(DocumentSignatureField.docx_path == os.path.abspath(doc.file_path or ""))
                        .filter(DocumentSignatureField.sig_key.in_(list(COMMITTEE_SIG_KEYS)))
                        .distinct()
                        .all()
                    )
                })
                if committee_total > 0 and committee_signed >= committee_total:
                    if record:
                        record.status = "complete"
                    audit_set = db.query(AuditSet).filter_by(id=doc.audit_set_id).first()
                    if audit_set and audit_set.workflow_status != "certified":
                        old = audit_set.workflow_status
                        audit_set.workflow_status  = "certified"
                        audit_set.cert_issued_date = now.date()
                        db.add(AuditSetStatusEvent(
                            audit_set_id=doc.audit_set_id,
                            from_status=old,
                            to_status="certified",
                            triggered_by=current_user.id,
                            notes="FR.233 signed by Certification Manager",
                        ))
            db.commit()
            return

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
            # so the counts below see sig_record.signed_at as non-NULL.
            db.flush()

            remaining_all = (
                db.query(AuditDocumentSignature)
                .filter_by(document_id=doc_id, required=True)
                .filter(AuditDocumentSignature.signed_at.is_(None))
                .count()
            )
            remaining_cb = (
                db.query(AuditDocumentSignature)
                .filter_by(document_id=doc_id, required=True)
                .filter(AuditDocumentSignature.signer_role_label != "client")
                .filter(AuditDocumentSignature.signed_at.is_(None))
                .count()
            )
            doc = db.query(AuditSetSharedDocument).filter_by(id=doc_id).first()
            advanced_to: str | None = None
            if doc:
                # Portal 49b — GM (and any other CB-side slots) complete →
                # release the document to the client for counter-signing.
                # Status transitions (quotation_sent / agreement_signed) now
                # fire on the CLIENT signature, not on release.
                if doc.status == "pending_cb_signature" and remaining_cb == 0:
                    doc.status = "released"
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

                if remaining_all == 0:
                    if doc.document_type not in ("quotation", "agreement"):
                        doc.status = "signed"
                    # Gate chain: stage reports fully signed → auto-advance.
                    completion_map = {
                        "stage1_report": ("stage1_in_progress", "stage1_complete"),
                        "stage2_report": ("stage2_in_progress", "stage2_complete"),
                    }
                    step = completion_map.get(doc.document_type)
                    audit_set = db.query(AuditSet).filter_by(id=doc.audit_set_id).first()
                    if audit_set and step and audit_set.workflow_status == step[0]:
                        audit_set.workflow_status = step[1]
                        db.add(AuditSetStatusEvent(
                            audit_set_id=doc.audit_set_id,
                            from_status=step[0],
                            to_status=step[1],
                            triggered_by=current_user.id,
                            notes=f"All signatures completed on {doc.label}",
                        ))
                        advanced_to = step[1]
            db.commit()

            if doc and advanced_to:
                from audit_set.pipeline_triggers import fire_phase_triggers
                fire_phase_triggers(
                    audit_set_id=doc.audit_set_id,
                    new_status=advanced_to,
                    triggered_by=current_user.id,
                    db=db,
                )

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

        elif sig_key == "CB_REVIEWER" and not report.reviewer_signed_at:
            report.reviewer_user_id     = current_user.id
            report.reviewer_signed_at   = now
            report.reviewer_signed_ip   = ip
            report.reviewer_otp_hash    = None
            report.reviewer_otp_expires = None
            report.status               = "approved"
            db.commit()
            # Portal 49a Part 3: the CB reviewer signing the audit report no
            # longer auto-advances the set to ``certified``. Certification now
            # requires the Cert Manager to sign FR.233 (see shared_doc branch
            # below for CERT_MANAGER_FR233).

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


# ── New endpoint: POST /viewer/sign/confirm ───────────────────────────────────

@router.post("/sign/confirm")
def sign_confirm(
    body:         SignConfirmRequest,
    request:      Request,
    db:           Session      = Depends(get_db),
    auth_db:      Session      = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """
    Direct sign endpoint — no OTP required.
    Validates authorization, records VisualSignaturePlacement with the user's
    saved signature image, then mirrors the event into workflow/legal tables
    via _commit_existing_signing_record.
    """
    _assert_can_sign(body.document_type, body.doc_id, body.sig_key, current_user, db)

    # Resolve the signature image to embed. For ORG_OPENING_*/ORG_CLOSING_* the
    # image is the employee's saved signature; for everything else it is the
    # current user's UserSignature.
    org_match = ORG_SIG_RE.match(body.sig_key)
    if org_match:
        emp = db.query(ClientOrgEmployee).filter_by(id=org_match.group(2)).first()
        if not emp or not emp.signature_data:
            raise HTTPException(400, "Employee signature missing — re-upload and try again.")
        signature_image_b64 = emp.signature_data
    else:
        user_sig = auth_db.query(UserSignature).filter_by(user_id=current_user.id).first()
        if not user_sig:
            raise HTTPException(
                400,
                "No signature on file. Go to Settings → My Signature to set one up, then try again.",
            )
        signature_image_b64 = user_sig.image_data

    # Reuse or create the pending VisualSignaturePlacement row.
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

    ip = request.client.host if request.client else None
    signed_at = (
        datetime.combine(body.signed_date, datetime.min.time())
        if body.signed_date else datetime.utcnow()
    )
    vsp.signature_image = signature_image_b64
    vsp.otp_hash        = None
    vsp.otp_expires     = None
    vsp.signed_at       = signed_at
    vsp.signed_ip       = ip
    db.commit()

    _commit_existing_signing_record(
        body.document_type, body.doc_id, body.sig_key, current_user, ip, db, auth_db,
        signed_at=signed_at,
    )

    return {
        "signed":    True,
        "sig_key":   body.sig_key,
        "signed_at": vsp.signed_at.isoformat(),
    }
