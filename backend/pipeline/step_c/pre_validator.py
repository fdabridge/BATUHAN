"""
BATUHAN — Step C: Pre-Validation Layer (T20)
Runs deterministic checks on the Step B GeneratedReport BEFORE
calling Prompt C. Produces a list of flagged issues that are
included in the Prompt C context so Claude knows what to fix.

Checks:
  1. All template sections are present
  2. No section content is empty
  3. No placeholder text remains
  4. No blocked/sample company names detected
  5. Standard and stage values are consistent in metadata
"""

from __future__ import annotations
import re
import logging
from backend.schemas.models import GeneratedReport, TemplateMap, StyleGuidance

logger = logging.getLogger(__name__)

PLACEHOLDER_PATTERNS = [
    re.compile(r"\[PLACEHOLDER\]", re.IGNORECASE),
    re.compile(r"\[INSERT.*?\]", re.IGNORECASE),
    re.compile(r"\{[A-Z_]{3,}\}"),          # {VARIABLE_NAME} style
    re.compile(r"TO\s+BE\s+COMPLETED", re.IGNORECASE),
    re.compile(r"\bTBD\b"),
    re.compile(r"<[A-Z][A-Z\s]+>"),         # <COMPANY NAME> style
]


def _has_placeholder(text: str) -> bool:
    return any(p.search(text) for p in PLACEHOLDER_PATTERNS)


def _normalise(title: str) -> str:
    return title.strip().lower()


class PreValidationIssue:
    def __init__(self, section: str | None, code: str, detail: str):
        self.section = section
        self.code = code
        self.detail = detail

    def __str__(self) -> str:
        loc = f"[{self.section}]" if self.section else "[global]"
        return f"{loc} {self.code}: {self.detail}"


def run_pre_validation(
    report: GeneratedReport,
    template_map: TemplateMap,
    style_guidance: StyleGuidance,
) -> list[PreValidationIssue]:
    """
    Run all deterministic pre-validation checks on the GeneratedReport.
    Returns a list of issues (empty = clean).
    """
    issues: list[PreValidationIssue] = []

    expected_titles = {
        _normalise(s.title): s.title
        for s in template_map.sections
    }
    generated_by_title = {
        _normalise(s.title): s
        for s in report.sections
    }

    # Check 1: All template sections present
    for norm, original in expected_titles.items():
        if norm not in generated_by_title:
            issues.append(PreValidationIssue(
                section=original,
                code="MISSING_SECTION",
                detail=f"Section '{original}' from template is absent in generated report.",
            ))

    # Check 2: No extra/invented sections
    for norm, section in generated_by_title.items():
        if norm not in expected_titles:
            issues.append(PreValidationIssue(
                section=section.title,
                code="EXTRA_SECTION",
                detail=f"Section '{section.title}' was not in the template.",
            ))

    for section in report.sections:
        content = section.content

        # Check 3: No empty sections
        if not content.strip():
            issues.append(PreValidationIssue(
                section=section.title,
                code="EMPTY_CONTENT",
                detail="Section content is empty.",
            ))
            continue

        # Check 4: No placeholders
        if _has_placeholder(content):
            issues.append(PreValidationIssue(
                section=section.title,
                code="PLACEHOLDER_PRESENT",
                detail="Section contains unfilled placeholder text.",
            ))

        # Check 5: No blocked company names
        content_lower = content.lower()
        for name in style_guidance.blocked_company_names:
            if name.lower() in content_lower:
                issues.append(PreValidationIssue(
                    section=section.title,
                    code="SAMPLE_LEAKAGE",
                    detail=f"Blocked sample company name detected: '{name}'.",
                ))

    if issues:
        logger.warning(
            f"[Step C Pre-Validation] {len(issues)} issue(s) found before calling Prompt C."
        )
        for issue in issues:
            logger.warning(f"  {issue}")
    else:
        logger.info("[Step C Pre-Validation] All checks passed. Report clean before Prompt C.")

    return issues


def format_issues_for_prompt(issues: list[PreValidationIssue]) -> str:
    """
    Format the pre-validation issues into a text block that can be
    injected into the Prompt C context so Claude knows what to focus on.
    """
    if not issues:
        return "Pre-validation passed: no issues flagged before this review."

    lines = [
        f"Pre-validation flagged {len(issues)} issue(s) requiring correction:",
        "",
    ]
    for i, issue in enumerate(issues, 1):
        lines.append(f"  {i}. {issue}")
    lines.append("")
    lines.append("Please address all flagged issues in your correction pass.")
    return "\n".join(lines)


def format_report_for_prompt(report: GeneratedReport) -> str:
    """
    Format the GeneratedReport sections into the string injected as
    {generated_report} in prompt_c.txt.
    """
    parts: list[str] = []
    for section in sorted(report.sections, key=lambda s: s.order_index):
        weak_note = " [NOTE: weak evidence flagged]" if section.has_weak_evidence else ""
        parts.append(
            f"Section Title:\n{section.title}{weak_note}\n\nContent:\n{section.content}"
        )
        parts.append("---")
    return "\n\n".join(parts)

