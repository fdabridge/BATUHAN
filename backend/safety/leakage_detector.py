"""
BATUHAN — Leakage Detection Safeguards (T32)
Scans Prompt B and C outputs for three categories of leakage:

  1. COMPANY_NAME   — blocked sample company names detected in content
  2. PLACEHOLDER    — template placeholder text still present
  3. PHRASE_COPY    — long verbatim phrases copied from sample report text

If any CRITICAL violations are found, delivery is blocked and the job
transitions to FAILED. Non-critical violations are logged as warnings.

Critical violations: COMPANY_NAME, PLACEHOLDER
Warning violations:  PHRASE_COPY (length-gated — copies > 80 chars)
"""

from __future__ import annotations
import json
import logging
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

from schemas.models import ValidatedReport, StyleGuidance
from storage.file_store import save_text_artifact

logger = logging.getLogger(__name__)

# Placeholder patterns that must never appear in final output
_PLACEHOLDER_PATTERNS: list[re.Pattern] = [
    re.compile(r"\[.*?\]"),           # [Section Placeholder]
    re.compile(r"\{.*?\}"),           # {variable}
    re.compile(r"<.*?>"),             # <insert here>
    re.compile(r"INSERT\s+HERE", re.IGNORECASE),
    re.compile(r"TODO", re.IGNORECASE),
    re.compile(r"TBD", re.IGNORECASE),
    re.compile(r"PLACEHOLDER", re.IGNORECASE),
    re.compile(r"lorem ipsum", re.IGNORECASE),
]

_PHRASE_MIN_LEN = 80   # chars — shorter matches are too common to flag


@dataclass
class LeakageViolation:
    section_title: str
    category: str           # COMPANY_NAME | PLACEHOLDER | PHRASE_COPY
    severity: str           # CRITICAL | WARNING
    detail: str


@dataclass
class LeakageReport:
    job_id: str
    is_clean: bool
    has_critical: bool
    violations: list[LeakageViolation] = field(default_factory=list)
    scanned_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# ---------------------------------------------------------------------------
# Internal scanners
# ---------------------------------------------------------------------------

def _scan_placeholders(section_title: str, content: str) -> list[LeakageViolation]:
    violations = []
    for pattern in _PLACEHOLDER_PATTERNS:
        match = pattern.search(content)
        if match:
            violations.append(LeakageViolation(
                section_title=section_title,
                category="PLACEHOLDER",
                severity="CRITICAL",
                detail=f"Placeholder pattern detected: '{match.group()[:60]}'",
            ))
    return violations


def _scan_company_names(
    section_title: str,
    content: str,
    blocked_names: list[str],
) -> list[LeakageViolation]:
    violations = []
    content_lower = content.lower()
    for name in blocked_names:
        if name and name.lower() in content_lower:
            violations.append(LeakageViolation(
                section_title=section_title,
                category="COMPANY_NAME",
                severity="CRITICAL",
                detail=f"Blocked company name detected: '{name}'",
            ))
    return violations


def _scan_phrase_copy(
    section_title: str,
    content: str,
    sample_texts: list[str],
) -> list[LeakageViolation]:
    violations = []
    words = content.split()
    # Sliding window of ~15 words → check for verbatim appearance in samples
    window = 15
    for i in range(len(words) - window + 1):
        phrase = " ".join(words[i:i + window])
        if len(phrase) < _PHRASE_MIN_LEN:
            continue
        phrase_lower = phrase.lower()
        for sample in sample_texts:
            if phrase_lower in sample.lower():
                violations.append(LeakageViolation(
                    section_title=section_title,
                    category="PHRASE_COPY",
                    severity="WARNING",
                    detail=f"Verbatim phrase from sample detected: '{phrase[:80]}...'",
                ))
                break  # one violation per window position is enough
    return violations


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scan_report_for_leakage(
    report: ValidatedReport,
    style_guidance: StyleGuidance,
    sample_texts: list[str] | None = None,
) -> LeakageReport:
    """
    Scan all sections of the validated report for leakage.

    Args:
        report:        The final report to scan (Step C output or fallback).
        style_guidance: Contains blocked_company_names and blocked_phrases.
        sample_texts:  Raw text from sample reports (optional — for phrase copy scan).

    Returns:
        LeakageReport with is_clean=True only when zero critical violations.
    """
    all_violations: list[LeakageViolation] = []

    for section in report.sections:
        content = section.content
        title = section.title

        all_violations += _scan_placeholders(title, content)
        all_violations += _scan_company_names(title, content, style_guidance.blocked_company_names)

        if sample_texts:
            all_violations += _scan_phrase_copy(title, content, sample_texts)

    has_critical = any(v.severity == "CRITICAL" for v in all_violations)
    return LeakageReport(
        job_id=report.job_id,
        is_clean=len(all_violations) == 0,
        has_critical=has_critical,
        violations=all_violations,
    )


def write_leakage_report(job_id: str, leakage: LeakageReport) -> str:
    """Persist the leakage scan result as leakage_scan.json. Returns artifact path."""
    path = save_text_artifact(
        job_id, "leakage_scan.json",
        json.dumps(leakage.to_dict(), indent=2),
    )
    if leakage.has_critical:
        logger.error(
            f"[Leakage] CRITICAL violations found for job {job_id}: "
            f"{sum(1 for v in leakage.violations if v.severity == 'CRITICAL')} critical, "
            f"{len(leakage.violations)} total."
        )
    elif leakage.violations:
        logger.warning(
            f"[Leakage] {len(leakage.violations)} warning violation(s) for job {job_id}."
        )
    else:
        logger.info(f"[Leakage] Clean scan for job {job_id}.")
    return path

