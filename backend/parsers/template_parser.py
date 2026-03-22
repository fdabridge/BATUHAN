"""
BATUHAN — Blank Template Parser (T10)
Parses the uploaded .docx audit report template.
Detects all section headings in order, preserves exact titles.
Produces a TemplateMap used by Prompt B and the DOCX assembly engine.
CRITICAL: Template structure must NEVER be altered.
"""

from __future__ import annotations
import logging
from pathlib import Path
from docx import Document
from docx.oxml.ns import qn
from schemas.models import TemplateMap, TemplateSection

logger = logging.getLogger(__name__)

# Word heading styles that indicate a report section
HEADING_STYLES = {
    "Heading 1", "Heading 2", "Heading 3",
    "heading 1", "heading 2", "heading 3",
}


def _is_heading(paragraph) -> bool:
    """Return True if the paragraph uses a heading style."""
    return paragraph.style.name in HEADING_STYLES


def _get_paragraph_text(paragraph) -> str:
    """Extract full text from a paragraph including runs."""
    return paragraph.text.strip()


def _collect_placeholder(paragraphs, start_index: int) -> str:
    """
    Collect any non-heading text immediately following a heading.
    This captures placeholder text like '[Insert content here]'.
    """
    parts: list[str] = []
    i = start_index
    while i < len(paragraphs):
        p = paragraphs[i]
        if _is_heading(p):
            break
        text = _get_paragraph_text(p)
        if text:
            parts.append(text)
        i += 1
    return "\n".join(parts)


def parse_template(template_path: str) -> TemplateMap:
    """
    Parse a .docx template and return a TemplateMap with all sections in order.

    Each TemplateSection contains:
    - title: exact heading text (must be preserved)
    - original_placeholder: any existing placeholder text under the heading
    - order_index: position in the document (0-based)

    Raises ValueError if the file cannot be parsed or has no headings.
    """
    path = Path(template_path)
    if not path.exists():
        raise ValueError(f"Template file not found: {template_path}")
    if path.suffix.lower() not in (".docx", ".doc"):
        raise ValueError(f"Template must be a .docx file, got: {path.suffix}")

    try:
        doc = Document(template_path)
    except Exception as e:
        raise ValueError(f"Failed to open template: {e}")

    paragraphs = doc.paragraphs
    sections: list[TemplateSection] = []
    order_index = 0

    i = 0
    while i < len(paragraphs):
        p = paragraphs[i]
        if _is_heading(p):
            title = _get_paragraph_text(p)
            if not title:
                i += 1
                continue
            # Collect placeholder text under this heading
            placeholder = _collect_placeholder(paragraphs, i + 1)
            sections.append(TemplateSection(
                title=title,
                original_placeholder=placeholder if placeholder else None,
                order_index=order_index,
            ))
            order_index += 1
        i += 1

    if not sections:
        raise ValueError(
            "No heading-style sections found in template. "
            "Ensure the template uses Word Heading styles (Heading 1, 2, or 3)."
        )

    logger.info(f"Template parsed: {len(sections)} sections found in '{path.name}'")
    for s in sections:
        logger.debug(f"  [{s.order_index}] {s.title}")

    return TemplateMap(sections=sections, source_path=str(path.resolve()))


def format_sections_for_prompt(template_map: TemplateMap) -> str:
    """
    Format the template section list as a string for injection into Prompt B.
    Lists all section titles in order so Claude knows exactly what to fill.
    """
    lines = ["The report must contain the following sections in this exact order:\n"]
    for s in template_map.sections:
        lines.append(f"{s.order_index + 1}. {s.title}")
    return "\n".join(lines)

