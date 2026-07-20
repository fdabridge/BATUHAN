"""
BATUHAN — Job Submission API Routes (T6 + T7)
Handles file uploads, audit metadata capture, and job creation.
POST /jobs/create  → accepts all inputs, encodes files, queues task, returns job_id
GET  /jobs/{job_id}/status → returns current job state (read from Redis)
"""

from __future__ import annotations
import base64
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from schemas.models import ISOStandard, AuditStage, JobStatus, JobState, ReportLanguage, JobAuditorConfig
from typing import List
from storage.file_store import (
    generate_job_id, validate_extension, save_text_artifact,
    job_exists, read_text_artifact, read_binary_artifact, list_job_ids,
)
from auth.db_models import PlatformUser
from auth.dependencies import require_auditor, require_any

router = APIRouter(prefix="/jobs", tags=["jobs"])
logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".png", ".jpg", ".jpeg", ".tiff"}


async def _encode_file(upload: UploadFile) -> dict:
    """Read an UploadFile and return {filename, content_b64} — JSON-serialisable."""
    content = await upload.read()
    return {
        "filename": upload.filename or "upload",
        "content_b64": base64.b64encode(content).decode("ascii"),
    }


@router.post("/create")
async def create_job(
    standards: List[str] = Form(..., description="One or more ISO standard codes (e.g. QMS, EMS). Repeat field for multiple."),
    stage: AuditStage = Form(..., description="Report context: Stage 1, Stage 2, Surveillance 1, Surveillance 2, or Recertification"),
    company_documents: list[UploadFile] = File(
        ..., description="Company documents (PDF, DOCX, TXT, PNG, JPG)"
    ),
    sample_reports: list[UploadFile] = File(
        ..., description="Sample audit reports for style reference"
    ),
    template: UploadFile = File(
        ..., description="Blank audit report template (.docx)"
    ),
    org_name: str | None = Form(None, description="Auditee / organisation name"),
    org_address: str | None = Form(None, description="Organisation address or site"),
    org_phone: str | None = Form(None, description="Organisation phone number"),
    language: ReportLanguage = Form(ReportLanguage.EN, description="Report writing language: EN (English) or TR (Turkish)"),
    accreditation_body: str = Form(default="UAF",
        description="Accreditation body: UAF or TURKAK"),
    auditor_config: str | None = Form(default=None,
        description="Optional JSON string: JobAuditorConfig — auditor-to-clause assignments"),
    _: PlatformUser = Depends(require_auditor),
):
    """
    Create a new BATUHAN audit job.
    File contents are read into memory, base64-encoded, and passed directly
    to the Celery task through Redis — no shared filesystem is required.
    """
    # Validate and deduplicate standard codes
    try:
        parsed_standards = list(dict.fromkeys(ISOStandard(s) for s in standards))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid standard code: {exc}")
    if not parsed_standards:
        raise HTTPException(status_code=400, detail="At least one standard must be selected.")

    valid_bodies = ["UAF", "TURKAK"]
    if accreditation_body.upper() not in valid_bodies:
        raise HTTPException(
            status_code=400,
            detail=f"accreditation_body must be one of {valid_bodies}",
        )

    parsed_auditor_config = None
    if auditor_config:
        try:
            parsed_auditor_config = JobAuditorConfig.model_validate_json(auditor_config)
        except Exception:
            raise HTTPException(status_code=422, detail="Invalid auditor_config JSON")

    job_id = generate_job_id()
    logger.info(f"Creating job {job_id} | standards={[s.value for s in parsed_standards]} | stage={stage}")

    # --- Validate template extension ---
    if not (template.filename or "").lower().endswith((".docx", ".doc")):
        raise HTTPException(status_code=400, detail="Template must be a .docx file.")

    standard_values = [s.value for s in parsed_standards]

    # --- Validate and encode company documents ---
    company_files: list[dict] = []
    for f in company_documents:
        if not validate_extension(f.filename or ""):
            raise HTTPException(
                status_code=400,
                detail=f"File type not allowed: {f.filename}. "
                       f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
            )
        company_files.append(await _encode_file(f))

    # --- Validate and encode sample reports ---
    sample_files: list[dict] = []
    for f in sample_reports:
        if not validate_extension(f.filename or ""):
            raise HTTPException(
                status_code=400,
                detail=f"File type not allowed: {f.filename}. "
                       f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
            )
        sample_files.append(await _encode_file(f))

    # --- Encode template ---
    template_file = await _encode_file(template)

    # --- Initialise job status in Redis (shared with the worker) ---
    status = JobStatus(
        job_id=job_id,
        state=JobState.QUEUED,
        started_at=datetime.utcnow(),
    )
    save_text_artifact(job_id, "status.json", status.model_dump_json(indent=2))

    # --- Persist lightweight metadata for the reports list view ---
    meta = {
        "job_id": job_id,
        "company": org_name or "",
        "standards": standard_values,
        "stage": stage.value,
        "language": language.value,
        "accreditation_body": accreditation_body.upper(),
        "submitted_at": datetime.utcnow().isoformat(),
    }
    save_text_artifact(job_id, "meta.json", json.dumps(meta, indent=2))

    # --- Queue pipeline — pass file contents directly, no filesystem dependency ---
    try:
        from jobs.tasks import run_pipeline
        run_pipeline.delay(
            job_id,
            company_files,
            sample_files,
            template_file,
            standard_values,
            stage.value,
            org_name or "",
            org_address or "",
            org_phone or "",
            language.value,
            accreditation_body.upper(),
            parsed_auditor_config.model_dump() if parsed_auditor_config else None,
        )
        logger.info(
            f"Job {job_id} queued with {len(company_files)} company docs, "
            f"{len(sample_files)} sample reports, standards={standard_values}, "
            f"language={language.value}."
        )
    except Exception as e:
        logger.warning(f"Could not queue job {job_id} via Celery: {e}.")

    return {
        "job_id": job_id,
        "status": JobState.QUEUED,
        "standards": standard_values,
        "stage": stage,
        "language": language.value,
        "company_documents_received": len(company_files),
        "sample_reports_received": len(sample_files),
        "template_received": True,
        "message": "Job created and queued. Poll /jobs/{job_id}/status for progress.",
    }


@router.get("/")
def list_jobs(_: PlatformUser = Depends(require_any)):
    """Return a summary of all known jobs for the reports list view.
    Combines persisted meta.json with the current status.json."""
    out: list[dict] = []
    for job_id in list_job_ids():
        try:
            meta_raw = read_text_artifact(job_id, "meta.json")
            meta = json.loads(meta_raw)
        except Exception:
            meta = {}
        try:
            status_raw = read_text_artifact(job_id, "status.json")
            status = json.loads(status_raw)
        except Exception:
            status = {}
        out.append({
            "job_id": job_id,
            "company": meta.get("company", ""),
            "standards": meta.get("standards", []),
            "stage": meta.get("stage", ""),
            "language": meta.get("language", ""),
            "accreditation_body": meta.get("accreditation_body", ""),
            "submitted_at": meta.get("submitted_at") or status.get("started_at"),
            "state": status.get("state", "QUEUED"),
            "current_step": status.get("current_step"),
            "error_message": status.get("error_message"),
            "completed_at": status.get("completed_at"),
        })
    out.sort(key=lambda j: j.get("submitted_at") or "", reverse=True)
    return out



@router.get("/{job_id}/status")
def get_job_status(job_id: str, _: PlatformUser = Depends(require_any)):
    """Return the current status of a job."""
    if not job_exists(job_id):
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    try:
        raw = read_text_artifact(job_id, "status.json")
        return json.loads(raw)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not read job status: {e}")


@router.get("/{job_id}/download/report")
def download_report(job_id: str, _: PlatformUser = Depends(require_any)):
    """Download the final assembled .docx report (served from Redis)."""
    if not job_exists(job_id):
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    try:
        content = read_binary_artifact(job_id, "final_report.docx")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Report not ready yet.")
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="audit_report_{job_id}.docx"'},
    )


@router.get("/{job_id}/summary")
def get_job_summary(job_id: str, _: PlatformUser = Depends(require_any)):
    """Return the job summary JSON (standard, stage, files, correction count)."""
    if not job_exists(job_id):
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    try:
        raw = read_text_artifact(job_id, "job_summary.json")
        return json.loads(raw)
    except Exception:
        raise HTTPException(status_code=404, detail="Summary not available yet.")


@router.get("/{job_id}/download/corrections")
def download_corrections(job_id: str, _: PlatformUser = Depends(require_any)):
    """Download the correction log as a text file."""
    if not job_exists(job_id):
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    try:
        content = read_text_artifact(job_id, "correction_log.txt")
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(content=content, media_type="text/plain")
    except Exception:
        raise HTTPException(status_code=404, detail="Correction log not ready yet.")


@router.get("/{job_id}/download/coverage-report")
def download_coverage_report(job_id: str, _: PlatformUser = Depends(require_any)):
    """Download the clause coverage validation report as a text file."""
    if not job_exists(job_id):
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    try:
        data = read_text_artifact(job_id, "coverage_validation_report.txt")
        if not data:
            raise HTTPException(status_code=404, detail="Coverage report not found")
        return Response(
            content=data,
            media_type="text/plain",
            headers={"Content-Disposition": f"attachment; filename=coverage_report_{job_id}.txt"},
        )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="Coverage report not found")
