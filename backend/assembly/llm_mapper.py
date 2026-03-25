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

_WNS  = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W14NS = "http://schemas.microsoft.com/office/word/2010/wordml"

# Regex matching template editorial-instruction text that must never appear in output.
# Catches food-safety boilerplate, generic placeholders, and reviewer/approver name stubs.
_INSTRUCTION_CELL_RE = re.compile(
    r"THESE TARGETS WILL BE USED FOR FOOD"
    r"|IF NO FOOD YOU CAN DELETE"
    r"|DELETE IF NOT APPLICABLE"
    r"|INSERT TEXT HERE"
    r"|\[Name of reviewer[^\]]*\]"
    r"|\[Name of approver[^\]]*\]"
    r"|\[Insert[^\]]+\]"
    r"|\[ADD[^\]]+\]"
    r"|\[YOUR[^\]]+\]",
    re.IGNORECASE,
)

# Tick symbols that signal "check this checkbox cell"
_TICK_SYMBOLS = {"√", "☑", "✓", "✔", "x", "X"}


def _wtag(name: str) -> str:
    return f"{{{_WNS}}}{name}"


def _w14tag(name: str) -> str:
    return f"{{{_W14NS}}}{name}"


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
# Checkbox helpers
# ---------------------------------------------------------------------------

def _tick_checkbox_cell(tc) -> bool:
    """
    Attempt to tick a Word checkbox control inside a table cell.

    Handles two forms:
      1. Modern SDT checkbox  (w14:checkbox inside w:sdtPr).
      2. Legacy form-field    (w:checkBox inside w:fldChar / w:ffData).

    Returns True if a checkbox was found and ticked; False if the cell
    contains no checkbox control (caller should fall back to text fill).
    """
    # --- Modern SDT checkbox ---
    for sdt in tc.iter(_wtag("sdt")):
        sdtPr = sdt.find(_wtag("sdtPr"))
        if sdtPr is None:
            continue
        checkbox_elem = sdtPr.find(_w14tag("checkbox"))
        if checkbox_elem is None:
            continue
        # Set w14:checked val="1"
        checked_elem = checkbox_elem.find(_w14tag("checked"))
        if checked_elem is None:
            checked_elem = etree.SubElement(checkbox_elem, _w14tag("checked"))
        checked_elem.set(_w14tag("val"), "1")
        # Update display character in sdtContent
        sdtContent = sdt.find(_wtag("sdtContent"))
        if sdtContent is not None:
            for t in sdtContent.iter(_wtag("t")):
                t.text = "☑"
                break
        logger.debug("[LLM Mapper] Ticked modern SDT checkbox in cell.")
        return True

    # --- Legacy form-field checkbox (w:fldChar / w:ffData / w:checkBox) ---
    for fldChar in tc.iter(_wtag("fldChar")):
        ffData = fldChar.find(_wtag("ffData"))
        if ffData is None:
            continue
        checkBox = ffData.find(_wtag("checkBox"))
        if checkBox is None:
            continue
        # Remove old default/checked children and set checked=1
        for old in list(checkBox):
            checkBox.remove(old)
        checked_elem = etree.SubElement(checkBox, _wtag("checked"))
        checked_elem.set(_wtag("val"), "1")
        logger.debug("[LLM Mapper] Ticked legacy fldChar checkbox in cell.")
        return True

    return False


# ---------------------------------------------------------------------------
# Post-assembly instruction strip
# ---------------------------------------------------------------------------

def strip_template_instruction_cells(body) -> int:
    """
    Walk every table cell in the document body and clear any whose text
    matches _INSTRUCTION_CELL_RE (template editorial instructions / food
    boilerplate / placeholder stubs).

    Called after apply_cell_mapping as a final safety pass — guarantees that
    strings like "THESE TARGETS WILL BE USED FOR FOOD. IF NO FOOD YOU CAN
    DELETE." can never appear in the saved output regardless of what the LLM
    returned.  Returns the number of cells cleared.
    """
    cleared = 0
    for tbl in body.findall(_wtag("tbl")):
        for tr in tbl.findall(_wtag("tr")):
            for tc in tr.findall(_wtag("tc")):
                cell_text = _get_cell_text(tc)
                if cell_text and _INSTRUCTION_CELL_RE.search(cell_text):
                    for p in list(tc.findall(_wtag("p"))):
                        tc.remove(p)
                    tc.append(etree.Element(_wtag("p")))
                    cleared += 1
                    logger.debug(
                        "[LLM Mapper] Cleared instruction cell: %r", cell_text[:80]
                    )
    logger.info("[LLM Mapper] strip_template_instruction_cells: %d cells cleared.", cleared)
    return cleared


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
                # Mask editorial instructions so Claude never outputs them.
                if cell_text and _INSTRUCTION_CELL_RE.search(cell_text):
                    display = "[TEMPLATE INSTRUCTION — DO NOT OUTPUT]"
                else:
                    display = cell_text[:300] if cell_text else "[EMPTY]"
                lines.append(f"  {coord}: {display}")
        lines.append("")

    return "\n".join(lines)


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
    org_info: dict | None = None,
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
    # Build the org_info block injected into the prompt
    if org_info and any(org_info.get(k) for k in ("name", "address", "phone")):
        org_lines = ["Use these submitted values verbatim — they override anything in the template:"]
        if org_info.get("name"):
            org_lines.append(f"  Organisation / Auditee Name: {org_info['name']}")
        if org_info.get("address"):
            org_lines.append(f"  Address / Site: {org_info['address']}")
        if org_info.get("phone"):
            org_lines.append(f"  Phone: {org_info['phone']}")
        org_block = "\n".join(org_lines)
    else:
        org_block = "(No explicit organisation details submitted — infer from report content.)"

    return (
        template
        .replace("{selected_standard}", selected_full)
        .replace("{non_applicable_standards}", "\n".join(non_applicable_lines))
        .replace("{org_info}", org_block)
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
        tc = coord_index[coord]
        # If the LLM returned a tick symbol, try to activate the Word checkbox
        # control first.  Fall back to plain-text fill if no control exists.
        if content.strip() in _TICK_SYMBOLS:
            if _tick_checkbox_cell(tc):
                filled += 1
                logger.debug("[LLM Mapper] Checkbox ticked at %s.", coord)
                continue
        _fill_tc_elem(tc, content.splitlines() or [""])
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
    org_info: dict | None = None,
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

    # Guard: template_to_structure_text must always return a non-empty string.
    # If it somehow returns None or "" (e.g. template has no tables), bail early
    # with a warning rather than crashing inside _build_prompt or the Claude call.
    if not structure_text:
        logger.warning(
            "[LLM Mapper] template_to_structure_text returned empty/None for job=%s — "
            "template may have no tables. Returning empty mapping.",
            job_id,
        )
        return {}

    report_text = _format_report_sections(validated_report)

    if job_id:
        from storage.file_store import save_text_artifact
        save_text_artifact(job_id, "assembly_template_structure.txt", structure_text)

    prompt = _build_prompt(structure_text, report_text, selected_standard, org_info=org_info)
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

