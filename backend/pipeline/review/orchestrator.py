"""
BATUHAN — Review Orchestrator
Runs the full AI review of an existing audit report DOCX against
accreditation body rules and returns a structured ReviewResult.
"""

from __future__ import annotations
import ast
import json
import logging
import re
from pathlib import Path
from typing import Any

from anthropic import Anthropic
from schemas.models import (
    ReviewResult, ReviewFinding, ReviewFindingType, ReviewFindingSeverity,
)
from config.review_profiles.loader import load_review_profile
from config.clause_configs.loader import load_clause_config, get_mandatory_clause_ids
from storage.file_store import save_text_artifact

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


def _load_prompt() -> str:
    path = _PROMPTS_DIR / "prompt_review.txt"
    raw = path.read_text(encoding="utf-8")
    lines = [ln for ln in raw.splitlines() if not ln.strip().startswith("#")]
    return "\n".join(lines)


def _render_prompt(template: str, values: dict[str, str]) -> str:
    """Replace known prompt tokens without interpreting JSON braces."""
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", value)
    return rendered


def _profile_to_text(profile: dict) -> str:
    """Convert the rule profile dict to readable text for the prompt."""
    lines = []
    lines.append(f"Accreditation Body: {profile.get('display_name', 'Unknown')}")
    lines.append(f"Governing Standard: {profile.get('governing_standard', 'ISO/IEC 17021-1')}")
    if profile.get("reference_basis"):
        lines.append("")
        lines.append("REFERENCE BASIS:")
        for item in profile.get("reference_basis", []):
            lines.append(f"  - {item}")
    if profile.get("required_report_elements"):
        lines.append("")
        lines.append("REQUIRED REPORT ELEMENTS:")
        for item in profile.get("required_report_elements", []):
            lines.append(f"  - {item}")
    if profile.get("nc_classifications"):
        lines.append("")
        lines.append("NC CLASSIFICATIONS:")
        for nc_type, definition in profile.get("nc_classifications", {}).items():
            lines.append(f"  {nc_type.upper()}: {definition}")
    lines.append("")

    lines.append("STAGE REQUIREMENTS:")
    for stage_key, rules in profile.get("stage_requirements", {}).items():
        title = stage_key.replace("_", " ").title()
        lines.append(f"  {title}:")
        for item in rules.get("mandatory_coverage", []):
            lines.append(f"    - {item}")
        if "language_requirements" in rules:
            lines.append(f"    Language: {rules['language_requirements']}")

    if profile.get("audit_logic_checks"):
        lines.append("")
        lines.append("AUDIT LOGIC CHECKS:")
        for item in profile["audit_logic_checks"]:
            lines.append(f"  - {item}")

    lines.append("")
    lines.append("FINDING DEPTH REQUIREMENTS:")
    fdr = profile.get("finding_depth_requirements", {})
    lines.append(f"  Minimum finding length: {fdr.get('minimum_finding_length_words', 'not specified')} words")
    lines.append(f"  Must reference evidence: {fdr.get('must_reference_evidence', True)}")
    if fdr.get("vague_finding_patterns"):
        lines.append("  Vague patterns to flag:")
        for p in fdr.get("vague_finding_patterns", []):
            lines.append(f'    - "{p}"')

    if profile.get("nc_rules"):
        lines.append("")
        lines.append("NC RULES:")
        for rule, value in profile.get("nc_rules", {}).items():
            lines.append(f"  - {rule}: {value}")

    if profile.get("forbidden_in_findings"):
        lines.append("")
        lines.append("FORBIDDEN PHRASES IN FINDINGS:")
        for phrase in profile.get("forbidden_in_findings", []):
            lines.append(f'  - "{phrase}"')

    return "\n".join(lines)


def _stage_to_key(stage: str) -> str:
    normalized = stage.strip().lower().replace("-", " ")
    if "stage 1" in normalized:
        return "stage_1"
    if "stage 2" in normalized:
        return "stage_2"
    if "surveillance" in normalized:
        return "surveillance"
    if "recert" in normalized:
        return "recertification"
    return "stage_2"


def _get_stage_specific_rules(profile: dict, stage: str) -> str:
    stage_key = _stage_to_key(stage)
    stage_requirements = profile.get("stage_requirements", {})
    stage_rules = (
        stage_requirements.get(stage_key)
        or stage_requirements.get("stage_2")
        or {}
    )
    lines = [f"\nACTIVE STAGE RULES ({stage}):"]
    for item in stage_rules.get("mandatory_coverage", []):
        lines.append(f"  - {item}")
    if "language_requirements" in stage_rules:
        lines.append(f"  Language requirement: {stage_rules['language_requirements']}")
    return "\n".join(lines)


def _split_standard_label(standard: str) -> list[str]:
    standards: list[str] = []
    for part in standard.replace("+", ",").split(","):
        code = part.strip().upper()
        if code and code not in standards:
            standards.append(code)
    return standards or [standard.strip().upper()]


def _get_standard_specific_rules(profile: dict, standards: list[str]) -> str:
    lines: list[str] = []
    profile_rules = profile.get("standard_specific_rules", {})
    for standard in standards:
        rules = profile_rules.get(standard, {})
        if not rules:
            continue
        lines.append(f"\nSTANDARD-SPECIFIC RULES FOR {standard}:")
        for _key, items in rules.items():
            for item in items:
                lines.append(f"  - {item}")
    return "\n".join(lines)


def _get_mandatory_clauses_text(standards: list[str]) -> str:
    sections: list[str] = []
    for standard in standards:
        try:
            clause_config = load_clause_config(standard)
            mandatory_ids = get_mandatory_clause_ids(clause_config)
            clauses = [
                f"  - {c.clause_id}: {c.title}"
                for c in clause_config.clauses
                if c.clause_id in mandatory_ids
            ]
            if clauses:
                sections.append(f"{standard}:\n" + "\n".join(clauses))
            else:
                sections.append(f"{standard}: All mandatory clauses defined for this standard")
        except Exception as e:
            logger.warning("Could not load clause config for %s: %s", standard, e)
            sections.append(f"{standard}: All clauses of {standard} standard")
    return "\n\n".join(sections)


def _strip_json_fence(raw: str) -> str:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _message_text(response: Any) -> str:
    chunks: list[str] = []
    for block in getattr(response, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            chunks.append(text)
    return "\n".join(chunks).strip()


def _save_review_debug_artifact(review_job_id: str, filename: str, content: str) -> None:
    try:
        save_text_artifact(review_job_id, filename, content[:100000])
    except Exception as e:
        logger.warning(
            "Review [%s]: could not save debug artifact %s: %s",
            review_job_id,
            filename,
            e,
        )


def _normalise_json_candidate(text: str) -> str:
    text = _strip_json_fence(text).lstrip("\ufeff").strip()
    return re.sub(r",\s*([}\]])", r"\1", text)


def _normalise_parsed_root(parsed: Any) -> dict[str, Any]:
    if isinstance(parsed, dict):
        likely_keys = {
            "findings",
            "issues",
            "overall_assessment",
            "overall_assurance_verdict",
            "overall_verdict",
            "verdict",
            "identity",
            "identity_line",
        }
        if any(key in parsed for key in likely_keys):
            return parsed

        for wrapper_key in (
            "result",
            "review",
            "assessment",
            "report_review",
            "response",
            "data",
            "review_result",
            "output",
        ):
            value = parsed.get(wrapper_key)
            if isinstance(value, (dict, list)):
                return _normalise_parsed_root(value)
        return parsed
    if isinstance(parsed, list):
        return {"findings": parsed}
    raise ValueError("AI response JSON root was not an object or finding list.")


def _parse_json_candidate(candidate: str) -> dict[str, Any]:
    cleaned = _normalise_json_candidate(candidate)
    try:
        return _normalise_parsed_root(json.loads(cleaned))
    except json.JSONDecodeError:
        parsed = ast.literal_eval(cleaned)
        return _normalise_parsed_root(parsed)


def _extract_balanced_json(text: str, start: int) -> str | None:
    opener = text[start]
    closer = "}" if opener == "{" else "]"
    in_string = False
    escaped = False
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return None


def _extract_json_object(raw: str) -> dict[str, Any]:
    """Parse model JSON even when it is wrapped, fenced, or lightly malformed."""
    text = _normalise_json_candidate(raw)
    try:
        return _parse_json_candidate(text)
    except Exception:
        pass

    decoder = json.JSONDecoder()
    for start, char in enumerate(text):
        if char not in "{[":
            continue
        try:
            parsed, _end = decoder.raw_decode(text[start:])
            return _normalise_parsed_root(parsed)
        except Exception:
            continue

    for start, char in enumerate(text):
        if char not in "{[":
            continue
        candidate = _extract_balanced_json(text, start)
        if not candidate:
            continue
        try:
            return _parse_json_candidate(candidate)
        except Exception:
            continue

    raise ValueError("AI response did not contain parseable review JSON.")


def _repair_json_response(
    client: Anthropic,
    model: str,
    raw: str,
    parse_error: Exception,
    max_tokens: int,
) -> str:
    prompt = f"""You are a JSON repair step for CertivAI report review.
Return ONLY one valid JSON object. No markdown. No prose.
Keep the original assessment content; do not add new facts.
Required shape:
{{
  "identity": "",
  "verdict": "",
  "completeness_matrix": {{}},
  "strengths": [],
  "priority_actions": [],
  "checks_applied": [],
  "findings": [
    {{
      "clause_id": "",
      "clause_title": "",
      "finding_type": "WEAK_EVIDENCE",
      "severity": "WARNING",
      "description": "",
      "suggestion": "",
      "quote": ""
    }}
  ]
}}
Allowed severity values: CRITICAL, MAJOR, MINOR, WARNING, OK.
Allowed finding_type values: MISSING_SECTION, WEAK_EVIDENCE, NC_MISCLASSIFICATION, VAGUE_FINDING, MISSING_NC_CLAUSE_REF, MISSING_NC_RATIONALE, PLACEHOLDER, FORBIDDEN_PHRASE, STANDARD_SPECIFIC_MISSING, INSUFFICIENT_EVIDENCE_SPECIFICITY, OK.
Parse error: {parse_error}
Raw response:
{raw[:50000]}
"""
    response = client.messages.create(
        model=model,
        max_tokens=min(max(max_tokens, 4000), 8000),
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    return _message_text(response)


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(f"- {_stringify(item)}" for item in value)
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            label = str(key).replace("_", " ").title()
            item_text = _stringify(item)
            if "\n" in item_text:
                lines.append(f"{label}:\n{item_text}")
            else:
                lines.append(f"{label}: {item_text}")
        return "\n".join(lines)
    return str(value)


def _coerce_finding_type(value: Any, severity: ReviewFindingSeverity) -> ReviewFindingType:
    if severity == ReviewFindingSeverity.OK:
        return ReviewFindingType.OK
    key = _stringify(value).strip().upper().replace(" ", "_").replace("-", "_")
    if key in ReviewFindingType.__members__:
        return ReviewFindingType[key]
    value_map = {
        "EVIDENCE_GAP": ReviewFindingType.WEAK_EVIDENCE,
        "UNSUPPORTED": ReviewFindingType.WEAK_EVIDENCE,
        "UNSUPPORTED_CLAIM": ReviewFindingType.WEAK_EVIDENCE,
        "INSUFFICIENT_EVIDENCE": ReviewFindingType.INSUFFICIENT_EVIDENCE_SPECIFICITY,
        "INSUFFICIENT_EVIDENCE_SPECIFICITY": ReviewFindingType.INSUFFICIENT_EVIDENCE_SPECIFICITY,
        "LOGIC_GAP": ReviewFindingType.INSUFFICIENT_EVIDENCE_SPECIFICITY,
        "CONTRADICTION": ReviewFindingType.INSUFFICIENT_EVIDENCE_SPECIFICITY,
        "INTERNAL_CONTRADICTION": ReviewFindingType.INSUFFICIENT_EVIDENCE_SPECIFICITY,
        "DECISION_INTEGRITY": ReviewFindingType.INSUFFICIENT_EVIDENCE_SPECIFICITY,
        "MISSING": ReviewFindingType.MISSING_SECTION,
        "MISSING_CONTENT": ReviewFindingType.MISSING_SECTION,
        "STANDARD_GAP": ReviewFindingType.STANDARD_SPECIFIC_MISSING,
        "SPECIFIC_STANDARD_MISSING": ReviewFindingType.STANDARD_SPECIFIC_MISSING,
        "NC_CLASSIFICATION": ReviewFindingType.NC_MISCLASSIFICATION,
        "NC_CLASSIFICATION_ERROR": ReviewFindingType.NC_MISCLASSIFICATION,
        "ISSUE": ReviewFindingType.INSUFFICIENT_EVIDENCE_SPECIFICITY,
        "GAP": ReviewFindingType.INSUFFICIENT_EVIDENCE_SPECIFICITY,
        "OBSERVATION": ReviewFindingType.VAGUE_FINDING,
        "OFI": ReviewFindingType.VAGUE_FINDING,
    }
    return value_map.get(key, ReviewFindingType.INSUFFICIENT_EVIDENCE_SPECIFICITY)


def _coerce_severity(value: Any) -> ReviewFindingSeverity:
    key = _stringify(value).strip().upper().replace(" ", "_").replace("-", "_")
    if key in ReviewFindingSeverity.__members__:
        return ReviewFindingSeverity[key]
    if key in {"BLOCKER", "HIGH", "FAIL", "NOT_ACCEPTABLE"}:
        return ReviewFindingSeverity.CRITICAL
    if key in {"MEDIUM", "SERIOUS"}:
        return ReviewFindingSeverity.MAJOR
    if key in {"LOW", "IMPROVEMENT"}:
        return ReviewFindingSeverity.MINOR
    if key in {"OBSERVATION", "OFI", "INFO"}:
        return ReviewFindingSeverity.WARNING
    return ReviewFindingSeverity.WARNING


def _normalise_findings(parsed: dict[str, Any]) -> list[Any]:
    findings = parsed.get("findings")
    if findings is None:
        findings = parsed.get("issues") or parsed.get("findings_and_recommendations") or []
    if isinstance(findings, dict):
        flattened: list[Any] = []
        for value in findings.values():
            if isinstance(value, list):
                flattened.extend(value)
            else:
                flattened.append(value)
        return flattened
    if isinstance(findings, list):
        return findings
    return []


def _compose_overall_assessment(parsed: dict[str, Any]) -> str:
    explicit = parsed.get("overall_assessment") or parsed.get("overall_assurance_verdict")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()

    sections = [
        ("Identity", parsed.get("identity_line") or parsed.get("identity")),
        (
            "Overall assurance verdict",
            parsed.get("verdict")
            or parsed.get("overall_verdict")
            or parsed.get("assurance_verdict"),
        ),
        ("ISO/IEC 17021-1 section 9.4.8 completeness matrix", parsed.get("completeness_matrix")),
        ("Strengths", parsed.get("strengths")),
        ("Priority actions", parsed.get("priority_actions") or parsed.get("actions")),
        ("Checks applied", parsed.get("checks_applied")),
    ]
    rendered = []
    for title, value in sections:
        text = _stringify(value).strip()
        if text:
            rendered.append(f"{title}: {text}" if "\n" not in text else f"{title}:\n{text}")
    return "\n\n".join(rendered) or "Overall assurance verdict: The review completed, but no narrative assessment was returned."


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
        standard:          ISO standard code or integrated label (e.g. "QMS + EMS").
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
    standards = _split_standard_label(standard)
    standard_label = " + ".join(standards)
    mandatory_clauses_text = _get_mandatory_clauses_text(standards)

    # Build full rule profile text for prompt injection
    rule_profile_text = _profile_to_text(profile)
    rule_profile_text += _get_stage_specific_rules(profile, stage)
    rule_profile_text += _get_standard_specific_rules(profile, standards)

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
    prompt = _render_prompt(
        prompt_template,
        {
            "standard": standard_label,
            "stage": stage,
            "accreditation_body": profile.get("display_name", accreditation_body),
            "rule_profile_text": rule_profile_text,
            "mandatory_clauses": mandatory_clauses_text,
            "report_text": report_text,
        },
    )
    logger.info(
        "Review [%s]: prompt built | %d chars | standard=%s stage=%s ab=%s",
        review_job_id, len(prompt), standard_label, stage, accreditation_body,
    )

    # Call Claude — retry and repair parse failures before failing the job.
    parsed: dict | None = None
    last_parse_error: Exception | None = None
    response_max_tokens = min(max(max_tokens, 4096), 12000)
    for attempt in range(3):
        raw = ""
        try:
            response = client.messages.create(
                model=model,
                max_tokens=response_max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = _message_text(response)
            _save_review_debug_artifact(
                review_job_id,
                f"review_ai_response_attempt_{attempt + 1}.txt",
                raw,
            )
            parsed = _extract_json_object(raw)
            logger.info(
                "Review [%s]: Claude response parsed on attempt %d",
                review_job_id, attempt + 1,
            )
            break
        except Exception as e:
            last_parse_error = e
            _save_review_debug_artifact(
                review_job_id,
                f"review_ai_parse_error_attempt_{attempt + 1}.txt",
                str(e),
            )
            logger.warning(
                "Review [%s]: attempt %d failed: %s", review_job_id, attempt + 1, e
            )
            try:
                repaired = _repair_json_response(
                    client=client,
                    model=model,
                    raw=raw,
                    parse_error=e,
                    max_tokens=response_max_tokens,
                )
                _save_review_debug_artifact(
                    review_job_id,
                    f"review_ai_repair_attempt_{attempt + 1}.txt",
                    repaired,
                )
                parsed = _extract_json_object(repaired)
                logger.info(
                    "Review [%s]: repaired Claude response parsed on attempt %d",
                    review_job_id,
                    attempt + 1,
                )
                break
            except Exception as repair_error:
                last_parse_error = repair_error
                logger.warning(
                    "Review [%s]: repair for attempt %d failed: %s",
                    review_job_id,
                    attempt + 1,
                    repair_error,
                )

    if parsed is None:
        logger.error(
            "Review [%s]: all parse and repair attempts failed: %s",
            review_job_id,
            last_parse_error,
        )
        raise ValueError(
            "AI review response could not be parsed into the required review format after repair attempts."
        )

    # Parse findings
    findings: list[ReviewFinding] = []
    for raw_finding in _normalise_findings(parsed):
        try:
            if not isinstance(raw_finding, dict):
                raw_finding = {"description": _stringify(raw_finding)}
            severity = _coerce_severity(raw_finding.get("severity", "WARNING"))
            finding_type = _coerce_finding_type(raw_finding.get("finding_type", ""), severity)
            clause_id = (
                raw_finding.get("clause_id")
                or raw_finding.get("id")
                or raw_finding.get("finding_id")
                or raw_finding.get("location")
                or ""
            )
            clause_title = (
                raw_finding.get("clause_title")
                or raw_finding.get("title")
                or raw_finding.get("basis")
                or raw_finding.get("area")
                or ""
            )
            finding = ReviewFinding(
                clause_id=_stringify(clause_id),
                clause_title=_stringify(clause_title),
                finding_type=finding_type,
                severity=severity,
                description=_stringify(raw_finding.get("description", "")),
                suggestion=_stringify(
                    raw_finding.get("suggestion")
                    or raw_finding.get("recommended_fix")
                    or raw_finding.get("fix")
                    or ""
                ),
                quote=_stringify(raw_finding.get("quote", "")),
            )
            findings.append(finding)
        except Exception as e:
            logger.warning(
                "Review [%s]: skipping malformed finding %s — %s",
                review_job_id, raw_finding, e,
            )

    severity_order = {
        ReviewFindingSeverity.CRITICAL: 0,
        ReviewFindingSeverity.MAJOR: 1,
        ReviewFindingSeverity.MINOR: 2,
        ReviewFindingSeverity.WARNING: 3,
        ReviewFindingSeverity.OK: 4,
    }
    findings.sort(key=lambda item: severity_order.get(item.severity, 5))

    critical = sum(1 for f in findings if f.severity == ReviewFindingSeverity.CRITICAL)
    major    = sum(1 for f in findings if f.severity == ReviewFindingSeverity.MAJOR)
    minor    = sum(1 for f in findings if f.severity == ReviewFindingSeverity.MINOR)
    warning  = sum(1 for f in findings if f.severity == ReviewFindingSeverity.WARNING)
    non_ok   = sum(1 for f in findings if f.finding_type != ReviewFindingType.OK)

    result = ReviewResult(
        review_job_id=review_job_id,
        standard_code=standard_label,
        stage=stage,
        accreditation_body=accreditation_body,
        total_findings=non_ok,
        critical_count=critical,
        major_count=major,
        minor_count=minor,
        warning_count=warning,
        findings=findings,
        overall_assessment=_compose_overall_assessment(parsed),
    )

    logger.info(
        "Review [%s]: complete | %d findings (%d critical, %d major, %d minor, %d warning)",
        review_job_id, non_ok, critical, major, minor, warning,
    )
    return result
