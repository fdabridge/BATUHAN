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

import logging
import os
import re
from datetime import datetime, date
from typing import Optional

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from audit_set.pdf_flattener import flatten_document
from storage.document_store import ensure_local, is_s3_ref, resolve_docx_key
from pydantic import BaseModel
from sqlalchemy.orm import Session

from audit_set.committee_slots import (
    STATIC_COMMITTEE_SIG_KEYS,
    committee_member_auditor_id,
    committee_member_name,
    expected_committee_sig_keys,
    is_dynamic_committee_member_sig_key,
    planned_committee_chair,
    planned_committee_slots,
)
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
from audit_set.report_signature_rules import audit_report_requires_appointed_reviewer
from auth.db_models import PlatformUser, UserSignature, get_db as get_auth_db
from auth.dependencies import get_current_user
from email_service import send_document_released
router = APIRouter(prefix="/viewer", tags=["viewer"])

# ── Constants ─────────────────────────────────────────────────────────────────

CB_ROLES = {"admin", "planner", "planner_us", "officer", "executive", "gm", "certification_manager"}

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
    # Portal 55 — appointed committee reviewer for stage reports (FR.231/FR.232)
    "appointed_reviewer": "APPOINTED_REVIEWER",
}
SIG_TO_ROLE: dict[str, str] = {v: k for k, v in ROLE_TO_SIG.items()}

# Portal 49a Part 2 — FR.225 organisation-personnel signature slots.
# Portal 73: format changed from ORG_OPENING_ORG_EMP_<uuid> to ORG_OPENING_ORG_EMP_<N>
# (1-based row index, ordering matches packager created_at).
ORG_SIG_RE = re.compile(
    r"^ORG_(OPENING|CLOSING)_ORG_EMP_(\d+)$"
)

# Portal 59 — FR.225 audit-team signature slots (added to all 9 templates in
# commit 90b77ab). Each auditor / technical expert signs their own Opening /
# Closing slot using their own UserSignature. No AuditDocumentSignature row is
# seeded — status is driven by VisualSignaturePlacement (mirrors ORG_SIG_RE).
ORG_TEAM_RE = re.compile(
    r"^ORG_(OPENING|CLOSING)_(LEAD_AUDITOR|AUDITOR_(\d+)|TE_(\d+))$"
)

# Portal 60 — FR.225 blank-placeholder org-employee rows. The packager seeds
# `sig_key="ORG_EMP_BLANK_N"` when no roster is registered yet, which the
# template wraps as `ORG_OPENING_ORG_EMP_BLANK_N` / `ORG_CLOSING_ORG_EMP_BLANK_N`.
# These markers must render as non-interactive ("awaiting registration") and
# be rejected on sign attempts.
ORG_BLANK_RE = re.compile(
    r"^ORG_(OPENING|CLOSING)_ORG_EMP_BLANK_(\d+)$"
)

# Portal 49a Part 3 — FR.233 certification committee signature slots.
# Portal 62: dynamic per-auditor keys replace static slots.
# Legacy static keys kept so old signed FR.233 docs still resolve.
COMMITTEE_SIG_KEYS = set(STATIC_COMMITTEE_SIG_KEYS)
FR233_CERT_MANAGER_KEYS = {
    "CB_CERT_MANAGER",
    "CERT_MANAGER_FR233",
    "CERT_MANAGER_REVIEW",
}
# Portal 62 — regex for old dynamic committee member sig keys: COMMITTEE_MEMBER_<auditor_id>
COMMITTEE_MEMBER_RE = re.compile(r"^COMMITTEE_MEMBER_(.+)$")

# Portal 59 Fix 4 — legacy sig-key aliases for VSP lookup. Existing rendered
# PDFs and existing VisualSignaturePlacement rows may carry pre-rename marker
# names. Scan-time normalization lives in doc_converter._normalize_sig_key;
# this map is the read-side fallback so VSP rows written under old names
# (or against legacy-keyed PDFs) still resolve when the legend asks for the
# new canonical key. Aliases are template-scoped at scan time, so adding an
# old name here only widens the VSP lookup — it does not change behaviour
# for documents where the old name is still canonical (FR.220/221/230 CLIENT,
# FR.218/229 CB_REVIEWER).
SIG_KEY_ALIASES: dict[str, str] = {
    "AUDITOR_MEMBER":      "ASSIGNED_AUDITOR",   # FR.224
    "CLIENT":              "ORG_REP",             # FR.211 / FR.223 only (template-scoped)
    # Portal 73 — FR.231/FR.232 templates now use CB_CERT_MANAGER.
    # Keep aliases so existing VisualSignaturePlacement rows written under the
    # old names (CB_REVIEWER, APPOINTED_REVIEWER) still resolve at read-time.
    "CB_REVIEWER":         "CB_CERT_MANAGER",
    "CERT_MANAGER_REVIEW": "CB_CERT_MANAGER",  # FR.233 only (template-scoped)
    "CERT_MANAGER_FR233":  "CB_CERT_MANAGER",  # legacy FR.233 generator key
}


def _aliased_sig_keys(sig_key: str) -> list[str]:
    """Return [sig_key, ...old aliases mapping to sig_key] for legacy VSP lookup."""
    aliases = [old for old, new in SIG_KEY_ALIASES.items() if new == sig_key]
    return [sig_key, *aliases] if aliases else [sig_key]


def _meeting_employee_count(doc: AuditSetSharedDocument, db: Session, auth_db: Session) -> int:
    client_user = (
        auth_db.query(PlatformUser)
        .filter_by(role="client", audit_set_id=doc.audit_set_id)
        .first()
    )
    if not client_user:
        return 0
    return (
        db.query(ClientOrgEmployee)
        .filter_by(client_user_id=client_user.id, is_active=True)
        .count()
    )


def _canonical_meeting_sig_key(
    sig_key: str,
    doc: AuditSetSharedDocument | None,
    db: Session,
    auth_db: Session,
) -> str:
    """Map stale FR.225 blank-row keys to real employee-row keys when possible."""
    if not doc or doc.document_type != "meeting_form":
        return sig_key
    blank = ORG_BLANK_RE.match(sig_key)
    if not blank:
        return sig_key
    phase, idx_raw = blank.group(1), blank.group(2)
    idx = int(idx_raw)
    if idx <= _meeting_employee_count(doc, db, auth_db):
        return f"ORG_{phase}_ORG_EMP_{idx}"
    return sig_key


def _repair_meeting_signature_fields(
    document_type: str,
    doc_id: str,
    docx_path: str,
    db: Session,
    auth_db: Session,
) -> None:
    """Self-heal cached FR.225 fields that still reference blank placeholder rows."""
    if document_type != "shared_doc":
        return
    doc = db.query(AuditSetSharedDocument).filter_by(id=doc_id).first()
    if not doc or doc.document_type != "meeting_form":
        return
    changed = False
    rows = db.query(DocumentSignatureField).filter_by(docx_path=docx_path).all()
    for row in rows:
        canonical = _canonical_meeting_sig_key(row.sig_key, doc, db, auth_db)
        if canonical != row.sig_key:
            row.sig_key = canonical
            changed = True
    if changed:
        db.commit()


# ── Pydantic request bodies ───────────────────────────────────────────────────

class SignConfirmRequest(BaseModel):
    document_type: str
    doc_id:        str
    sig_key:       str
    signed_date:   Optional[date] = None  # user-selected signing date; defaults to today
    # Portal 56 — required when the client is signing an org-rep slot
    # (sig_key CLIENT or ORG_REP). Identifies which registered employee from
    # the client's roster is signing on behalf of the organisation.
    employee_id:   Optional[str]  = None


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
    try:
        return ensure_local(path)
    except (FileNotFoundError, Exception):
        raise HTTPException(404, "Document file not found on server.")


# ── Prepare (convert + extract) ───────────────────────────────────────────────

@router.get("/prepare")
def viewer_prepare(
    document_type: str         = Query(..., description="shared_doc | audit_report | nc_form"),
    doc_id:        str         = Query(..., description="UUID of the document record"),
    db:            Session     = Depends(get_db),
    auth_db:       Session     = Depends(get_auth_db),
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
        prepare_document(docx_path, db)
    except RuntimeError as exc:
        raise HTTPException(500, f"Document preparation failed: {exc}") from exc

    _repair_meeting_signature_fields(document_type, doc_id, docx_path, db, auth_db)

    # Return the DB rows, not raw extractor output, so first-open responses also
    # include normalized/self-healed keys used by signing-status and flattening.
    fields = [
        {
            "sig_key":     f.sig_key,
            "page_number": f.page_number,
            "x0": f.x0, "y0": f.y0,
            "x1": f.x1, "y1": f.y1,
            "page_width":  f.page_width,
            "page_height": f.page_height,
        }
        for f in db.query(DocumentSignatureField)
            .filter(
                DocumentSignatureField.docx_path == docx_path,
                DocumentSignatureField.sig_key != "__none__",
            )
            .all()
    ]

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

    Self-healing: if the PDF cache is missing (e.g. after a Railway restart that
    wiped the ephemeral filesystem), the endpoint re-runs prepare_document() to
    regenerate it from the stored DOCX before flattening.

    Accessible by any authenticated user (CB, auditor, client).
    """
    from audit_set.doc_converter import prepare_document
    from audit_set.pdf_flattener import _resolve_docx_path

    try:
        docx_path_for_repair = _resolve_docx_path(document_type, doc_id, db)
        _repair_meeting_signature_fields(document_type, doc_id, docx_path_for_repair, db, auth_db)
        pdf_bytes = flatten_document(document_type, doc_id, db)

    except FileNotFoundError:
        # PDF cache is gone — try to regenerate it from the DOCX on disk.
        # This handles Railway restarts that wipe /app/storage if no volume is mounted.
        try:
            docx_path = _resolve_docx_path(document_type, doc_id, db)
            # If the DOCX is also missing (full storage wipe), raise immediately
            # so the inner FileNotFoundError handler returns 503 cleanly instead
            # of letting LibreOffice fail with a RuntimeError → HTTP 500.
            if not os.path.exists(docx_path):
                raise FileNotFoundError(f"DOCX not on disk: {docx_path}")
            prepare_document(docx_path, db)
            _repair_meeting_signature_fields(document_type, doc_id, docx_path, db, auth_db)
            pdf_bytes = flatten_document(document_type, doc_id, db)
        except FileNotFoundError:
            # DOCX itself is also gone — storage is wiped; can't recover.
            raise HTTPException(
                503,
                "The document file is no longer available on this server. "
                "This can happen after a server restart. Please ask the CB to "
                "re-upload or regenerate the document, then try again.",
            )
        except Exception as exc:
            logger.exception("[download-signed] re-prepare failed: %s", exc)
            raise HTTPException(500, f"Failed to regenerate PDF: {exc}") from exc

    except Exception as exc:
        logger.exception("[download-signed] flatten failed: %s", exc)
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
    sig_key: str,
    audit_set_id: str,
    current_user: PlatformUser,
    db: Session,
    doc_id: str | None = None,
) -> None:
    """Raise HTTPException(403) if `current_user` may not sign `sig_key` on FR.233."""
    if sig_key in FR233_CERT_MANAGER_KEYS:
        # Portal 61 — certification_manager is the canonical CM role; admin /
        # executive retained as escape hatches for existing data.
        if current_user.role not in ("certification_manager", "admin", "executive"):
            raise HTTPException(
                403, "Only the Certification Manager may sign this slot",
            )
        if doc_id:
            _, all_committee_signed = _fr233_committee_signing_state(
                doc_id, audit_set_id, db,
            )
            if not all_committee_signed:
                raise HTTPException(
                    409,
                    "All planned committee members must sign FR.233 before "
                    "the Certification Manager.",
                )
        return

    # Static keys are positional rows backed by the committee saved in planning.
    # Check these before the dynamic regex: COMMITTEE_MEMBER_1/2 look like old
    # dynamic keys, but their suffix is a row number, not an auditor id.
    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    member = planned_committee_slots(audit_set).get(sig_key) if audit_set else None
    if sig_key in COMMITTEE_SIG_KEYS:
        expected_auditor_id = committee_member_auditor_id(member)
        if expected_auditor_id is None:
            raise HTTPException(400, f"No committee member assigned for '{sig_key}'")
        if current_user.role == "admin":
            return
        if current_user.role != "auditor" or current_user.auditor_id != expected_auditor_id:
            raise HTTPException(403, "This signature slot is assigned to a different committee member")
        return

    # Portal 62 — dynamic COMMITTEE_MEMBER_<auditor_id> slots on older FR.233 docs.
    cm_match = COMMITTEE_MEMBER_RE.match(sig_key)
    if is_dynamic_committee_member_sig_key(sig_key) and cm_match:
        member_id = cm_match.group(1)
        if member_id.startswith("BLANK_"):
            raise HTTPException(
                400, "This is a placeholder row — appoint the committee first",
            )
        if current_user.role == "admin":
            return  # admin bypass
        if current_user.role not in ("auditor",):
            raise HTTPException(403, "Auditor account required to sign committee member slots")
        if not current_user.auditor_id or current_user.auditor_id != member_id:
            raise HTTPException(403, "This signature slot is assigned to a different committee member")
        # Verify the auditor is in the committee_members snapshot on the audit set
        if audit_set:
            members_snapshot = audit_set.committee_members or []
            if not any(x.get("id") == member_id for x in members_snapshot):
                raise HTTPException(403, "This auditor is not on the appointed committee")
        return


def _fr233_committee_signing_state(
    doc_id: str,
    audit_set_id: str,
    db: Session,
) -> tuple[set[str], bool]:
    """Return the expected FR.233 committee keys and whether all are signed."""
    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        return set(), False

    doc = db.query(AuditSetSharedDocument).filter_by(id=doc_id).first()
    document_keys: set[str] = set()
    if doc and doc.file_path:
        document_keys.update(
            key
            for (key,) in (
                db.query(DocumentSignatureField.sig_key)
                .filter_by(docx_path=resolve_docx_key(doc.file_path))
                .all()
            )
        )
    if not document_keys:
        document_keys.update(
            key
            for (key,) in (
                db.query(VisualSignaturePlacement.sig_key)
                .filter_by(document_type="shared_doc", doc_id=doc_id)
                .all()
            )
        )

    expected = expected_committee_sig_keys(audit_set, document_keys)
    if not expected:
        return expected, False
    signed = {
        key
        for (key,) in (
            db.query(VisualSignaturePlacement.sig_key)
            .filter_by(document_type="shared_doc", doc_id=doc_id)
            .filter(VisualSignaturePlacement.sig_key.in_(expected))
            .filter(VisualSignaturePlacement.signed_at.isnot(None))
            .all()
        )
    }
    return expected, expected.issubset(signed)


# ── Helpers: shared-doc slot eligibility + order gating (Portal 49b) ─────────

def _find_stage(db: Session, audit_set_id: str, stage_type: str | None) -> AuditSetStage | None:
    q = db.query(AuditSetStage).filter_by(audit_set_id=audit_set_id)
    if stage_type:
        result = q.filter_by(stage_type=stage_type).order_by(AuditSetStage.stage_order).first()
        if result:
            return result
        # stage_type was provided but nothing matched — doc may have been
        # uploaded with a mismatched stage_type. Fall back to the first stage
        # for this audit set so signing is never permanently blocked.
        logger.warning(
            "[_find_stage] stage_type=%r not found for audit_set=%s; "
            "falling back to first stage",
            stage_type, audit_set_id,
        )
    return q.order_by(AuditSetStage.stage_order).first()


def _audit_report_needs_appointed_reviewer(
    report: AuditSetAuditReport | None,
    db: Session,
) -> bool:
    if not report:
        return False
    audit_set = db.query(AuditSet).filter_by(id=report.audit_set_id).first()
    return audit_report_requires_appointed_reviewer(report, audit_set)


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
        return role in ("planner", "planner_us", "admin")
    if role_label == "cb_cert_manager":
        # Bug fix: include "certification_manager" (was incorrectly "executive" only)
        return role in ("admin", "certification_manager", "executive")
    if role_label == "cb_reviewer":
        # For FR.218: only the appointed fr218_reviewer auditor may sign this slot.
        if doc.document_type == "fr218_review":
            if role == "admin":
                return True
            if role != "auditor" or not current_user.auditor_id:
                return False
            audit_set = db.query(AuditSet).filter_by(id=doc.audit_set_id).first()
            return audit_set is not None and audit_set.fr218_reviewer_id == current_user.auditor_id
        # For other doc types: fall through (committee membership checked separately)
        return False
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
    if role_label == "appointed_reviewer":
        # Shared-doc APPOINTED_REVIEWER slots are handled as Certification
        # Manager slots. Audit reports use their own branch below because
        # FR.231 only needs the extra reviewer for FSMS/ISMS.
        return role in ("certification_manager", "admin")
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


# ── Helpers: FR.225 audit-team slot resolution (Portal 59) ────────────────────

def _lookup_auditor_id_by_name(name: str, db: Session) -> str | None:
    """
    Resolve an auditor's UUID by their display name.

    Fallback for stages where lead_auditor_id / auditor[N].id was not saved
    (pre-Portal 53 data). Mirrors the logic in repair_lead_auditor_ids.py.
    Safe: returns None if no exact-name match is found.
    """
    try:
        from auditors.db_models import Auditor
        auditor = db.query(Auditor).filter_by(name=name).first()
        if auditor:
            logger.debug(
                "[_lookup_auditor_id_by_name] resolved '%s' → %s", name, auditor.id,
            )
            return auditor.id
    except Exception as exc:
        logger.warning("[_lookup_auditor_id_by_name] lookup failed for '%s': %s", name, exc)
    return None


def _resolve_org_team_member(
    sig_key: str,
    doc: AuditSetSharedDocument,
    db: Session,
) -> tuple[Optional[str], Optional[str]]:
    """Return (auditor_id, display_name) for an ORG_TEAM_RE sig_key, or (None, None).

    When auditor_id is missing from the stage row (pre-Portal 53 data where
    lead_auditor_id / auditor[N].id was never saved), this function resolves
    the ID by exact-name lookup in the Auditor table so that signing is not
    permanently blocked. This mirrors what repair_lead_auditor_ids.py does at
    the DB level, but applies at read-time so no migration is needed.
    """
    m = ORG_TEAM_RE.match(sig_key)
    if not m:
        return None, None
    role_part = m.group(2)
    stage = _find_stage(db, doc.audit_set_id, doc.stage_type)
    if not stage:
        return None, None

    if role_part == "LEAD_AUDITOR":
        auditor_id   = stage.lead_auditor_id
        auditor_name = stage.lead_auditor_name or "Lead Auditor"
        if not auditor_id and stage.lead_auditor_name:
            auditor_id = _lookup_auditor_id_by_name(stage.lead_auditor_name, db)
        return auditor_id, auditor_name

    if role_part.startswith("AUDITOR_"):
        idx = int(role_part.split("_")[1])
        auditors = stage.auditors or []
        if idx >= len(auditors):
            return None, None
        a = auditors[idx]
        auditor_id   = a.get("id")
        auditor_name = a.get("name") or f"Auditor {idx}"
        if not auditor_id and a.get("name"):
            auditor_id = _lookup_auditor_id_by_name(a["name"], db)
        return auditor_id, auditor_name

    if role_part.startswith("TE_"):
        idx = int(role_part.split("_")[1])
        tes = stage.technical_experts or []
        if idx >= len(tes):
            return None, None
        t = tes[idx]
        auditor_id   = t.get("id")
        auditor_name = t.get("name") or f"Technical Expert {idx}"
        if not auditor_id and t.get("name"):
            auditor_id = _lookup_auditor_id_by_name(t["name"], db)
        return auditor_id, auditor_name

    return None, None


def _org_team_eligible(
    sig_key: str,
    doc: AuditSetSharedDocument,
    current_user: PlatformUser,
    db: Session,
) -> bool:
    """True if current_user is the auditor assigned to this ORG_TEAM slot."""
    if current_user.role == "admin":
        return True
    if current_user.role != "auditor":
        logger.debug("[ORG_TEAM] sig_key=%s user role=%s not auditor", sig_key, current_user.role)
        return False
    if not current_user.auditor_id:
        logger.warning("[ORG_TEAM] sig_key=%s user id=%s has no auditor_id", sig_key, current_user.id)
        return False
    auditor_id, _ = _resolve_org_team_member(sig_key, doc, db)
    if auditor_id is None:
        logger.warning(
            "[ORG_TEAM] sig_key=%s could not resolve auditor on stage (audit_set=%s stage_type=%s)",
            sig_key, doc.audit_set_id, doc.stage_type,
        )
        return False
    eligible = auditor_id == current_user.auditor_id
    logger.debug(
        "[ORG_TEAM] sig_key=%s user.auditor_id=%s vs stage.auditor_id=%s -> %s",
        sig_key, current_user.auditor_id, auditor_id, eligible,
    )
    return eligible


# ── Helper: resolve org employee by 1-based row index (Portal 73) ────────────

def _resolve_org_emp_by_index(
    audit_set_id: str,
    row_index: int,
    db: Session,
    auth_db: Session,
) -> Optional["ClientOrgEmployee"]:
    """Return the ClientOrgEmployee at 1-based row_index (created_at order).

    Ordering must match packager._resolve_org_attendees exactly so the
    sig_key ORG_EMP_N always refers to the same employee in both the DOCX
    template and this lookup.
    """
    client_user = auth_db.query(PlatformUser).filter_by(
        role="client", audit_set_id=audit_set_id
    ).first()
    if not client_user:
        return None
    employees = (
        db.query(ClientOrgEmployee)
        .filter_by(client_user_id=client_user.id, is_active=True)
        .order_by(ClientOrgEmployee.created_at)
        .all()
    )
    if 1 <= row_index <= len(employees):
        return employees[row_index - 1]
    return None


# ── Helper: _assert_can_sign ──────────────────────────────────────────────────

def _assert_can_sign(
    document_type: str,
    doc_id: str,
    sig_key: str,
    current_user: PlatformUser,
    db: Session,
    auth_db: Optional[Session] = None,
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

        elif ORG_BLANK_RE.match(sig_key):
            # Portal 60 — placeholder rows seeded when no client roster exists.
            # Reject signing; ask the planner to refresh FR.225 once employees
            # are registered.
            raise HTTPException(
                400,
                "This row is a placeholder — register the organisation's employees "
                "and refresh the meeting form before signing.",
            )

        elif ORG_SIG_RE.match(sig_key):
            # Portal 49a Part 2 — FR.225 organisation-personnel signing.
            # The client user signs on behalf of one of their roster employees;
            # the stored snapshot is the employee's own saved signature image.
            if current_user.role != "client":
                raise HTTPException(403, "Only the client account may sign organisation slots")
            if current_user.audit_set_id != doc.audit_set_id:
                raise HTTPException(403, "This document is not for your audit set")
            row_idx = int(ORG_SIG_RE.match(sig_key).group(2))
            emp = _resolve_org_emp_by_index(doc.audit_set_id, row_idx, db, auth_db)
            if not emp or emp.client_user_id != current_user.id:
                raise HTTPException(404, "Employee not in your roster")
            if not emp.signature_data:
                raise HTTPException(
                    400,
                    f"{emp.full_name} has no signature on file. "
                    "Go to Employees, upload their signature, then try again.",
                )

        elif ORG_TEAM_RE.match(sig_key):
            # Portal 59 — FR.225 audit-team slot. Auditor signs their own
            # Opening/Closing cell using their own UserSignature. No ordering
            # gate: all team slots may be signed independently.
            if not _org_team_eligible(sig_key, doc, current_user, db):
                raise HTTPException(403, "This signature slot is not assigned to you")

        elif (
            is_dynamic_committee_member_sig_key(sig_key)
            or sig_key in COMMITTEE_SIG_KEYS
            or (
                doc.document_type == "fr233"
                and sig_key in FR233_CERT_MANAGER_KEYS
            )
        ):
            # Portal 49a Part 3 / Portal 62 — FR.233 committee signing.
            # Dynamic COMMITTEE_MEMBER_<auditor_id> keys (Portal 62) and legacy
            # static keys are both handled by _check_committee_sig.
            _check_committee_sig(
                sig_key, doc.audit_set_id, current_user, db, doc_id=doc.id,
            )

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
            # Portal 63 — APPOINTED_REVIEWER: pure role check, no signer_user_id
            # gate and no ordering gate. CM and LA may sign in any order.
            if role_label == "appointed_reviewer":
                if current_user.role not in ("certification_manager", "admin"):
                    raise HTTPException(
                        403, "Only the Certification Manager may sign this slot",
                    )
            else:
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

        elif sig_key == "APPOINTED_REVIEWER":
            if not _audit_report_needs_appointed_reviewer(report, db):
                raise HTTPException(
                    400,
                    "This report does not require committee chairperson signing.",
                )
            # The "Approved By" row belongs to the committee chairperson saved
            # during audit planning, not a separate per-report reviewer.
            if report.appointed_reviewer_signed_at:
                raise HTTPException(400, "Committee chairperson has already signed this report")
            if current_user.role == "admin":
                return
            audit_set = db.query(AuditSet).filter_by(id=report.audit_set_id).first()
            chair = planned_committee_chair(audit_set) if audit_set else None
            chair_auditor_id = committee_member_auditor_id(chair)
            if not chair_auditor_id:
                raise HTTPException(
                    400,
                    "No committee chairperson has been selected in audit planning.",
                )
            if (
                current_user.role != "auditor"
                or current_user.auditor_id != chair_auditor_id
            ):
                raise HTTPException(
                    403,
                    "Only the planned committee chairperson may sign this slot",
                )
            if not report.la_signed_at:
                raise HTTPException(
                    400,
                    "The Lead Auditor must sign before the committee chairperson can sign",
                )

        elif sig_key in ("CB_REVIEWER", "CB_CERT_MANAGER"):
            # Portal 73 — templates now use CB_CERT_MANAGER; CB_REVIEWER kept as alias.
            if report.reviewer_signed_at:
                raise HTTPException(400, "Certification Manager has already signed this report")
            if current_user.role not in ("certification_manager", "admin"):
                raise HTTPException(403, "Only the Certification Manager may sign this slot")
            if not report.la_signed_at:
                raise HTTPException(
                    400,
                    "The Lead Auditor must sign before the Certification Manager can sign",
                )
            # If this document really requires APPOINTED_REVIEWER, that must be
            # signed first. FR.231 only requires it for FSMS/ISMS audits.
            if (
                _audit_report_needs_appointed_reviewer(report, db)
                and not report.appointed_reviewer_signed_at
            ):
                from storage.document_store import resolve_docx_key
                try:
                    docx_key = resolve_docx_key(report.file_path)
                except Exception:
                    docx_key = report.file_path  # fallback to raw path
                has_ar_field = (
                    db.query(DocumentSignatureField)
                    .filter_by(docx_path=docx_key, sig_key="APPOINTED_REVIEWER")
                    .first()
                ) is not None
                if has_ar_field:
                    raise HTTPException(
                        400,
                        "The committee chairperson must sign before the Certification Manager can sign",
                    )

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

        elif sig_key in ("CLIENT", "ORG_REP"):   # Portal 121
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
    # Portal 59 Fix 4 — also accept VSP rows written under legacy alias names.
    vsp = db.query(VisualSignaturePlacement).filter(
        VisualSignaturePlacement.document_type == document_type,
        VisualSignaturePlacement.doc_id == doc_id,
        VisualSignaturePlacement.sig_key.in_(_aliased_sig_keys(sig_key)),
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
                # Portal 56 — prefer the employee name stored on the CLIENT
                # slot (set when the org rep signed via the employee picker);
                # fall back to the platform user's name for legacy rows.
                client_slot = db.query(AuditDocumentSignature).filter_by(
                    document_id=doc_id, signer_role_label="client",
                ).first()
                display_name = (client_slot.signer_name if client_slot and client_slot.signer_name
                                else _user_name(doc.signed_by))
                return _result("signed", display_name, vsp.signature_image if vsp else None)
            if (current_user.role == "client"
                    and current_user.audit_set_id == doc.audit_set_id
                    and doc.status == "released"):
                return _result("current_user")
            blocked = doc.status == "pending_cb_signature"
            return _result("blocked" if blocked else "pending")

        # Portal 60 — FR.225 blank-placeholder rows render as non-interactive
        # ("awaiting registration"); a planner/auditor must register the
        # client's employees and call /meeting-form/regenerate before signing.
        if ORG_BLANK_RE.match(sig_key):
            return _result("pending", "Awaiting employee registration")

        # Portal 56 — FR.225 organisation-personnel slots. Status comes from
        # the VisualSignaturePlacement row (signed_at populated) since these
        # keys are not in SIG_TO_ROLE and have no AuditDocumentSignature slot.
        org_match = ORG_SIG_RE.match(sig_key)
        if org_match:
            row_idx = int(org_match.group(2))
            emp = _resolve_org_emp_by_index(doc.audit_set_id, row_idx, db, auth_db)
            emp_name = emp.full_name if emp else None
            if vsp:
                return _result("signed", emp_name, vsp.signature_image)
            if (current_user.role == "client"
                    and current_user.audit_set_id == doc.audit_set_id):
                return _result("current_user", emp_name)
            return _result("pending", emp_name)

        # Portal 59 — FR.225 audit-team slots (Lead Auditor / Auditor_N / TE_N).
        # No AuditDocumentSignature row is seeded; status mirrors ORG_SIG_RE
        # and reads directly from VisualSignaturePlacement. No ordering gate.
        if ORG_TEAM_RE.match(sig_key):
            _, member_name = _resolve_org_team_member(sig_key, doc, db)
            if vsp:
                return _result("signed", member_name, vsp.signature_image)
            if _org_team_eligible(sig_key, doc, current_user, db):
                return _result("current_user", member_name)
            return _result("pending", member_name)

        # Static FR.233 rows resolve against the committee saved during planning.
        # This must run before COMMITTEE_MEMBER_RE because MEMBER_1/MEMBER_2 also
        # match the old dynamic-key pattern.
        if sig_key in COMMITTEE_SIG_KEYS:
            audit_set = db.query(AuditSet).filter_by(id=doc.audit_set_id).first()
            slot_member = (
                planned_committee_slots(audit_set).get(sig_key)
                if audit_set else None
            )
            member_name = committee_member_name(slot_member)
            member_auditor_id = committee_member_auditor_id(slot_member)
            if vsp:
                return _result("signed", member_name, vsp.signature_image)
            if slot_member is None:
                return _result("not_applicable", "Not required")
            if current_user.role == "admin":
                return _result("current_user", member_name)
            if (
                current_user.role == "auditor"
                and current_user.auditor_id == member_auditor_id
            ):
                return _result("current_user", member_name)
            return _result("pending", member_name)

        if doc.document_type == "fr233" and sig_key in FR233_CERT_MANAGER_KEYS:
            # CM signs last; show "blocked" until all committee slots have signed.
            if vsp:
                return _result("signed", vsp.signer_name or _user_name(vsp.user_id), vsp.signature_image)
            _, all_committee_signed = _fr233_committee_signing_state(
                doc_id, doc.audit_set_id, db,
            )
            if current_user.role in ("certification_manager", "admin", "executive"):
                if all_committee_signed:
                    return _result("current_user", current_user.full_name)
                return _result("blocked")
            return _result("pending")

        # Portal 62 — dynamic COMMITTEE_MEMBER_<auditor_id> slots on FR.233.
        cm_match = COMMITTEE_MEMBER_RE.match(sig_key)
        if is_dynamic_committee_member_sig_key(sig_key) and cm_match:
            member_id = cm_match.group(1)
            if member_id.startswith("BLANK_"):
                return _result("pending", "Awaiting committee appointment")
            # Resolve auditor display name from committee_members snapshot.
            audit_set = db.query(AuditSet).filter_by(id=doc.audit_set_id).first()
            member_name: str | None = None
            if audit_set:
                snapshot = audit_set.committee_members or []
                entry = next((x for x in snapshot if x.get("id") == member_id), None)
                member_name = entry.get("name") if entry else None
            if vsp:
                return _result("signed", member_name, vsp.signature_image)
            # The specific auditor or an admin may sign this slot.
            if current_user.role == "admin":
                return _result("current_user", member_name)
            if (current_user.role == "auditor"
                    and current_user.auditor_id == member_id):
                return _result("current_user", member_name)
            return _result("pending", member_name)

        role_label = SIG_TO_ROLE.get(sig_key)
        if not role_label:
            return _result("pending")

        sig_record = db.query(AuditDocumentSignature).filter_by(
            document_id=doc_id, signer_role_label=role_label,
        ).first()
        if not sig_record:
            # No DB slot seeded for this sig_key on this document.
            # For fr218_review CB_REVIEWER: this means FSMS/ISMS reviewer not required.
            if doc and doc.document_type == "fr218_review" and role_label == "cb_reviewer":
                return _result("not_applicable")
            return _result("pending")

        # Portal 114 — stale cb_reviewer slot: slot exists in DB but the current
        # audit standards no longer require a reviewer. Mark as not_applicable
        # and flip required=False so it stops blocking remaining_all counts.
        if (
            role_label == "cb_reviewer"
            and doc and doc.document_type == "fr218_review"
            and sig_record.signed_at is None
        ):
            from audit_set.documents_router import _needs_reviewer
            _audit_set_for_slot = db.query(AuditSet).filter_by(id=doc.audit_set_id).first()
            if _audit_set_for_slot and not _needs_reviewer(_audit_set_for_slot):
                if sig_record.required:
                    sig_record.required = False
                    db.commit()
                return _result("not_applicable")

        if sig_record.signed_at:
            return _result("signed", sig_record.signer_name, vsp.signature_image if vsp else None)
        # Shared-doc APPOINTED_REVIEWER slots are treated as Certification
        # Manager slots. Audit reports use the dedicated report branch below.
        if role_label == "appointed_reviewer":
            cm_user = auth_db.query(PlatformUser).filter_by(
                role="certification_manager", is_active=True,
            ).first()
            reviewer_name = (
                sig_record.signer_name
                or (cm_user.full_name if cm_user else None)
                or _user_name(sig_record.signer_user_id)
            )
            if current_user.role in ("certification_manager", "admin"):
                return _result("current_user", reviewer_name)
            return _result("pending", reviewer_name)
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

        elif sig_key == "APPOINTED_REVIEWER":
            if not _audit_report_needs_appointed_reviewer(report, db):
                return _result("not_applicable")
            if report.appointed_reviewer_signed_at:
                return _result(
                    "signed",
                    _user_name(report.appointed_reviewer_user_id),
                    vsp.signature_image if vsp else None,
                )
            if not report.la_signed_at:
                return _result("blocked")
            audit_set = db.query(AuditSet).filter_by(id=report.audit_set_id).first()
            chair = planned_committee_chair(audit_set) if audit_set else None
            chair_name = committee_member_name(chair) or "Committee Chairperson"
            chair_auditor_id = committee_member_auditor_id(chair)
            if (
                current_user.role == "auditor"
                and chair_auditor_id
                and current_user.auditor_id == chair_auditor_id
            ):
                return _result("current_user", chair_name)
            if current_user.role == "admin":
                return _result("current_user", chair_name)
            return _result("pending", chair_name)

        elif sig_key in ("CB_REVIEWER", "CB_CERT_MANAGER"):
            # Portal 73 — templates now use CB_CERT_MANAGER; CB_REVIEWER kept as alias.
            if report.reviewer_signed_at:
                return _result("signed", _user_name(report.reviewer_user_id), vsp.signature_image if vsp else None)
            if not report.la_signed_at:
                return _result("blocked")
            cm_user = auth_db.query(PlatformUser).filter_by(
                role="certification_manager", is_active=True,
            ).first()
            reviewer_name = cm_user.full_name if cm_user else "Certification Manager"
            if current_user.role in ("certification_manager", "admin"):
                return _result("current_user", reviewer_name)
            return _result("pending", reviewer_name)

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

        elif sig_key in ("CLIENT", "ORG_REP"):   # Portal 121
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
    employee: Optional["ClientOrgEmployee"] = None,
) -> None:
    """Update existing signing tables so workflow/legal state stays consistent."""
    now = signed_at if signed_at is not None else datetime.utcnow()
    # Portal 56 — when an org employee signs on behalf of the client, the
    # legal user is still current_user (audit trail) but the displayed signer
    # name is the employee's full_name.
    signer_name = employee.full_name if employee else current_user.full_name

    if document_type == "shared_doc":
        doc = db.query(AuditSetSharedDocument).filter_by(id=doc_id).first()
        if not doc:
            return

        if sig_key == "CLIENT":
            if doc.signed_at:
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
                client_slot.signer_name    = signer_name
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

        elif ORG_TEAM_RE.match(sig_key):
            # Portal 59 — FR.225 audit-team placement was already saved in
            # sign_confirm. No workflow status change is associated with it.
            return

        elif (
            is_dynamic_committee_member_sig_key(sig_key)
            or sig_key in COMMITTEE_SIG_KEYS
            or (
                doc.document_type == "fr233"
                and sig_key in FR233_CERT_MANAGER_KEYS
            )
        ):
            # Portal 49a Part 3 / Portal 62 — FR.233 signing. Placement already
            # saved. Update AuditSetFR233Record and (for the CM slot) the audit
            # set's workflow status.
            from audit_set.db_models import AuditSetFR233Record
            record = db.query(AuditSetFR233Record).filter_by(
                audit_set_id=doc.audit_set_id,
            ).first()
            if record and record.status == "pending":
                record.status = "signing"

            if sig_key in FR233_CERT_MANAGER_KEYS:
                _, all_committee_signed = _fr233_committee_signing_state(
                    doc_id, doc.audit_set_id, db,
                )
                if all_committee_signed:
                    if record:
                        record.status = "complete"
                    doc.status = "signed"
                    doc.signed_by = current_user.id
                    doc.signed_at = now
                    doc.signed_ip = ip
                    # FR.233 approval completes the committee decision. The
                    # workflow becomes certified only when the certificate file
                    # itself is issued through Shared Documents.
                else:
                    logger.warning(
                        "FR.233 Certification Manager signature received before "
                        "all planned committee signatures for audit_set_id=%s",
                        doc.audit_set_id,
                    )
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
                sig_record.signer_name    = signer_name
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
            # Portal 114 — a stale cb_reviewer slot on a non-FSMS/ISMS fr218_review
            # document would make remaining_all > 0 permanently and prevent the
            # completion trigger from firing. Exclude it if the current audit
            # standards don't require a reviewer.
            # NOTE: `doc` is not yet in scope here; fetch inline to avoid NameError.
            if remaining_all > 0:
                _p114_doc = db.query(AuditSetSharedDocument).filter_by(id=doc_id).first()
                if _p114_doc and _p114_doc.document_type == "fr218_review":
                    from audit_set.documents_router import _needs_reviewer
                    _audit_set_for_doc = db.query(AuditSet).filter_by(id=_p114_doc.audit_set_id).first()
                    if _audit_set_for_doc and not _needs_reviewer(_audit_set_for_doc):
                        remaining_all = (
                            db.query(AuditDocumentSignature)
                            .filter_by(document_id=doc_id, required=True)
                            .filter(AuditDocumentSignature.signed_at.is_(None))
                            .filter(AuditDocumentSignature.signer_role_label != "cb_reviewer")
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

            # Portal 50b — FR.218 completion: when the fr218_review document is
            # fully signed, auto-advance fr218_in_progress → fr218_complete.
            if doc and doc.document_type == "fr218_review" and remaining_all == 0:
                from audit_set.pipeline_triggers import check_fr218_completion
                check_fr218_completion(
                    audit_set_id=doc.audit_set_id,
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

        elif sig_key == "APPOINTED_REVIEWER" and not report.appointed_reviewer_signed_at:
            if not _audit_report_needs_appointed_reviewer(report, db):
                return
            # Portal 123 — record appointed reviewer's sign without changing overall status
            report.appointed_reviewer_user_id   = current_user.id
            report.appointed_reviewer_signed_at  = now
            report.appointed_reviewer_signed_ip  = ip
            db.commit()

        elif sig_key in ("CB_REVIEWER", "CB_CERT_MANAGER") and not report.reviewer_signed_at:
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
            # below for the FR.233 Certification Manager slot).

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

        elif sig_key in ("CLIENT", "ORG_REP") and not nc.client_signed_at:   # Portal 121
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
    Returns the signing status for every sig field on a document.
    Sources:
      1. DocumentSignatureField rows (written by pdfplumber during /prepare)
      2. AuditDocumentSignature rows (DB slots seeded at upload time)
    The union ensures slots that pdfplumber missed still appear in the response.
    Status values: signed | current_user | pending | blocked | not_applicable
    """
    docx_path = _resolve_docx_path(document_type, doc_id, db)

    # Source 1 — pdfplumber-detected sig keys (have a PDF position)
    pdf_sig_keys = {
        row.sig_key
        for row in db.query(DocumentSignatureField.sig_key)
            .filter(
                DocumentSignatureField.docx_path == docx_path,
                DocumentSignatureField.sig_key != "__none__",
            )
            .distinct()
            .all()
    }
    doc_row = (
        db.query(AuditSetSharedDocument).filter_by(id=doc_id).first()
        if document_type == "shared_doc" else None
    )
    if doc_row and doc_row.document_type == "meeting_form":
        pdf_sig_keys = {
            _canonical_meeting_sig_key(sk, doc_row, db, auth_db)
            for sk in pdf_sig_keys
        }

    # Source 2 — DB slot records seeded at upload time
    db_sig_keys: set[str] = set()
    if document_type == "shared_doc":
        slot_rows = (
            db.query(AuditDocumentSignature.signer_role_label)
            .filter_by(document_id=doc_id)
            .all()
        )
        for row in slot_rows:
            mapped = ROLE_TO_SIG.get(row.signer_role_label)
            if mapped:
                db_sig_keys.add(mapped)

        # Portal 73 — FR.225 (meeting_form) fallback: seed sig keys from the
        # org-employee roster + stage team so signing buttons appear even when
        # pdfplumber misses the wrapped UUID-based markers in narrow cells.
        # Seeding is additive; pdf_sig_keys (with coordinates) take precedence
        # via the union below, so the overlay boxes still appear when the PDF
        # scan succeeds.
        if doc_row and doc_row.document_type == "meeting_form":
            # Org-employee slots (ORG_OPENING + ORG_CLOSING for each employee)
            try:
                client_user = (
                    auth_db.query(PlatformUser)
                    .filter_by(role="client", audit_set_id=doc_row.audit_set_id)
                    .first()
                )
                if client_user:
                    employees = (
                        db.query(ClientOrgEmployee)
                        .filter_by(client_user_id=client_user.id, is_active=True)
                        .order_by(ClientOrgEmployee.created_at)  # must match packager order
                        .all()
                    )
                    # Portal 73 — use 1-based index (matches packager._resolve_org_attendees)
                    for i, _ in enumerate(employees, 1):
                        db_sig_keys.add(f"ORG_OPENING_ORG_EMP_{i}")
                        db_sig_keys.add(f"ORG_CLOSING_ORG_EMP_{i}")
            except Exception:
                logger.warning("[FR225] Could not seed employee sig keys for doc=%s", doc_id, exc_info=True)

            # Audit-team slots derived from the stage assignment
            try:
                stage = (
                    db.query(AuditSetStage)
                    .filter_by(
                        audit_set_id=doc_row.audit_set_id,
                        stage_type=doc_row.stage_type,
                    )
                    .first()
                )
                if stage:
                    for prefix in ("ORG_OPENING", "ORG_CLOSING"):
                        db_sig_keys.add(f"{prefix}_LEAD_AUDITOR")
                        for idx, _ in enumerate(stage.auditors or []):
                            db_sig_keys.add(f"{prefix}_AUDITOR_{idx}")
                        for idx, _ in enumerate(stage.technical_experts or []):
                            db_sig_keys.add(f"{prefix}_TE_{idx}")
            except Exception:
                logger.warning("[FR225] Could not seed team sig keys for doc=%s", doc_id, exc_info=True)

    all_sig_keys = pdf_sig_keys | db_sig_keys

    fields = [
        _get_field_status(sk, document_type, doc_id, current_user, db, auth_db)
        for sk in sorted(all_sig_keys)   # sorted for stable ordering
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
    _assert_can_sign(body.document_type, body.doc_id, body.sig_key, current_user, db, auth_db)

    # Portal 56 — client-side org-rep slots require an employee from the
    # client's roster. The legal user is still current_user, but the displayed
    # signer name and the embedded signature image are the employee's.
    client_side_slots = {"CLIENT", "ORG_REP"}
    selected_employee: Optional[ClientOrgEmployee] = None
    if body.employee_id:
        selected_employee = db.query(ClientOrgEmployee).filter_by(
            id=body.employee_id,
            client_user_id=current_user.id,
            is_active=True,
        ).first()
        if not selected_employee:
            raise HTTPException(404, "Employee not found in your roster.")
        if not selected_employee.signature_data:
            raise HTTPException(
                400,
                f"{selected_employee.full_name} has no signature on file. "
                "Upload a signature for them in Employees, then try again.",
            )
    if body.sig_key in client_side_slots and selected_employee is None:
        raise HTTPException(
            400,
            "Pick an employee from your organisation roster to sign on behalf of. "
            "If your roster is empty, add employees with signatures in the Employees page first.",
        )

    # Resolve the signature image to embed.
    #   ORG_OPENING_*/ORG_CLOSING_*  → employee resolved by 1-based row index (Portal 73)
    #   CLIENT / ORG_REP             → selected_employee from the picker (Portal 56)
    #   everything else              → current user's UserSignature
    org_match = ORG_SIG_RE.match(body.sig_key)
    if org_match:
        row_idx = int(org_match.group(2))
        # Resolve audit_set_id from the shared-document record (meeting_form is always shared_doc).
        _doc = db.query(AuditSetSharedDocument).filter_by(id=body.doc_id).first()
        audit_set_id = _doc.audit_set_id if _doc else None
        emp = _resolve_org_emp_by_index(audit_set_id, row_idx, db, auth_db) if audit_set_id else None
        if not emp or not emp.signature_data:
            raise HTTPException(400, "Employee signature missing — re-upload and try again.")
        signature_image_b64 = emp.signature_data
        signer_display_name = emp.full_name
    elif selected_employee is not None:
        signature_image_b64 = selected_employee.signature_data
        signer_display_name = selected_employee.full_name
    else:
        user_sig = auth_db.query(UserSignature).filter_by(user_id=current_user.id).first()
        if not user_sig or not user_sig.image_data:
            raise HTTPException(
                400,
                "No signature image on file. Go to Settings → My Signature to upload your signature, then try again.",
            )
        signature_image_b64 = user_sig.image_data
        signer_display_name = current_user.full_name

    # Reuse or create the pending VisualSignaturePlacement row.
    vsp = (
        db.query(VisualSignaturePlacement)
        .filter_by(
            document_type=body.document_type,
            doc_id=body.doc_id,
            sig_key=body.sig_key,
            user_id=current_user.id,
        )
        .order_by(VisualSignaturePlacement.created_at.desc())
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
    vsp.signer_name     = signer_display_name
    vsp.otp_hash        = None
    vsp.otp_expires     = None
    vsp.signed_at       = signed_at
    vsp.signed_ip       = ip
    db.commit()

    _commit_existing_signing_record(
        body.document_type, body.doc_id, body.sig_key, current_user, ip, db, auth_db,
        signed_at=signed_at,
        employee=selected_employee,
    )

    return {
        "signed":    True,
        "sig_key":   body.sig_key,
        "signed_at": vsp.signed_at.isoformat(),
    }
