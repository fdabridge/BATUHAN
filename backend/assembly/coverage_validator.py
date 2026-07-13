"""
BATUHAN — Coverage Validator
Post-assembly check: verifies all mandatory clauses have filled Findings cells.
Fires targeted single-cell Claude retries for any that are empty.
"""

from __future__ import annotations
import re
import logging

from anthropic import Anthropic
from schemas.models import ScopeAnalysisResult

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
    client: Anthropic,
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

    # Build flat set of all mandatory clause IDs across all standards
    mandatory_ids = set()
    for std_result in scope_analysis.standards.values():
        for cid in std_result.applicable_clause_ids:
            mandatory_ids.add(cid.upper())

    if not mandatory_ids:
        coverage_report.append("No mandatory clause IDs found — coverage validation skipped.")
        return cell_mapping, coverage_report

    # Parse template structure to map clause IDs → coordinates of empty Findings cells
    clause_to_empty_coords = _map_clauses_to_empty_coords(
        template_structure_text, cell_mapping
    )

    # Find mandatory clauses with no filled cells
    uncovered = []
    for cid in sorted(mandatory_ids):
        coords = clause_to_empty_coords.get(cid, [])
        if coords:
            uncovered.append((cid, coords))

    coverage_report.append(
        f"Coverage check: {len(mandatory_ids)} mandatory clauses, "
        f"{len(uncovered)} have empty Findings cells."
    )

    if not uncovered:
        coverage_report.append("All mandatory clauses covered. No repair needed.")
        return cell_mapping, coverage_report

    # Fire targeted retry for each uncovered clause
    updated_mapping = dict(cell_mapping)
    repaired = 0

    for cid, coords in uncovered:
        try:
            filled = _repair_clause_cells(
                clause_id=cid,
                coords=coords,
                report_content=report_content,
                client=client,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                selected_standards=selected_standards,
            )
            for coord, content in filled.items():
                if content.strip():
                    updated_mapping[coord] = content
                    repaired += 1
            coverage_report.append(f"  Repaired [{cid}]: filled {len(filled)} cell(s).")
        except Exception as e:
            coverage_report.append(f"  Repair FAILED [{cid}]: {e}")
            logger.warning(f"Coverage repair failed for clause {cid}: {e}")

    coverage_report.append(
        f"Coverage repair complete. {repaired} cells filled across {len(uncovered)} clauses."
    )

    remaining = []
    for cid, coords in uncovered:
        still_empty = [
            coord for coord in coords
            if not str(updated_mapping.get(coord, "")).strip()
        ]
        if still_empty:
            remaining.append((cid, still_empty))

    if remaining:
        coverage_report.append(
            f"Coverage repair incomplete: {len(remaining)} mandatory clause(s) still have empty cells."
        )
        for cid, coords in remaining:
            coverage_report.append(f"  Still empty [{cid}]: {', '.join(coords)}")
    else:
        coverage_report.append("Coverage repair verified: all targeted mandatory clause cells are filled.")

    return updated_mapping, coverage_report


def _map_clauses_to_empty_coords(
    template_structure_text: str,
    cell_mapping: dict,
) -> dict:
    """
    Scans template structure lines for clause ID mentions.
    For each line containing a clause ID, finds any [EMPTY] coordinates
    in the same table row that are NOT already filled in cell_mapping.
    Returns {clause_id_upper: [coord, ...]}
    """
    clause_to_coords: dict[str, list[str]] = {}
    current_row_coords: list[str] = []
    current_row_clauses: list[str] = []
    last_row_key: str | None = None

    for line in template_structure_text.splitlines():
        coord_match = re.match(r'(T\d+_R\d+_C\d+)', line.strip())
        if not coord_match:
            continue
        coord = coord_match.group(1)

        # Determine row key (same table + row = same data row)
        row_key = "_".join(coord.split("_")[:2])  # T<n>_R<r>

        if row_key != last_row_key:
            # Flush previous row
            if current_row_clauses and current_row_coords:
                for cid in current_row_clauses:
                    if cid not in clause_to_coords:
                        clause_to_coords[cid] = []
                    clause_to_coords[cid].extend(current_row_coords)
            current_row_coords = []
            current_row_clauses = []
            last_row_key = row_key

        # Is this cell empty and unfilled?
        if "[EMPTY]" in line and coord not in cell_mapping:
            current_row_coords.append(coord)

        # Find clause IDs mentioned in this line
        for m in _CLAUSE_ID_RE.finditer(line):
            cid = m.group(0).upper()
            if cid not in current_row_clauses:
                current_row_clauses.append(cid)

    # Flush last row
    if current_row_clauses and current_row_coords:
        for cid in current_row_clauses:
            if cid not in clause_to_coords:
                clause_to_coords[cid] = []
            clause_to_coords[cid].extend(current_row_coords)

    return clause_to_coords


def _repair_clause_cells(
    clause_id: str,
    coords: list,
    report_content: str,
    client: Anthropic,
    model: str,
    max_tokens: int,
    temperature: float,
    selected_standards: list,
) -> dict:
    """
    Targeted single-clause Claude call. Returns {coord: content} for the given coords.
    """
    coords_list = "\n".join([f"CELL: {c}" for c in coords])
    standards_str = ", ".join(selected_standards)

    prompt = f"""You are filling specific empty cells in an ISO audit report table.

STANDARD(S): {standards_str}
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
- If this is a Conclusion/Result cell, write only: \u221a
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
