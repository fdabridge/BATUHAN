"""
BATUHAN — Step C: Response Parser (T21)
Parses the raw Claude Prompt C response into:
  - ValidatedReport  (corrected sections, same structure as Step B)
  - CorrectionLog    (structured list of corrections made)

Expected output format (from prompt_c.txt):

  ## Final Corrected Report

  Section Title:
  [Exact title]

  Content:
  [Corrected content]

  ---

  ## List of Corrections Made

  - correction 1
  - correction 2
  ...
  ---
"""

from __future__ import annotations
import re
import logging
from backend.schemas.models import (
    ValidatedReport, CorrectionLog, CorrectionEntry,
    ReportSection, ISOStandard, AuditStage,
)

logger = logging.getLogger(__name__)

# Heading markers expected from prompt_c.txt
REPORT_HEADING = re.compile(r"##\s*Final Corrected Report", re.IGNORECASE)
CORRECTIONS_HEADING = re.compile(r"##\s*List of Corrections Made", re.IGNORECASE)

WEAK_PHRASES = [
    "limited documented evidence",
    "the available evidence indicates",
    "based on the documented information provided",
    "was not observed",
    "not clearly evidenced",
]


def _is_weak(content: str) -> bool:
    lower = content.lower()
    return any(p in lower for p in WEAK_PHRASES)


def _split_top_level(raw_output: str) -> tuple[str, str]:
    """
    Split raw Prompt C output into (report_block, corrections_block).
    Returns empty strings if either part is missing.
    """
    corr_match = CORRECTIONS_HEADING.search(raw_output)
    if corr_match:
        report_block = raw_output[: corr_match.start()].strip()
        corrections_block = raw_output[corr_match.end():].strip()
    else:
        # Fallback: treat whole output as report, no corrections
        logger.warning(
            "[Step C] '## List of Corrections Made' heading not found. "
            "Treating full output as corrected report with no corrections list."
        )
        report_block = raw_output.strip()
        corrections_block = ""

    # Strip the ## Final Corrected Report heading from the report block
    rep_match = REPORT_HEADING.search(report_block)
    if rep_match:
        report_block = report_block[rep_match.end():].strip()

    return report_block, corrections_block


def _parse_sections(report_block: str, expected_titles: list[str]) -> list[ReportSection]:
    """Parse section blocks from the corrected report portion."""
    blocks = re.split(r"\n\s*---\s*\n", report_block)
    sections: list[ReportSection] = []

    for i, block in enumerate(blocks):
        block = block.strip()
        if not block:
            continue

        title = ""
        content_lines: list[str] = []
        mode = None

        for line in block.splitlines():
            stripped = line.strip()
            if re.match(r"^Section\s+Title\s*:", stripped, re.IGNORECASE):
                mode = "title"
                inline = re.sub(
                    r"^Section\s+Title\s*:\s*", "", stripped, flags=re.IGNORECASE
                ).strip()
                if inline:
                    title = inline
            elif re.match(r"^Content\s*:", stripped, re.IGNORECASE):
                mode = "content"
                inline = re.sub(
                    r"^Content\s*:\s*", "", stripped, flags=re.IGNORECASE
                ).strip()
                if inline:
                    content_lines.append(inline)
            elif mode == "title" and stripped and not title:
                title = stripped
            elif mode == "content":
                content_lines.append(line)

        content = "\n".join(content_lines).strip()
        if not title or not content:
            logger.warning(f"[Step C] Could not parse section block {i + 1}. Skipping.")
            continue

        order_index = i
        for idx, expected in enumerate(expected_titles):
            if expected.strip().lower() == title.strip().lower():
                order_index = idx
                break

        sections.append(ReportSection(
            title=title,
            content=content,
            order_index=order_index,
            has_weak_evidence=_is_weak(content),
        ))

    sections.sort(key=lambda s: s.order_index)
    return sections


def _parse_corrections(corrections_block: str, job_id: str) -> CorrectionLog:
    """Parse the bullet list of corrections into a CorrectionLog."""
    entries: list[CorrectionEntry] = []

    # Strip trailing --- separators
    corrections_block = corrections_block.rstrip("-").strip()

    for line in corrections_block.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Accept lines starting with -, *, •
        if stripped.startswith(("-", "*", "•")):
            text = stripped.lstrip("-*• ").strip()
        elif stripped.lower() == "no corrections required.":
            text = stripped
        else:
            continue

        if not text:
            continue

        # Try to extract section title prefix: "[Section Name]" or "Section Name:"
        section_title: str | None = None
        section_match = re.match(r"^\[(.+?)\]\s*[:\-–]?\s*(.+)", text)
        if section_match:
            section_title = section_match.group(1).strip()
            text = section_match.group(2).strip()

        entries.append(CorrectionEntry(section_title=section_title, description=text))

    return CorrectionLog(
        job_id=job_id,
        corrections=entries,
        correction_count=len(entries),
    )


def parse_validation_output(
    raw_output: str,
    job_id: str,
    standard: ISOStandard,
    stage: AuditStage,
    expected_titles: list[str] | None = None,
) -> tuple[ValidatedReport, CorrectionLog]:
    """
    Parse the full Prompt C response.

    Returns:
        (ValidatedReport, CorrectionLog)

    Raises:
        ValueError: If the output is empty or no sections could be parsed.
    """
    if not raw_output or not raw_output.strip():
        raise ValueError("Prompt C returned empty output. Cannot proceed.")

    report_block, corrections_block = _split_top_level(raw_output)

    sections = _parse_sections(report_block, expected_titles or [])
    if not sections:
        raise ValueError(
            "Prompt C output could not be parsed into any report sections."
        )

    correction_log = _parse_corrections(corrections_block, job_id)

    logger.info(
        f"[Step C] Parsed {len(sections)} corrected sections | "
        f"{correction_log.correction_count} correction(s) logged."
    )

    validated_report = ValidatedReport(
        job_id=job_id,
        sections=sections,
        correction_log=correction_log,
        raw_output=raw_output,
    )
    return validated_report, correction_log

