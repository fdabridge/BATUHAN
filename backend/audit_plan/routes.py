"""
BATUHAN — Audit Plan: API Route
POST /audit-plan/generate
  Accepts one pre-filled FR.223 .docx template, generates a schedule with
  the configured AI service, fills Table 2, and returns the completed .docx for download.
POST /audit-plan/jobs
  Queues the same controlled generation flow so browser/proxy interruptions do
  not discard long-running work. The synchronous endpoint remains compatible.
"""

from __future__ import annotations
import asyncio
import base64
import json
import logging
import re
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from auth.db_models import PlatformUser
from auth.dependencies import require_any
from .clause_map import normalize_audit_type, normalize_standard
from .template_reader import DayWindow, read_template
from .schedule_generator import generate_schedule
from .docx_filler import fill_schedule
from .service import audit_plan_filename, context_to_dict

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/audit-plan", tags=["audit-plan"])

MAX_FILE_SIZE_MB = 20


async def _read_template_upload(template: UploadFile) -> bytes:
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
    return content


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _normalise_clock(raw: str | None, fallback: str = "") -> str:
    value = _clean(raw)
    if not value:
        return fallback
    value = value.replace(":", ".")
    parts = value.split(".")
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"{int(parts[0]):02d}.{parts[1][:2].zfill(2)}"
    if len(value) == 4 and value.isdigit():
        return f"{int(value[:2]):02d}.{value[2:]}"
    return value


def _normalise_date(raw: str | None) -> str:
    value = _clean(raw)
    if not value:
        return ""
    # Browser date inputs send YYYY-MM-DD; FR.223 wants DD.MM.YYYY.
    if len(value) == 10 and value[4] == "-" and value[7] == "-":
        year, month, day = value.split("-")
        if year.isdigit() and month.isdigit() and day.isdigit():
            return f"{day}.{month}.{year}"
    return value


def _parse_standards(raw: str | None) -> tuple[list[str], str]:
    value = _clean(raw)
    if not value:
        return [], ""

    parts: list[str]
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            parts = [str(item) for item in parsed]
        else:
            parts = [value]
    except json.JSONDecodeError:
        parts = [p.strip() for p in re.split(r"[,\n;+]+", value) if p.strip()]

    standards: list[str] = []
    for part in parts:
        for candidate in re.split(r"[,\n;+]+", part):
            norm = normalize_standard(candidate)
            if norm and norm not in standards:
                standards.append(norm)
    return standards, ", ".join(standards or parts)


def _parse_day_windows(raw: str | None) -> list[DayWindow]:
    value = _clean(raw)
    if not value:
        return []

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"Day windows must be valid JSON: {exc}") from exc

    if not isinstance(parsed, list):
        raise HTTPException(status_code=422, detail="Day windows must be a JSON list.")

    windows: list[DayWindow] = []
    for index, item in enumerate(parsed, start=1):
        if not isinstance(item, dict):
            raise HTTPException(status_code=422, detail=f"Day {index} window must be an object.")

        date = _normalise_date(item.get("date"))
        start_time = _normalise_clock(item.get("start_time"))
        end_time = _normalise_clock(item.get("end_time"))
        lunch_start = _normalise_clock(item.get("lunch_start"), "13.00")
        lunch_end = _normalise_clock(item.get("lunch_end"), "14.00")
        site = _clean(item.get("site"))

        missing = []
        if not date:
            missing.append("date")
        if not start_time:
            missing.append("start time")
        if not end_time:
            missing.append("end time")
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"Day {index} is missing {', '.join(missing)}.",
            )

        windows.append(DayWindow(
            date=date,
            start_time=start_time,
            end_time=end_time,
            lunch_start=lunch_start,
            lunch_end=lunch_end,
            site=site,
        ))

    return windows


def _apply_manual_context(
    ctx,
    *,
    standards: str | None,
    audit_type: str | None,
    ea_code: str | None,
    category: str | None,
    scope: str | None,
    org_name: str | None,
    address: str | None,
    day_windows: str | None,
) -> None:
    parsed_standards, standards_raw = _parse_standards(standards)
    if parsed_standards:
        ctx.standards = parsed_standards
        ctx.standards_raw = standards_raw

    audit_type_value = _clean(audit_type)
    if audit_type_value:
        ctx.audit_type_raw = audit_type_value
        ctx.audit_type = normalize_audit_type(audit_type_value) or audit_type_value

    for attr, value in {
        "ea_code": ea_code,
        "category": category,
        "scope": scope,
        "org_name": org_name,
        "address": address,
    }.items():
        cleaned = _clean(value)
        if cleaned:
            setattr(ctx, attr, cleaned)

    windows = _parse_day_windows(day_windows)
    if windows:
        ctx.day_windows = windows
        ctx.audit_dates = ", ".join(window.date for window in windows)
        ctx.audit_time = "; ".join(
            f"{window.date} {window.start_time}-{window.end_time}"
            for window in windows
        )


async def _prepare_context(
    content: bytes,
    *,
    standards: str | None,
    audit_type: str | None,
    ea_code: str | None,
    category: str | None,
    scope: str | None,
    org_name: str | None,
    address: str | None,
    day_windows: str | None,
):
    try:
        ctx = await asyncio.to_thread(read_template, content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.error("[AuditPlan] Template read failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Could not parse template: {exc}")

    _apply_manual_context(
        ctx,
        standards=standards,
        audit_type=audit_type,
        ea_code=ea_code,
        category=category,
        scope=scope,
        org_name=org_name,
        address=address,
        day_windows=day_windows,
    )

    if not ctx.standards:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Could not identify any ISO standard in the template "
                f"(found: '{ctx.standards_raw}'). "
                "Ensure the Standard/s cell is filled correctly."
            ),
        )
    if not ctx.audit_dates:
        raise HTTPException(
            status_code=422,
            detail="Add at least one audit day with a date, start time, and end time.",
        )
    return ctx


@router.post("/generate")
async def audit_plan_generate(
    template: UploadFile = File(
        ...,
        description=(
            "Pre-filled FR.223 audit plan (.docx) with Tables 0 and 1 already "
            "completed. Table 2 (schedule) must be empty — BATUHAN will fill it."
        ),
    ),
    standards: str | None = Form(None),
    audit_type: str | None = Form(None),
    ea_code: str | None = Form(None),
    category: str | None = Form(None),
    scope: str | None = Form(None),
    org_name: str | None = Form(None),
    address: str | None = Form(None),
    day_windows: str | None = Form(None),
) -> Response:
    """
    Generate a filled audit plan schedule.

    1. Reads org info, audit type, dates, and team from the uploaded template.
    2. Looks up the correct clauses from the hardcoded FR.222 CLAUSE_MAP.
    3. Calls the AI service to generate an hourly schedule.
    4. Injects the schedule into Table 2 of the uploaded template.
    5. Returns the completed .docx as a file download.
    """
    content = await _read_template_upload(template)
    ctx = await _prepare_context(
        content,
        standards=standards,
        audit_type=audit_type,
        ea_code=ea_code,
        category=category,
        scope=scope,
        org_name=org_name,
        address=address,
        day_windows=day_windows,
    )

    logger.info(
        f"[AuditPlan] Template parsed | org='{ctx.org_name}' "
        f"standards={ctx.standards} type='{ctx.audit_type}' dates='{ctx.audit_dates}'"
    )

    # ---- Step 2: Generate schedule with AI (blocking I/O — run in thread pool) ----
    try:
        days = await asyncio.to_thread(generate_schedule, ctx)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.error(f"[AuditPlan] Schedule generation failed: {exc}", exc_info=True)
        raise HTTPException(
            status_code=502,
            detail=f"AI schedule generation error: {exc}",
        )

    # ---- Step 3: Fill Table 1 (sites) + Table 2 (schedule) in the template ----
    try:
        filled_bytes = await asyncio.to_thread(fill_schedule, content, days, ctx)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.error(f"[AuditPlan] DOCX filling failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fill template: {exc}")

    # ---- Step 4: Return filled .docx ----
    filename = audit_plan_filename(ctx)

    logger.info(f"[AuditPlan] Returning filled .docx: '{filename}' ({len(filled_bytes)} bytes)")

    return Response(
        content=filled_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/jobs")
async def create_audit_plan_job(
    template: UploadFile = File(...),
    standards: str | None = Form(None),
    audit_type: str | None = Form(None),
    ea_code: str | None = Form(None),
    category: str | None = Form(None),
    scope: str | None = Form(None),
    org_name: str | None = Form(None),
    address: str | None = Form(None),
    day_windows: str | None = Form(None),
    _: PlatformUser = Depends(require_any),
):
    """Queue audit-plan generation and return immediately with a stable job id."""
    from storage.file_store import generate_job_id, save_text_artifact

    content = await _read_template_upload(template)
    ctx = await _prepare_context(
        content,
        standards=standards,
        audit_type=audit_type,
        ea_code=ea_code,
        category=category,
        scope=scope,
        org_name=org_name,
        address=address,
        day_windows=day_windows,
    )
    job_id = generate_job_id()
    status = {
        "audit_plan_job_id": job_id,
        "state": "QUEUED",
        "error_message": None,
        "filename": None,
    }
    save_text_artifact(job_id, "audit_plan_status.json", json.dumps(status))

    try:
        from jobs.audit_plan_task import generate_audit_plan_job

        generate_audit_plan_job.delay(
            job_id=job_id,
            template_b64=base64.b64encode(content).decode("ascii"),
            context_payload=context_to_dict(ctx),
        )
    except Exception as exc:
        logger.error("Could not queue audit plan job %s: %s", job_id, exc, exc_info=True)
        status.update({
            "state": "FAILED",
            "error_message": "Could not queue the audit-plan job. Please try again.",
        })
        save_text_artifact(job_id, "audit_plan_status.json", json.dumps(status))
        raise HTTPException(status_code=503, detail=status["error_message"])

    return status


@router.get("/jobs/{job_id}")
async def get_audit_plan_job(
    job_id: str,
    _: PlatformUser = Depends(require_any),
):
    from storage.file_store import read_text_artifact

    try:
        return json.loads(read_text_artifact(job_id, "audit_plan_status.json"))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Audit-plan job not found.")


@router.get("/jobs/{job_id}/download")
async def download_audit_plan_job(
    job_id: str,
    _: PlatformUser = Depends(require_any),
) -> Response:
    from storage.file_store import read_binary_artifact, read_text_artifact

    try:
        status = json.loads(read_text_artifact(job_id, "audit_plan_status.json"))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Audit-plan job not found.")
    if status.get("state") != "COMPLETE":
        raise HTTPException(status_code=409, detail="Audit plan is not ready yet.")
    try:
        document = read_binary_artifact(job_id, "audit_plan.docx")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Generated audit plan was not found.")
    filename = status.get("filename") or f"AuditPlan_{job_id}.docx"
    return Response(
        content=document,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
