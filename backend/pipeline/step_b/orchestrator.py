"""
BATUHAN — Step B Orchestrator (T15)
Runs the full report generation step:
  1. Load prompt_b.txt
  2. Build stage + standard context (T16, T17)
  3. Inject evidence, template sections, style guidance
  4. Call Claude with retry
  5. Parse section-by-section output into GeneratedReport
  6. Run safety checks (T18) — retry flagged sections if needed
  7. Persist report + safety log
  8. Return validated GeneratedReport

Input:  ExtractedEvidence (from Step A) — no raw documents
Output: GeneratedReport — passed to Step C
"""

from __future__ import annotations
import logging
from pathlib import Path

from config.settings import get_settings
from schemas.models import (
    ExtractedEvidence, GeneratedReport, TemplateMap, StyleGuidance,
    ISOStandard, AuditStage,
)
from pipeline.step_a.evidence_parser import format_evidence_for_prompt
from pipeline.step_b.context_builder import build_prompt_b_context
from pipeline.step_b.report_parser import parse_report_output
from pipeline.step_b.safety_checker import (
    check_report_safety, format_violations, get_sections_needing_retry
)
from storage.file_store import save_text_artifact

logger = logging.getLogger(__name__)
settings = get_settings()

MAX_RETRIES = 2


def _load_prompt_b() -> str:
    prompt_path = Path(settings.prompts_dir) / "prompt_b.txt"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt B not found at: {prompt_path}")
    lines = [l for l in prompt_path.read_text(encoding="utf-8").splitlines()
             if not l.startswith("#")]
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


def run_step_b(
    job_id: str,
    evidence: ExtractedEvidence,
    template_map: TemplateMap,
    style_guidance: StyleGuidance,
    standard: ISOStandard,
    stage: AuditStage,
) -> GeneratedReport:
    """
    Execute Step B: Report Generation.

    Args:
        job_id:        Current job ID.
        evidence:      Validated ExtractedEvidence from Step A.
        template_map:  Ordered section map from the blank .docx template.
        style_guidance: Safe style/tone extracted from sample reports.
        standard:      Selected ISO standard.
        stage:         Audit stage.

    Returns:
        GeneratedReport with all sections filled and safety-checked.

    Raises:
        ValueError: If Claude returns unusable output after all retries.
        FileNotFoundError: If prompt_b.txt is missing.
    """
    logger.info(f"[Step B] Starting report generation | job={job_id}")

    prompt_template = _load_prompt_b()
    evidence_text = format_evidence_for_prompt(evidence)
    expected_titles = [s.title for s in sorted(template_map.sections, key=lambda x: x.order_index)]

    ctx = build_prompt_b_context(standard, stage, template_map, style_guidance, evidence_text)
    prompt = _build_prompt(prompt_template, ctx)

    last_error: Exception | None = None
    report: GeneratedReport | None = None

    for attempt in range(1, MAX_RETRIES + 2):
        logger.info(f"[Step B] Calling Claude (attempt {attempt}/{MAX_RETRIES + 1})")
        try:
            raw_output = _call_claude(prompt)
            report = parse_report_output(raw_output, job_id, standard, stage, expected_titles)
            break
        except ValueError as e:
            last_error = e
            logger.warning(f"[Step B] Attempt {attempt} parse failed: {e}")
            if attempt > MAX_RETRIES:
                raise ValueError(
                    f"[Step B] All {MAX_RETRIES + 1} attempts failed. Last: {last_error}"
                ) from last_error

    assert report is not None

    # --- Safety checks (T18) ---
    violations = check_report_safety(report, template_map, style_guidance)
    violation_text = format_violations(violations)
    save_text_artifact(job_id, "step_b_safety_check.txt", violation_text)

    if violations:
        for v in violations:
            logger.warning(f"[Step B] Safety violation: {v}")
        retry_sections = get_sections_needing_retry(violations)
        if retry_sections:
            logger.warning(
                f"[Step B] {len(retry_sections)} section(s) flagged for retry: "
                + ", ".join(f"'{s}'" for s in retry_sections)
            )
            # Sections are flagged — Step C will correct them.
            # We do not re-call Claude here to avoid infinite loops;
            # Prompt C is the correction mechanism.

    # --- Persist ---
    save_text_artifact(job_id, "step_b_report.json", report.model_dump_json(indent=2))

    formatted_sections = "\n\n".join(
        f"## {s.title}\n{s.content}" for s in report.sections
    )
    save_text_artifact(job_id, "step_b_formatted.txt", formatted_sections)

    weak_count = sum(1 for s in report.sections if s.has_weak_evidence)
    logger.info(
        f"[Step B] Complete | job={job_id} | "
        f"{len(report.sections)} sections | {weak_count} with weak evidence | "
        f"{len(violations)} safety violation(s)"
    )
    return report

