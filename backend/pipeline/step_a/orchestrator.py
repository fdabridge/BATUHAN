"""
BATUHAN — Step A Orchestrator (T12)
Runs the full evidence extraction step:
  1. Load prompt_a.txt
  2. Inject document corpus + standard + stage
  3. Call Claude (with retry on malformed output)
  4. Parse + validate the 7-section output
  5. Attach source traceability to each item
  6. Persist evidence + traceability report
  7. Return validated ExtractedEvidence

No raw documents pass beyond this step. Only ExtractedEvidence proceeds.
"""

from __future__ import annotations
import logging
import json
from pathlib import Path

from config.settings import get_settings
from schemas.models import (
    ExtractedEvidence, ParsedDocument, ISOStandard, AuditStage
)
from parsers.corpus_builder import format_corpus_for_prompt
from pipeline.step_a.evidence_parser import (
    parse_evidence_output, validate_evidence, format_evidence_for_prompt
)
from pipeline.step_a.traceability import (
    attach_traceability, build_traceability_report
)
from storage.file_store import save_text_artifact

logger = logging.getLogger(__name__)
settings = get_settings()

MAX_RETRIES = 2


def _load_prompt_a() -> str:
    prompt_path = Path(settings.prompts_dir) / "prompt_a.txt"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt A not found at: {prompt_path}")
    text = prompt_path.read_text(encoding="utf-8")
    # Strip comment lines (lines starting with #)
    lines = [l for l in text.splitlines() if not l.startswith("#")]
    return "\n".join(lines).strip()


def _build_prompt(
    prompt_template: str,
    corpus_text: str,
    standard: ISOStandard,
    stage: AuditStage,
) -> str:
    return (
        prompt_template
        .replace("{standard}", standard.value)
        .replace("{stage}", stage.value)
        .replace("{document_corpus}", corpus_text)
    )


def _call_claude(prompt: str) -> str:
    """Send the prompt to Claude and return the raw text response."""
    import anthropic
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model=settings.claude_model,
        max_tokens=settings.claude_max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def run_step_a(
    job_id: str,
    corpus: list[ParsedDocument],
    standard: ISOStandard,
    stage: AuditStage,
) -> ExtractedEvidence:
    """
    Execute Step A: Evidence Extraction.

    Args:
        job_id:   The current processing job ID.
        corpus:   Parsed company documents (text + OCR merged).
        standard: Selected ISO standard.
        stage:    Audit stage (Stage 1 or Stage 2).

    Returns:
        Validated ExtractedEvidence with traceability attached.

    Raises:
        ValueError: If Claude returns malformed output after all retries.
        FileNotFoundError: If prompt_a.txt is missing.
    """
    logger.info(f"[Step A] Starting evidence extraction | job={job_id}")

    prompt_template = _load_prompt_a()
    corpus_text = format_corpus_for_prompt(corpus)

    if not corpus_text.strip() or corpus_text == "[No readable content extracted from company documents]":
        raise ValueError("[Step A] Document corpus is empty. Cannot extract evidence.")

    prompt = _build_prompt(prompt_template, corpus_text, standard, stage)

    # --- Retry loop ---
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 2):
        logger.info(f"[Step A] Calling Claude (attempt {attempt}/{MAX_RETRIES + 1})")
        try:
            raw_output = _call_claude(prompt)
            evidence = parse_evidence_output(raw_output, job_id)
            warnings = validate_evidence(evidence)
            if warnings:
                for w in warnings:
                    logger.warning(f"[Step A] Validation warning: {w}")
            # Attach traceability
            evidence = attach_traceability(evidence, corpus)
            break
        except ValueError as e:
            last_error = e
            logger.warning(f"[Step A] Attempt {attempt} failed: {e}")
            if attempt > MAX_RETRIES:
                raise ValueError(
                    f"[Step A] All {MAX_RETRIES + 1} attempts failed. "
                    f"Last error: {last_error}"
                ) from last_error

    # --- Persist evidence object ---
    save_text_artifact(
        job_id,
        "step_a_evidence.json",
        evidence.model_dump_json(indent=2),
    )

    # --- Persist traceability report ---
    traceability_report = build_traceability_report(evidence)
    save_text_artifact(job_id, "step_a_traceability.txt", traceability_report)

    # --- Persist formatted evidence (for Prompt B injection) ---
    formatted = format_evidence_for_prompt(evidence)
    save_text_artifact(job_id, "step_a_formatted.txt", formatted)

    total_items = sum(
        len(getattr(evidence, f, []))
        for f in ["company_overview", "scope_of_activities", "documented_information",
                  "key_processes_and_functions", "evidence_of_system_implementation",
                  "audit_relevant_records", "identified_gaps"]
    )
    weak_items = sum(
        1
        for f in ["company_overview", "scope_of_activities", "documented_information",
                  "key_processes_and_functions", "evidence_of_system_implementation",
                  "audit_relevant_records", "identified_gaps"]
        for item in getattr(evidence, f, [])
        if item.is_weak
    )

    logger.info(
        f"[Step A] Complete | job={job_id} | "
        f"{total_items} evidence items | {weak_items} weak"
    )
    return evidence

