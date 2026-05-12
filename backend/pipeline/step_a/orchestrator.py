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
    ExtractedEvidence, ParsedDocument, ISOStandard, AuditStage,
    ScopeAnalysisResult,
)
from parsers.corpus_builder import format_corpus_for_prompt
from pipeline.step_a.evidence_parser import (
    parse_evidence_output, validate_evidence, format_evidence_for_prompt
)
from pipeline.step_a.traceability import (
    attach_traceability, build_traceability_report
)
from pipeline.step_a.merger import merge_per_standard_evidence
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
    standards: list[ISOStandard],
    stage: AuditStage,
    applicable_clauses_text: str = "All clauses applicable — no scope analysis available",
    excluded_clauses_text: str = "None",
) -> str:
    # For integrated audits, show all selected codes joined with " + "
    standards_label = " + ".join(s.value for s in standards)
    return (
        prompt_template
        .replace("{standard}", standards_label)
        .replace("{stage}", stage.value)
        .replace("{document_corpus}", corpus_text)
        .replace("{applicable_clauses}", applicable_clauses_text)
        .replace("{excluded_clauses}", excluded_clauses_text)
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


def _run_single_standard_extraction(
    std_code: str,
    corpus: list[ParsedDocument],
    corpus_text: str,
    applicable_clauses_text: str,
    excluded_clauses_text: str,
    stage: AuditStage,
    job_id: str,
    standards_for_prompt: list[ISOStandard],
) -> ExtractedEvidence:
    """
    Core evidence extraction for a single ISO standard.
    Runs the full prompt→Claude→parse→validate→traceability loop.

    Args:
        std_code:              Standard code string (e.g. "QMS").
        corpus:                Full parsed document corpus.
        corpus_text:           Pre-formatted corpus text (passed in to avoid
                               re-formatting per standard in integrated audits).
        applicable_clauses_text: Clause filter text already built from scope analysis.
        excluded_clauses_text:  Excluded clauses text.
        stage:                 Audit stage.
        job_id:                Current job ID.
        standards_for_prompt:  ISOStandard list used for prompt label
                               (single-element for per-standard passes).

    Returns:
        ExtractedEvidence with traceability attached.
    """
    prompt_template = _load_prompt_a()
    prompt = _build_prompt(
        prompt_template, corpus_text, standards_for_prompt, stage,
        applicable_clauses_text=applicable_clauses_text,
        excluded_clauses_text=excluded_clauses_text,
    )
    logger.info(
        f"[Step A] Prompt built for {std_code} | {len(prompt):,} chars"
    )

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 2):
        logger.info(
            f"[Step A] Calling Claude for {std_code} "
            f"(attempt {attempt}/{MAX_RETRIES + 1})"
        )
        try:
            raw_output = _call_claude(prompt)
            logger.info(
                f"[Step A] Claude response for {std_code}: "
                f"{len(raw_output):,} chars | preview: {raw_output[:200]!r}"
            )
            evidence = parse_evidence_output(raw_output, job_id)
            warnings = validate_evidence(evidence)
            for w in warnings:
                logger.warning(f"[Step A] [{std_code}] Validation warning: {w}")
            evidence = attach_traceability(evidence, corpus)
            return evidence
        except ValueError as e:
            last_error = e
            logger.warning(f"[Step A] [{std_code}] Attempt {attempt} failed: {e}")
            if attempt > MAX_RETRIES:
                raise ValueError(
                    f"[Step A] [{std_code}] All {MAX_RETRIES + 1} attempts failed. "
                    f"Last error: {last_error}"
                ) from last_error

    # Should never reach here
    raise RuntimeError(f"[Step A] Unexpected exit from retry loop for {std_code}")


def run_step_a(
    job_id: str,
    corpus: list[ParsedDocument],
    standards: list[ISOStandard],
    stage: AuditStage,
    scope_analysis: ScopeAnalysisResult | None = None,
    selected_standards: list | None = None,
) -> ExtractedEvidence:
    """
    Execute Step A: Evidence Extraction.

    Args:
        job_id:             The current processing job ID.
        corpus:             Parsed company documents (text + OCR merged).
        standards:          Selected ISO standard(s). Multiple = integrated audit.
        stage:              Audit stage (Stage 1 or Stage 2).
        scope_analysis:     Optional Step 0 result used to filter clause evidence.
        selected_standards: Optional list of standard code strings (e.g. ["QMS", "EMS"]).
                            When provided and contains 2+ entries, triggers per-standard
                            extraction passes followed by merging.

    Returns:
        Validated ExtractedEvidence with traceability attached.

    Raises:
        ValueError: If Claude returns malformed output after all retries.
        FileNotFoundError: If prompt_a.txt is missing.
    """
    logger.info(f"[Step A] Starting evidence extraction | job={job_id}")
    logger.info(
        f"[Step A] Corpus received: {len(corpus)} document(s) | "
        f"{sum(d.char_count for d in corpus):,} total chars"
    )
    for doc in corpus:
        logger.info(
            f"[Step A]   '{doc.filename}' | {doc.char_count:,} chars | ocr={doc.is_ocr_sourced}"
        )

    # Build applicable/excluded clause context from scope analysis
    applicable_clauses_text = "All clauses applicable — no scope analysis available"
    excluded_clauses_text = "None"

    if scope_analysis:
        applicable_lines = []
        excluded_lines = []
        for std_code, std_result in scope_analysis.standards.items():
            for cid in std_result.applicable_clause_ids:
                applicable_lines.append(f"  - [{std_code}] {cid}")
            for cid in std_result.excluded_clause_ids:
                excluded_lines.append(f"  - [{std_code}] {cid}")
        applicable_clauses_text = "\n".join(applicable_lines) if applicable_lines else "All clauses applicable"
        excluded_clauses_text = "\n".join(excluded_lines) if excluded_lines else "None"
        logger.info(
            f"[Step A] Scope analysis injected: "
            f"{len(applicable_lines)} applicable, {len(excluded_lines)} excluded clause entries"
        )

    corpus_text = format_corpus_for_prompt(corpus)
    logger.info(f"[Step A] Formatted corpus_text: {len(corpus_text):,} chars (after size cap)")

    if not corpus_text.strip() or corpus_text == "[No readable content extracted from company documents]":
        raise ValueError("[Step A] Document corpus is empty. Cannot extract evidence.")

    # ------------------------------------------------------------------
    # Determine extraction mode: integrated (2+ standards) vs. single
    # ------------------------------------------------------------------
    std_codes = selected_standards if selected_standards else [s.value for s in standards]

    if len(std_codes) >= 2:
        # ---------------------------------------------------------------
        # INTEGRATED AUDIT — one extraction pass per standard, then merge
        # ---------------------------------------------------------------
        logger.info(
            f"[Step A] Integrated audit detected: {std_codes}. "
            f"Running per-standard extraction passes."
        )
        per_standard_evidence: dict[str, ExtractedEvidence] = {}

        for std_code in std_codes:
            # Find the matching ISOStandard enum for prompt labelling
            try:
                std_enum = ISOStandard(std_code)
            except ValueError:
                std_enum = standards[0]  # safe fallback

            evidence_for_std = _run_single_standard_extraction(
                std_code=std_code,
                corpus=corpus,
                corpus_text=corpus_text,
                applicable_clauses_text=applicable_clauses_text,
                excluded_clauses_text=excluded_clauses_text,
                stage=stage,
                job_id=job_id,
                standards_for_prompt=[std_enum],
            )
            per_standard_evidence[std_code] = evidence_for_std
            logger.info(f"[Step A] Extracted evidence for {std_code}")

            # Persist per-standard artifact for debugging (non-blocking)
            try:
                save_text_artifact(
                    job_id,
                    f"step_a_evidence_{std_code.lower()}.json",
                    evidence_for_std.model_dump_json(indent=2),
                )
            except Exception as _e:
                logger.warning(
                    f"[Step A] Could not persist per-standard artifact for {std_code}: {_e}"
                )

        # Merge all per-standard results
        import anthropic as _anthropic
        _client = _anthropic.Anthropic(api_key=settings.anthropic_api_key)
        evidence = merge_per_standard_evidence(
            per_standard_evidence=per_standard_evidence,
            client=_client,
            model=settings.claude_model,
            max_tokens=settings.claude_max_tokens,
            temperature=settings.claude_temperature,
            job_id=job_id,
        )
        logger.info(
            f"[Step A] Merge complete | job={job_id} | "
            f"{len(std_codes)} standards merged"
        )

    else:
        # ---------------------------------------------------------------
        # SINGLE STANDARD — existing code path, no behaviour change
        # ---------------------------------------------------------------
        evidence = _run_single_standard_extraction(
            std_code=std_codes[0] if std_codes else "QMS",
            corpus=corpus,
            corpus_text=corpus_text,
            applicable_clauses_text=applicable_clauses_text,
            excluded_clauses_text=excluded_clauses_text,
            stage=stage,
            job_id=job_id,
            standards_for_prompt=standards,
        )

    # --- Persist final evidence object ---
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

    _fields = [
        "company_overview", "scope_of_activities", "documented_information",
        "key_processes_and_functions", "evidence_of_system_implementation",
        "audit_relevant_records", "identified_gaps",
    ]
    total_items = sum(len(getattr(evidence, f, [])) for f in _fields)
    weak_items = sum(
        1 for f in _fields
        for item in getattr(evidence, f, [])
        if item.is_weak
    )

    logger.info(
        f"[Step A] Complete | job={job_id} | "
        f"{total_items} evidence items | {weak_items} weak"
    )
    return evidence

