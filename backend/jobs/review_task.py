"""
BATUHAN — Review Celery Task
Runs the full report-review pipeline:
  PREPROCESSING → REVIEWING → ANNOTATING → COMPLETE

Reuses the existing celery_app from jobs.tasks — no new Celery instance.
"""

from __future__ import annotations
import base64
import datetime
import logging
import os
import shutil
import tempfile

from jobs.tasks import celery_app
from config.settings import get_settings
from schemas.models import ReviewJobState, ReviewJobStatus
from storage.file_store import save_text_artifact, save_binary_artifact

settings = get_settings()
logger = logging.getLogger(__name__)


@celery_app.task(name="batuhan.run_review_job", max_retries=0)
def run_review_job(
    review_job_id: str,
    report_b64: str,
    report_filename: str,
    standard: str,
    stage: str,
    accreditation_body: str,
):
    """
    Execute the full BATUHAN review pipeline for an uploaded audit report PDF or DOCX.
    Stores artifacts in Redis; API container retrieves them for downloads.
    """

    def update_review_state(state: ReviewJobState, error: str = "") -> None:
        status = ReviewJobStatus(
            review_job_id=review_job_id,
            state=state,
            standard_code=standard,
            accreditation_body=accreditation_body,
            error_message=error,
            created_at=datetime.datetime.utcnow().isoformat(),
            completed_at=(
                datetime.datetime.utcnow().isoformat()
                if state in (ReviewJobState.COMPLETE, ReviewJobState.FAILED)
                else ""
            ),
        )
        save_text_artifact(
            review_job_id, "review_status.json", status.model_dump_json(indent=2)
        )

    tmp_dir = tempfile.mkdtemp()
    try:
        # Decode report file to temp disk
        report_bytes = base64.b64decode(report_b64)
        report_path = os.path.join(tmp_dir, report_filename)
        with open(report_path, "wb") as f:
            f.write(report_bytes)

        # ------------------------------------------------------------------
        # PREPROCESSING — extract plain text from the uploaded report
        # ------------------------------------------------------------------
        update_review_state(ReviewJobState.PREPROCESSING)
        report_text = _extract_report_text(report_path)
        save_text_artifact(review_job_id, "review_report_text.txt", report_text)
        logger.info(
            "Review [%s]: extracted %d chars from report", review_job_id, len(report_text)
        )

        # ------------------------------------------------------------------
        # REVIEWING — Claude reviews report against accreditation rule profile
        # ------------------------------------------------------------------
        update_review_state(ReviewJobState.REVIEWING)
        from pipeline.review.orchestrator import run_review
        from anthropic import Anthropic

        client = Anthropic(api_key=settings.anthropic_api_key)
        review_result = run_review(
            report_text=report_text,
            standard=standard,
            stage=stage,
            accreditation_body=accreditation_body,
            review_job_id=review_job_id,
            client=client,
            model=settings.claude_model,
            max_tokens=settings.claude_max_tokens,
            temperature=settings.claude_temperature,
        )
        save_text_artifact(
            review_job_id,
            "review_summary.json",
            review_result.model_dump_json(indent=2),
        )
        logger.info(
            "Review [%s]: %d findings (%d critical, %d major)",
            review_job_id,
            review_result.total_findings,
            review_result.critical_count,
            review_result.major_count,
        )

        # ------------------------------------------------------------------
        # ANNOTATING — build annotated DOCX with inline Word comments
        # PDF reviews produce the structured findings summary only.
        # ------------------------------------------------------------------
        if report_filename.lower().endswith(".docx"):
            update_review_state(ReviewJobState.ANNOTATING)
            from pipeline.review.annotator import build_annotated_docx

            annotated_bytes = build_annotated_docx(
                report_path=report_path,
                review_result=review_result,
            )
            save_binary_artifact(review_job_id, "annotated_report.docx", annotated_bytes)
            logger.info("Review [%s]: annotated DOCX built", review_job_id)
        else:
            logger.info(
                "Review [%s]: PDF upload reviewed; annotated DOCX output skipped",
                review_job_id,
            )

        update_review_state(ReviewJobState.COMPLETE)

    except Exception as e:
        logger.error("Review job %s failed: %s", review_job_id, e, exc_info=True)
        update_review_state(ReviewJobState.FAILED, _public_error_message(e))
        raise
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _extract_report_text(report_path: str) -> str:
    """Extract plain text from the uploaded audit report."""
    try:
        from parsers.text_extractor import extract_text

        return extract_text(report_path)
    except Exception as e:
        logger.warning("Text extraction failed for review: %s. Returning empty.", e)
        return ""


def _public_error_message(error: Exception) -> str:
    """Return a safe, user-facing review failure reason."""
    message = str(error).strip()
    if not message:
        return "Report review failed. Please retry with a readable PDF or DOCX report."
    if "json" in message.lower() or "parse" in message.lower() or "expecting" in message.lower():
        return (
            "Report review failed because the AI response could not be converted into the required review format. "
            "Please retry the review."
        )
    if len(message) > 240:
        return message[:237].rstrip() + "..."
    return message
