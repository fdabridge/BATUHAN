"""
BATUHAN — Coverage Validator
Post-assembly check: verifies all mandatory clauses have filled Findings cells.
Fires targeted single-cell AI retries for any that are empty.
"""

from __future__ import annotations
import re
import logging

from ai.openai_client import OpenAIClient
from schemas.models import ScopeAnalysisResult, normalize_iso_standard

logger = logging.getLogger(__name__)

# Regex to find clause IDs in template structure lines
_CLAUSE_ID_RE = re.compile(
    r'\b([4-9]|10)\.\d+(\.\d+)?'   # main clauses: 4.1, 6.1.2, 10.2 etc
    r'|A\.\d+\.\d+'                  # Annex A: A.5.1, A.8.34 etc
)


def validate_and_repair_coverage(
    cell_mapping: dict,
    template_structure_text: str,
    scope_analysis: "ScopeAnalysisResult | None",
    report_content: str,
    client: OpenAIClient,
    model: str,
    max_tokens: int,
    temperature: float,
    selected_standards: list,
) -> tuple[dict, list]:
    """
    Post-assembly validator. Checks that all mandatory clauses have filled
    Findings cells. Fires targeted single-cell retries for any that are empty.
    Returns (updated_cell_mapping, coverage_report_lines).
    """
    coverage_report = []

    if not scope_analysis:
        coverage_report.append("No scope analysis available — coverage validation skipped.")
        return cell_mapping, coverage_report

    # Clause numbers repeat across management-system standards.  They must stay
    # paired with their owning standard; treating every "4.1" as one global item
    # previously copied QMS evidence into EMS and OHSMS tables.
    mandatory_pairs: set[tuple[str, str]] = set()
    selected_codes = {
        normalized.value
        for value in selected_standards
        if (normalized := normalize_iso_standard(value)) is not None
    }
    for raw_standard, std_result in scope_analysis.standards.items():
        normalized = normalize_iso_standard(raw_standard)
        if normalized is None:
            logger.warning("Coverage validator ignored unknown standard key %r.", raw_standard)
            continue
        standard_code = normalized.value
        if selected_codes and standard_code not in selected_codes:
            continue
        for cid in std_result.applicable_clause_ids:
            mandatory_pairs.add((standard_code, cid.upper()))

    if not mandatory_pairs:
        coverage_report.append("No mandatory clause IDs found — coverage validation skipped.")
        return cell_mapping, coverage_report

    # Parse template structure to map (standard, clause) → empty Findings cells.
    clause_to_empty_coords = _map_clauses_to_empty_coords(
        template_structure_text,
        cell_mapping,
        selected_standards=selected_codes,
    )

    # Find mandatory clauses with no filled cells
    uncovered = []
    for standard_code, cid in sorted(mandatory_pairs):
        coords = clause_to_empty_coords.get((standard_code, cid), [])
        if coords:
            uncovered.append((standard_code, cid, coords))

    coverage_report.append(
        f"Coverage check: {len(mandatory_pairs)} standard-specific mandatory clauses, "
        f"{len(uncovered)} have empty Findings cells."
    )

    if not uncovered:
        coverage_report.append("All mandatory clauses covered. No repair needed.")
        return cell_mapping, coverage_report

    # Fire targeted retry for each uncovered clause
    updated_mapping = dict(cell_mapping)
    repaired = 0

    for standard_code, cid, coords in uncovered:
        try:
            filled = _repair_clause_cells(
                standard_code=standard_code,
                clause_id=cid,
                coords=coords,
                report_content=report_content,
                client=client,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                selected_standards=[standard_code],
            )
            for coord, content in filled.items():
                if content.strip():
                    updated_mapping[coord] = content
                    repaired += 1
            coverage_report.append(
                f"  Repaired [{standard_code} {cid}]: filled {len(filled)} cell(s)."
            )
        except Exception as e:
            coverage_report.append(f"  Repair FAILED [{standard_code} {cid}]: {e}")
            logger.warning(
                "Coverage repair failed for %s clause %s: %s",
                standard_code,
                cid,
                e,
            )

    coverage_report.append(
        f"Coverage repair complete. {repaired} cells filled across {len(uncovered)} clauses."
    )

    remaining = []
    for standard_code, cid, coords in uncovered:
        still_empty = [
            coord for coord in coords
            if not str(updated_mapping.get(coord, "")).strip()
        ]
        if still_empty:
            remaining.append((standard_code, cid, still_empty))

    if remaining:
        coverage_report.append(
            f"Coverage repair incomplete: {len(remaining)} mandatory clause(s) still have empty cells."
        )
        for standard_code, cid, coords in remaining:
            coverage_report.append(
                f"  Still empty [{standard_code} {cid}]: {', '.join(coords)}"
            )
    else:
        coverage_report.append("Coverage repair verified: all targeted mandatory clause cells are filled.")

    return updated_mapping, coverage_report


def _map_clauses_to_empty_coords(
    template_structure_text: str,
    cell_mapping: dict,
    selected_standards: set[str] | None = None,
) -> dict:
    """
    Map each (standard, clause) to its empty Findings-column coordinate(s).

    Conclusion cells are deliberately excluded.  The assembly layer derives their
    compact result token after a finding is added.
    """
    selected_standards = selected_standards or set()
    table_standards: dict[int, str] = {}
    rows: dict[tuple[int, int], list[tuple[int, str, str]]] = {}

    current_table: int | None = None
    table_re = re.compile(r"^TABLE\s+(\d+)(.*)$")
    cell_re = re.compile(r"^\s*T(\d+)_R(\d+)_C(\d+):\s*(.*)$")
    for line in template_structure_text.splitlines():
        table_match = table_re.match(line)
        if table_match:
            current_table = int(table_match.group(1))
            code_match = re.search(r"\[STANDARD_CODE=([A-Z0-9]+)\]", table_match.group(2))
            if code_match:
                table_standards[current_table] = code_match.group(1)
            elif len(selected_standards) == 1:
                table_standards[current_table] = next(iter(selected_standards))
            continue
        cell_match = cell_re.match(line)
        if not cell_match:
            continue
        table_num, row_num, col_num = map(int, cell_match.group(1, 2, 3))
        coord = f"T{table_num}_R{row_num}_C{col_num}"
        rows.setdefault((table_num, row_num), []).append(
            (col_num, coord, cell_match.group(4))
        )

    findings_columns: dict[int, int] = {}
    for (table_num, _row_num), cells in rows.items():
        for col_num, _coord, text in cells:
            normalized = re.sub(r"\s+", " ", text).casefold()
            if "findings" in normalized or "audit evidence" in normalized:
                findings_columns.setdefault(table_num, col_num)

    clause_to_coords: dict[tuple[str, str], list[str]] = {}
    for (table_num, _row_num), cells in rows.items():
        standard_code = table_standards.get(table_num)
        findings_col = findings_columns.get(table_num)
        if standard_code is None or findings_col is None:
            continue
        clause_ids: set[str] = set()
        finding_coord: str | None = None
        finding_text = ""
        for col_num, coord, text in cells:
            if col_num == findings_col:
                finding_coord = coord
                finding_text = text
            else:
                clause_ids.update(match.group(0).upper() for match in _CLAUSE_ID_RE.finditer(text))
        if (
            not clause_ids
            or finding_coord is None
            or "[EMPTY]" not in finding_text
            or finding_coord in cell_mapping
        ):
            continue
        for clause_id in clause_ids:
            clause_to_coords.setdefault((standard_code, clause_id), []).append(finding_coord)

    return clause_to_coords


def _repair_clause_cells(
    standard_code: str,
    clause_id: str,
    coords: list,
    report_content: str,
    client: OpenAIClient,
    model: str,
    max_tokens: int,
    temperature: float,
    selected_standards: list,
) -> dict:
    """
    Targeted single-clause AI call. Returns {coord: content} for the given coords.
    """
    coords_list = "\n".join([f"CELL: {c}" for c in coords])
    standards_str = ", ".join(selected_standards)

    prompt = f"""You are filling specific empty cells in an ISO audit report table.

TARGET STANDARD: {standard_code}
SELECTED STANDARD(S): {standards_str}
CLAUSE: {clause_id}

The following table cells are empty and must be filled with audit findings \
for clause {clause_id}. Use the report content below as your evidence source.

CELLS TO FILL:
{coords_list}

REPORT CONTENT (use this as your evidence source):
{report_content[:3000]}

Respond ONLY in this format for each cell. No prose outside this format:

CELL: <coordinate>
CONTENT:
<your findings text for clause {clause_id}>
END_CELL

Rules:
- Write substantive audit findings, not placeholders
- Use evidence for {standard_code} only; do not reuse a finding labelled for another standard
- Every supplied coordinate is a Findings cell, never a Conclusion/Result cell
- Never leave CONTENT empty
"""

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = response.content[0].text.strip()

    from assembly.llm_mapper import parse_cell_mapping
    return parse_cell_mapping(raw)


def generate_coverage_report_text(coverage_report: list) -> str:
    return "\n".join(coverage_report)
