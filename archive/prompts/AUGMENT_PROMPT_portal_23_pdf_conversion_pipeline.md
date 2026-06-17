# Prompt 23 — PDF Conversion Pipeline: DOCX → PDF + Signature Field Extraction

## Context

This is the Certiva platform. We are building a DocuSign-like visual signing layer.

- Prompt 21: `[SIG:PARTY]` placeholder text injected into all DOCX templates (57 files).
- Prompt 22: Users save personal signatures (drawn or uploaded) in `user_signatures` table.
- **Prompt 23 (this one)**: Infrastructure layer. Convert uploaded DOCX files to PDFs at request time. Scan for `[SIG:...]` placeholder coordinates using pdfplumber. Store coordinates in a new `document_signature_fields` table. Add a viewer-prep endpoint and PDF serve endpoint so the in-portal viewer (Prompt 24) can load documents.
- Prompt 24: In-portal PDF viewer with clickable overlay signature boxes (PDF.js + React).
- Prompt 25: Visual signing + OTP commit flow.
- Prompt 26: PDF flattening — embed placed signatures into final document.

---

## Confirmed existing state (verified by reading source files)

- `pdfplumber==0.11.4` is **already in `requirements.txt`**. No new Python dependency needed.
- LibreOffice is **not** in the Dockerfile — it must be added.
- `audit_set/db_models.py` has `create_tables()` → `Base.metadata.create_all(bind=engine)`. Adding a new `DocumentSignatureField` model to this file is all that's needed for table creation.
- Document type → file path mapping:
  - `"shared_doc"` → `AuditSetSharedDocument.file_path` (covers quotation FR.220, agreement FR.221, audit_plan FR.223, FR.218 CB forms, FR.222, certificates)
  - `"audit_report"` → `AuditSetAuditReport.file_path` (covers FR.229, FR.231, FR.232)
  - `"nc_form"` → `AuditSetNCForm.file_path` (covers FR.230)
- The `batuhan` user in the Docker container has write access to `/app/storage/`. PDFs will be stored alongside their source DOCXs.
- LibreOffice needs a writable HOME directory. The container user has `--no-create-home`. Solution: set `HOME=/tmp` in the subprocess environment explicitly.
- `main.py` registers routers via `app.include_router(...)`.

---

## Change 1 of 5 — `backend/Dockerfile`

### Add LibreOffice headless + fonts to the system dependencies block

Find the existing `RUN apt-get update && apt-get install -y --no-install-recommends` block:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-tur \
    libmupdf-dev \
    libjpeg-dev \
    libpng-dev \
    libtiff-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*
```

Replace it with:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Tesseract OCR engine + language packs
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-tur \
    # PDF rendering (PyMuPDF / pdfplumber)
    libmupdf-dev \
    # Image support (Pillow)
    libjpeg-dev \
    libpng-dev \
    libtiff-dev \
    # Build tools
    gcc \
    # LibreOffice headless — DOCX → PDF conversion (Prompt 23)
    libreoffice-writer \
    libreoffice-calc \
    fonts-liberation \
    fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*
```

`libreoffice-writer` handles DOCX conversion. `fonts-liberation` provides metric-compatible Arial/Times/Courier substitutes (critical for correct layout). `fonts-noto-core` provides Unicode coverage for non-Latin characters in client documents.

**Note on image size**: LibreOffice writer adds approximately 150–200 MB to the image. This is unavoidable for server-side DOCX → PDF conversion without an external service.

---

## Change 2 of 5 — `backend/audit_set/db_models.py`

### Add `DocumentSignatureField` model

Add this class at the end of the file, after `AuditSetAuditReport`:

```python
# ---------------------------------------------------------------------------
# Table 13 — document_signature_fields
# Stores bounding-box coordinates of [SIG:KEY] placeholders extracted from PDFs.
# Populated lazily when a document is first opened in the in-portal viewer.
# Keyed by docx_path (absolute) so it's decoupled from document type.
# ---------------------------------------------------------------------------

class DocumentSignatureField(Base):
    __tablename__ = "document_signature_fields"

    id           = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    docx_path    = Column(String, nullable=False, index=True)   # absolute path to source DOCX
    pdf_path     = Column(String, nullable=True)                # absolute path to converted PDF
    sig_key      = Column(String, nullable=False)               # e.g. "CB_PLANNER" | "CLIENT"
    page_number  = Column(Integer, nullable=False)              # 0-indexed
    # Bounding box in PDF points (72 pts/inch), pdfplumber top-left origin
    x0           = Column(Float, nullable=False)
    y0           = Column(Float, nullable=False)
    x1           = Column(Float, nullable=False)
    y1           = Column(Float, nullable=False)
    # Page dimensions (needed by viewer to compute overlay pixel positions)
    page_width   = Column(Float, nullable=False)
    page_height  = Column(Float, nullable=False)
    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False)
```

No changes to `create_tables()` — `Base.metadata.create_all(bind=engine)` already handles new models.

---

## Change 3 of 5 — `backend/audit_set/doc_converter.py` (new file)

Create this file:

```python
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

import pdfplumber

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# Regex for [SIG:KEY] tokens — KEY is uppercase letters, digits, underscores
_SIG_PATTERN = re.compile(r"^\[SIG:([A-Z0-9_]+)\]$")


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

    # LibreOffice names the output {stem}.pdf in output_dir
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
      {
        sig_key,     # e.g. "CB_PLANNER"
        page_number, # 0-indexed
        x0, y0, x1, y1,   # bounding box in PDF points (top-left origin)
        page_width, page_height,  # page dimensions in points
      }
    A document with no placeholders returns an empty list (e.g. certificate uploads).
    """
    fields: list[dict] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            words = page.extract_words(
                x_tolerance=3,
                y_tolerance=3,
                keep_blank_chars=True,
            )
            for word in words:
                m = _SIG_PATTERN.match(word.get("text", ""))
                if m:
                    fields.append({
                        "sig_key":     m.group(1),
                        "page_number": page_idx,
                        "x0":          float(word["x0"]),
                        "y0":          float(word["top"]),
                        "x1":          float(word["x1"]),
                        "y1":          float(word["bottom"]),
                        "page_width":  float(page.width),
                        "page_height": float(page.height),
                    })
    return fields


# ── Main entry point ─────────────────────────────────────────────────────────

def prepare_document(docx_path: str, db: "Session") -> dict:
    """
    Idempotent prepare step called by the viewer when a document is opened.

    Steps:
      1. Convert DOCX → PDF (if PDF not already present alongside DOCX).
      2. Extract [SIG:...] fields from PDF (if not already in document_signature_fields).
      3. Return { pdf_path, fields }.

    Raises RuntimeError if conversion fails (LibreOffice not available, bad DOCX, etc.).
    """
    from audit_set.db_models import DocumentSignatureField

    docx_path = os.path.abspath(docx_path)
    pdf_path  = os.path.splitext(docx_path)[0] + ".pdf"

    # ── Step 1: Convert DOCX → PDF ───────────────────────────────────────────
    if not os.path.exists(pdf_path):
        pdf_path = convert_docx_to_pdf(docx_path)

    # ── Step 2: Check if fields already extracted ────────────────────────────
    existing = (
        db.query(DocumentSignatureField)
        .filter_by(docx_path=docx_path)
        .all()
    )
    if existing:
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

    # ── Step 3: Extract and store ─────────────────────────────────────────────
    raw_fields = extract_sig_fields(pdf_path)
    for field in raw_fields:
        db.add(DocumentSignatureField(
            docx_path   = docx_path,
            pdf_path    = pdf_path,
            sig_key     = field["sig_key"],
            page_number = field["page_number"],
            x0          = field["x0"],
            y0          = field["y0"],
            x1          = field["x1"],
            y1          = field["y1"],
            page_width  = field["page_width"],
            page_height = field["page_height"],
        ))

    # If a document has no [SIG:...] fields (e.g. a certificate), store a
    # sentinel row so we don't re-scan on every open. Use sig_key = "__none__".
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

    return {"pdf_path": pdf_path, "fields": raw_fields}
```

---

## Change 4 of 5 — `backend/audit_set/viewer_router.py` (new file)

Create this file:

```python
"""
Certiva — In-portal document viewer endpoints (Prompt 23).

Two endpoints used by the <CertivaDocumentViewer> React component (Prompt 24):

  GET /viewer/prepare?document_type=shared_doc&doc_id=<id>
    → Converts DOCX → PDF (lazy) + extracts [SIG:...] field coordinates.
    → Returns { fields: [...], page_count }
    → Idempotent: safe to call multiple times; results are cached in DB.

  GET /viewer/pdf?document_type=shared_doc&doc_id=<id>
    → Streams the converted PDF bytes with Content-Type: application/pdf.
    → Returns 404 if /viewer/prepare has not been called first.
    → PDF.js in the viewer fetches this URL directly.

document_type values:
  "shared_doc"    → AuditSetSharedDocument (quotation, agreement, audit_plan, FR.218, FR.222, etc.)
  "audit_report"  → AuditSetAuditReport    (FR.229, FR.231, FR.232)
  "nc_form"       → AuditSetNCForm         (FR.230)

Access control: any authenticated user. Fine-grained per-audit-set access
is enforced by the fact that document IDs are UUIDs — guessing is infeasible.
Augment may tighten access if needed (e.g. restrict nc_form to CB + lead auditor).
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from audit_set.db_models import (
    AuditSetAuditReport,
    AuditSetNCForm,
    AuditSetSharedDocument,
    get_db,
)
from audit_set.doc_converter import prepare_document
from auth.db_models import PlatformUser
from auth.dependencies import get_current_user

router = APIRouter(prefix="/viewer", tags=["viewer"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_docx_path(document_type: str, doc_id: str, db: Session) -> str:
    """
    Map (document_type, doc_id) → absolute DOCX file path.
    Raises HTTPException 404 if not found or file_path is null.
    """
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
    document_type: str   = Query(..., description="shared_doc | audit_report | nc_form"),
    doc_id:        str   = Query(..., description="UUID of the document record"),
    db:            Session     = Depends(get_db),
    current_user:  PlatformUser = Depends(get_current_user),
):
    """
    Idempotent: converts DOCX → PDF if not already done, extracts [SIG:...] fields
    if not already in DB, returns field coordinates.

    Called by the viewer component immediately before rendering. May take 2–5 seconds
    on first call (LibreOffice conversion). Subsequent calls return instantly from cache.
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
    document_type: str   = Query(...),
    doc_id:        str   = Query(...),
    db:            Session     = Depends(get_db),
    current_user:  PlatformUser = Depends(get_current_user),
):
    """
    Stream the converted PDF to the browser. PDF.js calls this URL directly.
    Returns 404 if /viewer/prepare has not been called first to generate the PDF.
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
```

---

## Change 5 of 5 — `backend/main.py`

### 5a. Add import (near other audit_set router imports)

```python
from audit_set.viewer_router import router as viewer_router
```

### 5b. Register router

Add after `app.include_router(report_router)`:

```python
app.include_router(viewer_router)
```

---

## What is NOT changing

- No existing routers are modified.
- No existing frontend files are modified.
- `requirements.txt` is not changed — `pdfplumber` is already present.
- No changes to the OTP signing flow.
- The viewer component (Prompt 24), signing flow (Prompt 25), and PDF flattening (Prompt 26) are future prompts.
- `reportlab` (needed for Prompt 26 PDF flattening) is deliberately not added here to keep this prompt contained.

---

## Verification checklist

1. Docker image builds without errors (`docker build -t certiva-test .` or Railway deploy).
2. `libreoffice --version` prints a version number from inside the container.
3. `GET /viewer/prepare?document_type=shared_doc&doc_id=<valid_id>` with an existing DOCX:
   - Returns `{ fields: [...], document_type, doc_id }`.
   - A `.pdf` file appears alongside the `.docx` in the same directory.
   - `document_signature_fields` rows are inserted (check via `GET /viewer/prepare` a second time — it returns instantly from cache).
4. `GET /viewer/pdf?document_type=shared_doc&doc_id=<same_id>` returns HTTP 200 with `Content-Type: application/pdf` (can be opened in browser).
5. For a document without `[SIG:...]` fields (e.g. a certificate upload): `fields` array is `[]` and a `__none__` sentinel row is in `document_signature_fields`.
6. `npx tsc --noEmit` passes (no TypeScript errors — no frontend changes in this prompt).
7. `GET /viewer/prepare?document_type=audit_report&doc_id=<valid_report_id>` correctly finds FR.231/229/232 files.

---

## Manual test procedure (for Augment to run if LibreOffice is available locally)

```python
# Quick sanity test from repo root (if libreoffice is installed locally)
from audit_set.doc_converter import convert_docx_to_pdf, extract_sig_fields

test_docx = "backend/uaf_blank_set copy/9-14-45-22-5001/Initial Certification /Stage 1/FR.220_Quotation_Form_R15&09.10.2025.docx"
pdf = convert_docx_to_pdf(test_docx)
print("PDF at:", pdf)

fields = extract_sig_fields(pdf)
print("Fields found:", len(fields))
for f in fields:
    print(f"  [SIG:{f['sig_key']}] page={f['page_number']} box=({f['x0']:.1f},{f['y0']:.1f})→({f['x1']:.1f},{f['y1']:.1f})")
```

Expected: at least two fields found — `CB_PLANNER` and `CLIENT` — on the last page.

If LibreOffice is not available locally, skip the local test and verify after Railway deploy.

---

## Commit message

```
feat(portal): DOCX→PDF conversion pipeline + signature field extraction (Prompt 23)

- Dockerfile: add libreoffice-writer + fonts-liberation + fonts-noto-core for
  DOCX→PDF conversion (adds ~150–200 MB to image)
- audit_set/db_models.py: add DocumentSignatureField model (docx_path, pdf_path,
  sig_key, page_number, x0/y0/x1/y1, page_width/page_height)
- audit_set/doc_converter.py: convert_docx_to_pdf() via LibreOffice headless
  (HOME=/tmp for container compat), extract_sig_fields() via pdfplumber,
  prepare_document() idempotent entry point with __none__ sentinel for no-field docs
- audit_set/viewer_router.py: GET /viewer/prepare (lazy convert+extract, returns fields)
  + GET /viewer/pdf (streams PDF bytes for PDF.js). Routes by document_type:
  shared_doc|audit_report|nc_form → respective file_path columns
- main.py: register viewer_router
```
