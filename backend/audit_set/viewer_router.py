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
