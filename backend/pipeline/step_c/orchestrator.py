"""
BATUHAN — Step C Orchestrator (T19)
Runs the full validation & correction step:
  1. Pre-validate the Step B report deterministically (T20)
  2. Build Prompt C context: report + evidence + standard + stage
  3. Call Claude with Prompt C
  4. Parse corrected report + correction log (T21)
  5. Post-validate final corrected report structure (T22)
  6. Persist all artifacts
  7. Return ValidatedReport + CorrectionLog

Input:  GeneratedReport (from Step B) + ExtractedEvidence (from Step A)
Output: ValidatedReport + CorrectionLog
"""

from __future__ import annotations
import logging
from pathlib import Path

from config.settings import get_settings
from schemas.models import (
    ExtractedEvidence, GeneratedReport, ValidatedReport,
    CorrectionLog, TemplateMap, StyleGuidance,
    ISOStandard, AuditStage,
)
from pipeline.step_a.evidence_parser import format_evidence_for_prompt
from pipeline.step_c.pre_validator import (
    run_pre_validation, format_issues_for_prompt, format_report_for_prompt,
)
from pipeline.step_c.response_parser import parse_validation_output
from pipeline.step_c.post_validator import run_post_validation, PostValidationError
from storage.file_store import save_text_artifact

logger = logging.getLogger(__name__)
settings = get_settings()

MAX_RETRIES = 1  # Step C retries once if output is unparseable


def _load_prompt_c() -> str:
    prompt_path = Path(settings.prompts_dir) / "prompt_c.txt"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt C not found at: {prompt_path}")
    lines = [ln for ln in prompt_path.read_text(encoding="utf-8").splitlines()
             if not ln.startswith("#")]
    return "\n".join(lines).strip()


def _build_prompt(template: str, ctx: dict[str, str]) -> str:
    result = template
    for key, value in ctx.items():
        result = result.replace("{" + key + "}", value)
    return result


def _call_claude(prompt: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model=settings.claude_model,
        max_tokens=settings.claude_max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def run_step_c(
    job_id: str,
    generated_report: GeneratedReport,
    evidence: ExtractedEvidence,
    template_map: TemplateMap,
    style_guidance: StyleGuidance,
) -> tuple[ValidatedReport, CorrectionLog]:
    """
    Execute Step C: Validation & Correction.

    Args:
        job_id:            Current job ID.
        generated_report:  Step B GeneratedReport.
        evidence:          Step A ExtractedEvidence (ground truth).
        template_map:      Section map from blank template.
        style_guidance:    Style/blocked-name guidance.

    Returns:
        (ValidatedReport, CorrectionLog) — both persisted as artifacts.

    Raises:
        ValueError: If Claude returns unparseable output after retries.
        PostValidationError: If the corrected report fails structural checks.
        FileNotFoundError: If prompt_c.txt is missing.
    """
    logger.info(f"[Step C] Starting validation & correction | job={job_id}")

    # --- T20: Pre-validation ---
    pre_issues = run_pre_validation(generated_report, template_map, style_guidance)
    pre_issues_text = format_issues_for_prompt(pre_issues)
    save_text_artifact(job_id, "step_c_pre_validation.txt", pre_issues_text)

    # --- Build Prompt C ---
    prompt_template = _load_prompt_c()
    expected_titles = [
        s.title for s in sorted(template_map.sections, key=lambda x: x.order_index)
    ]

    report_text = format_report_for_prompt(generated_report)
    evidence_text = format_evidence_for_prompt(evidence)

    standards_label = " + ".join(s.value for s in generated_report.standards)
    ctx = {
        "standard": standards_label,
        "stage": generated_report.stage.value,
        "generated_report": report_text,
        "extracted_evidence": evidence_text,
    }

    # Append pre-validation issues as a note at the end of the prompt
    prompt_text = _build_prompt(prompt_template, ctx)
    if pre_issues:
        prompt_text += (
            f"\n\n---\n\nPRE-VALIDATION NOTES (fix these specifically):\n{pre_issues_text}"
        )

    # --- T19: Call Claude ---
    last_error: Exception | None = None
    validated_report: ValidatedReport | None = None
    correction_log: CorrectionLog | None = None

    for attempt in range(1, MAX_RETRIES + 2):
        logger.info(f"[Step C] Calling Claude (attempt {attempt}/{MAX_RETRIES + 1})")
        try:
            raw_output = _call_claude(prompt_text)
            validated_report, correction_log = parse_validation_output(
                raw_output, job_id,
                generated_report.standards, generated_report.stage,
                expected_titles,
            )
            break
        except ValueError as exc:
            last_error = exc
            logger.warning(f"[Step C] Attempt {attempt} parse failed: {exc}")
            if attempt > MAX_RETRIES:
                raise ValueError(
                    f"[Step C] All {MAX_RETRIES + 1} attempts failed. Last: {last_error}"
                ) from last_error

    assert validated_report is not None
    assert correction_log is not None

    # --- T22: Post-validation (raises PostValidationError if failed) ---
    run_post_validation(validated_report, template_map)

    # --- Persist all artifacts ---
    save_text_artifact(job_id, "step_c_report.json", validated_report.model_dump_json(indent=2))
    save_text_artifact(
        job_id, "step_c_correction_log.json", correction_log.model_dump_json(indent=2)
    )
    corrections_text = "\n".join(
        f"- [{e.section_title or 'general'}] {e.description}"
        for e in correction_log.corrections
    ) or "No corrections required."
    save_text_artifact(job_id, "step_c_correction_log.txt", corrections_text)

    formatted = "\n\n".join(
        f"## {s.title}\n{s.content}"
        for s in validated_report.sections
    )
    save_text_artifact(job_id, "step_c_formatted.txt", formatted)

    logger.info(
        f"[Step C] Complete | job={job_id} | "
        f"{len(validated_report.sections)} sections | "
        f"{correction_log.correction_count} correction(s)"
    )
    return validated_report, correction_log

