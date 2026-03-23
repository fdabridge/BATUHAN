"""
BATUHAN — DOCX Assembly Engine (T23)
Inserts validated corrected section content into the original blank .docx template.

Strategy:
  1. Open the original blank template (preserves all styles, headers, footers, logos).
  2. Walk the document body XML elements directly (never via doc.paragraphs, which
     creates new wrapper objects on every access and breaks identity checks).
  3a. Heading-style templates: for each heading XML element matching a section title,
      remove subsequent non-heading body paragraphs and insert corrected content.
  3b. Table-style templates (fallback): delegate to the LLM-guided cell mapper
      (assembly/llm_mapper.py).  Claude receives the full template structure as a
      coordinate-tagged text representation and the generated report content, then
      returns a precise cell-by-cell mapping that is applied to the document XML.
  4. Preserve ALL heading/title elements exactly — never alter titles or structure.
  5. Save as a new file — never overwrite the original template.

CRITICAL RULE: Template structure is IMMUTABLE. Only content areas are replaced.
"""

from __future__ import annotations
import logging
from pathlib import Path
from lxml import etree
from docx import Document
from schemas.models import ValidatedReport, ReportSection, ISOStandard

logger = logging.getLogger(__name__)

# OOXML namespace
_WNS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

# Style IDs (w:pStyle w:val) used by Word for built-in Heading styles.
_HEADING_STYLE_IDS = {"Heading1", "Heading2", "Heading3"}


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
# Public API
# ---------------------------------------------------------------------------

def assemble_docx(
    template_path: str,
    validated_report: ValidatedReport,
    output_path: str,
    standard: ISOStandard | None = None,
    job_id: str | None = None,
) -> str:
    """
    Assemble the final report DOCX by injecting validated section content
    into the blank template.

    Supports both heading-style and table-style templates automatically:
      - Strategy 1: heading-paragraph templates (Heading 1/2/3 styles).
      - Strategy 2: table-based templates — uses LLM-guided cell mapping
        (llm_mapper) so Claude decides exactly which cell gets which content.

    Args:
        template_path:    Absolute path to the original blank .docx template.
        validated_report: Validated corrected report from Step C.
        output_path:      Where to save the completed .docx.
        standard:         The ISO standard for this job. Used by the LLM mapper
                          to skip / mark tables for non-selected standards.
        job_id:           Optional job identifier for debug artifact storage.

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
        # Strategy 2: LLM-guided table-cell mapping
        # -----------------------------------------------------------------------
        from assembly.llm_mapper import get_cell_mapping, apply_cell_mapping

        effective_standard = standard if standard is not None else next(iter(ISOStandard))
        logger.info(
            "[Assembly] No heading paragraphs found — using LLM-guided table injection | standard=%s | job=%s",
            effective_standard.value, job_id,
        )

        mapping = get_cell_mapping(
            template_path=template_path,
            validated_report=validated_report,
            selected_standard=effective_standard,
            job_id=job_id,
        )

        sections_injected = apply_cell_mapping(body, mapping)

        if sections_injected == 0:
            raise ValueError(
                "[Assembly] LLM mapper returned a non-empty mapping but no cells were "
                "found in the document. Check assembly_cell_mapping_raw.txt artifact."
            )

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))

    logger.info(
        "[Assembly] DOCX assembled | %d cells/sections injected | saved to '%s'",
        sections_injected, out_path.name,
    )
    return str(out_path.resolve())

