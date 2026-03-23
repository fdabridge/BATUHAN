"""
BATUHAN — LLM-Guided DOCX Assembly Mapper
==========================================
Converts the blank template to a coordinate-tagged text representation,
sends it (plus the generated report content) to Claude, and asks Claude
to return a cell-by-cell content mapping.  The mapping is then applied
to the open document XML — no brittle bold/caps heuristics required.

Public API
----------
template_to_structure_text(template_path, selected_standard) -> str
get_cell_mapping(template_path, validated_report, selected_standard, job_id) -> dict
apply_cell_mapping(body, mapping) -> int   (returns cells filled)
parse_cell_mapping(response) -> dict       (exposed for testing)
"""

from __future__ import annotations
import logging
import re
from pathlib import Path
from lxml import etree
from docx import Document
from config.settings import get_settings
from schemas.models import ValidatedReport, ISOStandard

logger = logging.getLogger(__name__)
settings = get_settings()

_WNS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _wtag(name: str) -> str:
    return f"{{{_WNS}}}{name}"


def _get_cell_text(tc) -> str:
    return "".join(t.text or "" for t in tc.iter(_wtag("t"))).strip()


def _make_text_para_elem(text: str):
    p = etree.Element(_wtag("p"))
    r = etree.SubElement(p, _wtag("r"))
    t = etree.SubElement(r, _wtag("t"))
    t.text = text
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    return p


def _fill_tc_elem(tc_elem, content_lines: list[str]) -> None:
    """Replace all paragraphs in a table cell with new content lines."""
    for p in list(tc_elem.findall(_wtag("p"))):
        tc_elem.remove(p)
    for line in content_lines:
        tc_elem.append(_make_text_para_elem(line))


# ---------------------------------------------------------------------------
# Standard-identification constants
# ---------------------------------------------------------------------------

_STANDARD_PATTERNS: dict[str, list] = {
    "QMS":   [re.compile(r"\bqms\b", re.IGNORECASE), re.compile(r"9001")],
    "EMS":   [re.compile(r"\bems\b", re.IGNORECASE), re.compile(r"14001")],
    "OHSMS": [re.compile(r"\bohsms\b", re.IGNORECASE), re.compile(r"45001")],
    "FSMS":  [re.compile(r"\bfsms\b", re.IGNORECASE), re.compile(r"22000")],
    "MDQMS": [re.compile(r"\bmdqms\b", re.IGNORECASE), re.compile(r"13485")],
    "ISMS":  [re.compile(r"\bisms\b", re.IGNORECASE), re.compile(r"27001")],
    "ABMS":  [re.compile(r"\babms\b", re.IGNORECASE), re.compile(r"37001")],
    "ENMS":  [re.compile(r"\benms\b", re.IGNORECASE), re.compile(r"50001")],
}

_STANDARD_FULL_NAMES: dict[str, str] = {
    "QMS":   "ISO 9001 Quality Management System",
    "EMS":   "ISO 14001 Environmental Management System",
    "OHSMS": "ISO 45001 Occupational Health & Safety Management System",
    "FSMS":  "ISO 22000 Food Safety Management System",
    "MDQMS": "ISO 13485 Medical Devices Quality Management System",
    "ISMS":  "ISO 27001 Information Security Management System",
    "ABMS":  "ISO 37001 Anti-Bribery Management System",
    "ENMS":  "ISO 50001 Energy Management System",
}


def _tbl_belongs_to_standard(tbl_elem) -> str | None:
    """Return the standard value this table belongs to, or None if neutral."""
    all_text = " ".join(t.text or "" for t in tbl_elem.iter(_wtag("t")))
    for std_value, patterns in _STANDARD_PATTERNS.items():
        for pattern in patterns:
            if pattern.search(all_text):
                return std_value
    return None


# ---------------------------------------------------------------------------
# Template → text representation
# ---------------------------------------------------------------------------

def template_to_structure_text(template_path: str, selected_standard: ISOStandard) -> str:
    """
    Convert a .docx template's table structure to a coordinate-tagged text
    representation suitable for inclusion in an LLM prompt.

    Each cell is labelled T<table>_R<row>_C<col> (all 1-based).
    Tables belonging to non-selected standards are annotated so Claude
    knows to write "Not applicable" messages for them.
    """
    doc = Document(template_path)
    body = doc.element.body

    lines = [
        "DOCUMENT TEMPLATE STRUCTURE",
        "=" * 50,
        "Cell coordinates: T<table>_R<row>_C<col>  (all 1-based)",
        "Empty content cells are shown as [EMPTY] — these need to be filled.",
        "",
    ]
    tbl_num = 0
    for tbl in body.findall(_wtag("tbl")):
        tbl_num += 1
        belongs_to = _tbl_belongs_to_standard(tbl)
        is_other = belongs_to is not None and belongs_to != selected_standard.value

        label = f"TABLE {tbl_num}"
        if is_other:
            full_name = _STANDARD_FULL_NAMES.get(belongs_to, belongs_to)
            label += f" [NON-SELECTED STANDARD — {full_name}]"
        elif belongs_to:
            label += f" [SELECTED STANDARD — {_STANDARD_FULL_NAMES.get(belongs_to, belongs_to)}]"
        lines.append(label)

        rows = tbl.findall(_wtag("tr"))
        for row_idx, tr in enumerate(rows, 1):
            tcs = tr.findall(_wtag("tc"))
            for col_idx, tc in enumerate(tcs, 1):
                cell_text = _get_cell_text(tc)
                coord = f"T{tbl_num}_R{row_idx}_C{col_idx}"
                display = cell_text[:300] if cell_text else "[EMPTY]"
                lines.append(f"  {coord}: {display}")


# ---------------------------------------------------------------------------
# Report content formatter
# ---------------------------------------------------------------------------

def _format_report_sections(validated_report: ValidatedReport) -> str:
    """Format ValidatedReport sections as plain text for the mapping prompt."""
    lines = ["GENERATED REPORT CONTENT", "=" * 50, ""]
    for s in validated_report.sections:
        lines.append(f"Section Title: {s.title}")
        lines.append("Content:")
        lines.append(s.content)
        lines.append("---")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _load_assembly_prompt() -> str:
    prompt_path = Path(settings.prompts_dir) / "prompt_assembly.txt"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Assembly prompt not found at: {prompt_path}")
    lines = [ln for ln in prompt_path.read_text(encoding="utf-8").splitlines()
             if not ln.startswith("#")]
    return "\n".join(lines).strip()


def _build_prompt(
    template_structure: str,
    report_content: str,
    selected_standard: ISOStandard,
) -> str:
    template = _load_assembly_prompt()
    non_applicable_lines = [
        f"  - {std}: {_STANDARD_FULL_NAMES.get(std, std)}"
        for std in _STANDARD_FULL_NAMES
        if std != selected_standard.value
    ]
    selected_full = (
        f"{selected_standard.value} — "
        f"{_STANDARD_FULL_NAMES.get(selected_standard.value, selected_standard.value)}"
    )
    return (
        template
        .replace("{selected_standard}", selected_full)
        .replace("{non_applicable_standards}", "\n".join(non_applicable_lines))
        .replace("{template_structure}", template_structure)
        .replace("{report_content}", report_content)
    )


# ---------------------------------------------------------------------------
# Claude API call
# ---------------------------------------------------------------------------

def _call_claude(prompt: str) -> str:
    """Send prompt to Claude and return raw text response."""
    import anthropic
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model=settings.claude_model,
        max_tokens=settings.claude_max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------

def parse_cell_mapping(response: str) -> dict[str, str]:
    """
    Parse Claude's cell-mapping response into a {coordinate: content} dict.

    Expected format for each cell assignment:

        CELL: T3_R5_C2
        CONTENT:
        [content text — may span multiple lines]
        END_CELL
    """
    mapping: dict[str, str] = {}
    pattern = re.compile(
        r"CELL:\s*(T\d+_R\d+_C\d+)\s*\nCONTENT:\s*\n(.*?)END_CELL",
        re.DOTALL | re.IGNORECASE,
    )
    for m in pattern.finditer(response):
        coord = m.group(1).strip().upper()
        content = m.group(2).strip()
        if content:
            mapping[coord] = content
    logger.info("[LLM Mapper] Parsed %d cell assignments from Claude.", len(mapping))
    return mapping


# ---------------------------------------------------------------------------
# Cell filler
# ---------------------------------------------------------------------------

def apply_cell_mapping(body, mapping: dict[str, str]) -> int:
    """
    Apply coordinate→content mapping to the document body XML.

    Builds an index of all table cells by their T_R_C coordinate, then
    fills matched cells.  Returns the number of cells modified.
    """
    coord_index: dict[str, object] = {}
    tbl_num = 0
    for tbl in body.findall(_wtag("tbl")):
        tbl_num += 1
        rows = tbl.findall(_wtag("tr"))
        for row_idx, tr in enumerate(rows, 1):
            tcs = tr.findall(_wtag("tc"))
            for col_idx, tc in enumerate(tcs, 1):
                coord_index[f"T{tbl_num}_R{row_idx}_C{col_idx}"] = tc

    filled = 0
    for coord, content in mapping.items():
        if coord not in coord_index:
            logger.warning("[LLM Mapper] Unknown coordinate %s — skipping.", coord)
            continue
        _fill_tc_elem(coord_index[coord], content.splitlines() or [""])
        filled += 1
        logger.debug("[LLM Mapper] Filled cell %s.", coord)
    return filled


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def get_cell_mapping(
    template_path: str,
    validated_report: ValidatedReport,
    selected_standard: ISOStandard,
    job_id: str | None = None,
) -> dict[str, str]:
    """
    Full LLM-guided mapping flow:
      1. Convert template to coordinate-tagged structure text.
      2. Format validated report sections as plain text.
      3. Build prompt and call Claude.
      4. Parse Claude's response into a {coordinate: content} dict.

    Intermediate artifacts (template structure, raw Claude response) are
    saved to Redis when job_id is provided — useful for debugging.

    Raises ValueError if Claude returns no parseable cell mappings.
    """
    structure_text = template_to_structure_text(template_path, selected_standard)
    report_text = _format_report_sections(validated_report)

    if job_id:
        from storage.file_store import save_text_artifact
        save_text_artifact(job_id, "assembly_template_structure.txt", structure_text)

    prompt = _build_prompt(structure_text, report_text, selected_standard)
    logger.info("[LLM Mapper] Calling Claude for cell-by-cell assembly mapping | job=%s", job_id)
    raw_response = _call_claude(prompt)

    if job_id:
        from storage.file_store import save_text_artifact
        save_text_artifact(job_id, "assembly_cell_mapping_raw.txt", raw_response)

    mapping = parse_cell_mapping(raw_response)
    if not mapping:
        raise ValueError(
            "[LLM Mapper] No cell mappings parsed from Claude's assembly response. "
            "Check assembly_cell_mapping_raw.txt artifact for raw output."
        )
    return mapping

