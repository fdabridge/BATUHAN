"""
BATUHAN — DOCX Assembly Engine (T23)
Inserts validated corrected section content into the original blank .docx template.

Strategy:
  1. Open the original blank template (preserves all styles, headers, footers, logos).
  2. Walk the document body XML elements directly (never via doc.paragraphs, which
     creates new wrapper objects on every access and breaks identity checks).
  3. For each heading XML element matching a section title, remove subsequent
     non-heading body paragraphs and insert the corrected content paragraphs.
  4. Preserve ALL heading elements exactly — never alter titles, styles or structure.
  5. Save as a new file — never overwrite the original template.

CRITICAL RULE: Template structure is IMMUTABLE. Only content paragraphs are replaced.
"""

from __future__ import annotations
import logging
from pathlib import Path
from lxml import etree
from docx import Document
from schemas.models import ValidatedReport, ReportSection

logger = logging.getLogger(__name__)

# OOXML namespace
_WNS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

# Style IDs (w:pStyle w:val) used by Word for built-in Heading styles.
# These are the XML IDs, not the display names ("Heading 1" → "Heading1").
_HEADING_STYLE_IDS = {"Heading1", "Heading2", "Heading3"}


def _wtag(name: str) -> str:
    return f"{{{_WNS}}}{name}"


def _norm(title: str) -> str:
    return title.strip().lower()


def _get_elem_text(elem) -> str:
    """Extract all text from a paragraph XML element."""
    return "".join(t.text or "" for t in elem.iter(_wtag("t"))).strip()


def _is_heading_elem(elem) -> bool:
    """Return True if the XML element is a heading paragraph."""
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


def _make_text_para_elem(text: str):
    """Create a bare w:p XML element containing the given text in a single run."""
    p = etree.Element(_wtag("p"))
    r = etree.SubElement(p, _wtag("r"))
    t = etree.SubElement(r, _wtag("t"))
    t.text = text
    # Preserve leading/trailing whitespace
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    return p


def _replace_section_content(body, heading_elem, content_lines: list[str]) -> None:
    """
    Remove all non-heading body children directly after heading_elem,
    then insert new paragraph elements for each line of content.
    Works entirely with XML element references — no python-docx wrapper objects.
    """
    current = list(body)
    idx = current.index(heading_elem)  # safe: same element object reference

    # Collect elements to remove (between this heading and the next heading / end)
    to_remove = []
    for child in current[idx + 1:]:
        if _is_heading_elem(child):
            break
        to_remove.append(child)

    for elem in to_remove:
        body.remove(elem)

    # Re-read position after removals and insert new content
    insert_after = list(body).index(heading_elem) + 1
    for line in reversed(content_lines):
        body.insert(insert_after, _make_text_para_elem(line))


def assemble_docx(
    template_path: str,
    validated_report: ValidatedReport,
    output_path: str,
) -> str:
    """
    Assemble the final report DOCX by injecting validated section content
    into the blank template.

    Args:
        template_path:    Absolute path to the original blank .docx template.
        validated_report: Validated corrected report from Step C.
        output_path:      Where to save the completed .docx.

    Returns:
        Absolute path of the saved DOCX file.

    Raises:
        ValueError: If template cannot be opened or has no headings.
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

    # Collect heading XML elements in document order (snapshot — stable references)
    heading_elems: list[tuple[object, str]] = []
    for child in list(body):
        if _is_heading_elem(child):
            text = _get_elem_text(child)
            if text:
                heading_elems.append((child, _norm(text)))

    if not heading_elems:
        raise ValueError("Template has no heading-style sections.")

    sections_injected = 0

    # Process in reverse order so earlier headings aren't affected by
    # insertion/removal of elements after later headings.
    for heading_elem, title_norm in reversed(heading_elems):
        raw_title = _get_elem_text(heading_elem)
        if title_norm not in content_by_title:
            logger.warning(
                f"[Assembly] No corrected content for heading '{raw_title}'. "
                "Leaving template placeholder intact."
            )
            continue

        section = content_by_title[title_norm]
        content_lines = section.content.splitlines() or [""]

        _replace_section_content(body, heading_elem, content_lines)
        sections_injected += 1
        logger.debug(f"[Assembly] Injected content for '{raw_title}'")

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))

    logger.info(
        f"[Assembly] DOCX assembled | {sections_injected} sections injected | "
        f"saved to '{out_path.name}'"
    )
    return str(out_path.resolve())

