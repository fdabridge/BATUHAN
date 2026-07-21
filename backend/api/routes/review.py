"""
BATUHAN — Review API Routes
POST /review/submit          → accept a completed audit report PDF or DOCX for AI review
GET  /review/{id}/status     → poll review job state
GET  /review/{id}/download/annotated-report  → download DOCX with Word comments
GET  /review/{id}/download/review-summary    → download JSON findings summary
"""

from __future__ import annotations
import base64
import logging
import uuid
import datetime
from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from schemas.models import ReviewJobStatus, ReviewJobState
from config.review_profiles.loader import load_review_profile, list_available_profiles
from storage.file_store import save_text_artifact, read_text_artifact, read_binary_artifact
from auth.db_models import PlatformUser
from auth.dependencies import require_any

router = APIRouter(prefix="/review", tags=["review"])
logger = logging.getLogger(__name__)

_VALID_STANDARDS = ["QMS", "EMS", "OHSMS", "FSMS", "MDQMS", "ISMS", "ABMS", "ENMS"]
_VALID_STAGES = ["Stage 1", "Stage 2", "Surveillance", "Recertification"]


def _normalize_standard_inputs(
    standards: List[str] | None,
    legacy_standard: str | None,
) -> list[str]:
    raw_values = list(standards or [])
    if legacy_standard:
        raw_values.append(legacy_standard)

    selected: list[str] = []
    for raw in raw_values:
        for part in raw.replace("+", ",").split(","):
            code = part.strip().upper()
            if code and code not in selected:
                selected.append(code)
    return selected


def _reference_summary(profile: dict) -> dict:
    return {
        "code": profile.get("accreditation_body", "").upper(),
        "display_name": profile.get("display_name", ""),
        "governing_standard": profile.get("governing_standard", ""),
        "reference_basis": profile.get("reference_basis", []),
        "required_report_elements": profile.get("required_report_elements", []),
    }


@router.get("/references")
async def list_review_references(_: PlatformUser = Depends(require_any)):
    """Return the supported report-review reference profiles and inputs."""
    profiles = []
    for code in sorted(list_available_profiles()):
        try:
            profiles.append(_reference_summary(load_review_profile(code)))
        except Exception as exc:
            logger.warning("Could not load review profile %s: %s", code, exc)
    return {
        "profiles": profiles,
        "standards": _VALID_STANDARDS,
        "stages": _VALID_STAGES,
        "file_types": [".pdf", ".docx"],
    }


@router.post("/submit")
async def submit_review(
    report: UploadFile = File(..., description="The audit report PDF or DOCX to review"),
    standards: List[str] | None = Form(default=None, description="One or more standard codes: QMS, EMS, OHSMS, FSMS, MDQMS, ISMS, ABMS, ENMS"),
    standard: str | None = Form(default=None, description="Legacy single standard code"),
    stage: str = Form(..., description="Stage 1, Stage 2, Surveillance, or Recertification"),
    accreditation_body: str = Form(..., description="UAF, IAF, or TURKAK"),
    _: PlatformUser = Depends(require_any),
):
    """Submit a completed audit report PDF or DOCX for AI-powered review against accreditation rules."""

    # Validate accreditation body
    try:
        load_review_profile(accreditation_body)
    except FileNotFoundError:
        available = list_available_profiles()
        raise HTTPException(
            status_code=400,
            detail=f"Unknown accreditation body '{accreditation_body}'. Available: {available}",
        )

    selected_standards = _normalize_standard_inputs(standards, standard)
    if not selected_standards:
        raise HTTPException(
            status_code=400,
            detail="At least one standard must be selected.",
        )

    invalid_standards = [
        selected for selected in selected_standards if selected not in _VALID_STANDARDS
    ]
    if invalid_standards:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown standard(s) {invalid_standards}. Valid: {_VALID_STANDARDS}",
        )
    standards_label = " + ".join(selected_standards)

    # Validate stage
    if stage not in _VALID_STAGES:
        raise HTTPException(
            status_code=400,
            detail=f"stage must be one of {_VALID_STAGES}",
        )

    # Validate file type
    filename_lower = (report.filename or "").lower()
    if not filename_lower.endswith((".pdf", ".docx")):
        raise HTTPException(
            status_code=400,
            detail="Only .pdf and .docx files are accepted for review.",
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
        standard_code=standards_label,
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
            standard=standards_label,
            stage=stage,
            accreditation_body=accreditation_body.upper(),
        )
        logger.info(
            "Review job %s queued | standard=%s | stage=%s | ab=%s",
            review_job_id, standards_label, stage, accreditation_body.upper(),
        )
    except Exception as e:
        logger.warning("Could not queue review job %s via Celery: %s", review_job_id, e)
        failed_status = ReviewJobStatus(
            review_job_id=review_job_id,
            state=ReviewJobState.FAILED,
            standard_code=standards_label,
            accreditation_body=accreditation_body.upper(),
            error_message="Could not queue the report review job.",
            created_at=initial_status.created_at,
            completed_at=datetime.datetime.utcnow().isoformat(),
        )
        save_text_artifact(
            review_job_id, "review_status.json", failed_status.model_dump_json(indent=2)
        )
        raise HTTPException(status_code=503, detail="Could not queue the report review job.")

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
