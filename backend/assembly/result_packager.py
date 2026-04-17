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
from storage.file_store import save_text_artifact, save_binary_artifact

logger = logging.getLogger(__name__)


def _has_tables(template_path: str) -> bool:
    """Return True if the template contains at least one table (table-based layout)."""
    from docx import Document
    _WNS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    doc = Document(template_path)
    return bool(doc.element.body.findall(f"{{{_WNS}}}tbl"))


def _assemble_with_llm_mapper(
    template_path: str,
    validated_report,
    output_path: str,
    standards,
    org_info: dict | None = None,
    job_id: str | None = None,
    language=None,
) -> None:
    """
    Assemble a DOCX report using the coordinate-based LLM mapper.
    Replaces the heuristic heading-detection for complex table-based templates.
    """
    from docx import Document
    from assembly.llm_mapper import (
        get_cell_mapping,
        apply_cell_mapping,
        strip_template_instruction_cells,
    )
    from schemas.models import ISOStandard

    # For integrated audits, use the first standard; the prompt covers all.
    primary_standard: ISOStandard = standards[0] if standards else ISOStandard.QMS

    logger.info(
        "[Packager] Using LLM-mapper assembly | job=%s | standard=%s",
        job_id, primary_standard.value,
    )

    mapping = get_cell_mapping(
        template_path=template_path,
        validated_report=validated_report,
        selected_standard=primary_standard,
        job_id=job_id,
        org_info=org_info,
        language=language,
    )

    doc = Document(template_path)
    body = doc.element.body

    filled = apply_cell_mapping(body, mapping)
    cleared = strip_template_instruction_cells(body)

    logger.info(
        "[Packager] LLM-mapper assembly done | %d cells filled | %d instruction cells cleared | job=%s",
        filled, cleared, job_id,
    )

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out))


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
    standards: list[ISOStandard],
    stage: AuditStage,
    files_used: list[str],
    correction_count: int,
    final_docx_path: str,
    correction_log_path: str,
) -> dict:
    return {
        "job_id": job_id,
        "standards": [s.value for s in standards],          # list for display
        "standard": " + ".join(s.value for s in standards), # backward-compat label
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
    standards: list[ISOStandard],
    stage: AuditStage,
    files_used: list[str],
    org_info: dict | None = None,
    language=None,
) -> JobResult:
    """
    Assemble all deliverables and return a JobResult.

    Args:
        job_id:            Current job ID.
        validated_report:  Step C output (corrected sections).
        correction_log:    Step C correction log.
        template_path:     Path to the blank .docx template.
        standards:         ISO standard(s) for this job.
        stage:             Audit stage for this job.
        files_used:        List of source filenames used in the job.
        org_info:          Organisation metadata (name, address, phone, scope).

    Returns:
        JobResult with paths to final_docx and correction_log.

    Raises:
        ValueError: If DOCX assembly fails.
    """
    logger.info(f"[Packager] Assembling deliverables | job={job_id}")

    # --- 1. Assemble final DOCX into a temp file, then push bytes to Redis ---
    import tempfile, os
    tmp_fd, tmp_docx_path = tempfile.mkstemp(suffix=".docx", prefix=f"batuhan_{job_id}_")
    os.close(tmp_fd)

    # Prefer coordinate-based LLM mapper for complex table-based templates;
    # fall back to the heuristic heading-detection assembler for plain heading templates.
    use_llm_mapper = _has_tables(template_path)
    try:
        if use_llm_mapper:
            logger.info("[Packager] Table-based template detected → LLM mapper | job=%s", job_id)
            try:
                _assemble_with_llm_mapper(
                    template_path=template_path,
                    validated_report=validated_report,
                    output_path=tmp_docx_path,
                    standards=standards,
                    org_info=org_info,
                    job_id=job_id,
                    language=language,
                )
            except Exception as llm_err:
                logger.warning(
                    "[Packager] LLM mapper failed (%s), falling back to heuristic | job=%s",
                    llm_err, job_id,
                )
                assemble_docx(
                    template_path=template_path,
                    validated_report=validated_report,
                    output_path=tmp_docx_path,
                    standards=standards,
                )
        else:
            logger.info("[Packager] Heading-based template → heuristic assembler | job=%s", job_id)
            assemble_docx(
                template_path=template_path,
                validated_report=validated_report,
                output_path=tmp_docx_path,
                standards=standards,
            )
        docx_bytes = Path(tmp_docx_path).read_bytes()
    finally:
        try:
            os.unlink(tmp_docx_path)
        except OSError:
            pass

    final_docx_path = save_binary_artifact(job_id, "final_report.docx", docx_bytes)

    # --- 2. Write human-readable correction log ---
    correction_log_txt = _format_correction_log_txt(correction_log)
    correction_log_path = save_text_artifact(job_id, "correction_log.txt", correction_log_txt)

    # --- 3. Write job summary JSON ---
    summary = _build_summary(
        job_id=job_id,
        standards=standards,
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
        f"DOCX stored at {final_docx_path}"
    )

    return JobResult(
        job_id=job_id,
        final_docx_path=final_docx_path,
        correction_log_path=correction_log_path,
        standards=standards,
        stage=stage,
        files_used=files_used,
        correction_count=correction_log.correction_count,
    )

