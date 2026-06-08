# Augment Prompt — Template Fixes Complete: Re-run Pipeline Test

## Summary

All Word template structural issues in `uaf_blank_set copy/` have been resolved programmatically. The pipeline should now generate a clean, zero-error audit package ZIP. Re-run the end-to-end test and report results.

---

## What Was Fixed (do NOT redo these — already applied to files on disk)

### 1. `{%tr if/endif %}` structural fixes across all template copies

**FR.218** (3 copies: 13485, 27001, 9-14-45-22-5001 / Stage 1):
- Table 3 (site rows): Rebuilt with correct 3-row sacrificial pattern for `sites[1]` (condition: `sites|length > 1`) and `sites[2]` (condition: `sites|length > 2`)
- Table 23 (standard rows): Rebuilt with 3-row sacrificial pattern for each standard: QMS, EMS, OHSMS, FSMS, ISMS, MDQMS, ABMS, ENMS

**FR.222** (3 copies / Stage 1):
- Table 0 site rows: Added `{%tr if sites|length > 1 %}` / `{%tr endif %}` wrappers around `sites[1]` and `sites[2]` rows (was missing — caused `list object has no element 2` error)
- Field name corrections: `sites[n].scope` → `sites[n].process_description`, `sites[n].employees` → `sites[n].employee_count`, removed `sites[n].audit_days` (field doesn't exist per-site)

**FR.225** (9 copies / Stage 1 and Stage 2):
- Orphan `{%tr endif %}` rows removed; all conditional blocks properly wrapped

**FR.232** (2 copies) and **FR.232-1** (2 copies) / Stage 2:
- Site rows wrapped with proper conditional sacrificial pattern

**FR.231-1** (1 copy, 13485 / Stage 1):
- Rows for `auditors[1]`, `technical_experts[0]`, `observers[0]`: were packed inline as `{%tr if cond %}data{%tr endif %}` in a single row — split into 3-row sacrificial pattern
- TC 1 and TC 2 in each data row cleaned to `{{ auditors[1].name }}`, `{{ technical_experts[0].name }}`, `{{ observers[0].name }}`

**FR.229** (2 copies, 27001 / Stage 2 and Surveillance):
- Site rows for `sites[1]` and `sites[2]`: inline `{%trifX%}data{%trendif%}` in single row — split into 3-row sacrificial pattern

### 2. proofErr elements removed from all 69 `.docx` files

Word inserts `<w:proofErr>` spell-check markers that split Jinja2 tags across XML runs. Removed from all templates.

### 3. Split-run merging applied

`{{ phone }}`, `{{ email }}`, and other short tags were split across consecutive `<w:r>` runs. Run-merging applied to FR.231-1 and FR.229 to fix `unexpected '/'` and `expected token 'end of print statement'` errors.

---

## Known Behaviour (not errors)

- **FR.229 renders slowly (~28s)**: The ISMS/PIMS Audit Report is a 225KB file (7MB uncompressed XML). `docxtpl.render()` takes ~28 seconds on this file. This is expected — not a bug. Set a generous timeout (60s) in the test for FR.229.
- **FR.222 Audit Duration column is blank for sites**: We removed `sites[n].audit_days` from the template because per-site audit days are not in the data model. The cell is now empty. This is intentional.

---

## Context Field Mapping to Verify (filler.py `build_base_context`)

The following fields were corrected in templates to match exactly what `filler.py` puts in the context:

| Template used (old) | Correct field (now in template) | Source in context |
|---|---|---|
| `sites[n].scope` | `sites[n].process_description` | `audit_set.sites[n]["process_description"]` |
| `sites[n].employees` | `sites[n].employee_count` | `audit_set.sites[n]["employee_count"]` |
| `sites[n].audit_days` | _(removed)_ | N/A — per-site days not tracked |

---

## Test to Re-run

Run the existing test file:

```bash
cd backend
pytest tests/test_uaf_pipeline.py -v --tb=short
```

If the test file does not exist yet, create it at `backend/tests/test_uaf_pipeline.py` using the fixture and assertions from `AUGMENT_PROMPT_uaf_end_to_end_test.md` (which is in the workspace).

---

## Expected Results

All 6 tests should now pass:

| Test | Expected | Notes |
|---|---|---|
| `test_stage1_zip_contents` | PASS | FR.218, FR.222, FR.223, FR.224×3, FR.211×3, FR.225, FR.230, FR.231 |
| `test_stage2_zip_contents` | PASS | FR.229, FR.231-1 or FR.232, FR.224×2, FR.211×2 (no TE on stage 2) |
| `test_no_render_errors` | **NOW PASS** | Previously failed on FR.218 + FR.222 structural issues — fixed |
| `test_fr222_conditional_rows` | **NOW PASS** | sites[1] conditional, QMS+EMS blocks present, no OHSMS/FSMS |
| `test_date_math` | PASS | Was already passing |
| `test_download_endpoint` | PASS | Was already passing |

---

## If Any Test Still Fails

Report the **exact error message and traceback** — do NOT ask clarifying questions. The answers are:

1. **"Variable X is undefined"** → The variable is missing from `filler.py`'s `build_base_context()`. Add it using data from `audit_set` or `stage`.
2. **"list object has no element N"** → A `sites[N]` reference is not wrapped in a `{%tr if sites|length > N %}` conditional. The fix is to add the 3-row sacrificial wrapper (see FR.222 fix above for pattern).
3. **"Encountered unknown tag 'endif'"** → An inline `{%tr if %}...{%tr endif %}` exists in a single row's cell — needs to be split into 3-row pattern.
4. **"unexpected '/'"** or **"expected token 'end of print statement'"** → Split runs. Apply run-merging: merge consecutive `<w:r>` elements in the same `<w:p>` where combined text spans a `{{` / `}}` boundary.
5. **FR.229 timeout** → Increase the test timeout for that specific file to 90 seconds.
