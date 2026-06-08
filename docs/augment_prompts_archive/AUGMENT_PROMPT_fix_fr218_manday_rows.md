# Fix FR.218 Per-Standard Man-Day Table Rows

## Context

FR.218 (Certification Application Review Form) has a table with one row per ISO standard and columns:
Standards | A/D | Inc/Dec A/D | Intg. Reduction | Rounding | Stage 1 | Stage 2 | Surveillance | Rec.

Currently: ALL per-standard cells are blank except "Intg. Reduction" which shows `2.4` for every row (this is the total `integration_reduction` value, not per-standard). The totals row at the bottom (Stage 1 = 2.5, Stage 2 = 4.5, Surv = 1.0, Rec = 1.5) is correct.

The calculator stores per-standard data in `man_day_result.standard_results` (a list of dicts). Each dict is a serialized `StandardAuditResult` with fields:
- `standard` — full name, e.g. "ISO 9001:2015"
- `category` — e.g. "High Risk"
- `eps` — effective person count
- `base_init` — total base audit days (initial)
- `base_ph1` — Stage 1 base days
- `base_ph2` — Stage 2 base days
- `base_surv` — Surveillance base days
- `base_recert` — Recertification total
- `site_addition` — extra days for additional sites
- `haccp_addition` — FSMS only, else null

The overall `CalculationResult` (also stored in `man_day_result`) has:
- `integration_reduction` — total days saved by IAF MD 11 integration (currently showing as 2.4 for 3-standard IMS)
- `reporting_reduction` — total days saved by 20% reporting/travel reduction
- `final_ph1`, `final_ph2`, `final_surv1`, `final_recert` — final rounded totals

## Task

### Step 1 — Inspect the FR.218 template XML

Run this Python snippet to extract and print the template's document.xml:

```bash
cd /app/backend   # or wherever backend/ is; adjust path
python3 - <<'EOF'
import zipfile, re, sys

# Adjust path to match actual template location
path = "uaf_blank_set/FR.218 Certification Application Review Form.docx"
with zipfile.ZipFile(path) as z:
    xml = z.read("word/document.xml").decode("utf-8", errors="replace")

# Extract all Jinja2 expressions/blocks
jinja_exprs = re.findall(r'\{\{.*?\}\}|\{%.*?%\}', xml)
for e in jinja_exprs:
    print(e)
EOF
```

Look at every `{{ ... }}` expression inside the man-day table rows. Note the exact variable names used.

### Step 2 — Understand the naming mismatch

The template likely uses names like `ad`, `stage_1`, `stage_2`, `surv`, `rec`, `intg_reduction` inside the per-standard row context. But `StandardAuditResult` uses `base_ph1`, `base_ph2`, `base_surv`, `base_recert`, `base_init`. These don't match.

### Step 3 — Fix `audit_set/filler.py`: add enriched `standard_results` to context

In `build_base_context()`, after the `standard_results_by_name` dict is built, add the following to the context dict:

```python
# Build a list of per-standard dicts with template-friendly names.
# These power the {%tr for sr in standard_results_rows %} loop in FR.218.
_num_standards = len(standards_full)
_int_reduction_total = man_day.get("integration_reduction", 0)
_report_reduction_total = man_day.get("reporting_reduction", 0)

standard_results_rows = []
for sr in (man_day.get("standard_results") or []):
    base_init  = sr.get("base_init", 0)
    base_ph1   = sr.get("base_ph1", 0)
    base_ph2   = sr.get("base_ph2", 0)
    base_surv  = sr.get("base_surv", 0)
    base_recert = sr.get("base_recert", 0)
    site_add   = sr.get("site_addition", 0)
    
    # Per-standard integration reduction = proportional share of total reduction
    # Proportional by base_init weight
    _combined_base = man_day.get("combined_base", 1) or 1
    _weight = (base_init + site_add) / _combined_base
    per_std_intg_reduction = round(_int_reduction_total * _weight, 2)
    per_std_report_reduction = round(_report_reduction_total * _weight, 2)
    
    # A/D = total base initial days for this standard (before reductions)
    ad = base_init + site_add
    inc_dec_ad = site_add  # site/HACCP additions shown in Inc/Dec column
    
    standard_results_rows.append({
        "standard":       sr.get("standard", ""),
        "category":       sr.get("category", ""),
        "eps":            sr.get("eps", ""),
        # Template-friendly column names:
        "ad":             round(ad, 2) if ad else "",
        "inc_dec_ad":     round(inc_dec_ad, 2) if inc_dec_ad else "",
        "intg_reduction": round(per_std_intg_reduction, 2) if per_std_intg_reduction else "",
        "stage_1":        round(base_ph1, 2) if base_ph1 else "",
        "stage_2":        round(base_ph2, 2) if base_ph2 else "",
        "surv":           round(base_surv, 2) if base_surv else "",
        "rec":            round(base_recert, 2) if base_recert else "",
        # Also expose raw fields in case template uses those names:
        "base_init":      round(base_init, 2),
        "base_ph1":       round(base_ph1, 2),
        "base_ph2":       round(base_ph2, 2),
        "base_surv":      round(base_surv, 2),
        "base_recert":    round(base_recert, 2),
        "site_addition":  round(site_add, 2),
    })

# Also expose aggregate reduction totals for the FR.218 context
"standard_results_rows": standard_results_rows,
"integration_reduction": man_day.get("integration_reduction", ""),
"reporting_reduction":   man_day.get("reporting_reduction", ""),
"combined_base":         man_day.get("combined_base", ""),
"final_total":           man_day.get("final_total", ""),
```

Make sure `standard_results_rows` is added to the returned context dict (not just assigned locally).

### Step 4 — Update the FR.218 template if the variable names don't match

After inspecting the template XML in Step 1:

**If the template loop uses `{%tr for sr in standard_results_rows %}` with `{{ sr.ad }}`, `{{ sr.stage_1 }}` etc.** — the filler.py fix from Step 3 is sufficient.

**If the template loop uses `{%tr for sr in man_day_result.standard_results %}` with `{{ sr.stage_1 }}` (which doesn't exist on the raw JSON)** — the cleanest fix is to update the template XML:

```bash
cd backend
python3 - <<'EOF'
import zipfile, shutil, re

template_path = "uaf_blank_set/FR.218 Certification Application Review Form.docx"
backup_path   = "uaf_blank_set/FR.218 Certification Application Review Form.docx.bak"
shutil.copy(template_path, backup_path)

with zipfile.ZipFile(template_path, "r") as zin:
    names = zin.namelist()
    contents = {name: zin.read(name) for name in names}

xml = contents["word/document.xml"].decode("utf-8")

# Replace loop source from man_day_result.standard_results to standard_results_rows
xml = xml.replace("man_day_result.standard_results", "standard_results_rows")

# Fix field name mappings if needed — check actual names from Step 1 and replace:
# Example:  {{ sr.stage1 }} → {{ sr.stage_1 }}
# Example:  {{ sr.surveillance }} → {{ sr.surv }}
# (Apply the actual replacements found in Step 1)

contents["word/document.xml"] = xml.encode("utf-8")

import os
os.remove(template_path)
with zipfile.ZipFile(template_path, "w", zipfile.ZIP_DEFLATED) as zout:
    for name, data in contents.items():
        zout.writestr(name, data)

print("Done — FR.218 template updated")
EOF
```

**Note:** Do NOT guess at replacements. Only replace variable names you actually found in Step 1 to be wrong. If the template uses `{{ sr.base_ph1 }}` and that matches, leave it alone.

### Step 5 — Fix the "Intg. Reduction" column showing total instead of per-standard

From Step 1's inspection, find which cell in the per-standard row shows "Intg. Reduction". Currently it shows `2.4` (the total integration_reduction). This cell should show `{{ sr.intg_reduction }}` (the per-standard value from `standard_results_rows`). Update it if needed.

### Step 6 — Verify and commit

After changes:
1. Run the backend locally or push to Railway and re-render FR.218
2. The per-standard table rows should now show:
   - A/D: ~3.6 per standard (base days before reduction)
   - Inc/Dec A/D: site additions if any (else blank)
   - Intg. Reduction: per-standard portion of integration reduction (~0.72 each for 3-standard IMS)
   - Stage 1: per-standard stage 1 base days (~1.2 each)
   - Stage 2: per-standard stage 2 base days (~2.4 each)
   - Surveillance: per-standard surv days (~0.5 each)
   - Rec.: per-standard recertification days (~0.75 each)
3. Commit with message: `fix(FR.218): fill per-standard man-day table rows from standard_results`
4. Push to main

## Files to edit
- `backend/audit_set/filler.py` — add `standard_results_rows` to context (required)
- `backend/uaf_blank_set/FR.218 Certification Application Review Form.docx` — update template XML only if Step 1 reveals name mismatches (conditional)
