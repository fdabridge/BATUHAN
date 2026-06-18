# Portal 80 — ISO 27001 (ISMS) System Fixes

## Overview

Three bugs block ISO 27001 from working end-to-end. Fix them all in one push.

---

## Bug 1 (CRITICAL) — ISMS auditors never appear in planning

### Root cause

`GET /auditors/available` filters auditors by `_auditor_covers_any_required`. For any standard
with `type: "ea"`, it checks:

```python
auditor_codes = qual.ea_codes or []
if any(c in auditor_codes for c in required_codes):
    return True
```

Every one of the 13 ISMS-qualified auditors in the DB has `ea_codes: []` for their ISO 27001
qualification (that's how they were imported). So `auditor_codes = []`, the `any(...)` is always
False, and ALL ISMS auditors are silently filtered out — zero results in the planning picker.

The same empty-codes path also affects `_compute_covered_scope`, which skips auditors with
no EA codes (so even if an auditor did sneak through, their covered_scope would be empty).

### Fix — `backend/api/routes/auditors.py`

**In `_auditor_covers_any_required`** (inside `get_available_auditors`), find the EA branch:

```python
else:  # ea
    auditor_codes = qual.ea_codes or []
if any(c in auditor_codes for c in required_codes):
    return True
```

Replace with:

```python
else:  # ea
    auditor_codes = qual.ea_codes or []
# If no EA codes are recorded for this auditor, treat as qualifying for any code.
# (Common for auditors imported without per-standard EA code breakdowns.)
if not auditor_codes:
    return True
if any(c in auditor_codes for c in required_codes):
    return True
```

**In `_compute_covered_scope`** (also inside `get_available_auditors`), find the EA branch:

```python
elif scope_type == "ea":
    auditor_codes = qual.ea_codes or []

# Intersection of required codes and auditor's codes
matched = [c for c in required_codes if c in auditor_codes]
if matched:
    covered[iso_std] = matched
```

Replace with:

```python
elif scope_type == "ea":
    auditor_codes = qual.ea_codes or []

# If auditor has no recorded EA codes, count them as covering all required codes.
if not auditor_codes:
    covered[iso_std] = required_codes
    continue
# Intersection of required codes and auditor's codes
matched = [c for c in required_codes if c in auditor_codes]
if matched:
    covered[iso_std] = matched
```

---

## Bug 2 (HIGH) — FR.233 missing from every audit package

### Root cause

FR.233 (Review & Decision Form) lives at:
```
uaf_blank_set/FR.233 Review And Decision Form R5&09.10.2025/FR.233 Review And Decision Form R5&09.10.2025.docx
```

The resolver looks for FR.233 inside each standard group's stage subfolder, e.g.:
```
uaf_blank_set/9-14-45-22-5001/İlk Belgelendirme/Aşama 2/FR.233*.docx
```

That path does not exist for any group. FR.233 is therefore in `MISSING_TEMPLATES.txt` in
every audit package generated — for QMS, MDQMS, and ISMS alike. Task #31 was supposed to
copy it but the copy never landed in the right places.

### Fix — copy FR.233 into all six locations

Run this Python script (or equivalent bash) from the repo root:

```python
import shutil
from pathlib import Path

SRC = Path("uaf_blank_set/FR.233 Review And Decision Form R5&09.10.2025/FR.233 Review And Decision Form R5&09.10.2025.docx")
DEST_FILENAME = "FR.233 Review And Decision Form R5&09.10.2025.docx"

DESTINATIONS = [
    # Stage 2
    "uaf_blank_set/9-14-45-22-5001/İlk Belgelendirme/Aşama 2",
    "uaf_blank_set/13485/İlk Belgelendirme/Aşama 2",
    "uaf_blank_set/27001/İlk Belgelendirme/Aşama 2",
    # Surveillance
    "uaf_blank_set/9-14-45-22-5001/Gözetim",
    "uaf_blank_set/13485/Gözetim",
    "uaf_blank_set/27001/Gözetim",
    # UAF English equivalents (if they exist)
    "uaf_blank_set/9-14-45-22-5001/Initial Certification/Stage 2",
    "uaf_blank_set/13485/Initial Certification/Stage 2",
    "uaf_blank_set/27001/Initial Certification/Stage 2",
    "uaf_blank_set/9-14-45-22-5001/Surveillance",
    "uaf_blank_set/13485/Surveillance",
    "uaf_blank_set/27001/Surveillance",
]

for dest_dir in DESTINATIONS:
    dest = Path(dest_dir)
    if dest.exists():
        dest_file = dest / DEST_FILENAME
        if not dest_file.exists():
            shutil.copy2(SRC, dest_file)
            print(f"Copied → {dest_file}")
        else:
            print(f"Already exists: {dest_file}")
    else:
        print(f"Dir not found (skipped): {dest_dir}")
```

Run from the repo root before committing so git tracks the new file copies.

After the copy, FR.233 will be picked up by the resolver's `_find_template` call for all
three standard groups in both Stage 2 and Surveillance folders.

---

## Bug 3 (HIGH) — FR.231 (Stage 1 Report) missing from ISMS-only Stage 1 packages

### Root cause

`_build_stage_1` in `resolver.py` adds the Stage 1 Report like this:

```python
if needs_base:
    _add(specs, seen, "FR.231",   "base",  sub, FR231_MAP, "stage_1", missing)
if needs_mdqms:
    _add(specs, seen, "FR.231-1", "mdqms", sub, FR231_MAP, "stage_1", missing)
# No branch for needs_isms!
```

The ISMS-specific Stage 1 Report (`FR.231_Stage1_Report_R9&09.10.2025.docx`) already exists
in `uaf_blank_set/27001/İlk Belgelendirme/Aşama 1/`. The code just never adds it.

### Fix — `backend/audit_set/resolver.py`

In `_build_stage_1`, find the FR.231 block:

```python
    if needs_base:
        _add(specs, seen, "FR.231",   "base",  sub, FR231_MAP, "stage_1", missing)
    if needs_mdqms:
        _add(specs, seen, "FR.231-1", "mdqms", sub, FR231_MAP, "stage_1", missing)
```

Add an ISMS branch after it:

```python
    if needs_base:
        _add(specs, seen, "FR.231",   "base",  sub, FR231_MAP, "stage_1", missing)
    if needs_mdqms:
        _add(specs, seen, "FR.231-1", "mdqms", sub, FR231_MAP, "stage_1", missing)
    if needs_isms:
        _add(specs, seen, "FR.231",   "isms",  sub, FR231_MAP, "stage_1", missing)
```

Note: for a QMS+ISMS integrated audit (`needs_base=True, needs_isms=True`), the base branch
adds FR.231 first (from the base group folder). The isms branch then tries to add "FR.231"
again, but since `"FR.231"` is already in `seen`, the `_add` call is a no-op (correct —
one FR.231 per package is enough; base template is used for integrated audits).

---

## Note on FR.229 / FR229_MAP — NOT a bug

FR.229 (`ISMS_PIMS_Audit_Report`) currently uses `FR232_MAP`. This is correct. The fillable
header sections in FR.229 (Tables 1, 2, 3, 4, 11) have the same structure as FR.232:
- Table 1 row 1 col 0 → organisation_block
- Table 2 row 1 col 0 → scope_en
- Table 3 rows 0-10 col 1 → plan_number, today_date, standards_str, lead/auditors/TEs/observer/representative
- Table 4 row 0 col 1 → audit_dates; col 3 → audit_days
- Table 11 rows 1-3 col 1 → total_employees, subcontractor_employees, effective_employees

FR.229 has 24 tables total (vs fewer in FR.232) but the extra tables are the ISMS/27701
clause checklists that auditors fill manually — they are not auto-filled by the system.
No FR229_MAP is needed.

---

## Verification checklist

1. Create an ISMS-only audit set. In planning → auditor picker, ISMS-qualified auditors
   should now appear. Previously: zero results.

2. Generate any QMS audit package (initial cert). Open the ZIP — FR.233 should now be
   present (Stage_2 folder). Previously: it was in MISSING_TEMPLATES.txt.

3. Generate an ISMS-only initial cert package. Stage_1 folder should contain FR.231
   (ISMS version from 27001 subfolder). Previously: missing.

4. Generate a QMS+ISMS integrated initial cert package.
   - Stage_2 should contain both FR.232 (QMS base report) and FR.229 (ISMS report).
   - One FR.233 should be present (from the base group copy).
   - Stage_1 should contain one FR.231 (base version, not duplicated from isms branch).

5. Confirm RENDER_ERRORS.txt is absent from the package (or empty of new errors).

## No DB migration needed

All changes are Python logic + file copies. No schema changes.
