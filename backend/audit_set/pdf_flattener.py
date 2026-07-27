"""
Certiva — PDF flattening (Prompt 26).

Embeds placed signature images into the PDF at the coordinates of each
[SIG:KEY] placeholder, hiding only the placeholder text first.

Uses PyMuPDF (fitz), which is already in requirements.txt.

Coordinate system
-----------------
pdfplumber (used in doc_converter.py) stores coordinates as:
  x0, y0 = left, top   (top-left origin, y increases downward)
  x1, y1 = right, bottom

PyMuPDF uses the SAME coordinate convention for its fitz.Rect objects on
a standard page, so pdfplumber coordinates can be passed to fitz.Rect
directly without inversion.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from io import BytesIO
from typing import TYPE_CHECKING, Any

import fitz  # PyMuPDF

import logging

from audit_set.signature_image import signature_pdf_streams, signature_png_bytes
from audit_set.signature_marker_visibility import (
    erase_marker_boxes,
    marker_hide_boxes,
    signature_marker_candidates,
)
from storage.document_store import ensure_local

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


# Minimum overlay dimensions in PDF points (1 pt = 1/72 inch)
SIG_MIN_W = 140.0
SIG_MIN_H = 28.0
NAME_TEXT_H = 10.0
NAME_GAP = 1.5

SIG_TO_ROLE = {
    "CB_PLANNER": "cb_planner",
    "CB_CERT_MANAGER": "cb_cert_manager",
    "CB_REVIEWER": "cb_reviewer",
    "LEAD_AUDITOR": "lead_auditor",
    "GM": "gm",
    "ORG_REP": "org_rep",
    "CLIENT": "client",
    "ASSIGNED_AUDITOR": "assigned_auditor",
    "REVIEWER": "reviewer",
    "APPOINTED_REVIEWER": "appointed_reviewer",
    "TRANSFER_REVIEWER": "transfer_reviewer",
    "TRANSFER_CERT_DECISION": "committee_chair",
}


def has_completed_visual_signatures(
    document_type: str,
    doc_id: str,
    db: "Session",
) -> bool:
    """Return True when a document has at least one burnable visual signature."""
    from audit_set.db_models import VisualSignaturePlacement

    return (
        db.query(VisualSignaturePlacement.id)
        .filter(
            VisualSignaturePlacement.document_type == document_type,
            VisualSignaturePlacement.doc_id == doc_id,
            VisualSignaturePlacement.signed_at.isnot(None),
            VisualSignaturePlacement.signature_image.isnot(None),
        )
        .first()
        is not None
    )


def flatten_document(
    document_type: str,
    doc_id: str,
    db: "Session",
) -> bytes:
    """
    Return a flattened PDF with all completed VisualSignaturePlacements
    burned in. Falls back to the raw converted PDF if no visual signatures
    exist yet (e.g. document was signed via the old OTP button before
    Prompt 25 was deployed).

    Raises FileNotFoundError if /viewer/prepare has not been called yet.
    """
    from audit_set.db_models import DocumentSignatureField, VisualSignaturePlacement

    # ── Resolve paths ─────────────────────────────────────────────────────────
    docx_path = _resolve_docx_path(document_type, doc_id, db)
    pdf_path  = os.path.splitext(docx_path)[0] + ".pdf"

    if not os.path.exists(pdf_path):
        raise FileNotFoundError(
            "PDF not found. Open the document in the viewer first to trigger conversion."
        )

    # ── Get completed placements (with signature images) ──────────────────────
    placements = (
        db.query(VisualSignaturePlacement)
        .filter(
            VisualSignaturePlacement.document_type == document_type,
            VisualSignaturePlacement.doc_id == doc_id,
            VisualSignaturePlacement.signed_at.isnot(None),
            VisualSignaturePlacement.signature_image.isnot(None),
        )
        .all()
    )

    if not placements:
        # No visual placements — return original converted PDF as-is
        with open(pdf_path, "rb") as f:
            return f.read()

    placement_map = {p.sig_key: p for p in placements}

    # ── Get field coordinates ─────────────────────────────────────────────────
    # ── Get field coordinates (alias-aware) ───────────────────────────────
    _SIG_ALIASES = {
        "CB_REVIEWER":         "CB_CERT_MANAGER",
        "AUDITOR_MEMBER":      "ASSIGNED_AUDITOR",
        "CLIENT":              "ORG_REP",
        "CERT_MANAGER_REVIEW": "CB_CERT_MANAGER",
        "CERT_MANAGER_FR233":  "CB_CERT_MANAGER",
    }
    all_sig_keys: set[str] = set()
    for k in placement_map.keys():
        all_sig_keys.add(k)
        for old_k, new_k in _SIG_ALIASES.items():
            if new_k == k:
                all_sig_keys.add(old_k)

    fields = (
        db.query(DocumentSignatureField)
        .filter(
            DocumentSignatureField.docx_path == docx_path,
            DocumentSignatureField.sig_key.in_(list(all_sig_keys)),
        )
        .all()
    )
    if not fields:
        logger.warning(
            "[flatten_document] No DocumentSignatureField rows found for %s/%s "
            "(docx_path=%s, sig_keys=%s). Returning raw PDF.",
            document_type, doc_id, docx_path, sorted(all_sig_keys),
        )
        with open(pdf_path, "rb") as f:
            return f.read()

    field_map = {f.sig_key: f for f in fields}

    # ── Open a fresh PDF and embed signatures ─────────────────────────────────
    # Existing cached PDFs may already contain old broad whiteouts from earlier
    # marker hiding. Flatten from a fresh conversion so downloads can self-heal.
    source_pdf_path = pdf_path
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    try:
        from audit_set.doc_converter import convert_docx_to_pdf

        temp_dir = tempfile.TemporaryDirectory(prefix="certiva-flatten-")
        temp_docx_path = os.path.join(temp_dir.name, os.path.basename(docx_path))
        shutil.copy2(docx_path, temp_docx_path)
        source_pdf_path = convert_docx_to_pdf(temp_docx_path)
    except Exception as exc:
        logger.warning(
            "[flatten_document] Could not regenerate fresh PDF for %s; "
            "using cached PDF %s: %s",
            docx_path,
            pdf_path,
            exc,
        )

    try:
        doc = fitz.open(source_pdf_path)
    except Exception as exc:
        # Corrupted or unreadable PDF — fall back to the raw file bytes.
        logger.warning(
            "[flatten_document] fitz.open() failed for %s/%s: %s — returning raw PDF",
            document_type, doc_id, exc,
        )
        if temp_dir is not None:
            temp_dir.cleanup()
        with open(pdf_path, "rb") as f:
            return f.read()

    render_jobs: list[tuple[int, Any, fitz.Rect, fitz.Rect, str | None]] = []
    marker_boxes_by_page: dict[int, list[tuple[float, float, float, float]]] = {}

    for sig_key, placement in placement_map.items():
        field = field_map.get(sig_key)
        if not field:
            for old_k, new_k in _SIG_ALIASES.items():
                if new_k == sig_key and old_k in field_map:
                    field = field_map[old_k]
                    break
        if not field:
            logger.warning(
                "[flatten_document] No DSF field for sig_key=%s on %s/%s — skipping",
                sig_key, document_type, doc_id,
            )
            continue

        page_idx = field.page_number   # 0-indexed
        if page_idx >= len(doc):
            continue

        page = doc[page_idx]

        # ── Compute overlay rectangle ─────────────────────────────────────────
        x0, y0, x1, y1 = field.x0, field.y0, field.x1, field.y1
        cx = (x0 + x1) / 2.0
        cy = (y0 + y1) / 2.0

        sig_w = max(SIG_MIN_W, (x1 - x0) + 40.0)
        sig_h = max(SIG_MIN_H, (y1 - y0) + 10.0)
        signer_name = _placement_signer_name(document_type, doc_id, sig_key, placement, db)

        overlay_rect = fitz.Rect(
            cx - sig_w / 2.0,
            cy - sig_h / 2.0,
            cx + sig_w / 2.0,
            cy + sig_h / 2.0,
        )
        name_rect = _name_rect_below_signature(overlay_rect, doc[page_idx].rect)

        # ── Hide only the [SIG:...] placeholder text ──────────────────────────
        marker_boxes = marker_hide_boxes(
            page,
            (float(field.x0), float(field.y0), float(field.x1), float(field.y1)),
            signature_marker_candidates(sig_key, field.sig_key),
        )
        if marker_boxes:
            marker_boxes_by_page.setdefault(page_idx, []).extend(marker_boxes)
        render_jobs.append((page_idx, placement, overlay_rect, name_rect, signer_name))

    # Remove all marker text before adding signature images or signer names.
    # Transparent text redaction preserves table lines, cell shading and images.
    for page_idx, marker_boxes in marker_boxes_by_page.items():
        erase_marker_boxes(doc[page_idx], marker_boxes)

    for page_idx, placement, overlay_rect, name_rect, signer_name in render_jobs:
        page = doc[page_idx]
        # ── Insert signature image ────────────────────────────────────────────
        try:
            _insert_signature_image(page, overlay_rect, placement.signature_image)
            if signer_name:
                _insert_signer_name(page, name_rect, signer_name)
        except Exception:
            # Fallback: print signer's name as text if image fails
            try:
                page.insert_text(
                    (overlay_rect.x0 + 4, overlay_rect.y0 + overlay_rect.height / 2 + 4),
                    signer_name or "[Signed]",
                    fontsize=9,
                    color=(0.1, 0.27, 0.19),
                )
            except Exception:
                pass  # don't let a single failed signature abort the whole document

    # ── Serialize ─────────────────────────────────────────────────────────────
    try:
        result = doc.tobytes(garbage=4, deflate=True)
    except Exception as exc:
        # If fitz can't serialise the modified document, return the original PDF.
        logger.warning(
            "[flatten_document] tobytes() failed for %s/%s: %s — returning raw PDF",
            document_type, doc_id, exc,
        )
        doc.close()
        if temp_dir is not None:
            temp_dir.cleanup()
        with open(pdf_path, "rb") as f:
            return f.read()

    doc.close()
    if temp_dir is not None:
        temp_dir.cleanup()
    return result


# ── Internal helper ───────────────────────────────────────────────────────────

def _fit_image_rect(rect: fitz.Rect, image_size: tuple[int, int]) -> fitz.Rect:
    """Fit an image inside a slot without stretching or covering extra PDF area."""
    image_width, image_height = image_size
    if image_width <= 0 or image_height <= 0 or rect.width <= 0 or rect.height <= 0:
        return rect

    image_ratio = image_width / image_height
    slot_ratio = rect.width / rect.height

    if image_ratio >= slot_ratio:
        fitted_width = rect.width
        fitted_height = fitted_width / image_ratio
    else:
        fitted_height = rect.height
        fitted_width = fitted_height * image_ratio

    cx = (rect.x0 + rect.x1) / 2.0
    cy = (rect.y0 + rect.y1) / 2.0
    return fitz.Rect(
        cx - fitted_width / 2.0,
        cy - fitted_height / 2.0,
        cx + fitted_width / 2.0,
        cy + fitted_height / 2.0,
    )


def _insert_signature_image(page: fitz.Page, rect: fitz.Rect, image_data: str) -> None:
    """Insert signature image with alpha mask so transparent pixels stay clear."""
    try:
        image_bytes, alpha_mask, image_size = signature_pdf_streams(image_data)
        image_rect = _fit_image_rect(rect, image_size)
        try:
            page.insert_image(
                image_rect,
                stream=image_bytes,
                mask=alpha_mask,
                keep_proportion=True,
            )
        except TypeError:
            page.insert_image(image_rect, stream=image_bytes, mask=alpha_mask)
        return
    except Exception:
        png_bytes = signature_png_bytes(image_data)
        image_rect = rect
        try:
            from PIL import Image

            with Image.open(BytesIO(png_bytes)) as image:
                image_rect = _fit_image_rect(rect, image.size)
        except Exception:
            pass
        try:
            page.insert_image(image_rect, stream=png_bytes, keep_proportion=True)
        except TypeError:
            page.insert_image(image_rect, stream=png_bytes)


def _name_rect_below_signature(signature_rect: fitz.Rect, page_rect: fitz.Rect) -> fitz.Rect:
    """Return a small centered text box just below the visual signature."""
    y0 = signature_rect.y1 + NAME_GAP
    y1 = y0 + NAME_TEXT_H
    if y1 > page_rect.y1 - 2:
        y1 = signature_rect.y1 - 1
        y0 = y1 - NAME_TEXT_H
    return fitz.Rect(signature_rect.x0, y0, signature_rect.x1, y1)


def _insert_signer_name(page: fitz.Page, rect: fitz.Rect, signer_name: str) -> None:
    """Draw the human signer name under the signature image."""
    cleaned = " ".join((signer_name or "").split())
    if not cleaned:
        return
    page.insert_textbox(
        rect,
        cleaned,
        fontsize=7.5,
        fontname="helv",
        color=(0.1, 0.27, 0.19),
        align=fitz.TEXT_ALIGN_CENTER,
    )


def _auth_user_name(user_id: str | None) -> str | None:
    if not user_id:
        return None
    try:
        from auth.db_models import PlatformUser, SessionLocal as AuthSessionLocal

        auth_db = AuthSessionLocal()
        try:
            user = auth_db.query(PlatformUser).filter_by(id=user_id).first()
            return user.full_name if user else None
        finally:
            auth_db.close()
    except Exception:
        return None


def _placement_signer_name(
    document_type: str,
    doc_id: str,
    sig_key: str,
    placement,
    db: "Session",
) -> str | None:
    """Best-effort display name for the burned-in signature label."""
    name = getattr(placement, "signer_name", None)
    if name:
        return name

    from audit_set.db_models import (
        AuditDocumentSignature,
        AuditSetAuditReport,
        AuditSetNCForm,
        AuditSetSharedDocument,
    )

    if document_type == "shared_doc":
        role_label = SIG_TO_ROLE.get(sig_key)
        if role_label:
            sig = db.query(AuditDocumentSignature).filter_by(
                document_id=doc_id, signer_role_label=role_label,
            ).first()
            if sig and sig.signer_name:
                return sig.signer_name
        doc = db.query(AuditSetSharedDocument).filter_by(id=doc_id).first()
        if doc and sig_key in ("CLIENT", "ORG_REP"):
            client_slot = db.query(AuditDocumentSignature).filter_by(
                document_id=doc_id, signer_role_label="client",
            ).first()
            if client_slot and client_slot.signer_name:
                return client_slot.signer_name

    elif document_type == "audit_report":
        report = db.query(AuditSetAuditReport).filter_by(id=doc_id).first()
        if report:
            if sig_key == "LEAD_AUDITOR":
                return _auth_user_name(report.la_user_id)
            if sig_key == "APPOINTED_REVIEWER":
                name = _auth_user_name(report.appointed_reviewer_user_id)
                return name or report.reviewer_auditor_name
            if sig_key in ("CB_REVIEWER", "CB_CERT_MANAGER"):
                return _auth_user_name(report.reviewer_user_id)

    elif document_type == "nc_form":
        nc = db.query(AuditSetNCForm).filter_by(id=doc_id).first()
        if nc:
            if sig_key == "LEAD_AUDITOR":
                return _auth_user_name(nc.la_user_id)
            if sig_key in ("CLIENT", "ORG_REP"):
                return _auth_user_name(nc.client_user_id)

    return _auth_user_name(getattr(placement, "user_id", None))


def _resolve_docx_path(document_type: str, doc_id: str, db: "Session") -> str:
    """Map (document_type, doc_id) → absolute DOCX file path."""
    from audit_set.db_models import AuditSetAuditReport, AuditSetNCForm, AuditSetSharedDocument

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

    if not path:
        raise FileNotFoundError("Document not found or has no file")

    try:
        return ensure_local(path)
    except (FileNotFoundError, Exception):
        raise FileNotFoundError(f"Document file not found: {path}")
