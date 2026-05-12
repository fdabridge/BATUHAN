"""
BATUHAN — Column Semantic Map
Classifies every column in every template table by semantic role (findings,
conclusion, clause_ref, label, other) via a single Claude call.
The result is reused across all assembly chunks to guide auto-tick logic.
"""

from anthropic import Anthropic
from dataclasses import dataclass
import json, logging, re

logger = logging.getLogger(__name__)


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
    client: Anthropic,
    model: str,
) -> ColumnSemanticMap:
    """
    Sends the template structure to Claude once and asks it to classify
    every column in every table by semantic role.
    Returns a ColumnSemanticMap usable for the rest of assembly.
    """
    # Truncate if very large — first 6000 chars is enough to see all headers
    structure_excerpt = template_structure_text[:6000]

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

        table_col_roles = {}
        for tbl_str, cols in tables_raw.items():
            tbl_num = int(tbl_str)
            table_col_roles[tbl_num] = {}
            for col_str, role in cols.items():
                col_num = int(col_str)
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
        return ColumnSemanticMap(table_col_roles={})


def extract_table_col(coord: str) -> tuple[int, int]:
    """
    Parses a coordinate string like T3_R5_C2 → (table=3, col=2).
    Returns (-1, -1) on parse failure.
    """
    m = re.match(r'T(\d+)_R\d+_C(\d+)', coord)
    if m:
        return int(m.group(1)), int(m.group(2))
    return -1, -1
