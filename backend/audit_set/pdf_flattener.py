"""
Certiva — PDF flattening (Prompt 26).

Embeds placed signature images into the PDF at the coordinates of each
[SIG:KEY] placeholder, whiting out the placeholder text first.

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

import base64
import os
from typing import TYPE_CHECKING

import fitz  # PyMuPDF

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


# Minimum overlay dimensions in PDF points (1 pt = 1/72 inch)
SIG_MIN_W = 140.0
SIG_MIN_H = 28.0

# Padding around the [SIG:...] text bounding box for the whiteout rect
WHITEOUT_PAD = 4.0


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
    fields = (
        db.query(DocumentSignatureField)
        .filter(
            DocumentSignatureField.docx_path == docx_path,
            DocumentSignatureField.sig_key.in_(list(placement_map.keys())),
        )
        .all()
    )
    if not fields:
        with open(pdf_path, "rb") as f:
            return f.read()

    field_map = {f.sig_key: f for f in fields}

    # ── Open PDF and embed signatures ─────────────────────────────────────────
    doc = fitz.open(pdf_path)

    for sig_key, placement in placement_map.items():
        field = field_map.get(sig_key)
        if not field:
            continue

        page_idx = field.page_number   # 0-indexed
        if page_idx >= len(doc):
            continue

        page = doc[page_idx]

        # Decode the base64 PNG data-URL
        img_data = placement.signature_image
        if img_data.startswith("data:"):
            img_data = img_data.split(",", 1)[1]
        try:
            img_bytes = base64.b64decode(img_data)
        except Exception:
            continue   # skip broken image, don't abort the whole document

        # ── Compute overlay rectangle ─────────────────────────────────────────
        x0, y0, x1, y1 = field.x0, field.y0, field.x1, field.y1
        cx = (x0 + x1) / 2.0
        cy = (y0 + y1) / 2.0

        sig_w = max(SIG_MIN_W, (x1 - x0) + 40.0)
        sig_h = max(SIG_MIN_H, (y1 - y0) + 10.0)

        overlay_rect = fitz.Rect(
            cx - sig_w / 2.0,
            cy - sig_h / 2.0,
            cx + sig_w / 2.0,
            cy + sig_h / 2.0,
        )

        # ── White-out the [SIG:...] placeholder text ──────────────────────────
        placeholder_rect = fitz.Rect(
            x0 - WHITEOUT_PAD,
            y0 - WHITEOUT_PAD,
            x1 + WHITEOUT_PAD,
            y1 + WHITEOUT_PAD,
        )
        # Draw a white filled rectangle with no visible border
        page.draw_rect(
            placeholder_rect,
            color=(1.0, 1.0, 1.0),
            fill=(1.0, 1.0, 1.0),
            width=0,
        )

        # ── Insert signature image ────────────────────────────────────────────
        try:
            page.insert_image(overlay_rect, stream=img_bytes)
        except Exception:
            # Fallback: print signer's name as text if image fails
            page.insert_text(
                (overlay_rect.x0 + 4, overlay_rect.y0 + overlay_rect.height / 2 + 4),
                "[Signed]",
                fontsize=9,
                color=(0.1, 0.27, 0.19),
            )

    # ── Serialize ─────────────────────────────────────────────────────────────
    result = doc.tobytes(garbage=4, deflate=True)
    doc.close()
    return result


# ── Internal helper ───────────────────────────────────────────────────────────

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

    return os.path.abspath(path)
