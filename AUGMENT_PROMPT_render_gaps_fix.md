# Augment Prompt — Fix All Template Rendering Gaps

## Context

The live app now produces actual `.docx` files (no more MISSING_TEMPLATES). But several fields are blank, showing "None", or crashing. This prompt covers every known gap — work through them in order. Do NOT ask clarifying questions; the answers are below.

---

## CRASH FIXES (do these first)

### FR.218 and FR.222 crash: "list object has no element 0"

**Root cause:** Both templates access `{{ sites[0].address }}` (and `.employee_count`) without any guard. When an audit set has no sites configured (user only entered a company address), `sites` is `[]` and `sites[0]` crashes.

**Fix in `backend/audit_set/filler.py`** — in `build_base_context()`, replace:

```python
sites = audit_set.sites or []
```

with:

```python
sites_raw = audit_set.sites or []
if not sites_raw:
    # Fallback: inject one entry from the top-level address so templates don't crash
    sites_raw = [{
        "address": audit_set.company_address or "",
        "process": audit_set.scope_en or "",
        "employee_count": audit_set.effective_employees or 0,
    }]

def _normalize_site(s: dict) -> dict:
    """Add all field aliases so every template variant works regardless of naming."""
    d = dict(s)
    # The DB stores 'process' (from SiteData schema). Add all aliases for template compat.
    process_val = d.get("process") or d.get("process_description") or d.get("scope") or ""
    d.setdefault("process", process_val)
    d.setdefault("process_description", process_val)   # some old templates use this
    d.setdefault("scope", process_val)                 # FR.222 sites[0] uses 'scope'
    d.setdefault("employee_count", d.get("employees", 0))
    d.setdefault("employees", d.get("employee_count", 0))   # FR.222 sites[0] uses 'employees'
    d.setdefault("audit_days", "")                     # per-site days don't exist
    d.setdefault("address", "")
    return d

sites = [_normalize_site(s) for s in sites_raw]
```

---

## NONE → "" FIXES

Several fields render as the literal word "None" in the documents. In `build_base_context()`, replace the current one-liner assignments with `or ""` fallbacks for all of these:

```python
# Replace every line below with the `or ""` version shown:
"ea_code":               audit_set.ea_code or "",
"ea_category":           audit_set.ea_category or "",
"ea_technical_area":     audit_set.ea_technical_area or "",
"non_applicable_clauses": audit_set.non_applicable_clauses or "",
"representative":        audit_set.representative or "",
"certification_fee":     audit_set.certification_fee if audit_set.certification_fee is not None else "",
"initial_fee":           audit_set.certification_fee if audit_set.certification_fee is not None else "",
"surveillance_fee":      audit_set.surveillance_fee if audit_set.surveillance_fee is not None else "",
"scope_en":              audit_set.scope_en or "",
"scope_tr":              audit_set.scope_tr or "",
"website":               audit_set.website or "",
"phone":                 audit_set.phone or "",
"email":                 audit_set.email or "",
```

Also fix `site_addresses` to fall back to company address when sites is empty:

```python
# Replace:
"site_addresses": "\n".join(s.get("address", "") for s in sites),
# With:
"site_addresses": "\n".join(s.get("address", "") for s in sites) or (audit_set.company_address or ""),
```

---

## AUDIT DAYS FIX

`stage.audit_days` is often null (not explicitly set on the stage). The templates need the actual day count. Add a fallback that derives it from `man_day_result` when not explicitly set:

```python
# In build_base_context(), derive audit_days fallback before the return dict:
_stage_type = stage.stage_type  # "stage_1" | "stage_2" | "surveillance"
if _stage_type == "stage_1":
    _audit_days_fallback = man_day.get("final_ph1", "")
elif _stage_type == "stage_2":
    _audit_days_fallback = man_day.get("final_ph2", "")
else:  # surveillance
    _audit_days_fallback = man_day.get("final_surv1", "")

# Then in the return dict:
"audit_days":   stage.audit_days if stage.audit_days is not None else (_audit_days_fallback or ""),
"stage_1_days": (stage1.audit_days if stage1 and stage1.audit_days is not None
                 else man_day.get("final_ph1", "")) if stage1 else "",
"stage_2_days": (stage2.audit_days if stage2 and stage2.audit_days is not None
                 else man_day.get("final_ph2", "")) if stage2 else "",
"surv_days":    man_day.get("final_surv1", ""),
```

---

## ADD STANDARD SELECTION BOOLEANS TO CONTEXT

Several templates need to know which standards are selected. Add these to the return dict in `build_base_context()`:

```python
# Standard selection booleans + full ISO names
"standards_full":   standards_full,          # ["ISO 9001:2015", ...]
"qms_selected":     "QMS" in standards_codes,
"ems_selected":     "EMS" in standards_codes,
"ohsms_selected":   "OHSMS" in standards_codes,
"fsms_selected":    "FSMS" in standards_codes,
"isms_selected":    "ISMS" in standards_codes,
"mdqms_selected":   "MDQMS" in standards_codes,
"abms_selected":    "ABMS" in standards_codes,
"enms_selected":    "ENMS" in standards_codes,
```

---

## TEMPLATE FIXES

These require Python scripts to edit the `.docx` XML directly.

### Fix 1 — FR.222: Wrong field names in sites[0] row AND sites[1]/sites[2] rows

The FR.222 template has two problems:
1. `sites[0]` row uses `.scope`, `.employees`, `.audit_days` (wrong field names)
2. `sites[1]` and `sites[2]` rows use `.process_description` (our previous fix was wrong — DB stores `process`)

Write a Python script to fix both copies of FR.222:
- `backend/uaf_blank_set/9-14-45-22-5001/Initial Certification /Stage 1/FR.222_Audit Programı R7&09.10.2025.docx`
- `backend/uaf_blank_set/13485/Initial Certification /Stage 1/FR.222_Audit Programı R7&09.10.2025.docx`
- `backend/uaf_blank_set/27001/Initial Certification/Stage 1/FR.222_Audit Programı R7&09.10.2025.docx`

**What to fix in each file using `lxml` + `zipfile`:**
- All occurrences of `sites[0].scope` → `sites[0].process`
- All occurrences of `sites[0].employees` → `sites[0].employee_count`
- All occurrences of `sites[0].audit_days` → remove this reference (or replace with `""`)
- All occurrences of `sites[1].process_description` → `sites[1].process`
- All occurrences of `sites[2].process_description` → `sites[2].process`
- All occurrences of `sites[1].scope` → `sites[1].process` (if any)
- All occurrences of `sites[2].scope` → `sites[2].process` (if any)

After our `_normalize_site()` fix in filler.py, the aliases will also work, so this template fix is belt-and-suspenders.

### Fix 2 — FR.222 audit time column for sites[0]

The sites[0] row in the "Audit Program" table has an "Audit Duration" column that previously referenced `sites[0].audit_days`. Since per-site audit days don't exist in the data model, this cell should be cleared to empty. Replace `{{ sites[0].audit_days }}` (or any variant) with `""`.

### Fix 3 — FR.231: FSMS-specific audit objectives always showing (red text)

FR.231's "Audit Objectives" cell contains FSMS-specific sub-objectives (about PRPs, food safety hazards, HACCP, food legislation, etc.) that should only appear when FSMS is in scope. Currently they're not wrapped in a conditional.

In `FR.231_Stage1_Report_R9&09.10.2025.docx` (all copies: 9-14-45-22-5001 and 13485):
The cell also contains a red-colored instruction line reading "THESE TARGETS WILL BE USED FOR FOOD. IF NO FOOD YOU CAN DELETE." — this must be removed entirely from the template (it's an editorial note, not data).

The FSMS objectives rows (the red-text block and the preceding FSMS objectives a-h) need to be wrapped in a `{%tr if "FSMS" in standards %}` / `{%tr endif %}` sacrificial pattern. Since these are cell content (not separate rows), the cleanest fix is to leave the static objectives for all audit types and remove the FSMS-specific block + red instruction text entirely from the template.

**If it's in a single cell** (not separate rows): Use `lxml` to find the paragraph containing the red text ("THESE TARGETS WILL BE USED FOR FOOD") and the preceding FSMS paragraphs, and delete them from the cell's `<w:tc>` element.

### Fix 4 — FR.220 and FR.221: Standard checkboxes

FR.220 and FR.221 use DOCX legacy form field checkboxes (`<w:checkBox>` inside `<w:ffData>`) for the standards table. docxtpl cannot fill these. There are two options:

**Recommended approach (post-render fixup):** In `packager.py`, after calling `render_docx()` for FR.220 or FR.221 files, apply a post-render function using `python-docx` (`lxml`) to:

1. Open the rendered bytes as a ZipFile
2. Parse `word/document.xml`
3. Find the standards table (the table containing the standards grid — search for cell text "ISO 9001")
4. For each standard cell, check if the standard is in the audit's `standards_codes`
5. Find the `<w:checkBox>` element in that cell and set `<w:default w:val="1"/>` if selected, `<w:default w:val="0"/>` if not

Create a helper function `apply_checkbox_selection(docx_bytes: bytes, standards_codes: list[str]) -> bytes` in `packager.py` or a new `backend/audit_set/postprocess.py` module. Call it after `render_docx()` for FR.220 and FR.221.

The standards map to cells in this order (FR.220 table layout):
- Row 1: QMS (ISO 9001:2015) | EMS (ISO 14001:2015) | OHSMS (ISO 45001:2018) | FSMS (ISO 22000:2018)
- Row 2: ISMS (ISO/IEC 27001:2022) | ENMS (ISO 50001:2018) | MDQMS (ISO 13485:2016) | ABMS (ISO 37001:2016)

If the `<w:checkBox>` approach is complex, an alternative: replace each checkbox cell text with `☑ ISO 9001:2015` (checked) or `☐ ISO 9001:2015` (unchecked) using lxml text replacement on the relevant `<w:t>` elements.

---

## FRONTEND ADDITIONS

### New fields needed on the Audit Set form

These fields exist in the DB model and create schema but are not collected through the frontend UI. Add them.

#### 1. Organization Representative (`representative`)
- **Where:** In the audit set create/edit form, in the company info section (after E-mail / Website)
- **Label:** "Organization Representative" (contact person name)
- **Type:** Text input
- **DB field:** `audit_sets.representative`
- **Already in:** `AuditSetCreateSchema.representative` and DB — just needs frontend field

#### 2. Not Applicable Clauses (`non_applicable_clauses`)
- **Where:** After the Scope field in the audit set form
- **Label:** "Not Applicable Clauses (e.g. 7.1.5, 8.3)"
- **Type:** Textarea or text input
- **DB field:** `audit_sets.non_applicable_clauses`
- **Already in:** `AuditSetCreateSchema.non_applicable_clauses` and DB

#### 3. Fees (`certification_fee`, `surveillance_fee`)
- **Where:** In the planning section (after man-day calculation result, before scheduling)
- **Labels:** "Initial Certification Fee" and "Surveillance Fee"
- **Type:** Number input (float)
- **DB fields:** `audit_sets.certification_fee`, `audit_sets.surveillance_fee`
- **Already in:** `AuditSetUpdatePlanningSchema.certification_fee / surveillance_fee` and DB

---

## SCHEMA ADDITION

`AuditSetUpdatePlanningSchema` is missing `representative` and `non_applicable_clauses`. Add them so they can be updated after creation:

```python
class AuditSetUpdatePlanningSchema(BaseModel):
    # ... existing fields ...
    representative: Optional[str] = None
    non_applicable_clauses: Optional[str] = None
```

Then in `service.py`, in the `update_planning()` function (or equivalent), add:
```python
if payload.representative is not None:
    audit_set.representative = payload.representative
if payload.non_applicable_clauses is not None:
    audit_set.non_applicable_clauses = payload.non_applicable_clauses
```

---

## FR.224: Auditor EA Code / Category column is blank

The FR.224 template uses `{{ lead_auditor_codes }}` and `{{ auditors[0].covered_codes_display }}`. These come from `build_auditor_scope_strings()` in filler.py. They will be blank when:
1. `required_scope` is null (scope derivation was never run)
2. The auditor's `standard_qualifications` in the DB have no matching EA codes

Short-term fix: When `lead_auditor_codes` would be empty, fall back to showing the audit-set level `ea_code` field instead:

In `build_base_context()`, after merging the auditor scope strings, add:
```python
# Fallback: if lead_auditor_codes is empty, use the audit-set ea_code
if not ctx.get("lead_auditor_codes") and audit_set.ea_code:
    ctx["lead_auditor_codes"] = audit_set.ea_code
```

Wait — `build_auditor_scope_strings` is called separately from `build_base_context`. In `packager.py`, after merging both, apply the fallback:
```python
ctx = build_base_context(audit_set, stage)
ctx.update(build_auditor_scope_strings(stage, auditor_lookup, required_scope))
# EA code fallback for display when auditor profile is incomplete
if not ctx.get("lead_auditor_codes"):
    ctx["lead_auditor_codes"] = audit_set.ea_code or ""
```

---

## TESTING

After all changes:

```bash
cd backend
pytest tests/test_uaf_pipeline.py -v --tb=short
```

All 6 tests should pass. Additionally, test manually:
1. Create an audit set with only ISO 9001:2015, single site, one auditor
2. Download the audit package
3. Open FR.218, FR.222, FR.220, FR.221, FR.223, FR.224, FR.231
4. Verify:
   - No "None" anywhere in any document
   - No blank audit day count (FR.223 "Audit Time" column)
   - Site address populated in FR.221, FR.223, FR.224, FR.231
   - FR.231 does NOT show red FSMS instructions

---

## DO NOT CHANGE

- The `{%tr if sites|length > 1 %}` / `{%tr endif %}` wrappers around sites[1] and sites[2] rows — these are correct
- The `audit_days` per-site removal was intentional — do not add it back
- The `_normalize_site()` aliases — keep them all even after fixing field names in templates, as a safety net
