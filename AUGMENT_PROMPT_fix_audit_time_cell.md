# Augment Prompt — Fix Static "audit/day" Text in FR.223 and FR.224

## Problem

FR.223 (Audit Plan) and FR.224 (Audit Team Information Form) have a cell that should show the number of audit days followed by "audit/day". Currently it contains **only the static text "audit/day"** — there is no Jinja2 variable at all, so the rendered document always shows blank "audit/day" regardless of input.

This was confirmed by Jinja2 extraction: neither FR.223 nor FR.224 contain `{{ audit_days }}` or `{{ stage_1_days }}` anywhere. The "Audit Time" cell is hardcoded.

## What to Fix

In the Jinja2 context (from `filler.py`), the correct variable is:
- `stage_1_days` → Stage 1 audit day count (falls back from `man_day_result["final_ph1"]`)
- `audit_days` → Current stage's day count (works for Stage 2 and Surveillance too)

For FR.223 and FR.224 (always Stage 1 forms), use `stage_1_days`.

## Script

Write a Python script that:
1. Opens each target `.docx` with `zipfile`
2. Parses `word/document.xml` with `lxml`
3. Searches for a `<w:tc>` (table cell) element whose text content is exactly or contains `"audit/day"` but does NOT contain any Jinja2 `{{ }}` expression
4. Replaces the text in that cell so it reads: `{{ stage_1_days }} audit/day` (or `{{ audit_days }} audit/day` for surveillance copies)
5. Saves the modified document back in-place

```python
import zipfile, io, re
from lxml import etree
from pathlib import Path
from copy import deepcopy

NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{NS}}}"

def get_cell_text(tc):
    return "".join(t.text or "" for t in tc.iter(f"{W}t"))

def fix_audit_time_cell(docx_path: Path, variable: str = "stage_1_days"):
    """Replace static 'audit/day' cell with '{{ variable }} audit/day'."""
    data = docx_path.read_bytes()
    buf = io.BytesIO(data)
    out = io.BytesIO()
    
    with zipfile.ZipFile(buf, 'r') as zin, zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            item_data = zin.read(item.filename)
            if item.filename == 'word/document.xml':
                item_data = _patch_audit_time(item_data, variable)
            zout.writestr(item, item_data)
    
    docx_path.write_bytes(out.getvalue())
    print(f"  Fixed: {docx_path.name}")

def _patch_audit_time(xml_bytes: bytes, variable: str) -> bytes:
    tree = etree.fromstring(xml_bytes)
    patched = 0
    
    for tc in tree.iter(f"{W}tc"):
        cell_text = get_cell_text(tc).strip()
        # Target: cell that contains ONLY "audit/day" (no Jinja2 expression present)
        if cell_text == "audit/day" and "{{" not in cell_text:
            # Find the paragraph(s) in this cell and update the text
            for para in tc.findall(f".//{W}p"):
                for run in para.findall(f".//{W}r"):
                    for t in run.findall(f"{W}t"):
                        if t.text and "audit/day" in t.text:
                            # Replace with Jinja2 expression
                            t.text = "{{{{ {var} }}}} audit/day".format(var=variable)
                            # Preserve whitespace
                            t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                            patched += 1
            break  # Only one such cell expected per document
    
    if patched == 0:
        print(f"  WARNING: 'audit/day' cell not found — document may already be patched or structure differs")
    else:
        print(f"  Patched {patched} text element(s)")
    
    return etree.tostring(tree, xml_declaration=True, encoding='UTF-8', standalone=True)


# Apply to all FR.223 and FR.224 copies
base = Path("backend/uaf_blank_set")

targets = [
    # FR.223 — Audit Plan (Stage 1)
    (base / "9-14-45-22-5001/Initial Certification /Stage 1/FR.223_Audit_Plan_R6&09.10.2025.docx", "stage_1_days"),
    (base / "13485/Initial Certification /Stage 1/FR.223_Audit_Plan_R6&09.10.2025.docx", "stage_1_days"),
    (base / "27001/Initial Certification/Stage 1/FR.223_Audit_Plan_R6&09.10.2025.docx", "stage_1_days"),
    
    # FR.223 — Audit Plan (Stage 2) — uses stage_2_days
    (base / "9-14-45-22-5001/Initial Certification /Stage 2/FR.223_Audit_Plan_R6&09.10.2025.docx", "stage_2_days"),
    (base / "13485/Initial Certification /Stage 2/FR.223_Audit_Plan_R6&09.10.2025.docx", "stage_2_days"),
    (base / "27001/Initial Certification/Stage 2/FR.223_Audit_Plan_R6&09.10.2025.docx", "stage_2_days"),
    
    # FR.223 — Audit Plan (Surveillance) — uses surv_days  
    (base / "9-14-45-22-5001/Surveillance/FR.223_Audit_Plan_R6&09.10.2025.docx", "surv_days"),
    (base / "13485/Surveillance/FR.223_Audit_Plan_R6&09.10.2025.docx", "surv_days"),
    (base / "27001/Surveillance/FR.223_Audit_Plan_R6&09.10.2025.docx", "surv_days"),
    
    # FR.224 — Audit Team Information Form (Stage 1) 
    (base / "9-14-45-22-5001/Initial Certification /Stage 1/FR.224_Audit Team Information Form-R7&09.10.2025.docx", "stage_1_days"),
    (base / "13485/Initial Certification /Stage 1/FR.224_Audit Team Information Form-R7&09.10.2025.docx", "stage_1_days"),
    (base / "27001/Initial Certification/Stage 1/FR.224_Audit Team Information Form-R7&09.10.2025.docx", "stage_1_days"),
    
    # FR.224 — Stage 2
    (base / "9-14-45-22-5001/Initial Certification /Stage 2/FR.224_Audit Team Information Form-R7&09.10.2025.docx", "stage_2_days"),
    (base / "13485/Initial Certification /Stage 2/FR.224_Audit Team Information Form-R7&09.10.2025.docx", "stage_2_days"),
    (base / "27001/Initial Certification/Stage 2/FR.224_Audit Team Information Form-R7&09.10.2025.docx", "stage_2_days"),
    
    # FR.224 — Surveillance
    (base / "9-14-45-22-5001/Surveillance/FR.224_Audit Team Information Form-R7&09.10.2025.docx", "surv_days"),
    (base / "13485/Surveillance/FR.224_Audit Team Information Form-R7&09.10.2025.docx", "surv_days"),
    (base / "27001/Surveillance/FR.224_Audit Team Information Form-R7&09.10.2025.docx", "surv_days"),
]

for path, var in targets:
    if path.exists():
        print(f"Processing {path.name} (var={var})...")
        fix_audit_time_cell(path, var)
    else:
        print(f"SKIP (not found): {path}")
```

Run this script from the repo root: `python3 fix_audit_time.py`

## Context Variables (already in filler.py)

These variables are already returned by `build_base_context()` (or will be after AUGMENT_PROMPT_render_gaps_fix.md is applied):
- `stage_1_days` — Stage 1 audit days (from stage1.audit_days, fallback to man_day_result["final_ph1"])
- `stage_2_days` — Stage 2 audit days (from stage2.audit_days, fallback to man_day_result["final_ph2"])
- `surv_days` — Surveillance days (from man_day_result["final_surv1"])
- `audit_days` — Current stage's days

## Also Check FR.231 "Audit/Day Number" Cell

FR.231 already has `{{ audit_days }}` in the Jinja2 — but the cell currently renders blank because `stage.audit_days` is null. This will be fixed by the `audit_days` fallback in AUGMENT_PROMPT_render_gaps_fix.md. No template change needed for FR.231.

## After Running

```bash
git add backend/uaf_blank_set/
git commit -m "fix: FR.223 and FR.224 audit time cell now uses stage days variable instead of static 'audit/day'"
git push
```
