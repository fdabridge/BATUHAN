"""
BATUHAN — Step B: Safety Checker (T18)
Validates the GeneratedReport before it proceeds to Step C.

Checks enforced:
  1. Every template section title is present in the output (no missing sections).
  2. Section titles exactly match the template (no renamed/added sections).
  3. No placeholder text remains in any section content.
  4. No blocked company names or phrases from sample reports appear in content.
  5. Content is non-empty for every section.
  6. No extra sections were invented beyond the template.
"""

from __future__ import annotations
import re
import logging
from backend.schemas.models import GeneratedReport, ReportSection, TemplateMap, StyleGuidance

logger = logging.getLogger(__name__)


class SafetyViolation:
    """A single safety rule violation found in the report."""
    def __init__(self, section_title: str | None, rule: str, detail: str):
        self.section_title = section_title
        self.rule = rule
        self.detail = detail

    def __str__(self) -> str:
        loc = f"[{self.section_title}]" if self.section_title else "[global]"
        return f"{loc} Rule '{self.rule}': {self.detail}"


PLACEHOLDER_PATTERNS = [
    re.compile(r"\[PLACEHOLDER\]", re.IGNORECASE),
    re.compile(r"\[INSERT.*?\]", re.IGNORECASE),
    re.compile(r"\{.*?\}"),
    re.compile(r"TO\s+BE\s+COMPLETED", re.IGNORECASE),
    re.compile(r"\bTBD\b"),
    re.compile(r"\bN/A\b\s*\(placeholder\)", re.IGNORECASE),
    re.compile(r"<[A-Z\s]+>"),
]


def _has_placeholder(text: str) -> bool:
    return any(p.search(text) for p in PLACEHOLDER_PATTERNS)


def _normalise_title(title: str) -> str:
    return title.strip().lower()


def check_report_safety(
    report: GeneratedReport,
    template_map: TemplateMap,
    style_guidance: StyleGuidance,
) -> list[SafetyViolation]:
    """
    Run all safety checks on the generated report.
    Returns list of violations. Empty list = passed all checks.
    """
    violations: list[SafetyViolation] = []

    expected_titles = [s.title for s in sorted(template_map.sections, key=lambda x: x.order_index)]
    generated_titles = {_normalise_title(s.title): s for s in report.sections}
    generated_raw_titles = [s.title for s in report.sections]

    # --- Rule 1: All template sections must be present ---
    for expected in expected_titles:
        if _normalise_title(expected) not in generated_titles:
            violations.append(SafetyViolation(
                section_title=expected,
                rule="MISSING_SECTION",
                detail=f"Template section '{expected}' was not generated.",
            ))

    # --- Rule 2: No extra sections invented beyond the template ---
    expected_normalised = {_normalise_title(t) for t in expected_titles}
    for title in generated_raw_titles:
        if _normalise_title(title) not in expected_normalised:
            violations.append(SafetyViolation(
                section_title=title,
                rule="EXTRA_SECTION",
                detail=f"Section '{title}' was not in the template.",
            ))

    for section in report.sections:
        # --- Rule 3: No placeholder text ---
        if _has_placeholder(section.content):
            violations.append(SafetyViolation(
                section_title=section.title,
                rule="PLACEHOLDER_PRESENT",
                detail="Section content contains unfilled placeholder text.",
            ))

        # --- Rule 4: Content must not be empty ---
        if not section.content.strip():
            violations.append(SafetyViolation(
                section_title=section.title,
                rule="EMPTY_CONTENT",
                detail="Section has no content.",
            ))

        # --- Rule 5: No blocked company names from sample reports ---
        content_lower = section.content.lower()
        for blocked_name in style_guidance.blocked_company_names:
            if blocked_name.lower() in content_lower:
                violations.append(SafetyViolation(
                    section_title=section.title,
                    rule="SAMPLE_LEAKAGE",
                    detail=f"Blocked company name detected: '{blocked_name}'.",
                ))

        # --- Rule 6: No blocked phrases from sample reports ---
        for blocked_phrase in style_guidance.blocked_phrases:
            if len(blocked_phrase) > 10 and blocked_phrase.lower() in content_lower:
                violations.append(SafetyViolation(
                    section_title=section.title,
                    rule="PHRASE_LEAKAGE",
                    detail=f"Blocked sample phrase detected: '{blocked_phrase[:60]}...'",
                ))

    return violations


def format_violations(violations: list[SafetyViolation]) -> str:
    """Format violations as a readable string for logging/storage."""
    if not violations:
        return "No safety violations detected."
    lines = [f"Safety check: {len(violations)} violation(s) found:"]
    for i, v in enumerate(violations, 1):
        lines.append(f"  {i}. {v}")
    return "\n".join(lines)


def get_sections_needing_retry(violations: list[SafetyViolation]) -> set[str]:
    """
    Return the set of section titles that failed safety checks
    and need to be retried with Claude.
    """
    RETRYABLE_RULES = {"PLACEHOLDER_PRESENT", "EMPTY_CONTENT", "SAMPLE_LEAKAGE", "PHRASE_LEAKAGE"}
    return {
        v.section_title
        for v in violations
        if v.rule in RETRYABLE_RULES and v.section_title
    }

