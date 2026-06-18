# Portal 79 — Surveillance Document Parity with Stage 2

## Problem

The surveillance audit package has six bugs compared to the Stage 2 / initial
certification package. S1 and S2 forms are the source of truth; surveillance must
match them exactly.

1. **No green cell highlighting** — FR.223, FR.224, FR.225, FR.232 etc. never have the
   selected-standard / audit-type cells painted green. Only FR.220 and FR.221 get
   the highlight treatment, but those forms don't appear in surveillance at all.
2. **`audit_type_str` missing** — FR.223, FR.224, FR.225 each reference a context key
   `audit_type_str` in their field maps, but `build_base_context()` only provides
   `audit_type_display`. The cell for "Initial Certification / Surveillance /
   Recertification" is always blank.
3. **Date key mismatch** — `FR223_MAP` and `FR224_MAP` reference key `"stage_1_date"` for
   the "Audit Date/s" cell; `FR232_MAP` references key `"stage_2_date"` for its "Audit
   Date/s" cell; `FR231_MAP` and `FR211_MAP` also reference `"stage_1_date"`. But
   `build_base_context()` only has `"stage1_dates"` and `"stage2_dates"` (with an 's'
   suffix), so all those cells are always blank.
4. **MDQMS surveillance uses FR.232 instead of FR.232-1** — `_build_surveillance` lumps
   all three groups (base, mdqms, isms) through the same `FR.232` form. Stage 2 correctly
   uses `FR.232-1` for MDQMS.
5. **ISMS surveillance uses FR.232 instead of FR.229** — same root cause. Stage 2
   correctly uses `FR.229` for ISMS.
6. **`surveillance_date` missing from context** — `FR234_MAP` references
   `"surveillance_date"` but `build_base_context()` never adds it.

---

## Files to change

```
backend/audit_set/packager.py
backend/audit_set/filler.py
backend/audit_set/field_maps.py
backend/audit_set/resolver.py
```

---

## Fix 1 — `packager.py`: apply green highlighting to ALL forms

**Why:** `apply_standard_highlighting` and `apply_audit_type_highlighting` are safe
no-ops on any form that doesn't contain "ISO 9001", "ISO 14001", "Initial", or
"Recertification" text in table cells. Only `apply_checkbox_selection` must stay
gated to `CHECKBOX_FORMS` because only FR.220 and FR.221 have `<w:checkBox>` XML
elements.

There are two callsites — fix both.

### 2a. `render_single_document` (around line 277)

Find:
```python
    data = render_docx(spec.template_path, ctx)
    if fr_number in CHECKBOX_FORMS:
        data = apply_checkbox_selection(data, standards_codes)
        data = apply_standard_highlighting(data, standards_codes)
        data = apply_audit_type_highlighting(data, audit_set.audit_type or "")
    return spec.output_filename, data
```

Replace with:
```python
    data = render_docx(spec.template_path, ctx)
    # Always apply colour highlighting (safe no-op on forms without standard/audit-type cells).
    data = apply_standard_highlighting(data, standards_codes)
    data = apply_audit_type_highlighting(data, audit_set.audit_type or "")
    # Tick legacy Word checkboxes only on FR.220 / FR.221.
    if fr_number in CHECKBOX_FORMS:
        data = apply_checkbox_selection(data, standards_codes)
    return spec.output_filename, data
```

### 2b. `build_audit_set_zip` inner loop (around line 337)

Find:
```python
                        data = render_docx(doc.template_path, rctx)
                        if doc.fr_number in CHECKBOX_FORMS:
                            data = apply_checkbox_selection(data, standards_codes)
                            data = apply_standard_highlighting(data, standards_codes)
                            data = apply_audit_type_highlighting(
                                data, audit_set.audit_type or ""
                            )
```

Replace with:
```python
                        data = render_docx(doc.template_path, rctx)
                        # Always apply colour highlighting (safe no-op on forms without
                        # standard/audit-type cells).
                        data = apply_standard_highlighting(data, standards_codes)
                        data = apply_audit_type_highlighting(data, audit_set.audit_type or "")
                        # Tick legacy Word checkboxes only on FR.220 / FR.221.
                        if doc.fr_number in CHECKBOX_FORMS:
                            data = apply_checkbox_selection(data, standards_codes)
```

---

## Fix 2 — `filler.py`: add `audit_type_str`, `stage_1_date`, `stage_2_date`, `surveillance_date`

Open `build_base_context()`. Find the block that already has:
```python
        # Audit type
        "audit_type": audit_type,
        "audit_type_display": AUDIT_TYPE_DISPLAY.get(audit_type, audit_type),
        "is_initial": is_initial,
        "is_surveillance": is_surveillance,
        "is_recertification": is_recertification,
        "is_special": is_special,
```

After `"is_special": is_special,` add:
```python
        "audit_type_str": AUDIT_TYPE_DISPLAY.get(audit_type, audit_type),
```

(This is the same value as `audit_type_display`. The field maps for FR.223/FR.224/FR.225
reference the key `audit_type_str`; without it the cells are always blank.)

Then find the block that has:
```python
        "stage1_dates": format_date_range(stage1.audit_date_start, stage1.audit_date_end) if stage1 else "",
        "stage2_dates": format_date_range(stage2.audit_date_start, stage2.audit_date_end) if stage2 else "",
```

After `"stage2_dates": ...` add:
```python
        # Underscore-named aliases used by FR.233 (stage_1_date = Stage 1 audit date,
        # stage_2_date = Stage 2 OR surveillance audit date) and by FR.232, FR.231,
        # FR.211 via the field maps.
        "stage_1_date": format_date_range(stage1.audit_date_start, stage1.audit_date_end) if stage1 else "",
        "stage_2_date": (
            format_date_range(stage2.audit_date_start, stage2.audit_date_end) if stage2
            else (format_date_range(start, end) if (is_surveillance or is_recertification) else "")
        ),
        "surveillance_date": format_date_range(start, end) if is_surveillance else "",
```

(`start` and `end` are already local variables defined just above the `return {}` block as
`start = stage.audit_date_start` and `end = stage.audit_date_end`.)

### What each key produces for each stage

| Context key | Stage 1 render | Stage 2 render | Surveillance render |
|---|---|---|---|
| `stage_1_date` | Stage 1 dates (historical) or "" | Stage 1 historical dates | Stage 1 historical dates or "" |
| `stage_2_date` | "" | Stage 2 dates | Surveillance dates (fallback = `audit_dates`) |
| `surveillance_date` | "" | "" | Surveillance dates |

For FR.233 (Review & Decision):
- `stage_1_date` cell → Stage 1 actual date ✅
- `stage_2_date` cell → "Stage 2 / Surveillance / Re-cert Audit Date" ✅

---

## Fix 3 — `field_maps.py`: rename mis-labelled date keys

Several forms labelled their "Audit Date/s" cell (= current stage dates) as
`"stage_1_date"` or `"stage_2_date"`. This conflates "the dates of this document's own
audit" with "the Stage 1 historical date". Rename them to `"audit_dates"` so they pick up
the always-correct `audit_dates` value from context (which is already `format_date_range(start, end)` for the current stage).

### In `FR223_MAP`

Find:
```python
    "audit_type_str":        (0, 10, 1),
    "stage_1_date":          (0, 10, 4),   # Audit Date/s
```

Change to:
```python
    "audit_type_str":        (0, 10, 1),
    "audit_dates":           (0, 10, 4),   # Audit Date/s (current stage)
```

### In `FR224_MAP`

Find:
```python
    "audit_type_str":        (0, 10, 1),
    "stage_1_date":          (0, 10, 4),
```

Change to:
```python
    "audit_type_str":        (0, 10, 1),
    "audit_dates":           (0, 10, 4),   # Audit Date/s (current stage)
```

### In `FR232_MAP`

Find:
```python
    "stage_2_date":          (4, 0, 1),
```

Change to:
```python
    "audit_dates":           (4, 0, 1),   # Audit Date/s (current stage — Stage 2 or Surveillance)
```

### In `FR231_MAP`

Find:
```python
    "stage_1_date":          (4, 0, 1),    # Audit Date/s
```

Change to:
```python
    "audit_dates":           (4, 0, 1),    # Audit Date/s (current stage)
```

### In `FR211_MAP`

Find:
```python
    "stage_1_date":          (0, 1, 1),    # Audit Date/s — caller may override with stage date
```

Change to:
```python
    "audit_dates":           (0, 1, 1),    # Audit Date/s (current stage)
```

**After these renames:** `"stage_1_date"` remains ONLY in `FR233_MAP` (where it genuinely
means "Stage 1 Audit Date" as a historical reference) and nowhere else. `"stage_2_date"`
remains ONLY in `FR233_MAP` (where it means "Stage 2 / Surveillance / Re-cert Audit Date").

---

## Fix 4 — `resolver.py`: fix `_build_surveillance` for MDQMS and ISMS

The current `_build_surveillance` puts FR.232, FR.234, and FR.211 into one combined loop
that runs for all three standard groups. That means:
- MDQMS gets FR.232 (wrong — should be FR.232-1, same as `_build_stage_2`)
- ISMS gets FR.232 (wrong — should be FR.229, same as `_build_stage_2`)
- FR.234 is included from whichever group fires first (acceptable, but fragile)

Replace the entire `_build_surveillance` function:

```python
def _build_surveillance(needs_base, needs_mdqms, needs_isms, sub: str, missing: list[str]) -> list[DocumentSpec]:
    specs: list[DocumentSpec] = []
    seen: set[str] = set()

    # Common plan / meeting / NC forms — same template for all standard groups.
    for fr, fmap in [
        ("FR.223", FR223_MAP), ("FR.224", FR224_MAP), ("FR.225", FR225_MAP),
        ("FR.230", FR230_MAP),
    ]:
        if needs_base:  _add(specs, seen, fr, "base",  sub, fmap, "surveillance", missing)
        if needs_mdqms: _add(specs, seen, fr, "mdqms", sub, fmap, "surveillance", missing)
        if needs_isms:  _add(specs, seen, fr, "isms",  sub, fmap, "surveillance", missing)

    # Audit report — standard-specific form (mirrors _build_stage_2).
    if needs_base:
        _add(specs, seen, "FR.232",   "base",  sub, FR232_MAP, "surveillance", missing)
    if needs_mdqms:
        _add(specs, seen, "FR.232-1", "mdqms", sub, FR232_MAP, "surveillance", missing)
    if needs_isms:
        _add(specs, seen, "FR.229",   "isms",  sub, FR232_MAP, "surveillance", missing)

    # Auditor assessment — one per standard group.
    if needs_base:  _add(specs, seen, "FR.211", "base",  sub, FR211_MAP, "surveillance", missing)
    if needs_mdqms: _add(specs, seen, "FR.211", "mdqms", sub, FR211_MAP, "surveillance", missing)
    if needs_isms:  _add(specs, seen, "FR.211", "isms",  sub, FR211_MAP, "surveillance", missing)

    # Single-instance forms (primary group only).
    primary = "base" if needs_base else ("mdqms" if needs_mdqms else ("isms" if needs_isms else None))
    if primary:
        _add(specs, seen, "FR.234", primary, sub, FR234_MAP, "surveillance", missing)
        _add(specs, seen, "FR.233", primary, sub, FR233_MAP, "surveillance", missing)

    return specs
```

This mirrors `_build_stage_2` exactly: FR.232 → base, FR.232-1 → mdqms, FR.229 → isms.

---

## Verification checklist

1. Generate a QMS-only surveillance audit package.
   - Confirm FR.232 (not FR.232-1 or FR.229) is in the ZIP.
   - Confirm selected standard cells in FR.223 / FR.224 are green.
   - Confirm the "Audit Date/s" cell in FR.223, FR.224, FR.232 shows the surveillance dates.
   - Confirm FR.233 shows surveillance dates in the "Stage 2 / Surveillance" column.
   - Confirm FR.234 shows surveillance dates.

2. Generate an ISMS-only surveillance package.
   - Confirm FR.229 is in the ZIP (not FR.232).
   - Confirm no RENDER_ERRORS.txt in the ZIP.

3. Generate a MDQMS-only surveillance package.
   - Confirm FR.232-1 is in the ZIP (not FR.232).

4. Generate a QMS+ISMS integrated surveillance package.
   - Both FR.232 (base) and FR.229 (isms) in ZIP.
   - FR.223 and FR.224 appear once each (deduplication by `seen`).

5. Generate a QMS-only Stage 2 (initial cert) package and confirm it is UNCHANGED:
   - FR.232 present, audit dates in date cell, green highlighting.
   - No regressions from the field_maps renaming.

6. Download any existing initial cert package with FR.220.
   - Confirm checkboxes are still ticked (apply_checkbox_selection still runs for FR.220/FR.221).
   - Confirm green shading still correct.

## No DB migration needed

All changes are in Python logic only. No schema changes, no new columns.
