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
from celery.schedules import crontab
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
# Celery Beat — scheduled tasks
# ---------------------------------------------------------------------------

celery_app.conf.beat_schedule = {
    # Meetings: check every 5 min for meetings starting in ~30 min (TRT-based)
    "meetings-30min-checker": {
        "task": "meetings.tasks.check_upcoming_meetings",
        "schedule": crontab(minute="*/5"),
    },
    # Meetings: nightly digest at 23:00 TRT = 20:00 UTC
    "meetings-nightly": {
        "task": "meetings.tasks.send_nightly_digest",
        "schedule": crontab(hour=20, minute=0),
    },
    # Meetings: weekly summary every Sunday 23:00 TRT = 20:00 UTC
    "meetings-weekly": {
        "task": "meetings.tasks.send_weekly_summary",
        "schedule": crontab(hour=20, minute=0, day_of_week=0),
    },
}

# Register meetings tasks so the worker can discover them
import meetings.tasks  # noqa: E402, F401


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
    standard_values: list[str],   # One or more standard codes, e.g. ["QMS", "EMS"]
    stage_value: str,
    org_name: str | None = None,
    org_address: str | None = None,
    org_phone: str | None = None,
    language_value: str = "EN",   # "EN" or "TR"
    accreditation_body: str = "UAF",  # "UAF" or "TURKAK"
) -> dict:
    """
    Execute the full BATUHAN pipeline for a job:
      PREPROCESSING → STEP_A → STEP_B → STEP_C → ASSEMBLING → COMPLETE

    File contents are received as base64-encoded dicts and written to a
    temporary directory for processing. All output artifacts are stored in
    Redis so the API container can retrieve them for downloads.

    The task does NOT retry automatically — retries would re-bill the API.
    Integrated audits pass multiple standard codes in standard_values.
    """
    accreditation_body = (accreditation_body or "UAF").upper()
    logger.info(f"[Pipeline] Starting job {job_id} | accreditation_body={accreditation_body}")
    # Create a dedicated temp directory for this job's files
    tmp_root = Path(tempfile.gettempdir()) / "batuhan_jobs" / job_id

    try:
        from schemas.models import ReportLanguage
        standards = [ISOStandard(v) for v in standard_values]
        stage = AuditStage(stage_value)
        language = ReportLanguage(language_value) if language_value else ReportLanguage.EN

        # -----------------------------------------------------------
        # Build accreditation instruction for Step B / Step C
        # -----------------------------------------------------------
        try:
            from config.review_profiles.loader import load_review_profile
            profile = load_review_profile(accreditation_body)
            rules = profile.get("rules", {})
            min_words = rules.get("minimum_finding_length_words", 20)
            depth = rules.get("finding_depth", "standard")
            must_state_nc = rules.get("nc_must_state_why_it_is_major_or_minor", False)
            forbidden = rules.get("forbidden_phrases", [])

            lines = [
                f"ACCREDITATION BODY: {accreditation_body}",
                f"Finding depth required: {depth}",
                f"Each finding must be at least {min_words} words.",
            ]
            if must_state_nc:
                lines.append(
                    "For every NC (nonconformity) explicitly state whether it is Major "
                    "or Minor AND explain why (cite the clause and the specific gap)."
                )
            if forbidden:
                lines.append("Forbidden phrases (must not appear in findings): "
                             + ", ".join(f'"{p}"' for p in forbidden[:10]))
            accreditation_instruction = "\n".join(lines)
        except Exception as _ai_exc:
            logger.warning(
                "[Pipeline] Could not load accreditation profile '%s': %s — using empty instruction.",
                accreditation_body, _ai_exc,
            )
            accreditation_instruction = f"ACCREDITATION BODY: {accreditation_body}"

        # -----------------------------------------------------------
        # STEP 0 — Load clause applicability configs
        # -----------------------------------------------------------
        from config.clause_configs.loader import load_clause_config, get_mandatory_clause_ids

        clause_configs = {}
        mandatory_clause_ids = {}
        for std in standards:
            try:
                cfg = load_clause_config(std.value)
                clause_configs[std.value] = cfg
                mandatory_clause_ids[std.value] = get_mandatory_clause_ids(cfg)
            except Exception as e:
                logger.warning(f"Could not load clause config for {std.value}: {e}")

        logger.info(
            "[Pipeline] Clause configs loaded: %d/%d standards. job=%s",
            len(clause_configs), len(standards), job_id,
        )

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

        # Filter out any "blocked" company names that already appear in the
        # blank template (e.g. the certifier's own letterhead — IFC GLOBAL LLC).
        # Those names belong in every report and must never be treated as leakage.
        if style_guidance.blocked_company_names:
            from parsers.text_extractor import extract_text
            try:
                template_text_lower = extract_text(template_path).lower()
                before = len(style_guidance.blocked_company_names)
                style_guidance.blocked_company_names = [
                    name for name in style_guidance.blocked_company_names
                    if name.lower() not in template_text_lower
                ]
                removed = before - len(style_guidance.blocked_company_names)
                if removed:
                    logger.info(
                        "[Pipeline] Removed %d certifier name(s) from blocked list "
                        "(found in template — these are the certifier's own names): job=%s",
                        removed, job_id,
                    )
            except Exception as exc:
                logger.warning("[Pipeline] Could not filter certifier names from blocked list: %s", exc)

        # -----------------------------------------------------------
        # STEP 0 — Scope Analysis (clause applicability)
        # -----------------------------------------------------------
        update_job_state(job_id, JobState.STEP_0)

        from parsers.corpus_builder import format_corpus_for_prompt
        from storage.file_store import save_text_artifact
        from pipeline.step_0.orchestrator import run_step_0
        import anthropic as _anthropic

        full_corpus_text = format_corpus_for_prompt(corpus)
        anthropic_client = _anthropic.Anthropic(api_key=settings.anthropic_api_key)

        scope_analysis = run_step_0(
            document_corpus=full_corpus_text,
            clause_configs=clause_configs,
            client=anthropic_client,
            model=settings.claude_model,
            max_tokens=1024,
            temperature=settings.claude_temperature,
        )

        scope_analysis_json = scope_analysis.model_dump_json(indent=2)
        save_text_artifact(job_id, "step_0_scope_analysis.json", scope_analysis_json)
        logger.info(
            f"[Pipeline] Step 0 complete. Standards analyzed: "
            f"{list(scope_analysis.standards.keys())} | job={job_id}"
        )

        # -----------------------------------------------------------
        # STEP A — Evidence Extraction
        # -----------------------------------------------------------
        update_job_state(job_id, JobState.STEP_A)

        from pipeline.step_a.orchestrator import run_step_a
        evidence = run_step_a(
            job_id=job_id,
            corpus=corpus,
            standards=standards,
            stage=stage,
            scope_analysis=scope_analysis,
            selected_standards=[s.value for s in standards],
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
            standards=standards,
            stage=stage,
            language=language,
            scope_analysis=scope_analysis,
            accreditation_instruction=accreditation_instruction,
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
                language=language,
                scope_analysis=scope_analysis,
                accreditation_instruction=accreditation_instruction,
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
        _org_info = {
            "name": org_name or "",
            "address": org_address or "",
            "phone": org_phone or "",
        }
        package_results(
            job_id=job_id,
            validated_report=validated_report,
            correction_log=correction_log,
            template_path=template_path,
            standards=standards,
            stage=stage,
            files_used=files_used,
            org_info=_org_info,
            language=language,
        )

        # -----------------------------------------------------------
        # Coverage validation — check all mandatory clauses are filled
        # -----------------------------------------------------------
        from assembly.coverage_validator import (
            validate_and_repair_coverage,
            generate_coverage_report_text,
        )
        from storage.file_store import read_text_artifact

        template_structure_text = ""
        try:
            structure_artifact = read_text_artifact(job_id, "assembly_template_structure_chunk1.txt")
            if structure_artifact:
                template_structure_text = structure_artifact
        except Exception:
            pass

        report_content_text = ""
        try:
            report_content_text = read_text_artifact(job_id, "step_c_formatted.txt") or ""
        except Exception:
            pass
        if not report_content_text:
            try:
                report_content_text = read_text_artifact(job_id, "step_b_formatted.txt") or ""
            except Exception:
                pass

        _cell_mapping, coverage_report_lines = validate_and_repair_coverage(
            cell_mapping={},
            template_structure_text=template_structure_text,
            scope_analysis=scope_analysis,
            report_content=report_content_text,
            client=anthropic_client,
            model=settings.claude_model,
            max_tokens=settings.claude_max_tokens,
            temperature=settings.claude_temperature,
            selected_standards=[s.value for s in standards],
        )

        coverage_report_text = generate_coverage_report_text(coverage_report_lines)
        save_text_artifact(job_id, "coverage_validation_report.txt", coverage_report_text)
        logger.info("[Pipeline] Coverage validation complete. | job=%s", job_id)

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

