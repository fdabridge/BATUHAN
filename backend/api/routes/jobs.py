"""
BATUHAN — Job Submission API Routes (T6 + T7)
Handles file uploads, audit metadata capture, and job creation.
POST /jobs/create  → accepts all inputs, stores files, returns job_id
GET  /jobs/{job_id}/status → returns current job state
"""

from __future__ import annotations
import json
import logging
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from backend.schemas.models import (
    ISOStandard, AuditStage, JobStatus, JobState, UploadBundle
)
from backend.storage.file_store import (
    generate_job_id, save_upload, save_text_artifact,
    list_files, job_exists, read_text_artifact
)
from datetime import datetime

router = APIRouter(prefix="/jobs", tags=["jobs"])
logger = logging.getLogger(__name__)


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
    Accepts all required inputs, stores them, and queues the pipeline.
    Returns the job_id for status polling.
    """
    job_id = generate_job_id()
    logger.info(f"Creating job {job_id} | standard={standard} | stage={stage}")

    # --- Validate template extension ---
    if not (template.filename or "").lower().endswith((".docx", ".doc")):
        raise HTTPException(
            status_code=400,
            detail="Template must be a .docx file."
        )

    # --- Save company documents ---
    company_paths: list[str] = []
    for f in company_documents:
        try:
            path = await save_upload(f, job_id, "company_documents")
            company_paths.append(path)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # --- Save sample reports ---
    sample_paths: list[str] = []
    for f in sample_reports:
        try:
            path = await save_upload(f, job_id, "sample_reports")
            sample_paths.append(path)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # --- Save template ---
    try:
        template_path = await save_upload(template, job_id, "template")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # --- Persist job metadata ---
    bundle = UploadBundle(
        job_id=job_id,
        standard=standard,
        stage=stage,
        company_document_paths=company_paths,
        sample_report_paths=sample_paths,
        template_path=template_path,
    )
    save_text_artifact(job_id, "bundle.json", bundle.model_dump_json(indent=2))

    # --- Initialise job status ---
    status = JobStatus(
        job_id=job_id,
        state=JobState.QUEUED,
        started_at=datetime.utcnow(),
    )
    save_text_artifact(job_id, "status.json", status.model_dump_json(indent=2))

    # --- Queue the pipeline (Celery task — imported lazily to avoid circular) ---
    try:
        from backend.jobs.tasks import run_pipeline
        run_pipeline.delay(job_id)
        logger.info(f"Job {job_id} queued for pipeline execution.")
    except Exception as e:
        logger.warning(f"Could not queue job {job_id} via Celery: {e}. Run manually.")

    return {
        "job_id": job_id,
        "status": JobState.QUEUED,
        "standard": standard,
        "stage": stage,
        "company_documents_received": len(company_paths),
        "sample_reports_received": len(sample_paths),
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
    """Download the final assembled .docx report."""
    if not job_exists(job_id):
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    files = list_files(job_id, "artifacts")
    # Packager saves as 'final_report.docx' (no prefix)
    docx_files = [f for f in files if f.endswith("final_report.docx")]
    if not docx_files:
        raise HTTPException(status_code=404, detail="Report not ready yet.")
    return FileResponse(
        path=docx_files[0],
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"audit_report_{job_id}.docx",
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

