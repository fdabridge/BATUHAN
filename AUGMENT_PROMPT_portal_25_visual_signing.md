# Prompt 25 — Visual Signing + OTP Commit

## Context

This is the Certiva platform. We are building a DocuSign-like signing layer for in-portal PDF documents.

Completed so far:
- **Prompt 21**: `[SIG:PARTY]` placeholders injected into all DOCX templates.
- **Prompt 22**: `user_signatures` table; every user can draw or upload a personal signature (Settings page in all 3 portals).
- **Prompt 23**: DOCX → PDF conversion (LibreOffice), pdfplumber coordinate extraction, `document_signature_fields` table, `/viewer/prepare` and `/viewer/pdf` endpoints.
- **Prompt 24**: `CertivaDocumentViewer` React component — PDF.js canvas render + clickable `[SIG:...]` overlay boxes; standalone viewer page `/viewer/[type]/[id]`; `onSignatureClick` stub that fires `alert()`.

**Prompt 25 (this one)** wires up `onSignatureClick` to a real signing flow:
1. User clicks their `"current_user"` (green pulsing) box → `SignatureConfirmDialog` opens.
2. Dialog shows their saved signature image + "Send verification code" button.
3. They click → backend generates OTP, emails it to them.
4. They enter the code → backend verifies OTP, records `VisualSignaturePlacement` (stores their signature image), and mirrors the signing event into the existing legal/workflow signing tables.
5. Dialog closes, viewer re-fetches signing status → box turns green with their name and signature image.

FR.225 (meeting attendance — guest token flow) is intentionally **out of scope** for this prompt; it was already handled in Prompt 17.

---

## Files to change — summary

| # | File | Action |
|---|------|--------|
| 1 | `backend/audit_set/db_models.py` | Add `VisualSignaturePlacement` model; add column-safety migration entries |
| 2 | `backend/audit_set/viewer_router.py` | Add 3 new endpoints + ~200 lines of helper functions |
| 3 | `frontend/src/components/SignatureConfirmDialog.tsx` | **New file** |
| 4 | `frontend/src/components/CertivaDocumentViewer.tsx` | Add `'blocked'` to `SigStatus`; render blocked state in `SignatureBox`; add `onPrepared` callback |
| 5 | `frontend/src/app/(app)/viewer/[type]/[id]/page.tsx` | Replace stub `alert()` with full signing flow |

---

## 1. `backend/audit_set/db_models.py`

### 1a. Add `VisualSignaturePlacement` model

Add this class **after** `DocumentSignatureField` and before the `create_tables()` call:

```python
# ---------------------------------------------------------------------------
# Table 14 — visual_signature_placements
# Records the visual signature placement for each [SIG:KEY] field.
# Created when a user completes OTP verification via the in-portal viewer.
# One row per (document_type, doc_id, sig_key) — upserted on re-sign.
# Separate from the existing signing tables (AuditDocumentSignature,
# AuditSetSharedDocument.signed_at, etc.) — those remain the legal/workflow
# source of truth. This table stores the signature IMAGE for PDF flattening
# (Prompt 26) and for display in the viewer.
# ---------------------------------------------------------------------------

class VisualSignaturePlacement(Base):
    __tablename__ = "visual_signature_placements"

    id              = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    document_type   = Column(String, nullable=False)   # shared_doc | audit_report | nc_form
    doc_id          = Column(String, nullable=False, index=True)
    sig_key         = Column(String, nullable=False)   # CB_PLANNER | CB_REVIEWER | etc.
    user_id         = Column(String, nullable=False)   # PlatformUser.id who placed it
    signature_image = Column(Text, nullable=True)      # base64 PNG data-URL snapshot at sign time
    otp_hash        = Column(String, nullable=True)    # sha256; cleared after use
    otp_expires     = Column(DateTime, nullable=True)  # cleared after use
    signed_at       = Column(DateTime, nullable=True)  # set on successful OTP verification
    signed_ip       = Column(String, nullable=True)
    created_at      = Column(DateTime, default=datetime.utcnow, nullable=False)
```

### 1b. Add to `_safe_add_column` / migration helpers

In `create_tables()` (or wherever the `_safe_add_column_audit` helper is used to add columns that may already exist from previous deployments), add:

```python
_safe_add_column_audit(engine, "visual_signature_placements", "otp_hash",        "TEXT")
_safe_add_column_audit(engine, "visual_signature_placements", "otp_expires",      "TIMESTAMP")
_safe_add_column_audit(engine, "visual_signature_placements", "signed_ip",        "TEXT")
```

`Base.metadata.create_all(engine)` will create the table itself on first deploy; the `_safe_add_column` calls guard against re-running on an existing DB with the table already created but missing columns.

---

## 2. `backend/audit_set/viewer_router.py`

### 2a. New imports

Add to the existing imports at the top of the file:

```python
import hashlib
import secrets
from datetime import timedelta

from fastapi import Body, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

# Already present — ensure these are included:
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
from auth.db_models import PlatformUser, UserSignature, get_db as get_auth_db
from auth.dependencies import get_current_user
from audit_set.doc_converter import prepare_document
from email_service import send_document_released, send_otp_code, send_client_status_update
```

### 2b. New module-level constants (add near the top, after imports)

```python
OTP_EXPIRY = 10  # minutes

CB_ROLES = {"admin", "planner", "officer", "executive"}

# Maps AuditDocumentSignature.signer_role_label ↔ [SIG:KEY] placeholder key
ROLE_TO_SIG: dict[str, str] = {
    "cb_planner":      "CB_PLANNER",
    "cb_cert_manager": "CB_CERT_MANAGER",
    "cb_reviewer":     "CB_REVIEWER",
    "lead_auditor":    "LEAD_AUDITOR",
}
SIG_TO_ROLE: dict[str, str] = {v: k for k, v in ROLE_TO_SIG.items()}


def _hash_otp(otp: str) -> str:
    return hashlib.sha256(otp.encode()).hexdigest()
```

### 2c. Pydantic request bodies

```python
class SignOtpRequest(BaseModel):
    document_type: str   # shared_doc | audit_report | nc_form
    doc_id:        str
    sig_key:       str   # CB_PLANNER | CB_REVIEWER | LEAD_AUDITOR | CLIENT | etc.


class SignVerifyRequest(BaseModel):
    document_type: str
    doc_id:        str
    sig_key:       str
    otp:           str
```

### 2d. Helper: `_get_doc_label`

```python
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
```

### 2e. Helper: `_assert_can_sign`

This validates that `current_user` is authorized to sign `sig_key` on the given document **right now** (correct role, correct assignment, correct document state). Raises `HTTPException` on failure.

```python
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
                    f"No signature slot for '{sig_key}' found on this document. "
                    "Has the document been released with the correct signature setup?",
                )
            if sig_record.signed_at:
                raise HTTPException(400, "This field has already been signed")
            if sig_record.signer_user_id is not None and sig_record.signer_user_id != current_user.id:
                raise HTTPException(403, "This signature slot is assigned to a different user")
            if sig_record.signer_user_id is None:
                # Unassigned — only cb_cert_manager slots can be self-claimed by admin/executive
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
                return  # admin bypass for testing
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
```

### 2f. Helper: `_get_field_status`

Per-(sig_key, document) — returns a dict with `sig_key`, `status`, `signer_name`, `signature_image`.

```python
def _get_field_status(
    sig_key: str,
    document_type: str,
    doc_id: str,
    current_user: PlatformUser,
    db: Session,
    auth_db: Session,
) -> dict:
    """Return signing status for one sig_key on one document."""
    # Check for a completed visual placement (provides signature image)
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

    # ── shared_doc ────────────────────────────────────────────────────────────
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
            # Document not yet released to client (CB hasn't signed yet)
            blocked = doc.status == "pending_cb_signature"
            return _result("blocked" if blocked else "pending")

        # CB-side field
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
            # Unassigned — check if current user can claim it
            can_claim = (role_label == "cb_cert_manager" and current_user.role in ("admin", "executive"))
            if can_claim:
                return _result("current_user")
        return _result("pending")

    # ── audit_report ──────────────────────────────────────────────────────────
    elif document_type == "audit_report":
        report = db.query(AuditSetAuditReport).filter_by(id=doc_id).first()
        if not report:
            return _result("pending")

        if sig_key == "LEAD_AUDITOR":
            if report.la_signed_at:
                return _result("signed", _user_name(report.la_user_id), vsp.signature_image if vsp else None)
            # Check if current user is the LA
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
            # Block if LA hasn't signed yet
            if not report.la_signed_at:
                return _result("blocked")
            member = db.query(AuditSetCommitteeMember).filter_by(
                audit_set_id=report.audit_set_id,
                user_id=current_user.id,
                role="reviewer",
            ).first()
            return _result("current_user" if member else "pending")

        return _result("pending")

    # ── nc_form ───────────────────────────────────────────────────────────────
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
```

### 2g. Helper: `_commit_existing_signing_record`

After OTP is verified and `VisualSignaturePlacement` is written, this function mirrors the event into the existing legal/workflow signing tables (same logic as the existing `signatures_router`, `documents_router`, `report_router`, `nc_router` verify endpoints).

```python
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

    # ── shared_doc ────────────────────────────────────────────────────────────
    if document_type == "shared_doc":
        if sig_key == "CLIENT":
            doc = db.query(AuditSetSharedDocument).filter_by(id=doc_id).first()
            if not doc or doc.signed_at:
                return  # guard: already signed or gone
            doc.status         = "signed"
            doc.signed_by      = current_user.id
            doc.signed_at      = now
            doc.signed_ip      = ip
            doc.otp_hash       = None
            doc.otp_expires_at = None

            # Auto-advance workflow (mirrors documents_router.verify_sign_otp)
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
            # CB-side field — mirror into AuditDocumentSignature
            role_label = SIG_TO_ROLE.get(sig_key)
            if not role_label:
                return
            sig_record = db.query(AuditDocumentSignature).filter_by(
                document_id=doc_id, signer_role_label=role_label,
            ).first()
            if not sig_record or sig_record.signed_at:
                return  # guard

            # Self-assign if slot is unassigned (cb_cert_manager claim)
            if sig_record.signer_user_id is None:
                sig_record.signer_user_id = current_user.id
                sig_record.signer_name    = current_user.full_name
                sig_record.signer_email   = current_user.email

            sig_record.signed_at      = now
            sig_record.signed_ip      = ip
            sig_record.otp_hash       = None
            sig_record.otp_expires_at = None

            # Check if all required signatures are now collected → release doc
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

                # Notify client
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

    # ── audit_report ──────────────────────────────────────────────────────────
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

            # Notify appointed committee reviewer (mirrors report_router.la_verify_otp)
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
            report.reviewer_user_id      = current_user.id
            report.reviewer_signed_at    = now
            report.reviewer_signed_ip    = ip
            report.reviewer_otp_hash     = None
            report.reviewer_otp_expires  = None
            report.status                = "approved"
            db.commit()

            # Auto-advance workflow: under_review → certified
            # (mirrors report_router.review_verify_otp)
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

    # ── nc_form ───────────────────────────────────────────────────────────────
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

            # Notify client (mirrors nc_router.la_verify_otp)
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
```

### 2h. New endpoint: `GET /viewer/signing-status`

```python
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
    Reads field keys from document_signature_fields (populated by /viewer/prepare).
    If the document has not been prepared yet, returns an empty fields list.

    Status values:
      "signed"       — field has been signed; includes signer_name and signature_image (if visual)
      "current_user" — the calling user is the designated signer for this field, and may sign now
      "pending"      — waiting for another person (not the calling user)
      "blocked"      — sequential signing: the prior signer must sign first (e.g. reviewer before LA)
    """
    docx_path = _resolve_docx_path(document_type, doc_id, db)

    # Get sig_keys from document_signature_fields.
    # If empty, the document hasn't been prepared yet — viewer will call /prepare first.
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
```

### 2i. New endpoint: `POST /viewer/sign/request-otp`

```python
@router.post("/sign/request-otp")
def sign_request_otp(
    body:         SignOtpRequest,
    db:           Session      = Depends(get_db),
    auth_db:      Session      = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """
    Validate authorization, create/update a pending VisualSignaturePlacement,
    generate an OTP, and email it to the user.
    """
    # 1. Validate
    _assert_can_sign(body.document_type, body.doc_id, body.sig_key, current_user, db)

    # 2. Get or create a pending (unsigned) placement record for this user
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

    # 3. Generate and store OTP
    otp = f"{secrets.randbelow(900000) + 100000}"
    vsp.otp_hash    = _hash_otp(otp)
    vsp.otp_expires = datetime.utcnow() + timedelta(minutes=OTP_EXPIRY)
    db.commit()

    # 4. Send OTP email
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
```

### 2j. New endpoint: `POST /viewer/sign/verify`

```python
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
    # 1. Find the pending placement (unsigned, for this user)
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

    # 2. Fetch the user's saved signature image (snapshot at sign time)
    user_sig = auth_db.query(UserSignature).filter_by(user_id=current_user.id).first()

    # 3. Mark visual placement complete
    ip = request.client.host if request.client else None
    vsp.signature_image = user_sig.image_data if user_sig else None
    vsp.otp_hash        = None
    vsp.otp_expires     = None
    vsp.signed_at       = datetime.utcnow()
    vsp.signed_ip       = ip
    db.commit()

    # 4. Mirror into existing legal/workflow signing tables
    _commit_existing_signing_record(
        body.document_type, body.doc_id, body.sig_key, current_user, ip, db, auth_db,
    )

    return {
        "signed":    True,
        "sig_key":   body.sig_key,
        "signed_at": vsp.signed_at.isoformat(),
    }
```

---

## 3. `frontend/src/components/SignatureConfirmDialog.tsx` (new file)

Create this file in its entirety:

```tsx
'use client'

/**
 * SignatureConfirmDialog — Signs a [SIG:KEY] field via OTP.
 *
 * Flow:
 *   1. Fetches user's saved signature from /me/signature.
 *   2. Shows preview + "Send code" button.
 *   3. User clicks → POST /viewer/sign/request-otp.
 *   4. Shows OTP input + "Confirm signature" button.
 *   5. User enters code → POST /viewer/sign/verify.
 *   6. On success: calls onSigned(sigKey) and auto-closes.
 */

import { useEffect, useRef, useState } from 'react'
import { AlertCircle, CheckCircle2, Loader2, PenLine, X } from 'lucide-react'
import api from '@/lib/api'

// ── Types ─────────────────────────────────────────────────────────────────────

type Stage = 'loading' | 'no_signature' | 'preview' | 'otp_sent' | 'verifying' | 'success'

interface Props {
  isOpen:       boolean
  sigKey:       string
  documentType: string   // "shared_doc" | "audit_report" | "nc_form"
  docId:        string
  onClose:      () => void
  onSigned:     (sigKey: string) => void
}

const SIG_KEY_LABELS: Record<string, string> = {
  CB_PLANNER:      'Planning Officer',
  CB_CERT_MANAGER: 'Certification Manager',
  CB_REVIEWER:     'Committee Reviewer',
  LEAD_AUDITOR:    'Lead Auditor',
  CLIENT:          'Organisation Representative',
  AUDITOR_MEMBER:  'Audit Team Member',
}

// ── Component ─────────────────────────────────────────────────────────────────

export function SignatureConfirmDialog({
  isOpen, sigKey, documentType, docId, onClose, onSigned,
}: Props) {
  const [stage,     setStage]     = useState<Stage>('loading')
  const [sigImage,  setSigImage]  = useState<string | null>(null)
  const [otp,       setOtp]       = useState('')
  const [errorMsg,  setErrorMsg]  = useState('')
  const [statusMsg, setStatusMsg] = useState('')
  const otpRef = useRef<HTMLInputElement>(null)

  // Reset and load signature on open
  useEffect(() => {
    if (!isOpen) return
    setStage('loading')
    setOtp('')
    setErrorMsg('')
    setStatusMsg('')

    api.get('/me/signature')
      .then((r) => {
        if (r.data?.has_signature && r.data?.image_data) {
          setSigImage(r.data.image_data)
          setStage('preview')
        } else {
          setSigImage(null)
          setStage('no_signature')
        }
      })
      .catch(() => {
        setSigImage(null)
        setStage('no_signature')
      })
  }, [isOpen, sigKey])

  // Auto-focus OTP input
  useEffect(() => {
    if (stage === 'otp_sent') {
      const t = setTimeout(() => otpRef.current?.focus(), 80)
      return () => clearTimeout(t)
    }
  }, [stage])

  async function handleRequestOtp() {
    setErrorMsg('')
    setStatusMsg('Sending verification code…')
    try {
      const r = await api.post('/viewer/sign/request-otp', {
        document_type: documentType,
        doc_id:        docId,
        sig_key:       sigKey,
      })
      setStatusMsg(r.data.message ?? 'Code sent to your email.')
      setStage('otp_sent')
    } catch (e: any) {
      setErrorMsg(e.response?.data?.detail ?? 'Failed to send code. Please try again.')
      setStatusMsg('')
    }
  }

  async function handleVerify() {
    if (otp.length !== 6) return
    setStage('verifying')
    setErrorMsg('')
    try {
      await api.post('/viewer/sign/verify', {
        document_type: documentType,
        doc_id:        docId,
        sig_key:       sigKey,
        otp:           otp.trim(),
      })
      setStage('success')
      setTimeout(() => onSigned(sigKey), 1400)
    } catch (e: any) {
      setErrorMsg(e.response?.data?.detail ?? 'Invalid code. Please try again.')
      setStage('otp_sent')
    }
  }

  if (!isOpen) return null

  const roleLabel = SIG_KEY_LABELS[sigKey] ?? sigKey
  const busy      = stage === 'verifying'

  return (
    /* Backdrop */
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-md overflow-hidden rounded-xl bg-white shadow-2xl">

        {/* ── Header ── */}
        <div className="flex items-center justify-between border-b px-6 py-4">
          <div className="flex items-center gap-2.5">
            <PenLine size={17} className="text-[#1A4731]" />
            <h2 className="text-sm font-semibold text-gray-900">
              Sign as {roleLabel}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded p-1 text-gray-400 hover:text-gray-600 disabled:opacity-40"
          >
            <X size={17} />
          </button>
        </div>

        {/* ── Body ── */}
        <div className="px-6 py-5 space-y-4">

          {/* Loading */}
          {stage === 'loading' && (
            <div className="flex items-center justify-center gap-2 py-10 text-sm text-gray-400">
              <Loader2 size={18} className="animate-spin" /> Loading…
            </div>
          )}

          {/* No signature — prompt user to create one */}
          {stage === 'no_signature' && (
            <>
              <p className="text-sm text-gray-600">
                You don't have a saved signature yet. Go to{' '}
                <strong>Settings → My Signature</strong> to draw or upload your signature, then come back.
              </p>
              <a
                href="/settings/signature"
                target="_blank"
                rel="noreferrer"
                className="block w-full rounded-lg border-2 border-dashed border-[#1A4731] py-3 text-center
                  text-sm font-medium text-[#1A4731] hover:bg-[#1A4731]/5 transition-colors"
              >
                Set up my signature →
              </a>
              <p className="text-xs text-gray-400 text-center">
                Opens in a new tab. Save your signature, then close this dialog and try again.
              </p>
            </>
          )}

          {/* Preview + send code */}
          {stage === 'preview' && (
            <>
              <p className="text-sm text-gray-600">
                Your saved signature will be placed on the document. Click{' '}
                <strong>Send verification code</strong> to proceed.
              </p>

              {/* Signature preview */}
              <div
                className="flex items-center justify-center rounded-lg p-4"
                style={{
                  background:
                    'repeating-conic-gradient(#e5e7eb 0% 25%, #fff 0% 50%) 0 0 / 12px 12px',
                  minHeight: 90,
                }}
              >
                {sigImage ? (
                  <img
                    src={sigImage}
                    alt="Your signature"
                    className="max-h-20 max-w-full object-contain drop-shadow"
                  />
                ) : (
                  <span className="text-xs italic text-gray-400">No image preview</span>
                )}
              </div>

              {statusMsg && <p className="text-xs text-[#1A4731]">{statusMsg}</p>}

              {errorMsg && (
                <div className="flex items-start gap-1.5 rounded-lg bg-red-50 p-3 text-sm text-red-600">
                  <AlertCircle size={15} className="mt-0.5 shrink-0" />
                  {errorMsg}
                </div>
              )}

              <button
                type="button"
                onClick={handleRequestOtp}
                className="w-full rounded-lg bg-[#1A4731] py-2.5 text-sm font-medium
                  text-white hover:bg-[#1A4731]/90 active:scale-[0.98] transition-all"
              >
                Send verification code
              </button>
            </>
          )}

          {/* OTP entry */}
          {stage === 'otp_sent' && (
            <>
              <p className="text-sm text-gray-600">
                {statusMsg || 'A 6-digit code has been sent to your email address.'}
              </p>

              <input
                ref={otpRef}
                type="text"
                inputMode="numeric"
                maxLength={6}
                value={otp}
                onChange={(e) => setOtp(e.target.value.replace(/\D/g, '').slice(0, 6))}
                onKeyDown={(e) => e.key === 'Enter' && otp.length === 6 && handleVerify()}
                placeholder="000000"
                className="w-full rounded-lg border border-gray-300 px-4 py-3.5 text-center
                  text-2xl font-mono tracking-[0.5em]
                  focus:border-[#1A4731] focus:outline-none focus:ring-2 focus:ring-[#1A4731]/20"
              />

              {errorMsg && (
                <div className="flex items-start gap-1.5 rounded-lg bg-red-50 p-3 text-sm text-red-600">
                  <AlertCircle size={15} className="mt-0.5 shrink-0" />
                  {errorMsg}
                </div>
              )}

              <button
                type="button"
                onClick={handleVerify}
                disabled={otp.length !== 6}
                className="w-full rounded-lg bg-[#1A4731] py-2.5 text-sm font-medium
                  text-white hover:bg-[#1A4731]/90 disabled:opacity-40
                  active:scale-[0.98] transition-all"
              >
                Confirm signature
              </button>

              <button
                type="button"
                onClick={() => { setStage('preview'); setOtp(''); setErrorMsg('') }}
                className="w-full text-sm text-gray-500 hover:text-gray-700"
              >
                ← Back
              </button>
            </>
          )}

          {/* Verifying spinner */}
          {stage === 'verifying' && (
            <div className="flex items-center justify-center gap-2 py-10 text-sm text-gray-500">
              <Loader2 size={18} className="animate-spin text-[#1A4731]" />
              Verifying signature…
            </div>
          )}

          {/* Success */}
          {stage === 'success' && (
            <div className="flex flex-col items-center gap-3 py-8 text-center">
              <CheckCircle2 size={44} className="text-[#1A4731]" />
              <p className="font-semibold text-gray-800">Signed successfully</p>
              <p className="text-sm text-gray-500">
                Your signature has been recorded on this document.
              </p>
            </div>
          )}

        </div>
      </div>
    </div>
  )
}
```

---

## 4. `frontend/src/components/CertivaDocumentViewer.tsx` — add `'blocked'` status

### 4a. Extend the `SigStatus` type

```typescript
// BEFORE:
export type SigStatus = 'pending' | 'current_user' | 'signed'

// AFTER:
export type SigStatus = 'pending' | 'current_user' | 'signed' | 'blocked'
```

### 4b. Add `Lock` to the lucide-react import

```typescript
// BEFORE:
import {
  ChevronLeft, ChevronRight, CheckCircle2, Clock,
  Loader2, PenLine, AlertTriangle,
} from 'lucide-react'

// AFTER:
import {
  ChevronLeft, ChevronRight, CheckCircle2, Clock, Lock,
  Loader2, PenLine, AlertTriangle,
} from 'lucide-react'
```

### 4c. Update `SignatureBox` — add `blocked` branch

In the `SignatureBox` function, add the `blocked` case immediately before the final `return` (the `pending` state):

```typescript
  // Add this block just before the final return (pending state):
  if (status === 'blocked') {
    return (
      <div
        style={style}
        className="pointer-events-none flex flex-col items-center justify-center
          gap-1 rounded border border-dashed border-gray-300 bg-gray-50/80"
      >
        <Lock size={13} className="text-gray-300" />
        <span className="text-center text-[10px] text-gray-400 leading-tight px-1">
          {sigLabel(field.sig_key)}<br />Waiting for prior signer
        </span>
      </div>
    )
  }
```

### 4d. Update the legend to handle `blocked`

In the legend section at the bottom of the component, update the status display:

```typescript
// BEFORE the ov.status ternary in the legend:
<span className={`h-2.5 w-2.5 rounded-full ${
  ov.status === 'signed'        ? 'bg-emerald-500'
  : ov.status === 'current_user' ? 'bg-[#1A4731] animate-pulse'
  : 'bg-gray-300'
}`} />

// AFTER:
<span className={`h-2.5 w-2.5 rounded-full ${
  ov.status === 'signed'        ? 'bg-emerald-500'
  : ov.status === 'current_user' ? 'bg-[#1A4731] animate-pulse'
  : ov.status === 'blocked'     ? 'bg-gray-200'
  : 'bg-gray-300'
}`} />

// BEFORE the status text:
{ov.status === 'signed'
  ? (ov.signer_name ? `✓ ${ov.signer_name}` : '✓ Signed')
  : ov.status === 'current_user' ? 'Your signature' : 'Awaiting'}

// AFTER:
{ov.status === 'signed'
  ? (ov.signer_name ? `✓ ${ov.signer_name}` : '✓ Signed')
  : ov.status === 'current_user' ? 'Your signature'
  : ov.status === 'blocked'      ? 'Waiting for prior signer'
  : 'Awaiting'}
```

### 4e. Add `onPrepared` callback prop

This lets the viewer page know when `/viewer/prepare` has returned so it can safely call `/viewer/signing-status` (which reads from `document_signature_fields`, populated by `/prepare`).

```typescript
// Extend CertivaDocumentViewerProps:
interface CertivaDocumentViewerProps {
  documentType:        DocumentType
  docId:               string
  signatureOverrides?: SignatureOverride[]
  onSignatureClick?:   (sigKey: string) => void
  onPrepared?:         () => void   // ← ADD THIS
}

// In the component destructuring:
export function CertivaDocumentViewer({
  documentType,
  docId,
  signatureOverrides = [],
  onSignatureClick,
  onPrepared,          // ← ADD THIS
}: CertivaDocumentViewerProps) {
```

In the `load()` function inside `useEffect`, fire `onPrepared()` right after the `/prepare` call succeeds (before the PDF fetch):

```typescript
// After: setRawFields((prepareRes.data.fields as RawField[]) ?? [])
// Add:
onPrepared?.()
```

This fires `onPrepared` once the `DocumentSignatureField` records are guaranteed to exist in the DB, so the parent's `/signing-status` call will return the correct sig_keys.

---

## 5. `frontend/src/app/(app)/viewer/[type]/[id]/page.tsx`

Replace the entire file with:

```tsx
'use client'

import { useCallback, useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { ArrowLeft } from 'lucide-react'
import api from '@/lib/api'
import {
  CertivaDocumentViewer,
  type DocumentType,
  type SignatureOverride,
} from '@/components/CertivaDocumentViewer'
import { SignatureConfirmDialog } from '@/components/SignatureConfirmDialog'

const VALID_TYPES: DocumentType[] = ['shared_doc', 'audit_report', 'nc_form']

export default function ViewerPage() {
  const params = useParams()
  const router = useRouter()
  const documentType = params.type as DocumentType
  const docId        = params.id   as string

  const [overrides,     setOverrides]     = useState<SignatureOverride[]>([])
  const [activeSigKey,  setActiveSigKey]  = useState<string | null>(null)
  const [docPrepared,   setDocPrepared]   = useState(false)

  // Load signing status — only after the document has been prepared
  const loadStatus = useCallback(async () => {
    try {
      const r = await api.get('/viewer/signing-status', {
        params: { document_type: documentType, doc_id: docId },
      })
      setOverrides(r.data.fields ?? [])
    } catch {
      // fail silently — boxes default to "pending" if status unavailable
    }
  }, [documentType, docId])

  // Fetch signing status once the viewer signals it's prepared the document
  useEffect(() => {
    if (docPrepared) {
      loadStatus()
    }
  }, [docPrepared, loadStatus])

  if (!VALID_TYPES.includes(documentType)) {
    return (
      <div className="p-8 text-sm text-red-600">
        Unknown document type: <code>{documentType}</code>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen flex-col">
      {/* Header */}
      <div className="sticky top-0 z-10 flex items-center gap-3 border-b bg-white px-6 py-3 shadow-sm">
        <button
          type="button"
          onClick={() => router.back()}
          className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800"
        >
          <ArrowLeft size={16} />
          Back
        </button>
        <span className="text-sm font-medium text-gray-700 capitalize">
          {documentType.replace(/_/g, ' ')}
        </span>
      </div>

      {/* PDF Viewer */}
      <CertivaDocumentViewer
        documentType={documentType}
        docId={docId}
        signatureOverrides={overrides}
        onSignatureClick={(sigKey) => setActiveSigKey(sigKey)}
        onPrepared={() => setDocPrepared(true)}
      />

      {/* Signing dialog */}
      <SignatureConfirmDialog
        isOpen={activeSigKey !== null}
        sigKey={activeSigKey ?? ''}
        documentType={documentType}
        docId={docId}
        onClose={() => setActiveSigKey(null)}
        onSigned={(sk) => {
          setActiveSigKey(null)
          loadStatus()  // refresh overlays after signing
        }}
      />
    </div>
  )
}
```

---

## FR.225 — out of scope

FR.225 (Meeting Attendance) uses the guest-token signing flow built in Prompt 17. Meeting attendees are NOT Certiva users — they sign via a tokenized link delivered by email (`AuditSetMeetingAttendee.token`). The in-portal viewer is for authenticated users only; it does not apply to FR.225 guests. This prompt does not change the guest signing flow.

---

## What is NOT changing

- `backend/audit_set/signatures_router.py` — the existing CB OTP signing endpoints remain unchanged.
- `backend/audit_set/documents_router.py` — the existing client OTP signing endpoints remain unchanged.
- `backend/audit_set/report_router.py` — the existing LA + reviewer OTP endpoints remain unchanged.
- `backend/audit_set/nc_router.py` — unchanged.
- Neither the existing "Sign" buttons on the portal pages nor any existing OTP flow is removed. Both flows (portal button AND viewer box) write to the same underlying signing records — they are idempotent: the second one is a no-op because `signed_at` is already set.
- `backend/auth/user_signature_router.py` — already has `GET /me/signature` from Prompt 22. No changes needed.

---

## Dependency notes

- `UserSignature` is in `auth/db_models.py` — imported via `from auth.db_models import PlatformUser, UserSignature, get_db as get_auth_db`.
- `send_client_status_update` must be importable from `email_service`. If it doesn't exist yet, add a minimal stub:
  ```python
  def send_client_status_update(to, full_name, new_status, notes=""):
      pass  # TODO: implement proper email template
  ```

---

## Verification checklist

1. `GET /viewer/signing-status?document_type=shared_doc&doc_id=<id>` returns a `fields` array with correct `status` per sig_key.
2. `POST /viewer/sign/request-otp` with `sig_key="CLIENT"` from a client account sends an OTP email and returns a 200 with `message`.
3. `POST /viewer/sign/verify` with correct OTP:
   - Sets `VisualSignaturePlacement.signed_at` and stores `signature_image`.
   - Sets `AuditSetSharedDocument.signed_at` (for CLIENT) or `AuditDocumentSignature.signed_at` (for CB fields).
   - Returns `{"signed": true, "sig_key": "...", "signed_at": "..."}`.
4. Viewer page: after `onPrepared` fires, `/viewer/signing-status` is called and overlays update.
5. After signing via the dialog, `loadStatus()` re-runs and the box turns green with the signer's name.
6. Signing a doc already signed via the old OTP button returns a 400 with "already signed".
7. A `blocked` sig_key (e.g. CB_REVIEWER before LA has signed) renders as a non-clickable gray box in the viewer.
8. `SignatureConfirmDialog` with no saved signature shows the "Set up my signature →" link.

---

## Commit message

```
feat(viewer): visual signing + OTP commit flow (Prompt 25)

Backend:
- audit_set/db_models.py: add VisualSignaturePlacement model (Table 14)
  stores signature_image + OTP fields; one row per (doc_type, doc_id, sig_key)
- audit_set/viewer_router.py: add 3 new endpoints:
  GET  /viewer/signing-status   — per-sig_key status for the calling user
  POST /viewer/sign/request-otp — validates authorization, generates OTP, emails it
  POST /viewer/sign/verify      — verifies OTP, records visual placement,
                                   mirrors event into existing signing tables
  Supporting helpers: _assert_can_sign, _get_field_status (_shared_doc_field_status,
  _audit_report_field_status, _nc_form_field_status), _commit_existing_signing_record,
  _get_doc_label

Frontend:
- components/SignatureConfirmDialog.tsx: new component — 5-stage OTP signing
  dialog (loading → no_signature → preview → otp_sent → verifying → success)
- components/CertivaDocumentViewer.tsx: add 'blocked' SigStatus, Lock icon,
  onPrepared callback prop
- app/(app)/viewer/[type]/[id]/page.tsx: replace alert() stub with real flow —
  fetches signing status after onPrepared, handles onSignatureClick,
  re-fetches after successful sign
```
