"""Background task for resilient Certiv.AI audit-plan generation."""

from __future__ import annotations

import base64
import datetime
import json
import logging

from audit_plan.service import context_from_dict, generate_audit_plan_document
from jobs.tasks import celery_app
from storage.file_store import save_binary_artifact, save_text_artifact

logger = logging.getLogger(__name__)


def _status(
    job_id: str,
    state: str,
    *,
    error_message: str = "",
    filename: str = "",
) -> None:
    save_text_artifact(
        job_id,
        "audit_plan_status.json",
        json.dumps({
            "audit_plan_job_id": job_id,
            "state": state,
            "error_message": error_message or None,
            "filename": filename or None,
            "updated_at": datetime.datetime.utcnow().isoformat(),
        }),
    )


def _public_error(error: Exception) -> str:
    message = str(error).strip()
    if not message:
        return "Audit-plan generation failed. Please try again."
    if len(message) > 400:
        return message[:397].rstrip() + "..."
    return message


@celery_app.task(name="batuhan.generate_audit_plan", max_retries=0)
def generate_audit_plan_job(
    job_id: str,
    template_b64: str,
    context_payload: dict,
) -> dict:
    """Generate the schedule away from the browser request and persist the DOCX."""
    try:
        _status(job_id, "GENERATING")
        template_bytes = base64.b64decode(template_b64)
        ctx = context_from_dict(context_payload)
        document, filename = generate_audit_plan_document(template_bytes, ctx)

        _status(job_id, "ASSEMBLING", filename=filename)
        save_binary_artifact(job_id, "audit_plan.docx", document)
        _status(job_id, "COMPLETE", filename=filename)
        logger.info("Audit plan job %s completed: %s", job_id, filename)
        return {"audit_plan_job_id": job_id, "state": "COMPLETE", "filename": filename}
    except Exception as exc:
        logger.error("Audit plan job %s failed: %s", job_id, exc, exc_info=True)
        _status(job_id, "FAILED", error_message=_public_error(exc))
        raise
