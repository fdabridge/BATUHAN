"""
BATUHAN — Celery Worker & Pipeline Task (T28)
Defines the Celery application and the run_pipeline task that executes
the full A→B→C→Assembly pipeline for a given job_id.

Start the worker with:
  celery -A backend.jobs.tasks worker --loglevel=info
"""

from __future__ import annotations
import logging
from pathlib import Path

from celery import Celery
from config.settings import get_settings
from schemas.models import JobState, UploadBundle
from jobs.state import update_job_state
from safety.failure_handler import (
    PipelineAbort,
    filter_readable_documents,
    assert_template_valid,
    assert_evidence_valid,
    step_c_fallback,
)
from safety.leakage_detector import scan_report_for_leakage, write_leakage_report
from safety.audit_trail import write_audit_trail

settings = get_settings()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Celery application
# ---------------------------------------------------------------------------

celery_app = Celery(
    "batuhan",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,          # acknowledge only after completion (safe)
    worker_prefetch_multiplier=1,  # one task at a time per worker (resource-heavy AI calls)
)


# ---------------------------------------------------------------------------
# Pipeline task
# ---------------------------------------------------------------------------

@celery_app.task(name="batuhan.run_pipeline", bind=True, max_retries=0)
def run_pipeline(self, job_id: str) -> dict:
    """
    Execute the full BATUHAN pipeline for a job:
      PREPROCESSING → STEP_A → STEP_B → STEP_C → ASSEMBLING → COMPLETE

    On any unrecoverable failure, transitions to FAILED with an error message.
    The task does NOT retry automatically — retries would re-bill the Anthropic API.
    """
    logger.info(f"[Pipeline] Starting job {job_id}")
    try:
        # --- Load job bundle ---
        from storage.file_store import read_text_artifact
        raw_bundle = read_text_artifact(job_id, "bundle.json")
        bundle = UploadBundle.model_validate_json(raw_bundle)

        # -----------------------------------------------------------
        # PREPROCESSING — text extraction, OCR, template, style
        # -----------------------------------------------------------
        update_job_state(job_id, JobState.PREPROCESSING)

        from parsers.text_extractor import parse_documents
        from parsers.ocr_pipeline import run_ocr_pipeline
        from parsers.template_parser import parse_template
        from parsers.style_extractor import build_style_guidance

        raw_corpus = parse_documents(bundle.company_document_paths)
        ocr_docs = run_ocr_pipeline(bundle.company_document_paths)
        all_docs = raw_corpus + ocr_docs

        # T31: skip unreadable files, abort if ALL documents are empty
        corpus = filter_readable_documents(bundle.company_document_paths, all_docs)

        template_map = parse_template(bundle.template_path)
        # T31: abort if template has no sections
        assert_template_valid(template_map)

        style_guidance = build_style_guidance(bundle.sample_report_paths)

        # -----------------------------------------------------------
        # STEP A — Evidence Extraction
        # -----------------------------------------------------------
        update_job_state(job_id, JobState.STEP_A)

        from pipeline.step_a.orchestrator import run_step_a
        evidence = run_step_a(
            job_id=job_id,
            corpus=corpus,
            standard=bundle.standard,
            stage=bundle.stage,
        )
        # T31: abort if Step A produced nothing
        assert_evidence_valid(evidence, job_id)

        # -----------------------------------------------------------
        # STEP B — Report Generation
        # -----------------------------------------------------------
        update_job_state(job_id, JobState.STEP_B)

        from pipeline.step_b.orchestrator import run_step_b
        generated_report = run_step_b(
            job_id=job_id,
            evidence=evidence,
            template_map=template_map,
            style_guidance=style_guidance,
            standard=bundle.standard,
            stage=bundle.stage,
        )

        # -----------------------------------------------------------
        # STEP C — Validation & Correction  (T31: fallback on failure)
        # -----------------------------------------------------------
        update_job_state(job_id, JobState.STEP_C)

        from pipeline.step_c.orchestrator import run_step_c
        try:
            validated_report, correction_log = run_step_c(
                job_id=job_id,
                generated_report=generated_report,
                evidence=evidence,
                template_map=template_map,
                style_guidance=style_guidance,
            )
        except Exception as step_c_exc:
            # T31: revert to Step B output rather than fail entirely
            validated_report, correction_log = step_c_fallback(
                job_id, generated_report, step_c_exc
            )

        # -----------------------------------------------------------
        # T32: Leakage scan — block delivery on critical violations
        # -----------------------------------------------------------
        leakage = scan_report_for_leakage(validated_report, style_guidance)
        write_leakage_report(job_id, leakage)
        if leakage.has_critical:
            raise PipelineAbort(
                f"Leakage scan blocked delivery: "
                f"{sum(1 for v in leakage.violations if v.severity == 'CRITICAL')} critical violation(s). "
                "See leakage_scan.json for details."
            )

        # -----------------------------------------------------------
        # ASSEMBLING — DOCX + correction log + summary
        # -----------------------------------------------------------
        update_job_state(job_id, JobState.ASSEMBLING)

        from assembly.result_packager import package_results
        files_used = [Path(p).name for p in bundle.company_document_paths]
        package_results(
            job_id=job_id,
            validated_report=validated_report,
            correction_log=correction_log,
            template_path=bundle.template_path,
            standard=bundle.standard,
            stage=bundle.stage,
            files_used=files_used,
        )

        # -----------------------------------------------------------
        # T30: Write audit trail, then mark COMPLETE
        # -----------------------------------------------------------
        write_audit_trail(job_id)
        update_job_state(job_id, JobState.COMPLETE)
        logger.info(f"[Pipeline] Job {job_id} completed successfully.")
        return {"job_id": job_id, "status": "COMPLETE"}

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        logger.error(f"[Pipeline] Job {job_id} FAILED: {error_msg}", exc_info=True)
        update_job_state(job_id, JobState.FAILED, error_message=error_msg)
        raise  # Re-raise so Celery records task as failed

