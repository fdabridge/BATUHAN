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
from assembly.column_semantics import (
    ColumnSemanticMap, build_column_semantic_map, extract_table_col,
)

logger = logging.getLogger(__name__)
settings = get_settings()

_WNS  = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W14NS = "http://schemas.microsoft.com/office/word/2010/wordml"

# Regex matching template editorial-instruction text that must never appear in output.
# Catches food-safety boilerplate, generic placeholders, and reviewer/approver name stubs.
# IMPORTANT: Keep patterns specific — do NOT use broad patterns like bare "DELETE" or
# "NOT APPLICABLE" that would match legitimate audit-objectives or findings text.
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

# Regex that positively identifies cells containing LEGITIMATE audit content.
# A cell matching this pattern is PROTECTED from being cleared by
# strip_template_instruction_cells even if it also contains an instruction fragment.
# Covers: numbered audit objectives (a) to determine…), scope statements, findings text.
_AUDIT_CONTENT_RE = re.compile(
    r"\ba\)\s+to\s+(determine|evaluate|assess|examine|verify|review|confirm|establish)"
    r"|\baudit\s+objective"
    r"|\bthe\s+objective[s]?\s+of\s+this\s+audit"
    r"|\bto\s+determine\s+(the\s+)?(conformity|compliance|effectiveness)"
    r"|\bscope\s+of\s+(the\s+)?audit",
    re.IGNORECASE,
)

# Tick symbols that signal "check this checkbox cell"
_TICK_SYMBOLS = {"√", "☑", "✓", "✔", "x", "X"}

# ---------------------------------------------------------------------------
# Chunking thresholds for large-table assembly
# ---------------------------------------------------------------------------
# Tables with more empty cells than this get their own Claude call instead of
# being bundled with other small tables.
_LARGE_TABLE_THRESHOLD = 40
# When a single table's empty cells exceed this further, it is split into
# row-range sub-chunks so no single call exceeds the token limit.
_ROW_CHUNK_SIZE = 35

# Column-type detection for auto-tick post-processing
# Legacy regex fallback — used when semantic map has no entry for a column
_CONCLUSION_COL_RE = re.compile(r"conclusion|result|\u2713|tick|\bnc\b|\bobs\b", re.IGNORECASE)
_FINDINGS_COL_RE   = re.compile(r"finding|observation|remark",                re.IGNORECASE)


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

    Handles three forms — detection and type are logged at DEBUG level:
      1. Modern SDT content-control checkbox  (w14:checkbox inside w:sdtPr).
      2. Legacy form-field checkbox           (w:checkBox inside w:fldChar / w:ffData).
      3. Unicode checkbox character           (☐ / □ / ▢ in a w:t element).
         The character is replaced in-place preserving all run/font formatting.

    Returns True if a checkbox was found and ticked; False if the cell
    contains no checkbox control (caller should fall back to text fill).
    """
    # --- Type-detection probe: log what we find before acting ---
    has_sdt_checkbox = any(
        sdt.find(_wtag("sdtPr")) is not None
        and sdt.find(_wtag("sdtPr")).find(_w14tag("checkbox")) is not None
        for sdt in tc.iter(_wtag("sdt"))
    )
    has_legacy_checkbox = any(
        fldChar.find(_wtag("ffData")) is not None
        and fldChar.find(_wtag("ffData")).find(_wtag("checkBox")) is not None
        for fldChar in tc.iter(_wtag("fldChar"))
    )
    unicode_checkbox_chars = {"☐", "□", "▢", "\u2610", "\u25a1", "\u25a2"}
    cell_t_texts = [t.text or "" for t in tc.iter(_wtag("t"))]
    has_unicode_checkbox = any(
        any(ch in txt for ch in unicode_checkbox_chars)
        for txt in cell_t_texts
    )

    if has_sdt_checkbox:
        logger.debug("[LLM Mapper] Checkbox type detected: MODERN SDT content-control.")
    elif has_legacy_checkbox:
        logger.debug("[LLM Mapper] Checkbox type detected: LEGACY form-field (fldChar).")
    elif has_unicode_checkbox:
        logger.debug("[LLM Mapper] Checkbox type detected: UNICODE character (☐/□).")
    else:
        logger.debug("[LLM Mapper] No checkbox control found in cell — will use text fill fallback.")

    # --- Branch 1: Modern SDT checkbox ---
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

    # --- Branch 2: Legacy form-field checkbox (w:fldChar / w:ffData / w:checkBox) ---
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

    # --- Branch 3: Unicode checkbox character in w:t text ---
    # Replace ☐/□/▢ with ☑ in-place, preserving the run's font and formatting.
    replaced = False
    for t_elem in tc.iter(_wtag("t")):
        if t_elem.text and any(ch in t_elem.text for ch in unicode_checkbox_chars):
            for ch in unicode_checkbox_chars:
                t_elem.text = t_elem.text.replace(ch, "☑")
            replaced = True
    if replaced:
        logger.debug("[LLM Mapper] Replaced Unicode checkbox character with ☑ in cell.")
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
                if not cell_text:
                    continue
                if not _INSTRUCTION_CELL_RE.search(cell_text):
                    continue
                # PROTECT cells that contain legitimate audit content (e.g. audit
                # objectives a/b/c/d) even if they also contain an instruction fragment.
                if _AUDIT_CONTENT_RE.search(cell_text):
                    logger.debug(
                        "[LLM Mapper] Skipping protected audit-content cell: %r",
                        cell_text[:80],
                    )
                    continue
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

def _build_table_structure_lines(
    tbl,
    tbl_num: int,
    selected_values: set[str],
    row_start: int = 1,
    row_end: int | None = None,
) -> tuple[list[str], int]:
    """
    Build coordinate-tagged structure lines for ONE table (or a row-range slice).

    Returns (lines, empty_count).
      • lines        — list of strings ready for "\n".join(); ends with a blank string.
      • empty_count  — number of [EMPTY] cells in the requested row range.

    row_start / row_end are 1-based inclusive; row_end=None means the last row.
    The returned lines do NOT include the global header block — callers
    must prepend that before passing the text to Claude.
    """
    belongs_to = _tbl_belongs_to_standard(tbl)
    is_other = belongs_to is not None and belongs_to not in selected_values
    label = f"TABLE {tbl_num}"
    if row_end is not None:
        label += f" (rows {row_start}–{row_end})"
    if is_other:
        label += f" [NON-SELECTED STANDARD — {_STANDARD_FULL_NAMES.get(belongs_to, belongs_to)}]"
    elif belongs_to:
        label += f" [SELECTED STANDARD — {_STANDARD_FULL_NAMES.get(belongs_to, belongs_to)}]"
    lines = [label]

    rows = tbl.findall(_wtag("tr"))
    all_rows_tcs: list[list] = [tr.findall(_wtag("tc")) for tr in rows]
    total_rows = len(rows)
    effective_end = min(row_end if row_end is not None else total_rows, total_rows)

    empty_count = 0
    for row_idx in range(row_start, effective_end + 1):
        tcs = all_rows_tcs[row_idx - 1]
        non_empty_texts = [_get_cell_text(tc) for tc in tcs]
        distinct_non_empty = sum(1 for t in non_empty_texts if t)
        is_col_header_row = distinct_non_empty >= 2

        for col_idx, tc in enumerate(tcs, 1):
            cell_text = _get_cell_text(tc)
            coord = f"T{tbl_num}_R{row_idx}_C{col_idx}"

            if cell_text and _INSTRUCTION_CELL_RE.search(cell_text) and not _AUDIT_CONTENT_RE.search(cell_text):
                display = "[TEMPLATE INSTRUCTION — DO NOT OUTPUT]"
            elif cell_text:
                is_label = is_col_header_row
                if not is_label and col_idx < len(tcs):
                    # label→value pattern: next sibling cell is empty
                    if not _get_cell_text(tcs[col_idx]):
                        is_label = True
                display = f"{cell_text[:200]} [LABEL — DO NOT MODIFY]" if is_label else cell_text[:300]
            else:
                display = "[EMPTY]"
                empty_count += 1
            lines.append(f"  {coord}: {display}")
    lines.append("")
    return lines, empty_count


def template_to_structure_text(template_path: str, selected_standards: list[ISOStandard]) -> str:
    """
    Convert a .docx template's table structure to a coordinate-tagged text
    representation suitable for inclusion in an LLM prompt.

    Each cell is labelled T<table>_R<row>_C<col> (all 1-based).
    Tables belonging to non-selected standards are annotated so Claude
    knows to write "Not applicable" messages for them.
    For integrated audits, ALL selected standards are treated as active.
    """
    doc = Document(template_path)
    body = doc.element.body
    selected_values = {s.value for s in selected_standards}
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
        tbl_lines, _ = _build_table_structure_lines(tbl, tbl_num, selected_values)
        lines.extend(tbl_lines)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Chunked call planner
# ---------------------------------------------------------------------------

_STRUCT_HEADER = (
    "DOCUMENT TEMPLATE STRUCTURE\n"
    + "=" * 50 + "\n"
    + "Cell coordinates: T<table>_R<row>_C<col>  (all 1-based)\n"
    + "Empty content cells are shown as [EMPTY] — these need to be filled.\n\n"
)


def _plan_call_chunks(
    template_path: str,
    selected_standards: list[ISOStandard],
) -> list[dict]:
    """
    Analyse the template and group tables into Claude call chunks so that
    no single call is overwhelmed by too many empty cells.

    Rules
    -----
    • Tables with ≤ _LARGE_TABLE_THRESHOLD empty cells are buffered together.
    • Tables with > _LARGE_TABLE_THRESHOLD empty cells flush the buffer and
      get their own chunk.
    • Tables with > _LARGE_TABLE_THRESHOLD * 2 empty cells are further split
      into row-range sub-chunks of _ROW_CHUNK_SIZE rows each; the first sub-
      chunk starts at row 1 (includes the header row naturally), subsequent
      sub-chunks repeat row 1 as context.

    Returns list of dicts:
        {"label": str, "structure_text": str, "empty_count": int}
    """
    doc = Document(template_path)
    body = doc.element.body
    selected_values = {s.value for s in selected_standards}

    chunks: list[dict] = []
    buf_lines: list[str] = []
    buf_empty = 0

    def _flush_buffer(label: str = "general_tables") -> None:
        nonlocal buf_lines, buf_empty
        if buf_lines:
            chunks.append({
                "label": label,
                "structure_text": _STRUCT_HEADER + "\n".join(buf_lines),
                "empty_count": buf_empty,
            })
        buf_lines.clear()
        buf_empty = 0

    tbl_num = 0
    for tbl in body.findall(_wtag("tbl")):
        tbl_num += 1
        all_lines, total_empty = _build_table_structure_lines(tbl, tbl_num, selected_values)

        if total_empty <= _LARGE_TABLE_THRESHOLD:
            buf_lines.extend(all_lines)
            buf_empty += total_empty
            continue

        # Large table — flush the accumulated small-table buffer first
        _flush_buffer()

        rows = tbl.findall(_wtag("tr"))
        total_rows = len(rows)

        if total_empty <= _LARGE_TABLE_THRESHOLD * 2:
            # Medium-large: give it its own chunk, no row splitting needed
            chunks.append({
                "label": f"T{tbl_num}",
                "structure_text": _STRUCT_HEADER + "\n".join(all_lines),
                "empty_count": total_empty,
            })
            continue

        # Very large (e.g. Annex A with 90+ controls): split into row-range sub-chunks.
        # The first sub-chunk starts at row 1 so the column header row is included.
        # Subsequent sub-chunks prepend the header row again for Claude's context.
        hdr_lines, _ = _build_table_structure_lines(tbl, tbl_num, selected_values, 1, 1)
        chunk_start = 1
        while chunk_start <= total_rows:
            chunk_end = min(chunk_start + _ROW_CHUNK_SIZE - 1, total_rows)
            c_lines, c_empty = _build_table_structure_lines(
                tbl, tbl_num, selected_values, chunk_start, chunk_end,
            )
            if chunk_start > 1 and c_empty > 0:
                # Repeat header row so Claude knows column layout in every sub-chunk
                c_lines = (
                    hdr_lines[:-1]
                    + [f"  ... (continuing — rows {chunk_start}–{chunk_end}) ..."]
                    + c_lines
                )
            if c_empty > 0:
                chunks.append({
                    "label": f"T{tbl_num}_rows{chunk_start}-{chunk_end}",
                    "structure_text": _STRUCT_HEADER + "\n".join(c_lines),
                    "empty_count": c_empty,
                })
            chunk_start = chunk_end + 1

    _flush_buffer("general_tables_tail")
    return chunks


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
    selected_standards: list[ISOStandard],
    org_info: dict | None = None,
    language=None,
) -> str:
    from pipeline.step_b.context_builder import get_language_instruction

    template = _load_assembly_prompt()
    selected_values = {s.value for s in selected_standards}
    non_applicable_lines = [
        f"  - {std}: {_STANDARD_FULL_NAMES.get(std, std)}"
        for std in _STANDARD_FULL_NAMES
        if std not in selected_values
    ]
    selected_full = " + ".join(
        f"{s.value} — {_STANDARD_FULL_NAMES.get(s.value, s.value)}"
        for s in selected_standards
    )
    # Build the org_info block injected into the prompt
    if org_info and any(
        org_info.get(k) for k in ("name", "address", "phone", "scope_en", "scope_tr")
    ):
        org_lines = ["Use these submitted values verbatim — they override anything in the template:"]
        if org_info.get("name"):
            org_lines.append(f"  Organisation / Auditee Name: {org_info['name']}")
        if org_info.get("address"):
            org_lines.append(f"  Address / Site: {org_info['address']}")
        if org_info.get("phone"):
            org_lines.append(f"  Phone: {org_info['phone']}")
        if org_info.get("scope_en"):
            org_lines.append(f"  Certification Scope (English): {org_info['scope_en']}")
        if org_info.get("scope_tr"):
            org_lines.append(f"  Certification Scope (Turkish): {org_info['scope_tr']}")
        org_block = "\n".join(org_lines)
    else:
        org_block = "(No explicit organisation details submitted — infer from report content.)"

    lang_instruction = get_language_instruction(language) if language else ""

    return (
        template
        .replace("{selected_standard}", selected_full)
        .replace("{non_applicable_standards}", "\n".join(non_applicable_lines))
        .replace("{org_info}", org_block)
        .replace("{language_instruction}", lang_instruction)
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
# Auto-tick helper — post-fills Conclusion cells when Claude missed them
# ---------------------------------------------------------------------------

def _auto_tick_conclusion_cells(
    body,
    mapping: dict[str, str],
    semantic_map: "ColumnSemanticMap | None" = None,
) -> int:
    """
    For each table, detect the Findings column and the Conclusion/Result column
    from the header row, then add √ to any Conclusion cell that is:
      • empty in the template, AND
      • not already assigned by Claude in *mapping*, AND
      • in the same row as a Findings cell that *is* in the mapping.

    Uses semantic_map for column-role detection when available;
    falls back to _CONCLUSION_COL_RE / _FINDINGS_COL_RE otherwise.
    Modifies *mapping* in-place.  Returns the count of ticks added.
    """

    def _is_conclusion_col(header_text: str, tbl_num: int, col_num: int) -> bool:
        if semantic_map and semantic_map.table_col_roles:
            role = semantic_map.get_role(tbl_num, col_num)
            if role != "other":
                return role == "conclusion"
        # Fallback to regex
        return bool(_CONCLUSION_COL_RE.search(header_text))

    def _is_findings_col(header_text: str, tbl_num: int, col_num: int) -> bool:
        if semantic_map and semantic_map.table_col_roles:
            role = semantic_map.get_role(tbl_num, col_num)
            if role != "other":
                return role == "findings"
        # Fallback to regex
        return bool(_FINDINGS_COL_RE.search(header_text))

    added = 0
    tbl_num = 0
    for tbl in body.findall(_wtag("tbl")):
        tbl_num += 1
        rows = tbl.findall(_wtag("tr"))
        if not rows:
            continue

        # Scan the first 3 rows to find the column-header row
        findings_col: int | None = None
        conclusion_col: int | None = None
        header_row_idx = 0

        for ri, tr in enumerate(rows[:3], 1):
            tcs = tr.findall(_wtag("tc"))
            non_empty = [(ci + 1, _get_cell_text(tc)) for ci, tc in enumerate(tcs) if _get_cell_text(tc)]
            if len(non_empty) < 2:
                continue
            for col_idx, col_text in non_empty:
                if _is_findings_col(col_text, tbl_num, col_idx):
                    findings_col = col_idx
                if _is_conclusion_col(col_text, tbl_num, col_idx):
                    conclusion_col = col_idx
            if findings_col and conclusion_col:
                header_row_idx = ri
                break

        if not findings_col or not conclusion_col:
            continue  # table has no Findings/Conclusion column pair

        # Walk data rows after the header
        for ri, tr in enumerate(rows, 1):
            if ri <= header_row_idx:
                continue
            tcs = tr.findall(_wtag("tc"))
            f_coord = f"T{tbl_num}_R{ri}_C{findings_col}"
            c_coord = f"T{tbl_num}_R{ri}_C{conclusion_col}"

            if f_coord in mapping and c_coord not in mapping:
                # Only auto-tick if the template cell is actually empty
                if conclusion_col <= len(tcs) and not _get_cell_text(tcs[conclusion_col - 1]):
                    mapping[c_coord] = "√"
                    added += 1

    logger.info("[LLM Mapper] _auto_tick_conclusion_cells: %d ticks auto-added.", added)
    return added


# ---------------------------------------------------------------------------
# Cell filler
# ---------------------------------------------------------------------------

def apply_cell_mapping(
    body,
    mapping: dict[str, str],
    semantic_map: "ColumnSemanticMap | None" = None,
) -> int:
    """
    Apply coordinate→content mapping to the document body XML.

    First runs _auto_tick_conclusion_cells to guarantee that every row with
    a Findings entry also gets a Conclusion tick (in case Claude omitted it).
    Then builds an index of all table cells by their T_R_C coordinate and
    fills matched cells.  Returns the total number of cells modified.

    semantic_map is forwarded to _auto_tick_conclusion_cells for improved
    column-role detection (falls back to regex when None or empty).
    """
    # Post-process: auto-fill √ in Conclusion cells adjacent to filled Findings cells
    _auto_tick_conclusion_cells(body, mapping, semantic_map=semantic_map)

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
    selected_standards: list[ISOStandard],
    job_id: str | None = None,
    org_info: dict | None = None,
    language=None,
    semantic_map: "ColumnSemanticMap | None" = None,
) -> dict[str, str]:
    """
    Full LLM-guided mapping flow using chunked Claude calls:
      1. Plan chunks — group tables by empty-cell count to avoid token-limit
         truncation.  Large tables (e.g. ISO 27001 Annex A) are automatically
         split into row-range sub-chunks of _ROW_CHUNK_SIZE rows each.
      2. For each active chunk: build prompt → call Claude → parse response.
      3. Merge all partial mappings into one {coordinate: content} dict.

    Chunks with zero empty cells are skipped.
    Intermediate artifacts are saved to Redis when job_id is provided.
    Raises ValueError if no mappings are parsed from any chunk.
    semantic_map is stored for use by apply_cell_mapping / _auto_tick_conclusion_cells.
    """
    chunks = _plan_call_chunks(template_path, selected_standards)
    active_chunks = [c for c in chunks if c["empty_count"] > 0]

    if not active_chunks:
        logger.warning("[LLM Mapper] No chunks with empty cells found | job=%s", job_id)
        return {}

    report_text = _format_report_sections(validated_report)
    all_mappings: dict[str, str] = {}

    for idx, chunk in enumerate(active_chunks, 1):
        logger.info(
            "[LLM Mapper] Chunk %d/%d label=%s empty=%d | job=%s",
            idx, len(active_chunks), chunk["label"], chunk["empty_count"], job_id,
        )
        prompt = _build_prompt(
            chunk["structure_text"],
            report_text,
            selected_standards,
            org_info=org_info,
            language=language,
        )
        if job_id:
            from storage.file_store import save_text_artifact
            save_text_artifact(
                job_id,
                f"assembly_template_structure_chunk{idx}.txt",
                chunk["structure_text"],
            )

        raw_response = _call_claude(prompt)

        if job_id:
            from storage.file_store import save_text_artifact
            save_text_artifact(
                job_id,
                f"assembly_cell_mapping_raw_chunk{idx}.txt",
                raw_response,
            )

        chunk_mapping = parse_cell_mapping(raw_response)
        logger.info("[LLM Mapper] Chunk %d → %d mappings.", idx, len(chunk_mapping))
        all_mappings.update(chunk_mapping)

    if not all_mappings:
        raise ValueError(
            "[LLM Mapper] No cell mappings parsed from any assembly chunk. "
            "Check assembly_cell_mapping_raw_chunk*.txt artifacts for raw output."
        )
    return all_mappings
