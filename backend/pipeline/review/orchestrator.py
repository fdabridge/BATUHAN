"""
BATUHAN — Review Orchestrator
Runs the full AI review of an existing audit report DOCX against
accreditation body rules and returns a structured ReviewResult.
"""

from __future__ import annotations
import json
import logging
import re
from pathlib import Path

from anthropic import Anthropic
from schemas.models import (
    ReviewResult, ReviewFinding, ReviewFindingType, ReviewFindingSeverity,
)
from config.review_profiles.loader import load_review_profile
from config.clause_configs.loader import load_clause_config, get_mandatory_clause_ids

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


def _load_prompt() -> str:
    path = _PROMPTS_DIR / "prompt_review.txt"
    raw = path.read_text(encoding="utf-8")
    lines = [ln for ln in raw.splitlines() if not ln.strip().startswith("#")]
    return "\n".join(lines)


def _profile_to_text(profile: dict) -> str:
    """Convert the rule profile dict to readable text for the prompt."""
    lines = []
    lines.append(f"Accreditation Body: {profile['display_name']}")
    lines.append(f"Governing Standard: {profile['governing_standard']}")
    lines.append("")
    lines.append("NC CLASSIFICATIONS:")
    for nc_type, definition in profile["nc_classifications"].items():
        lines.append(f"  {nc_type.upper()}: {definition}")
    lines.append("")

    # Include both stage blocks so Claude has full context
    lines.append("STAGE REQUIREMENTS (Stage 1):")
    s1 = profile["stage_requirements"]["stage_1"]
    for item in s1.get("mandatory_coverage", []):
        lines.append(f"  - {item}")
    if "language_requirements" in s1:
        lines.append(f"  Language: {s1['language_requirements']}")

    lines.append("")
    lines.append("STAGE REQUIREMENTS (Stage 2):")
    s2 = profile["stage_requirements"]["stage_2"]
    for item in s2.get("mandatory_coverage", []):
        lines.append(f"  - {item}")
    if "language_requirements" in s2:
        lines.append(f"  Language: {s2['language_requirements']}")

    lines.append("")
    lines.append("FINDING DEPTH REQUIREMENTS:")
    fdr = profile["finding_depth_requirements"]
    lines.append(f"  Minimum finding length: {fdr['minimum_finding_length_words']} words")
    lines.append(f"  Must reference evidence: {fdr['must_reference_evidence']}")
    lines.append("  Vague patterns to flag:")
    for p in fdr["vague_finding_patterns"]:
        lines.append(f'    - "{p}"')

    lines.append("")
    lines.append("NC RULES:")
    for rule, value in profile["nc_rules"].items():
        lines.append(f"  - {rule}: {value}")

    lines.append("")
    lines.append("FORBIDDEN PHRASES IN FINDINGS:")
    for phrase in profile["forbidden_in_findings"]:
        lines.append(f'  - "{phrase}"')

    return "\n".join(lines)


def _get_stage_specific_rules(profile: dict, stage: str) -> str:
    stage_key = "stage_1" if "1" in stage else "stage_2"
    stage_rules = profile["stage_requirements"].get(stage_key, {})
    lines = [f"\nACTIVE STAGE RULES ({stage}):"]
    for item in stage_rules.get("mandatory_coverage", []):
        lines.append(f"  - {item}")
    if "language_requirements" in stage_rules:
        lines.append(f"  Language requirement: {stage_rules['language_requirements']}")
    return "\n".join(lines)


def _get_standard_specific_rules(profile: dict, standard: str) -> str:
    rules = profile.get("standard_specific_rules", {}).get(standard, {})
    if not rules:
        return ""
    lines = [f"\nSTANDARD-SPECIFIC RULES FOR {standard}:"]
    for key, items in rules.items():
        for item in items:
            lines.append(f"  - {item}")
    return "\n".join(lines)


def _empty_result(
    review_job_id: str, standard: str, stage: str, accreditation_body: str
) -> ReviewResult:
    return ReviewResult(
        review_job_id=review_job_id,
        standard_code=standard,
        stage=stage,
        accreditation_body=accreditation_body,
        total_findings=0,
        critical_count=0,
        major_count=0,
        minor_count=0,
        warning_count=0,
        findings=[],
        overall_assessment="Review could not be completed due to a processing error.",
    )


def run_review(
    report_text: str,
    standard: str,
    stage: str,
    accreditation_body: str,
    review_job_id: str,
    client: Anthropic,
    model: str,
    max_tokens: int,
    temperature: float,
) -> ReviewResult:
    """
    Execute the AI review of an audit report against accreditation rules.

    Args:
        report_text:       Plain text extracted from the uploaded report DOCX.
        standard:          ISO standard code (e.g. "QMS", "ISMS").
        stage:             Audit stage string ("Stage 1" or "Stage 2").
        accreditation_body: Accreditation body code ("UAF" or "TURKAK").
        review_job_id:     The review job ID for artifact labelling.
        client:            Anthropic client instance.
        model:             Claude model identifier.
        max_tokens:        Max tokens for Claude response.
        temperature:       Claude temperature setting.

    Returns:
        ReviewResult with per-clause findings and overall assessment.
    """
    profile = load_review_profile(accreditation_body)

    # Load clause config to build mandatory clause list
    try:
        clause_config = load_clause_config(standard)
        mandatory_ids = get_mandatory_clause_ids(clause_config)
        mandatory_clauses_text = "\n".join(
            f"  - {c.clause_id}: {c.title}"
            for c in clause_config.clauses
            if c.clause_id in mandatory_ids
        )
    except Exception as e:
        logger.warning("Could not load clause config for %s: %s", standard, e)
        mandatory_clauses_text = f"All clauses of {standard} standard"

    # Build full rule profile text for prompt injection
    rule_profile_text = _profile_to_text(profile)
    rule_profile_text += _get_stage_specific_rules(profile, stage)
    rule_profile_text += _get_standard_specific_rules(profile, standard)

    # Cap report text to avoid token overflow
    # Review prompt + profile + clauses ~ 3k tokens; leave ~20k for report
    max_report_chars = 25000
    if len(report_text) > max_report_chars:
        logger.warning(
            "Review [%s]: report text truncated from %d to %d chars",
            review_job_id, len(report_text), max_report_chars,
        )
        report_text = report_text[:max_report_chars] + "\n[... report truncated ...]"

    # Load and format prompt
    prompt_template = _load_prompt()
    prompt = prompt_template.format(
        standard=standard,
        stage=stage,
        accreditation_body=profile["display_name"],
        rule_profile_text=rule_profile_text,
        mandatory_clauses=mandatory_clauses_text,
        report_text=report_text,
    )
    logger.info(
        "Review [%s]: prompt built | %d chars | standard=%s stage=%s ab=%s",
        review_job_id, len(prompt), standard, stage, accreditation_body,
    )

    # Call Claude — retry up to 3 attempts on parse failure
    parsed: dict | None = None
    for attempt in range(3):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            raw = re.sub(r'^```json\s*', '', raw)
            raw = re.sub(r'^```\s*', '', raw)
            raw = re.sub(r'\s*```$', '', raw)
            parsed = json.loads(raw)
            logger.info(
                "Review [%s]: Claude response parsed on attempt %d",
                review_job_id, attempt + 1,
            )
            break
        except Exception as e:
            logger.warning(
                "Review [%s]: attempt %d failed: %s", review_job_id, attempt + 1, e
            )
            if attempt == 2:
                logger.error(
                    "Review [%s]: all 3 attempts failed — returning empty result",
                    review_job_id,
                )
                return _empty_result(review_job_id, standard, stage, accreditation_body)

    assert parsed is not None

    # Parse findings
    findings: list[ReviewFinding] = []
    for raw_finding in parsed.get("findings", []):
        try:
            finding = ReviewFinding(
                clause_id=raw_finding.get("clause_id", ""),
                clause_title=raw_finding.get("clause_title", ""),
                finding_type=ReviewFindingType(raw_finding.get("finding_type", "OK")),
                severity=ReviewFindingSeverity(raw_finding.get("severity", "OK")),
                description=raw_finding.get("description", ""),
                suggestion=raw_finding.get("suggestion", ""),
                quote=raw_finding.get("quote", ""),
            )
            findings.append(finding)
        except Exception as e:
            logger.warning(
                "Review [%s]: skipping malformed finding %s — %s",
                review_job_id, raw_finding, e,
            )

    critical = sum(1 for f in findings if f.severity == ReviewFindingSeverity.CRITICAL)
    major    = sum(1 for f in findings if f.severity == ReviewFindingSeverity.MAJOR)
    minor    = sum(1 for f in findings if f.severity == ReviewFindingSeverity.MINOR)
    warning  = sum(1 for f in findings if f.severity == ReviewFindingSeverity.WARNING)
    non_ok   = sum(1 for f in findings if f.finding_type != ReviewFindingType.OK)

    result = ReviewResult(
        review_job_id=review_job_id,
        standard_code=standard,
        stage=stage,
        accreditation_body=accreditation_body,
        total_findings=non_ok,
        critical_count=critical,
        major_count=major,
        minor_count=minor,
        warning_count=warning,
        findings=findings,
        overall_assessment=parsed.get("overall_assessment", ""),
    )

    logger.info(
        "Review [%s]: complete | %d findings (%d critical, %d major, %d minor, %d warning)",
        review_job_id, non_ok, critical, major, minor, warning,
    )
    return result
