"""
BATUHAN — DOCX Assembly Engine (T23)
Inserts validated corrected section content into the original blank .docx template.

Strategy:
  1. Open the original blank template (preserves all styles, headers, footers, logos).
  2. Walk the document body XML elements directly (never via doc.paragraphs, which
     creates new wrapper objects on every access and breaks identity checks).
  3a. Heading-style templates: for each heading XML element matching a section title,
      remove subsequent non-heading body paragraphs and insert corrected content.
  3b. Table-style templates (fallback): for each table cell that looks like a heading
      (bold or ALL CAPS short text), inject content into the adjacent content cell
      in the same row, or into the first cell of the next row if no adjacent cell exists.
  4. Preserve ALL heading/title elements exactly — never alter titles or structure.
  5. Save as a new file — never overwrite the original template.

CRITICAL RULE: Template structure is IMMUTABLE. Only content areas are replaced.
"""

from __future__ import annotations
import logging
import re
from pathlib import Path
from lxml import etree
from docx import Document
from schemas.models import ValidatedReport, ReportSection, ISOStandard

logger = logging.getLogger(__name__)

# OOXML namespace
_WNS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

# Style IDs (w:pStyle w:val) used by Word for built-in Heading styles.
# These are the XML IDs, not the display names ("Heading 1" → "Heading1").
_HEADING_STYLE_IDS = {"Heading1", "Heading2", "Heading3"}

# Maximum text length for a table cell to be considered a section heading.
_MAX_HEADING_LEN = 150

# Compiled regex patterns used to identify which standard a table belongs to.
# Word-bounded abbreviations + unique ISO numbers (ISO numbers cannot appear
# inside other words, so no word boundary needed for the numeric patterns).
_STANDARD_PATTERNS: dict[str, list[re.Pattern]] = {
    "QMS":   [re.compile(r"\bqms\b", re.IGNORECASE), re.compile(r"9001")],
    "EMS":   [re.compile(r"\bems\b", re.IGNORECASE), re.compile(r"14001")],
    "OHSMS": [re.compile(r"\bohsms\b", re.IGNORECASE), re.compile(r"45001")],
    "FSMS":  [re.compile(r"\bfsms\b", re.IGNORECASE), re.compile(r"22000")],
    "MDQMS": [re.compile(r"\bmdqms\b", re.IGNORECASE), re.compile(r"13485")],
    "ISMS":  [re.compile(r"\bisms\b", re.IGNORECASE), re.compile(r"27001")],
    "ABMS":  [re.compile(r"\babms\b", re.IGNORECASE), re.compile(r"37001")],
    "ENMS":  [re.compile(r"\benms\b", re.IGNORECASE), re.compile(r"50001")],
}


# ---------------------------------------------------------------------------
# Generic XML helpers
# ---------------------------------------------------------------------------

def _wtag(name: str) -> str:
    return f"{{{_WNS}}}{name}"


def _norm(title: str) -> str:
    return title.strip().lower()


def _get_elem_text(elem) -> str:
    """Extract all text from a paragraph or cell XML element."""
    return "".join(t.text or "" for t in elem.iter(_wtag("t"))).strip()


def _make_text_para_elem(text: str):
    """Create a bare w:p XML element containing the given text in a single run."""
    p = etree.Element(_wtag("p"))
    r = etree.SubElement(p, _wtag("r"))
    t = etree.SubElement(r, _wtag("t"))
    t.text = text
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    return p


# ---------------------------------------------------------------------------
# Heading-style paragraph helpers
# ---------------------------------------------------------------------------

def _is_heading_elem(elem) -> bool:
    """Return True if the XML element is a Heading 1/2/3 paragraph."""
    if elem.tag != _wtag("p"):
        return False
    pPr = elem.find(_wtag("pPr"))
    if pPr is None:
        return False
    pStyle = pPr.find(_wtag("pStyle"))
    if pStyle is None:
        return False
    val = pStyle.get(_wtag("val"), "")
    return val in _HEADING_STYLE_IDS


def _replace_section_content(body, heading_elem, content_lines: list[str]) -> None:
    """
    Remove all non-heading body children directly after heading_elem,
    then insert new paragraph elements for each line of content.
    """
    current = list(body)
    idx = current.index(heading_elem)

    to_remove = []
    for child in current[idx + 1:]:
        if _is_heading_elem(child):
            break
        to_remove.append(child)

    for elem in to_remove:
        body.remove(elem)

    insert_after = list(body).index(heading_elem) + 1
    for line in reversed(content_lines):
        body.insert(insert_after, _make_text_para_elem(line))


# ---------------------------------------------------------------------------
# Table-cell heading helpers
# ---------------------------------------------------------------------------

def _is_all_caps(text: str) -> bool:
    """True if text has at least one alpha character and all alpha chars are uppercase."""
    alpha = [c for c in text if c.isalpha()]
    return bool(alpha) and all(c.isupper() for c in alpha)


def _is_bold_para_elem(p_elem) -> bool:
    """True if every text-carrying run in a paragraph XML element is bold."""
    bold_flags: list[bool] = []
    for r in p_elem.findall(_wtag("r")):
        t = r.find(_wtag("t"))
        if t is None or not (t.text or "").strip():
            continue
        rPr = r.find(_wtag("rPr"))
        bold_flags.append(rPr is not None and rPr.find(_wtag("b")) is not None)
    return bool(bold_flags) and all(bold_flags)


def _tc_is_heading(tc_elem) -> tuple[bool, str]:
    """
    Decide whether a table-cell element looks like a section heading.

    Returns (is_heading, full_cell_text).
    Criteria (either is sufficient):
      - First non-empty paragraph is ALL CAPS.
      - First non-empty paragraph has all bold runs.
    Text must be ≤ _MAX_HEADING_LEN characters.
    """
    paragraphs = tc_elem.findall(_wtag("p"))
    if not paragraphs:
        return False, ""

    # Gather all non-empty text lines from the cell
    lines = [_get_elem_text(p) for p in paragraphs if _get_elem_text(p)]
    if not lines:
        return False, ""

    full_text = " ".join(lines)
    if len(full_text) > _MAX_HEADING_LEN:
        return False, ""

    first_p = next((p for p in paragraphs if _get_elem_text(p)), None)
    if first_p is None:
        return False, ""

    first_text = _get_elem_text(first_p)
    if _is_all_caps(first_text) or _is_bold_para_elem(first_p):
        return True, full_text

    return False, ""


def _fill_tc_elem(tc_elem, content_lines: list[str]) -> None:
    """
    Replace all paragraphs in a table-cell element with the given content lines.
    Preserves the cell element itself (borders, shading, etc. stay intact).
    """
    for p in list(tc_elem.findall(_wtag("p"))):
        tc_elem.remove(p)
    for line in content_lines:
        tc_elem.append(_make_text_para_elem(line))


def _tbl_matches_standards(tbl_elem, selected_std_values: set[str]) -> bool:
    """
    Return True if this table should be processed for the selected standard(s).

    Logic:
    - If the table text contains identifiers for a standard NOT in the
      selected set, return False → skip (leave its 'N/A' text intact).
    - If the table text contains no standard identifiers at all (neutral
      header/cover tables), return True → process normally.
    - If the table text matches any selected standard, return True → process.

    For integrated audits (multiple standards), tables belonging to ALL
    selected standards are processed; only tables for unselected standards
    are skipped.
    """
    all_text = " ".join(t.text or "" for t in tbl_elem.iter(_wtag("t")))
    for std_value, patterns in _STANDARD_PATTERNS.items():
        if std_value in selected_std_values:
            continue  # Don't skip any selected standard's table
        for pattern in patterns:
            if pattern.search(all_text):
                logger.debug(
                    "[Assembly] Skipping table — belongs to %s, not in selected %s.",
                    std_value, selected_std_values,
                )
                return False
    return True


def _collect_table_heading_targets(body, selected_standards: list[ISOStandard]) -> list[tuple[str, object]]:
    """
    Scan all tables in the document body for heading-like cells.

    For each heading cell, the injection target is determined by:
      - Pattern B (two-column): the next cell in the same row.
      - Pattern A (one-column): the first cell of the next row.

    Returns list of (normalised_title, content_tc_elem) pairs in document order.
    Heading cells are never themselves modified.
    For integrated audits, pass all selected standards so their tables are
    all processed rather than skipped.
    """
    selected_std_values = {s.value for s in selected_standards}
    results: list[tuple[str, object]] = []

    for tbl in body.findall(_wtag("tbl")):
        # Skip tables that belong to a standard NOT in the selected set.
        if not _tbl_matches_standards(tbl, selected_std_values):
            continue

        rows = tbl.findall(_wtag("tr"))
        seen_tc_ids: set[int] = set()

        for row_idx, tr in enumerate(rows):
            tcs = tr.findall(_wtag("tc"))
            for tc_idx, tc in enumerate(tcs):
                if id(tc) in seen_tc_ids:
                    continue
                seen_tc_ids.add(id(tc))

                is_hdr, text = _tc_is_heading(tc)
                if not is_hdr or not text:
                    continue

                # Determine content target cell
                content_tc = None
                if tc_idx + 1 < len(tcs):
                    # Pattern B (two-column): RIGHT cell in the same row.
                    content_tc = tcs[tc_idx + 1]
                elif row_idx + 1 < len(rows):
                    # Pattern A (one-column): first cell of the next row.
                    next_tcs = rows[row_idx + 1].findall(_wtag("tc"))
                    if next_tcs:
                        content_tc = next_tcs[0]

                if content_tc is not None:
                    # Bug 1 fix: mark the content cell as seen so it is never
                    # re-evaluated as a heading itself. Without this, the right
                    # cell of a two-column row could be detected as a second
                    # heading and inject content into the LEFT cell of the next
                    # row instead of staying in the correct right cell.
                    seen_tc_ids.add(id(content_tc))
                    results.append((_norm(text), content_tc))

    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def assemble_docx(
    template_path: str,
    validated_report: ValidatedReport,
    output_path: str,
    standards: list[ISOStandard] | None = None,
) -> str:
    """
    Assemble the final report DOCX by injecting validated section content
    into the blank template.

    Supports both heading-style and table-style templates automatically.

    Args:
        template_path:    Absolute path to the original blank .docx template.
        validated_report: Validated corrected report from Step C.
        output_path:      Where to save the completed .docx.
        standards:        The ISO standard(s) for this job. Tables belonging
                          to standards NOT in this list are left untouched.
                          For integrated audits, pass all selected standards.

    Returns:
        Absolute path of the saved DOCX file.

    Raises:
        ValueError: If template cannot be opened or has no detectable sections.
    """
    path = Path(template_path)
    if not path.exists():
        raise ValueError(f"Template not found: {template_path}")

    doc = Document(template_path)
    body = doc.element.body

    # Build lookup: normalised title → ReportSection
    content_by_title: dict[str, ReportSection] = {
        _norm(s.title): s for s in validated_report.sections
    }

    sections_injected = 0

    # -----------------------------------------------------------------------
    # Strategy 1: Heading-style paragraphs (Heading 1/2/3)
    # -----------------------------------------------------------------------
    heading_elems: list[tuple[object, str]] = []
    for child in list(body):
        if _is_heading_elem(child):
            text = _get_elem_text(child)
            if text:
                heading_elems.append((child, _norm(text)))

    if heading_elems:
        logger.info("[Assembly] Using heading-style injection (%d headings found).", len(heading_elems))
        for heading_elem, title_norm in reversed(heading_elems):
            raw_title = _get_elem_text(heading_elem)
            if title_norm not in content_by_title:
                logger.warning(
                    "[Assembly] No corrected content for heading '%s'. "
                    "Leaving template placeholder intact.", raw_title
                )
                continue
            section = content_by_title[title_norm]
            content_lines = section.content.splitlines() or [""]
            _replace_section_content(body, heading_elem, content_lines)
            sections_injected += 1
            logger.debug("[Assembly] Injected content for heading '%s'.", raw_title)

    else:
        # -----------------------------------------------------------------------
        # Strategy 2: Table-cell headings (bold / ALL CAPS)
        # -----------------------------------------------------------------------
        # Fall back to [QMS] if no standards supplied (keeps function self-contained).
        effective_standards = standards if standards else [next(iter(ISOStandard))]
        table_targets = _collect_table_heading_targets(body, effective_standards)
        if not table_targets:
            raise ValueError(
                "Template has no detectable sections. "
                "Use Word Heading styles (Heading 1/2/3) or bold/ALL CAPS text "
                "in table cells to mark section titles."
            )

        logger.info("[Assembly] Using table-cell injection (%d heading cells found).", len(table_targets))
        for title_norm, content_tc in table_targets:
            if title_norm not in content_by_title:
                logger.warning(
                    "[Assembly] No corrected content for table heading '%s'. "
                    "Leaving cell intact.", title_norm
                )
                continue
            section = content_by_title[title_norm]
            content_lines = section.content.splitlines() or [""]
            _fill_tc_elem(content_tc, content_lines)
            sections_injected += 1
            logger.debug("[Assembly] Injected content into table cell for '%s'.", title_norm)

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))

    logger.info(
        "[Assembly] DOCX assembled | %d sections injected | saved to '%s'",
        sections_injected, out_path.name,
    )
    return str(out_path.resolve())

