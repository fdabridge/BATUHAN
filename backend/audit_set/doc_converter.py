"""
Certiva — DOCX → PDF conversion + signature field extraction (Prompt 23).

Provides two public functions:
  - prepare_document(docx_path, db)  ← main entry point used by viewer_router
  - extract_sig_fields(pdf_path)     ← pure pdfplumber scan, no DB side effects

LibreOffice headless performs the conversion. HOME is set to /tmp to allow
the container's no-home-dir user to write LibreOffice's config files.

Coordinate system: pdfplumber returns coordinates in PDF points (72 pts/inch)
with origin at the top-left of the page. page_width and page_height are also
in points. The viewer uses these values to compute pixel overlay positions.
"""
from __future__ import annotations

import os
import re
import subprocess
from typing import TYPE_CHECKING

import fitz
import pdfplumber

from storage.document_store import ensure_local, is_s3_ref

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# Portal 65 — KEY now allows lowercase and hyphens so UUID-based sig keys
# (e.g. ORG_OPENING_ORG_EMP_<uuid> and COMMITTEE_MEMBER_<auditor_id>) are
# matched when the UUID contains lowercase hex digits and hyphens.
_SIG_PATTERN = re.compile(r"^\[SIG:\s*([A-Za-z0-9_-]+)\]$")
# Search pattern used with page.search() — must match _SIG_PATTERN exactly.
_SIG_SEARCH  = r"\[SIG:\s*[A-Za-z0-9_\-]+\]"
MARKER_HIDE_PAD = 1.5


# Portal 59 Fix 4 — legacy sig-key migration. Older rendered PDFs on disk still
# carry pre-rename marker names; remap them to the current canonical names so
# the viewer can find the placement coordinates without forcing a re-upload.
# Applied conditionally per template basename because some keys (CLIENT,
# CB_REVIEWER) remain canonical in other templates (FR.220/221/230 use CLIENT;
# FR.218/229 use CB_REVIEWER).
def _normalize_sig_key(raw_key: str, docx_basename: str) -> str:
    if raw_key == "AUDITOR_MEMBER":
        return "ASSIGNED_AUDITOR"
    name = docx_basename.upper()
    if raw_key == "CLIENT" and (
        "FR.211" in name or "FR.223" in name
        or "FR.230" in name or "FR230" in name   # Portal 121 — NC form
    ):
        return "ORG_REP"
    # Portal 123 — old templates used [SIG:CB_REVIEWER] for the appointed reviewer's
    # slot in stage reports. Normalize to APPOINTED_REVIEWER (canonical key). New
    # templates write [SIG:APPOINTED_REVIEWER] directly, so this rule is a
    # backward-compat fallback for already-uploaded pre-Portal-123 reports.
    if raw_key == "CB_REVIEWER" and ("FR.231" in name or "FR.232" in name):
        return "APPOINTED_REVIEWER"
    # FR.233 now uses the same canonical Certification Manager key as the rest
    # of the system. Normalize both historical variants for already-uploaded
    # documents.
    if (
        raw_key in ("CERT_MANAGER_REVIEW", "CERT_MANAGER_FR233")
        and "FR.233" in name
    ):
        return "CB_CERT_MANAGER"
    return raw_key


# ── DOCX → PDF ───────────────────────────────────────────────────────────────

def convert_docx_to_pdf(docx_path: str) -> str:
    """
    Convert a DOCX to PDF using LibreOffice headless.
    The PDF is written to the same directory as the DOCX.
    Returns the absolute path to the generated PDF.
    Raises RuntimeError on failure.
    """
    docx_path  = os.path.abspath(docx_path)
    output_dir = os.path.dirname(docx_path)

    env = os.environ.copy()
    env["HOME"] = "/tmp"  # LibreOffice needs a writable home for user profile

    result = subprocess.run(
        [
            "libreoffice", "--headless",
            "--convert-to", "pdf",
            "--outdir", output_dir,
            docx_path,
        ],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"LibreOffice conversion failed (exit {result.returncode}).\n"
            f"stderr: {result.stderr[:500]}"
        )

    stem     = os.path.splitext(os.path.basename(docx_path))[0]
    pdf_path = os.path.join(output_dir, f"{stem}.pdf")

    if not os.path.exists(pdf_path):
        raise RuntimeError(
            f"LibreOffice succeeded but PDF not found at expected path:\n  {pdf_path}"
        )

    return pdf_path


# ── Field extraction ─────────────────────────────────────────────────────────

def extract_sig_fields(pdf_path: str) -> list[dict]:
    """
    Scan a PDF for [SIG:KEY] placeholder text injected by Prompt 21.
    Returns a list of dicts, one per found placeholder:
      { sig_key, page_number, x0, y0, x1, y1, page_width, page_height }
    A document with no placeholders returns an empty list.

    Portal 65 — primary scan uses page.search() so that:
      1. Keys whose text spans multiple PDF text runs (produced when docxtpl
         substitutes a Jinja2 expression inside a sig marker) are still found.
      2. UUID-embedded keys (ORG_OPENING_ORG_EMP_<uuid>, COMMITTEE_MEMBER_<id>)
         that contain lowercase hex digits and hyphens are matched correctly.

    Portal 73 — fallback scan uses word-level concatenation to detect long
    UUID-based sig keys (e.g. ORG_OPENING_ORG_EMP_<uuid>, 60+ chars) that
    wrap across PDF lines in narrow FR.225 table cells and therefore escape
    the single-line page.search() regex.  The bounding box is computed from
    the union of the words that together form the wrapped key.
    """
    fields: list[dict] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            # ── Primary scan ───────────────────────────────────────────────
            found_keys: set[str] = set()
            matches = page.search(_SIG_SEARCH, regex=True)
            for match in matches:
                m = _SIG_PATTERN.match(match.get("text", ""))
                if m:
                    sig_key = m.group(1)
                    found_keys.add(sig_key)
                    fields.append({
                        "sig_key":     sig_key,
                        "page_number": page_idx,
                        "x0":          float(match["x0"]),
                        "y0":          float(match["top"]),
                        "x1":          float(match["x1"]),
                        "y1":          float(match["bottom"]),
                        "page_width":  float(page.width),
                        "page_height": float(page.height),
                    })

            # ── Fallback scan for line-wrapped keys (Portal 73) ────────────
            # FR.225 uses UUID-based sig keys (60+ chars) inside narrow table
            # cells (~1.7 in).  LibreOffice wraps these across two PDF lines,
            # breaking page.search()'s single-line regex.  We use extract_words()
            # and slide a growing window over adjacent words, concatenating their
            # text until a complete [SIG:...] pattern is formed.
            words = page.extract_words(use_text_flow=True, keep_blank_chars=False)
            i = 0
            while i < len(words):
                w_text = words[i]["text"]
                if "[SIG:" not in w_text:
                    i += 1
                    continue
                # A word containing "[SIG:" found — grow window to find the "]"
                accumulated = w_text
                j = i
                while "]" not in accumulated and j < len(words) - 1:
                    j += 1
                    accumulated += words[j]["text"]
                m = _SIG_PATTERN.match(accumulated.strip())
                if m:
                    sig_key = m.group(1)
                    if sig_key not in found_keys:
                        window = words[i: j + 1]
                        x0 = float(min(w["x0"]     for w in window))
                        y0 = float(min(w["top"]    for w in window))
                        x1 = float(max(w["x1"]     for w in window))
                        y1 = float(max(w["bottom"] for w in window))
                        fields.append({
                            "sig_key":     sig_key,
                            "page_number": page_idx,
                            "x0":          x0,
                            "y0":          y0,
                            "x1":          x1,
                            "y1":          y1,
                            "page_width":  float(page.width),
                            "page_height": float(page.height),
                        })
                        found_keys.add(sig_key)
                i += 1
    return fields


def _field_value(field, key: str):
    if isinstance(field, dict):
        return field[key]
    return getattr(field, key)


def hide_signature_markers(pdf_path: str, fields: list) -> None:
    """
    Cover [SIG:...] marker text in the cached viewer PDF after coordinates are
    extracted. The marker positions remain in the DB for signing overlays.
    """
    visible_fields = [f for f in fields if _field_value(f, "sig_key") != "__none__"]
    if not visible_fields or not os.path.exists(pdf_path):
        return

    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return

    changed = False
    saved_copy: str | None = None
    try:
        for field in visible_fields:
            page_idx = int(_field_value(field, "page_number"))
            if page_idx < 0 or page_idx >= len(doc):
                continue

            page = doc[page_idx]
            rect = fitz.Rect(
                max(0.0, float(_field_value(field, "x0")) - MARKER_HIDE_PAD),
                max(0.0, float(_field_value(field, "y0")) - MARKER_HIDE_PAD),
                min(page.rect.x1, float(_field_value(field, "x1")) + MARKER_HIDE_PAD),
                min(page.rect.y1, float(_field_value(field, "y1")) + MARKER_HIDE_PAD),
            )
            if rect.is_empty:
                continue
            page.draw_rect(rect, color=(1.0, 1.0, 1.0), fill=(1.0, 1.0, 1.0), width=0)
            changed = True

        if changed:
            try:
                doc.saveIncr()
            except Exception:
                saved_copy = f"{pdf_path}.markers.tmp"
                try:
                    doc.save(saved_copy, garbage=4, deflate=True)
                except Exception:
                    saved_copy = None
    finally:
        doc.close()
    if saved_copy:
        try:
            os.replace(saved_copy, pdf_path)
        except Exception:
            pass


# ── Main entry point ─────────────────────────────────────────────────────────

def prepare_document(docx_path: str, db: "Session") -> dict:
    """
    Idempotent prepare step called by the viewer when a document is opened.

    Steps:
      1. Convert DOCX → PDF (if PDF not already present alongside DOCX).
      2. Extract [SIG:...] fields from PDF (if not already in document_signature_fields).
      3. Return { pdf_path, fields }.

    Raises RuntimeError if conversion fails.
    """
    from audit_set.db_models import DocumentSignatureField

    docx_path = ensure_local(docx_path) if is_s3_ref(docx_path) else os.path.abspath(docx_path)
    pdf_path  = os.path.splitext(docx_path)[0] + ".pdf"

    # Step 1: Convert DOCX → PDF
    if not os.path.exists(pdf_path):
        pdf_path = convert_docx_to_pdf(docx_path)

    # Step 2: Return from cache if already extracted.
    # Exception: if the ONLY cached row is the "__none__" sentinel it means a
    # previous scan found nothing (possibly before the sliding-window scanner
    # was deployed, or before the document was regenerated with real UUID
    # markers). Delete the sentinel and fall through to re-scan so the improved
    # scanner gets a chance to find the markers now.
    existing = db.query(DocumentSignatureField).filter_by(docx_path=docx_path).all()
    if existing:
        if len(existing) == 1 and existing[0].sig_key == "__none__":
            db.query(DocumentSignatureField).filter_by(
                docx_path=docx_path, sig_key="__none__"
            ).delete()
            db.commit()
            existing = []
        else:
            hide_signature_markers(pdf_path, existing)
            return {
                "pdf_path": pdf_path,
                "fields": [
                    {
                        "sig_key":     f.sig_key,
                        "page_number": f.page_number,
                        "x0": f.x0, "y0": f.y0,
                        "x1": f.x1, "y1": f.y1,
                        "page_width":  f.page_width,
                        "page_height": f.page_height,
                    }
                    for f in existing
                ],
            }

    # Step 3: Extract and store
    raw_fields = extract_sig_fields(pdf_path)
    docx_basename = os.path.basename(docx_path)
    for field in raw_fields:
        db.add(DocumentSignatureField(
            docx_path   = docx_path,
            pdf_path    = pdf_path,
            sig_key     = _normalize_sig_key(field["sig_key"], docx_basename),
            page_number = field["page_number"],
            x0          = field["x0"],
            y0          = field["y0"],
            x1          = field["x1"],
            y1          = field["y1"],
            page_width  = field["page_width"],
            page_height = field["page_height"],
        ))

    # Sentinel for docs with no [SIG:...] fields — avoids re-scanning on every open
    if not raw_fields:
        db.add(DocumentSignatureField(
            docx_path   = docx_path,
            pdf_path    = pdf_path,
            sig_key     = "__none__",
            page_number = 0,
            x0=0, y0=0, x1=0, y1=0,
            page_width=0, page_height=0,
        ))

    db.commit()
    stored_fields = (
        db.query(DocumentSignatureField)
        .filter(DocumentSignatureField.docx_path == docx_path)
        .all()
    )
    hide_signature_markers(pdf_path, stored_fields)
    return {"pdf_path": pdf_path, "fields": raw_fields}
