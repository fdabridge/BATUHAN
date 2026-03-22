"""
BATUHAN — Step A: Evidence Parser (T13)
Parses the raw Claude Prompt A response into a validated ExtractedEvidence object.
Enforces the 7 required sections. Flags weak evidence. Rejects malformed output.
"""

from __future__ import annotations
import re
import logging
from schemas.models import ExtractedEvidence, EvidenceItem

logger = logging.getLogger(__name__)

# The 7 required section headings exactly as defined in prompt_a.txt and A.pdf
REQUIRED_SECTIONS = [
    "Company Overview",
    "Scope of Activities",
    "Documented Information Identified",
    "Key Processes and Functions",
    "Evidence of System Implementation",
    "Audit-Relevant Records",
    "Identified Gaps or Unclear Areas",
]

# Map section headings → ExtractedEvidence field names
SECTION_FIELD_MAP = {
    "Company Overview":                   "company_overview",
    "Scope of Activities":                "scope_of_activities",
    "Documented Information Identified":  "documented_information",
    "Key Processes and Functions":        "key_processes_and_functions",
    "Evidence of System Implementation":  "evidence_of_system_implementation",
    "Audit-Relevant Records":             "audit_relevant_records",
    "Identified Gaps or Unclear Areas":   "identified_gaps",
}

WEAK_EVIDENCE_MARKERS = [
    "not clearly evidenced",
    "unclear",
    "not observed",
    "insufficient",
    "not provided",
    "not available",
    "not found",
    "limited evidence",
    "no evidence",
]


def _is_weak(statement: str) -> bool:
    lower = statement.lower()
    return any(marker in lower for marker in WEAK_EVIDENCE_MARKERS)


def _parse_bullets(text: str) -> list[str]:
    """Extract bullet-point lines from a section body."""
    bullets: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        # Accept lines starting with -, *, •, or plain text
        if stripped.startswith(("-", "*", "•")):
            content = stripped.lstrip("-*• ").strip()
        elif stripped and not stripped.startswith("#"):
            content = stripped
        else:
            continue
        if content:
            bullets.append(content)
    return bullets


def _split_into_sections(raw_output: str) -> dict[str, str]:
    """
    Split the Claude response into sections by ## headings.
    Returns dict of {section_title: section_body_text}.
    """
    sections: dict[str, str] = {}
    # Match ## Section Title patterns
    pattern = re.compile(r"^##\s+(.+)$", re.MULTILINE)
    matches = list(pattern.finditer(raw_output))

    for i, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw_output)
        body = raw_output[start:end].strip()
        sections[title] = body

    return sections


def _find_section(sections: dict[str, str], expected_title: str) -> str:
    """
    Find a section body by title with fuzzy matching.
    Handles minor casing/spacing differences from Claude.
    """
    # Exact match first
    if expected_title in sections:
        return sections[expected_title]
    # Case-insensitive match
    for title, body in sections.items():
        if title.lower().strip() == expected_title.lower().strip():
            return body
    # Partial match (Claude may abbreviate)
    for title, body in sections.items():
        if expected_title.lower() in title.lower() or title.lower() in expected_title.lower():
            return body
    return ""


def parse_evidence_output(raw_output: str, job_id: str) -> ExtractedEvidence:
    """
    Parse the raw Prompt A response into a validated ExtractedEvidence object.

    - Splits by ## headings
    - Maps each heading to the correct field
    - Converts bullet lines to EvidenceItem objects
    - Flags weak items (containing 'Not clearly evidenced' etc.)
    - Logs any missing sections as warnings

    Raises ValueError if the output is completely unparseable (empty or no sections).
    """
    if not raw_output or not raw_output.strip():
        raise ValueError("Prompt A returned empty output. Cannot proceed.")

    sections = _split_into_sections(raw_output)

    if not sections:
        raise ValueError(
            "Prompt A output contains no ## section headings. "
            "Response may be malformed. Raw output logged for review."
        )

    evidence_data: dict[str, list[EvidenceItem]] = {}

    for section_title in REQUIRED_SECTIONS:
        field_name = SECTION_FIELD_MAP[section_title]
        body = _find_section(sections, section_title)

        if not body:
            logger.warning(f"[Step A] Section missing from output: '{section_title}'")
            evidence_data[field_name] = [
                EvidenceItem(
                    statement="Not clearly evidenced — section not returned by extraction.",
                    is_weak=True,
                )
            ]
            continue

        bullets = _parse_bullets(body)
        if not bullets:
            logger.warning(f"[Step A] Section '{section_title}' has no bullet points.")
            evidence_data[field_name] = [
                EvidenceItem(
                    statement="Not clearly evidenced — no extractable content in section.",
                    is_weak=True,
                )
            ]
            continue

        items = [
            EvidenceItem(
                statement=bullet,
                is_weak=_is_weak(bullet),
            )
            for bullet in bullets
        ]
        evidence_data[field_name] = items
        weak_count = sum(1 for i in items if i.is_weak)
        logger.info(
            f"[Step A] '{section_title}': {len(items)} items, {weak_count} weak."
        )

    return ExtractedEvidence(
        job_id=job_id,
        raw_output=raw_output,
        **evidence_data,
    )


def validate_evidence(evidence: ExtractedEvidence) -> list[str]:
    """
    Run post-parse validation checks on the ExtractedEvidence object.
    Returns a list of warning strings. Empty list = passed.
    """
    warnings: list[str] = []
    for section_title, field_name in SECTION_FIELD_MAP.items():
        items: list[EvidenceItem] = getattr(evidence, field_name, [])
        if not items:
            warnings.append(f"Section '{section_title}' is empty.")
        elif all(item.is_weak for item in items):
            warnings.append(
                f"Section '{section_title}' contains only weak/unclear evidence."
            )
    return warnings


def format_evidence_for_prompt(evidence: ExtractedEvidence) -> str:
    """
    Format the ExtractedEvidence object as a string for injection into Prompt B/C.
    Each section is clearly labelled. Weak items are flagged.
    """
    parts: list[str] = []
    for section_title, field_name in SECTION_FIELD_MAP.items():
        items: list[EvidenceItem] = getattr(evidence, field_name, [])
        parts.append(f"## {section_title}")
        if not items:
            parts.append("- Not clearly evidenced.")
        else:
            for item in items:
                weak_tag = " [WEAK EVIDENCE]" if item.is_weak else ""
                src_tag = f" (source: {item.source_filename})" if item.source_filename else ""
                parts.append(f"- {item.statement}{weak_tag}{src_tag}")
        parts.append("")
    return "\n".join(parts)

