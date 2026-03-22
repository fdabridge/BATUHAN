"""
BATUHAN — Safe Failure Handler (T31)
Defines custom exceptions and guard functions for every failure mode
that can occur in the pipeline. Policy:

  - Unreadable file         → skip with warning, continue with remaining docs
  - Empty corpus            → PipelineAbort (no usable text = no report)
  - Template parse failure  → PipelineAbort (can't assemble without structure)
  - Empty Step A output     → PipelineAbort (no evidence = no report)
  - Step C failure          → fallback to Step B output with warning artifact

Raising PipelineAbort anywhere in the pipeline transitions the job to FAILED
and writes a human-readable error artifact before exiting.
"""

from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from backend.schemas.models import (
    GeneratedReport, ValidatedReport, CorrectionLog,
    ExtractedEvidence, TemplateMap, ParsedDocument,
)
from backend.storage.file_store import save_text_artifact

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------

class PipelineAbort(RuntimeError):
    """
    Raised when the pipeline must stop immediately.
    The job will transition to FAILED. The message is stored as the error.
    """


class StepCFallbackWarning(UserWarning):
    """Raised (as a log warning, not re-raised) when Step C fails and we revert."""


# ---------------------------------------------------------------------------
# Guard: Unreadable / empty files
# ---------------------------------------------------------------------------

def filter_readable_documents(
    paths: list[str],
    parsed: list[ParsedDocument],
) -> list[ParsedDocument]:
    """
    Filter out documents with empty text. Logs a warning for each skipped file.
    If ALL documents are unreadable, raises PipelineAbort.
    """
    readable = [d for d in parsed if d.text.strip()]
    skipped = len(parsed) - len(readable)
    if skipped:
        logger.warning(
            f"[SafetyHandler] {skipped} document(s) yielded no text and will be skipped."
        )
    if not readable:
        raise PipelineAbort(
            "All uploaded company documents are unreadable or empty. "
            "Cannot proceed without usable document text."
        )
    return readable


# ---------------------------------------------------------------------------
# Guard: Template validity
# ---------------------------------------------------------------------------

def assert_template_valid(template_map: TemplateMap) -> None:
    """
    Abort if the template has no sections. A structureless template means
    the DOCX assembly will produce an empty report.
    """
    if not template_map.sections:
        raise PipelineAbort(
            "The uploaded template contains no detectable sections. "
            "Ensure the Word document uses Heading styles to define sections."
        )


# ---------------------------------------------------------------------------
# Guard: Step A output validity
# ---------------------------------------------------------------------------

_EVIDENCE_FIELDS = (
    "company_overview",
    "scope_of_activities",
    "documented_information",
    "key_processes_and_functions",
    "evidence_of_system_implementation",
    "audit_relevant_records",
    "identified_gaps",
)


def assert_evidence_valid(evidence: ExtractedEvidence, job_id: str) -> None:
    """
    Abort if Step A produced no usable evidence in any section.
    Writes a warning artifact before raising.
    """
    total_items = sum(len(getattr(evidence, f, [])) for f in _EVIDENCE_FIELDS)
    if total_items == 0:
        save_text_artifact(
            job_id, "step_a_abort_warning.txt",
            f"[{datetime.now(timezone.utc).isoformat()}] "
            "Step A returned zero evidence sections. "
            "Pipeline aborted — cannot generate a report without evidence."
        )
        raise PipelineAbort(
            "Step A (Evidence Extraction) returned no sections. "
            "Check that the company documents contain readable audit-relevant content."
        )


# ---------------------------------------------------------------------------
# Fallback: Step C failure → revert to Step B output
# ---------------------------------------------------------------------------

def step_c_fallback(
    job_id: str,
    generated_report: GeneratedReport,
    error: Exception,
) -> tuple[ValidatedReport, CorrectionLog]:
    """
    When Step C fails, convert the Step B report into a ValidatedReport
    and write a warning artifact. The report is still delivered but marked
    as uncorrected.

    Returns:
        (ValidatedReport, CorrectionLog) both flagged as fallback.
    """
    logger.warning(
        f"[SafetyHandler] Step C failed for job {job_id}: {error}. "
        "Reverting to Step B output with warning."
    )

    warning_text = (
        f"[{datetime.now(timezone.utc).isoformat()}]\n"
        "WARNING: Step C (Validation & Correction) failed.\n"
        f"Error: {type(error).__name__}: {error}\n\n"
        "The report was assembled from Step B output without correction.\n"
        "Manual review is REQUIRED before this report is used."
    )
    save_text_artifact(job_id, "step_c_fallback_warning.txt", warning_text)
    logger.warning(f"[SafetyHandler] step_c_fallback_warning.txt written for {job_id}.")

    fallback_log = CorrectionLog(
        job_id=job_id,
        corrections=[],
        correction_count=0,
    )
    fallback_report = ValidatedReport(
        job_id=job_id,
        sections=generated_report.sections,
        correction_log=fallback_log,
        raw_output="[FALLBACK — Step C failed, using Step B output]",
    )
    return fallback_report, fallback_log

