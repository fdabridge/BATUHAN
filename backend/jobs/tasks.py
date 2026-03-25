"""
BATUHAN — Celery Worker & Pipeline Task (T28)
Defines the Celery application and the run_pipeline task that executes
the full A→B→C→Assembly pipeline for a given job_id.

File data is passed directly as base64-encoded task arguments — no shared
filesystem is required between the API container and the Worker container.

Start the worker with:
  celery -A jobs.tasks worker --loglevel=info --concurrency=2
"""

from __future__ import annotations
import base64
import logging
import shutil
import tempfile
from pathlib import Path

from celery import Celery
from config.settings import get_settings
from schemas.models import ISOStandard, AuditStage, JobState
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
    task_acks_late=True,           # acknowledge only after completion (safe)
    worker_prefetch_multiplier=1,  # one task at a time per worker
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _write_files(file_list: list[dict], dest_dir: Path) -> list[str]:
    """
    Decode base64 file data and write each file to dest_dir.
    Returns a list of absolute path strings.
    Each item in file_list must have {"filename": str, "content_b64": str}.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    for item in file_list:
        filename = item["filename"]
        content = base64.b64decode(item["content_b64"])
        dest = dest_dir / filename
        # Handle duplicate filenames
        counter = 1
        while dest.exists():
            stem = Path(filename).stem
            suffix = Path(filename).suffix
            dest = dest_dir / f"{stem}_{counter}{suffix}"
            counter += 1
        dest.write_bytes(content)
        paths.append(str(dest))
        logger.debug(f"[Pipeline] Wrote temp file: {dest} ({len(content)} bytes)")
    return paths


# ---------------------------------------------------------------------------
# Pipeline task
# ---------------------------------------------------------------------------

@celery_app.task(name="batuhan.run_pipeline", bind=True, max_retries=0)
def run_pipeline(
    self,
    job_id: str,
    company_files: list[dict],
    sample_files: list[dict],
    template_file: dict,
    standard_value: str,
    stage_value: str,
    org_name: str | None = None,
    org_address: str | None = None,
    org_phone: str | None = None,
) -> dict:
    """
    Execute the full BATUHAN pipeline for a job:
      PREPROCESSING → STEP_A → STEP_B → STEP_C → ASSEMBLING → COMPLETE

    File contents are received as base64-encoded dicts and written to a
    temporary directory for processing. All output artifacts are stored in
    Redis so the API container can retrieve them for downloads.

    The task does NOT retry automatically — retries would re-bill the API.
    """
    logger.info(f"[Pipeline] Starting job {job_id}")
    # Create a dedicated temp directory for this job's files
    tmp_root = Path(tempfile.gettempdir()) / "batuhan_jobs" / job_id

    try:
        standard = ISOStandard(standard_value)
        stage = AuditStage(stage_value)

        # -----------------------------------------------------------
        # Write uploaded file data to the worker's local temp dir
        # -----------------------------------------------------------
        company_paths = _write_files(company_files, tmp_root / "company_documents")
        sample_paths = _write_files(sample_files, tmp_root / "sample_reports")
        template_paths = _write_files([template_file], tmp_root / "template")
        template_path = template_paths[0]

        # -----------------------------------------------------------
        # PREPROCESSING — text extraction, OCR, template, style
        # -----------------------------------------------------------
        update_job_state(job_id, JobState.PREPROCESSING)

        from parsers.corpus_builder import build_corpus
        from parsers.template_parser import parse_template
        from parsers.style_extractor import build_style_guidance

        # build_corpus handles text extraction + OCR + deduplication in one pass
        all_docs = build_corpus(company_paths)

        # T31: skip unreadable files, abort if ALL documents are empty
        corpus = filter_readable_documents(company_paths, all_docs)

        template_map = parse_template(template_path)
        # T31: abort if template has no sections
        assert_template_valid(template_map)

        style_guidance = build_style_guidance(sample_paths)

        # -----------------------------------------------------------
        # STEP A — Evidence Extraction
        # -----------------------------------------------------------
        update_job_state(job_id, JobState.STEP_A)

        from pipeline.step_a.orchestrator import run_step_a
        evidence = run_step_a(
            job_id=job_id,
            corpus=corpus,
            standard=standard,
            stage=stage,
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
            standard=standard,
            stage=stage,
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
        # ASSEMBLING — DOCX + correction log + summary (all in Redis)
        # -----------------------------------------------------------
        update_job_state(job_id, JobState.ASSEMBLING)

        from assembly.result_packager import package_results
        files_used = [item["filename"] for item in company_files]
        org_info = {
            "name":    org_name    or "",
            "address": org_address or "",
            "phone":   org_phone   or "",
        }
        package_results(
            job_id=job_id,
            validated_report=validated_report,
            correction_log=correction_log,
            template_path=template_path,
            standard=standard,
            stage=stage,
            files_used=files_used,
            org_info=org_info,
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

    finally:
        # Always clean up temp files — whether the job succeeded or failed
        if tmp_root.exists():
            shutil.rmtree(tmp_root, ignore_errors=True)
            logger.debug(f"[Pipeline] Cleaned up temp dir: {tmp_root}")

