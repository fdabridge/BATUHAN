"""
BATUHAN — Audit Plan: API Route
POST /audit-plan/generate
  Accepts one pre-filled FR.223 .docx template, generates a schedule with
  Claude, fills Table 2, and returns the completed .docx for download.
  Fully synchronous — no Celery queue.
"""

from __future__ import annotations
import logging
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response

from .template_reader import read_template
from .schedule_generator import generate_schedule
from .docx_filler import fill_schedule

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/audit-plan", tags=["audit-plan"])

MAX_FILE_SIZE_MB = 20


@router.post("/generate")
async def audit_plan_generate(
    template: UploadFile = File(
        ...,
        description=(
            "Pre-filled FR.223 audit plan (.docx) with Tables 0 and 1 already "
            "completed. Table 2 (schedule) must be empty — BATUHAN will fill it."
        ),
    ),
) -> Response:
    """
    Generate a filled audit plan schedule.

    1. Reads org info, audit type, dates, and team from the uploaded template.
    2. Looks up the correct clauses from the hardcoded FR.222 CLAUSE_MAP.
    3. Calls Claude to generate an hourly schedule.
    4. Injects the schedule into Table 2 of the uploaded template.
    5. Returns the completed .docx as a file download.
    """
    # ---- Validate extension ----
    ext = Path(template.filename or "").suffix.lower()
    if ext not in {".docx", ".doc"}:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type '{ext}'. Please upload a .docx audit plan template.",
        )

    content = await template.read()

    if len(content) > MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds {MAX_FILE_SIZE_MB} MB limit.",
        )

    if not content:
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")

    # ---- Step 1: Read template context ----
    try:
        ctx = read_template(content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.error(f"[AuditPlan] Template read failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Could not parse template: {exc}")

    if not ctx.standards:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Could not identify any ISO standard in the template "
                f"(found: '{ctx.standards_raw}'). "
                "Ensure the Standard/s cell is filled correctly."
            ),
        )

    logger.info(
        f"[AuditPlan] Template parsed | org='{ctx.org_name}' "
        f"standards={ctx.standards} type='{ctx.audit_type}' dates='{ctx.audit_dates}'"
    )

    # ---- Step 2: Generate schedule with Claude ----
    try:
        days = generate_schedule(ctx)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.error(f"[AuditPlan] Schedule generation failed: {exc}", exc_info=True)
        raise HTTPException(
            status_code=502,
            detail=f"Claude schedule generation error: {exc}",
        )

    # ---- Step 3: Fill Table 2 in the template ----
    try:
        filled_bytes = fill_schedule(content, days)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.error(f"[AuditPlan] DOCX filling failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fill template: {exc}")

    # ---- Step 4: Return filled .docx ----
    safe_org = "".join(c if c.isalnum() or c in " _-" else "_" for c in ctx.org_name)[:40]
    filename = f"AuditPlan_{safe_org}_{ctx.audit_type.replace(' ', '')}_{ctx.audit_dates.replace('/', '-')}.docx"

    logger.info(f"[AuditPlan] Returning filled .docx: '{filename}' ({len(filled_bytes)} bytes)")

    return Response(
        content=filled_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
