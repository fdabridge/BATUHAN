"""
BATUHAN — Result Delivery & Packaging (T24)
Assembles all final deliverables after Step C completes, persists them,
and returns a JobResult summarising the completed job.

Deliverables:
  1. final_report.docx  — Corrected report assembled into the original template
  2. correction_log.txt — Human-readable list of all corrections made
  3. job_summary.json   — Metadata: standard, stage, files used, correction count

The JobResult object is the canonical response sent back to the UI/API.
"""

from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from schemas.models import (
    ValidatedReport, CorrectionLog, JobResult,
    ISOStandard, AuditStage,
)
from assembly.docx_builder import assemble_docx
from storage.file_store import save_text_artifact, save_binary_artifact, _subdir

logger = logging.getLogger(__name__)


def _format_correction_log_txt(correction_log: CorrectionLog) -> str:
    """Render the correction log as a human-readable plain-text document."""
    lines = [
        "BATUHAN — Audit Report Correction Log",
        "=" * 40,
        f"Job ID:           {correction_log.job_id}",
        f"Validated at:     {correction_log.validated_at.strftime('%Y-%m-%d %H:%M UTC')}",
        f"Total corrections: {correction_log.correction_count}",
        "",
        "CORRECTIONS MADE",
        "-" * 40,
    ]
    if not correction_log.corrections:
        lines.append("No corrections were required.")
    else:
        for i, entry in enumerate(correction_log.corrections, 1):
            section_label = f"[{entry.section_title}] " if entry.section_title else ""
            lines.append(f"{i}. {section_label}{entry.description}")
    lines.append("")
    return "\n".join(lines)


def _build_summary(
    job_id: str,
    standard: ISOStandard,
    stage: AuditStage,
    files_used: list[str],
    correction_count: int,
    final_docx_path: str,
    correction_log_path: str,
) -> dict:
    return {
        "job_id": job_id,
        "standard": standard.value,
        "stage": stage.value,
        "files_used": files_used,
        "correction_count": correction_count,
        "final_report": final_docx_path,
        "correction_log": correction_log_path,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }


def package_results(
    job_id: str,
    validated_report: ValidatedReport,
    correction_log: CorrectionLog,
    template_path: str,
    standard: ISOStandard,
    stage: AuditStage,
    files_used: list[str],
) -> JobResult:
    """
    Assemble all deliverables and return a JobResult.

    Args:
        job_id:            Current job ID.
        validated_report:  Step C output (corrected sections).
        correction_log:    Step C correction log.
        template_path:     Path to the blank .docx template.
        standard:          ISO standard for this job.
        stage:             Audit stage for this job.
        files_used:        List of source filenames used in the job.

    Returns:
        JobResult with paths to final_docx and correction_log.

    Raises:
        ValueError: If DOCX assembly fails.
    """
    logger.info(f"[Packager] Assembling deliverables | job={job_id}")

    # --- 1. Assemble final DOCX ---
    artifacts_dir = str(_subdir(job_id, "artifacts"))
    docx_output_path = str(Path(artifacts_dir) / "final_report.docx")

    final_docx_path = assemble_docx(
        template_path=template_path,
        validated_report=validated_report,
        output_path=docx_output_path,
    )

    # --- 2. Write human-readable correction log ---
    correction_log_txt = _format_correction_log_txt(correction_log)
    correction_log_path = save_text_artifact(job_id, "correction_log.txt", correction_log_txt)

    # --- 3. Write job summary JSON ---
    summary = _build_summary(
        job_id=job_id,
        standard=standard,
        stage=stage,
        files_used=files_used,
        correction_count=correction_log.correction_count,
        final_docx_path=final_docx_path,
        correction_log_path=correction_log_path,
    )
    save_text_artifact(job_id, "job_summary.json", json.dumps(summary, indent=2))

    logger.info(
        f"[Packager] Complete | job={job_id} | "
        f"{correction_log.correction_count} correction(s) | "
        f"DOCX: {Path(final_docx_path).name}"
    )

    return JobResult(
        job_id=job_id,
        final_docx_path=final_docx_path,
        correction_log_path=correction_log_path,
        standard=standard,
        stage=stage,
        files_used=files_used,
        correction_count=correction_log.correction_count,
    )

