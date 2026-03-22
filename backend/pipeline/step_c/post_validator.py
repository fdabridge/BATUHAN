"""
BATUHAN — Step C: Post-Validation Layer (T22)
Runs structural verification on the ValidatedReport AFTER Prompt C returns.
This is the final gate before the report is accepted for DOCX assembly.

Checks:
  1. All original template sections are still present (none dropped)
  2. No extra sections were added by Prompt C
  3. No section content is empty
  4. No placeholder text remains
  5. Sections are in the correct template order
"""

from __future__ import annotations
import re
import logging
from backend.schemas.models import ValidatedReport, TemplateMap

logger = logging.getLogger(__name__)

PLACEHOLDER_PATTERNS = [
    re.compile(r"\[PLACEHOLDER\]", re.IGNORECASE),
    re.compile(r"\[INSERT.*?\]", re.IGNORECASE),
    re.compile(r"\{[A-Z_]{3,}\}"),
    re.compile(r"TO\s+BE\s+COMPLETED", re.IGNORECASE),
    re.compile(r"\bTBD\b"),
    re.compile(r"<[A-Z][A-Z\s]+>"),
]


def _has_placeholder(text: str) -> bool:
    return any(p.search(text) for p in PLACEHOLDER_PATTERNS)


def _norm(title: str) -> str:
    return title.strip().lower()


class PostValidationError(Exception):
    """Raised when the ValidatedReport fails final structural checks."""
    def __init__(self, message: str, violations: list[str]):
        super().__init__(message)
        self.violations = violations


def run_post_validation(
    validated_report: ValidatedReport,
    template_map: TemplateMap,
) -> list[str]:
    """
    Verify the ValidatedReport meets all structural requirements.

    Returns:
        List of violation strings (empty = passed).

    Raises:
        PostValidationError: If critical structural violations are found.
    """
    violations: list[str] = []

    expected_titles_ordered = [
        s.title for s in sorted(template_map.sections, key=lambda x: x.order_index)
    ]
    expected_norm = {_norm(t): t for t in expected_titles_ordered}
    generated_norm = {_norm(s.title): s for s in validated_report.sections}

    # Check 1: All template sections present
    for norm, original in expected_norm.items():
        if norm not in generated_norm:
            violations.append(
                f"MISSING_SECTION: '{original}' is absent from the validated report."
            )

    # Check 2: No extra/invented sections
    for norm, section in generated_norm.items():
        if norm not in expected_norm:
            violations.append(
                f"EXTRA_SECTION: '{section.title}' was not in the original template."
            )

    for section in validated_report.sections:
        # Check 3: No empty content
        if not section.content.strip():
            violations.append(
                f"EMPTY_CONTENT: Section '{section.title}' has no content after validation."
            )
            continue

        # Check 4: No placeholders remaining
        if _has_placeholder(section.content):
            violations.append(
                f"PLACEHOLDER_PRESENT: Section '{section.title}' still contains "
                "placeholder text after Prompt C correction."
            )

    # Check 5: Section order matches template
    validated_ordered = [
        s.title for s in sorted(validated_report.sections, key=lambda s: s.order_index)
    ]
    expected_that_exist = [t for t in expected_titles_ordered if _norm(t) in generated_norm]
    validated_that_exist = [t for t in validated_ordered if _norm(t) in expected_norm]

    for exp, got in zip(expected_that_exist, validated_that_exist):
        if _norm(exp) != _norm(got):
            violations.append(
                f"ORDER_MISMATCH: Expected '{exp}' at this position but found '{got}'."
            )
            break  # Report only the first order mismatch

    if violations:
        logger.error(
            f"[Step C Post-Validation] {len(violations)} violation(s) detected. "
            "Report CANNOT proceed to assembly."
        )
        for v in violations:
            logger.error(f"  {v}")
        raise PostValidationError(
            f"Step C post-validation failed with {len(violations)} violation(s).",
            violations,
        )

    logger.info(
        "[Step C Post-Validation] All checks passed. "
        f"{len(validated_report.sections)} sections verified. Report approved for assembly."
    )
    return violations

