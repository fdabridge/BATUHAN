"""
BATUHAN — Column Semantic Map
Classifies every column in every template table by semantic role (findings,
conclusion, clause_ref, label, other) via a single AI call.
The result is reused across all assembly chunks to guide auto-tick logic.
"""

from ai.openai_client import OpenAIClient
from dataclasses import dataclass
import json, logging, re

logger = logging.getLogger(__name__)

_VALID_ROLES = {"findings", "conclusion", "clause_ref", "label", "other"}


def _deterministic_column_roles(template_structure_text: str) -> dict[int, dict[int, str]]:
    """Infer obvious column roles from *all* template header/label cells.

    This deliberately runs before the model-based classifier.  A report template is
    the authority for its own layout; model output may fill cells, but must not be
    allowed to reinterpret an explicit ``Findings`` or ``Conclusion`` header.

    The previous implementation sent only the first 6,000 characters to the model,
    which meant the large clause tables near the end of FR.232 were never seen.  The
    deterministic pass scans the complete coordinate structure and therefore covers
    every standard table, including integrated-audit sections.
    """
    cell_re = re.compile(r"^\s*T(\d+)_R(\d+)_C(\d+):\s*(.*)$")
    scores: dict[int, dict[int, tuple[int, str]]] = {}
    parsed_cells: list[tuple[int, int, int, str, str]] = []
    non_empty_by_row: dict[tuple[int, int], int] = {}

    for line in template_structure_text.splitlines():
        match = cell_re.match(line)
        if not match:
            continue
        table_num, row_num, col_num = map(int, match.group(1, 2, 3))
        raw = match.group(4)
        text = re.sub(r"\s*\[(?:LABEL|TEMPLATE INSTRUCTION).*", "", raw, flags=re.I)
        parsed_cells.append((table_num, row_num, col_num, raw, text))
        if "[EMPTY]" not in raw and "[TEMPLATE INSTRUCTION" not in raw:
            key = (table_num, row_num)
            non_empty_by_row[key] = non_empty_by_row.get(key, 0) + 1

    for table_num, row_num, col_num, raw, text in parsed_cells:
        normalized = re.sub(r"\s+", " ", text).strip().casefold()
        role = "other"
        score = 0
        is_header_row = non_empty_by_row.get((table_num, row_num), 0) >= 2

        # Explicit column headers are stronger than generic LABEL annotations.
        if is_header_row and (
            re.search(r"\b(conclusion|result)\b", normalized) or any(
            symbol in text for symbol in ("✓", "√", "☑")
            )
        ):
            role, score = "conclusion", 100
        elif is_header_row and re.search(
            r"\b(findings?|observations?|remarks?)\b|non[- ]?conformity statement|audit evidence",
            normalized,
        ):
            role, score = "findings", 95
        elif is_header_row and re.search(
            r"\b(requirements?|controls?)\b|\bclause\s*(?:no|number)?\b|standard\s*/\s*clause",
            normalized,
        ):
            role, score = "clause_ref", 90
        elif "[LABEL" in raw.upper():
            role, score = "label", 20

        # Header roles normally appear near the top.  Keep scanning the complete
        # table, but slightly prefer earlier matches when two labels compete.
        score -= min(row_num, 15)
        current = scores.setdefault(table_num, {}).get(col_num)
        if role != "other" and (current is None or score > current[0]):
            scores[table_num][col_num] = (score, role)

    return {
        table_num: {col_num: scored_role[1] for col_num, scored_role in columns.items()}
        for table_num, columns in scores.items()
    }


@dataclass
class ColumnSemanticMap:
    """
    Stores the semantic role of each column index per table.
    Built once at template upload/job start, reused across all assembly chunks.
    """
    # table_num (int) → col_num (int) → role (str)
    # Roles: "findings", "conclusion", "clause_ref", "label", "other"
    table_col_roles: dict  # {table_num: {col_num: role}}

    def get_role(self, table_num: int, col_num: int) -> str:
        return self.table_col_roles.get(table_num, {}).get(col_num, "other")

    def is_findings(self, table_num: int, col_num: int) -> bool:
        return self.get_role(table_num, col_num) == "findings"

    def is_conclusion(self, table_num: int, col_num: int) -> bool:
        return self.get_role(table_num, col_num) == "conclusion"


def build_column_semantic_map(
    template_structure_text: str,
    client: OpenAIClient,
    model: str,
) -> ColumnSemanticMap:
    """
    Sends the template structure to the model once and asks it to classify
    every column in every table by semantic role.
    Returns a ColumnSemanticMap usable for the rest of assembly.
    """
    deterministic_roles = _deterministic_column_roles(template_structure_text)

    # Give the model a compact view of every coordinate line that looks like a
    # header/label instead of truncating the document before its clause tables.
    structure_lines = []
    for line in template_structure_text.splitlines():
        coord_match = re.match(r"\s*T\d+_R(\d+)_C\d+:", line)
        if line.startswith("TABLE ") or (
            coord_match
            and int(coord_match.group(1)) <= 8
            and (
                "[LABEL" in line
                or re.search(
                    r"finding|conclusion|result|requirement|control|clause|observation|remark",
                    line,
                    re.I,
                )
            )
        ):
            structure_lines.append(line)
    structure_excerpt = "\n".join(structure_lines)[:18000]

    prompt = f"""You are analyzing the structure of an ISO audit report Word template.
Below is the coordinate-tagged structure of the template tables.
Each line shows a cell coordinate (T<table>_R<row>_C<col>) and its content.

Your job: for every table, identify the semantic role of each column.

ROLES:
- "findings"    → column where audit findings/observations are written (main text column)
- "conclusion"  → column for tick/result (√, NC, OBS, conforming/nonconforming)
- "clause_ref"  → column that contains ISO clause numbers or references
- "label"       → column that contains row labels/headings (marked as LABEL)
- "other"       → any other column (dates, auditor names, signatures, etc.)

TEMPLATE STRUCTURE:
{structure_excerpt}

Respond ONLY with valid JSON in this exact format. No prose, no explanation:

{{
  "tables": {{
    "<table_num>": {{
      "<col_num>": "<role>",
      "<col_num>": "<role>"
    }}
  }}
}}

Where table_num and col_num are integers matching the T and C numbers in coordinates.
Include every table and every column you can identify. When unsure, use "other".
"""

    try:
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            temperature=0.0,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = response.content[0].text.strip()

        # Strip markdown code fences if present
        raw = re.sub(r'^```json\s*', '', raw)
        raw = re.sub(r'^```\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)

        parsed = json.loads(raw)
        tables_raw = parsed.get("tables", {})

        table_col_roles = {
            table_num: dict(columns)
            for table_num, columns in deterministic_roles.items()
        }
        for tbl_str, cols in tables_raw.items():
            tbl_num = int(tbl_str)
            table_col_roles.setdefault(tbl_num, {})
            for col_str, role in cols.items():
                col_num = int(col_str)
                if role not in _VALID_ROLES:
                    role = "other"
                # An explicit template header always wins.  AI classification is
                # supplemental for columns the template did not make obvious.
                # A low-confidence generic "label" inference may be refined.
                existing = table_col_roles[tbl_num].get(col_num)
                if existing not in {"findings", "conclusion", "clause_ref"}:
                    table_col_roles[tbl_num][col_num] = role

        logger.info(
            f"Semantic column map built: {len(table_col_roles)} tables classified."
        )
        return ColumnSemanticMap(table_col_roles=table_col_roles)

    except Exception as e:
        logger.warning(
            f"Semantic column detection failed: {e}. "
            f"Falling back to regex detection."
        )
        return ColumnSemanticMap(table_col_roles=deterministic_roles)


def extract_table_col(coord: str) -> tuple[int, int]:
    """
    Parses a coordinate string like T3_R5_C2 → (table=3, col=2).
    Returns (-1, -1) on parse failure.
    """
    m = re.match(r'T(\d+)_R\d+_C(\d+)', coord)
    if m:
        return int(m.group(1)), int(m.group(2))
    return -1, -1
