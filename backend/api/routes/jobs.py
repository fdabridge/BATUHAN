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

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from schemas.models import ISOStandard, AuditStage, JobStatus, JobState
from storage.file_store import (
    generate_job_id, validate_extension, save_text_artifact,
    job_exists, read_text_artifact, read_binary_artifact,
)

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
    standard: ISOStandard = Form(..., description="ISO standard (e.g. QMS, EMS)"),
    stage: AuditStage = Form(..., description="Audit stage: 'Stage 1' or 'Stage 2'"),
    company_documents: list[UploadFile] = File(
        ..., description="Company documents (PDF, DOCX, TXT, PNG, JPG)"
    ),
    sample_reports: list[UploadFile] = File(
        ..., description="Sample audit reports for style reference"
    ),
    template: UploadFile = File(
        ..., description="Blank audit report template (.docx)"
    ),
):
    """
    Create a new BATUHAN audit job.
    File contents are read into memory, base64-encoded, and passed directly
    to the Celery task through Redis — no shared filesystem is required.
    """
    job_id = generate_job_id()
    logger.info(f"Creating job {job_id} | standard={standard} | stage={stage}")

    # --- Validate template extension ---
    if not (template.filename or "").lower().endswith((".docx", ".doc")):
        raise HTTPException(status_code=400, detail="Template must be a .docx file.")

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

    # --- Queue pipeline — pass file contents directly, no filesystem dependency ---
    try:
        from jobs.tasks import run_pipeline
        run_pipeline.delay(
            job_id,
            company_files,
            sample_files,
            template_file,
            standard.value,
            stage.value,
        )
        logger.info(f"Job {job_id} queued with {len(company_files)} company docs, "
                    f"{len(sample_files)} sample reports.")
    except Exception as e:
        logger.warning(f"Could not queue job {job_id} via Celery: {e}.")

    return {
        "job_id": job_id,
        "status": JobState.QUEUED,
        "standard": standard,
        "stage": stage,
        "company_documents_received": len(company_files),
        "sample_reports_received": len(sample_files),
        "template_received": True,
        "message": "Job created and queued. Poll /jobs/{job_id}/status for progress.",
    }


@router.get("/{job_id}/status")
def get_job_status(job_id: str):
    """Return the current status of a job."""
    if not job_exists(job_id):
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    try:
        raw = read_text_artifact(job_id, "status.json")
        return json.loads(raw)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not read job status: {e}")


@router.get("/{job_id}/download/report")
def download_report(job_id: str):
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
def get_job_summary(job_id: str):
    """Return the job summary JSON (standard, stage, files, correction count)."""
    if not job_exists(job_id):
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    try:
        raw = read_text_artifact(job_id, "job_summary.json")
        return json.loads(raw)
    except Exception:
        raise HTTPException(status_code=404, detail="Summary not available yet.")


@router.get("/{job_id}/download/corrections")
def download_corrections(job_id: str):
    """Download the correction log as a text file."""
    if not job_exists(job_id):
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    try:
        content = read_text_artifact(job_id, "correction_log.txt")
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(content=content, media_type="text/plain")
    except Exception:
        raise HTTPException(status_code=404, detail="Correction log not ready yet.")

