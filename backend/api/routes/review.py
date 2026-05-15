"""
BATUHAN — Review API Routes
POST /review/submit          → accept a completed audit report DOCX for AI review
GET  /review/{id}/status     → poll review job state
GET  /review/{id}/download/annotated-report  → download DOCX with Word comments
GET  /review/{id}/download/review-summary    → download JSON findings summary
"""

from __future__ import annotations
import base64
import logging
import uuid
import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from schemas.models import ReviewJobStatus, ReviewJobState, AccreditationBody
from config.review_profiles.loader import load_review_profile, list_available_profiles
from storage.file_store import save_text_artifact, read_text_artifact, read_binary_artifact
from auth.db_models import PlatformUser
from auth.dependencies import require_auditor, require_any

router = APIRouter(prefix="/review", tags=["review"])
logger = logging.getLogger(__name__)

_VALID_STANDARDS = ["QMS", "EMS", "OHSMS", "FSMS", "MDQMS", "ISMS", "ABMS", "ENMS"]


@router.post("/submit")
async def submit_review(
    report: UploadFile = File(..., description="The audit report DOCX to review"),
    standard: str = Form(..., description="Standard code: QMS, EMS, OHSMS, FSMS, MDQMS, ISMS, ABMS, ENMS"),
    stage: str = Form(..., description="Stage 1 or Stage 2"),
    accreditation_body: str = Form(..., description="UAF or TURKAK"),
    _: PlatformUser = Depends(require_auditor),
):
    """Submit a completed audit report DOCX for AI-powered review against accreditation rules."""

    # Validate accreditation body
    try:
        load_review_profile(accreditation_body)
    except FileNotFoundError:
        available = list_available_profiles()
        raise HTTPException(
            status_code=400,
            detail=f"Unknown accreditation body '{accreditation_body}'. Available: {available}",
        )

    # Validate standard
    if standard.upper() not in _VALID_STANDARDS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown standard '{standard}'. Valid: {_VALID_STANDARDS}",
        )

    # Validate stage
    if stage not in ["Stage 1", "Stage 2"]:
        raise HTTPException(
            status_code=400,
            detail="stage must be 'Stage 1' or 'Stage 2'",
        )

    # Validate file type
    if not (report.filename or "").lower().endswith(".docx"):
        raise HTTPException(
            status_code=400,
            detail="Only .docx files are accepted for review.",
        )

    # Read and encode file
    report_bytes = await report.read()
    report_b64 = base64.b64encode(report_bytes).decode("ascii")

    # Generate review job ID
    review_job_id = str(uuid.uuid4())

    # Store initial status (text, matching jobs.py pattern)
    initial_status = ReviewJobStatus(
        review_job_id=review_job_id,
        state=ReviewJobState.QUEUED,
        standard_code=standard.upper(),
        accreditation_body=accreditation_body.upper(),
        created_at=datetime.datetime.utcnow().isoformat(),
    )
    save_text_artifact(
        review_job_id, "review_status.json", initial_status.model_dump_json(indent=2)
    )

    # Dispatch Celery task
    try:
        from jobs.review_task import run_review_job
        run_review_job.delay(
            review_job_id=review_job_id,
            report_b64=report_b64,
            report_filename=report.filename or "report.docx",
            standard=standard.upper(),
            stage=stage,
            accreditation_body=accreditation_body.upper(),
        )
        logger.info(
            "Review job %s queued | standard=%s | stage=%s | ab=%s",
            review_job_id, standard.upper(), stage, accreditation_body.upper(),
        )
    except Exception as e:
        logger.warning("Could not queue review job %s via Celery: %s", review_job_id, e)

    return {"review_job_id": review_job_id, "state": "QUEUED"}


@router.get("/{review_job_id}/status")
async def get_review_status(review_job_id: str, _: PlatformUser = Depends(require_any)):
    """Return the current status of a review job."""
    data = read_text_artifact(review_job_id, "review_status.json")
    if not data:
        raise HTTPException(status_code=404, detail="Review job not found")
    return ReviewJobStatus.model_validate_json(data)


@router.get("/{review_job_id}/download/annotated-report")
async def download_annotated_report(review_job_id: str, _: PlatformUser = Depends(require_any)):
    """Download the annotated DOCX with inline Word comments for each finding."""
    try:
        data = read_binary_artifact(review_job_id, "annotated_report.docx")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Annotated report not ready yet.")
    if not data:
        raise HTTPException(status_code=404, detail="Annotated report not found.")
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename=review_{review_job_id}.docx"
        },
    )


@router.get("/{review_job_id}/download/review-summary")
async def download_review_summary(review_job_id: str, _: PlatformUser = Depends(require_any)):
    """Download the review findings summary as JSON."""
    data = read_text_artifact(review_job_id, "review_summary.json")
    if not data:
        raise HTTPException(status_code=404, detail="Review summary not ready yet.")
    return Response(
        content=data,
        media_type="application/json",
        headers={
            "Content-Disposition": f"attachment; filename=review_summary_{review_job_id}.json"
        },
    )
