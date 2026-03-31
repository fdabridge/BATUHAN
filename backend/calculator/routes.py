"""
BATUHAN — Audit Time Calculator: API Route
POST /calculator/calculate
  Accepts one or more uploaded files (PDF/DOCX/TXT of the application form),
  extracts data with Claude, runs the calculation engine, and returns a
  CalculationResult JSON immediately (synchronous — no job queue).
"""

from __future__ import annotations
import logging
import tempfile
import os
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from .extractor import extract_form_data
from .engine import calculate
from .models import CalculationResult

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calculator", tags=["calculator"])

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt"}
MAX_FILE_SIZE_MB = 20


@router.post("/calculate", response_model=CalculationResult)
async def calculator_calculate(
    files: list[UploadFile] = File(
        ...,
        description=(
            "One or more certification application form files "
            "(PDF, DOCX, TXT). For ISO 50001, also upload the EnMS form."
        ),
    ),
) -> CalculationResult:
    """
    Extract data from uploaded application form(s) using Claude, then calculate
    audit time according to ISO-specific tables and rules.

    Returns a CalculationResult with all phase splits and surveillance values.
    """
    if not files:
        raise HTTPException(status_code=422, detail="At least one file must be uploaded.")

    # ---- Validate file extensions ----
    for f in files:
        ext = Path(f.filename or "").suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Unsupported file type '{ext}' for '{f.filename}'. "
                    f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
                ),
            )

    # ---- Save uploads to temp files and extract text ----
    document_texts: list[dict[str, str]] = []
    tmp_paths: list[str] = []

    try:
        for upload in files:
            content = await upload.read()

            # File size check
            if len(content) > MAX_FILE_SIZE_MB * 1024 * 1024:
                raise HTTPException(
                    status_code=413,
                    detail=f"File '{upload.filename}' exceeds {MAX_FILE_SIZE_MB} MB limit.",
                )

            ext = Path(upload.filename or "upload").suffix.lower()
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                tmp.write(content)
                tmp_paths.append(tmp.name)

            # Import inline to avoid circular dependencies
            from parsers.text_extractor import extract_text
            text = extract_text(tmp_paths[-1])

            if not text.strip():
                logger.warning(f"No text extracted from '{upload.filename}' — file may be scanned/image-only.")

            document_texts.append({"filename": upload.filename or "upload", "text": text})

        if not any(d["text"].strip() for d in document_texts):
            raise HTTPException(
                status_code=422,
                detail=(
                    "No readable text could be extracted from the uploaded file(s). "
                    "Ensure files are not scanned images without OCR text."
                ),
            )

        # ---- Extract structured data with Claude ----
        logger.info(f"Starting Claude extraction for {len(document_texts)} file(s).")
        try:
            extracted = extract_form_data(document_texts)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except Exception as e:
            logger.error(f"Claude extraction failed: {e}", exc_info=True)
            raise HTTPException(
                status_code=502,
                detail=f"Claude extraction error: {e}",
            )

        logger.info(
            f"Extraction complete: org='{extracted.org_name}', "
            f"standards={extracted.standards}, "
            f"employees={extracted.total_employees}"
        )

        # ---- Run calculation engine ----
        try:
            result = calculate(extracted)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except Exception as e:
            logger.error(f"Calculation engine failed: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Calculation error: {e}",
            )

        logger.info(
            f"Calculation complete: final_total={result.final_total} days, "
            f"ph1={result.final_ph1}, ph2={result.final_ph2}"
        )
        return result

    finally:
        # Always clean up temp files
        for path in tmp_paths:
            try:
                os.unlink(path)
            except OSError:
                pass

