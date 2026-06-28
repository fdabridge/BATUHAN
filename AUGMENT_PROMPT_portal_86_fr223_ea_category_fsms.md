# Portal 86 — FR.223 Audit Plan: fix empty ea_category (Category/Subcategory) for ISO 22000 / FSMS audit sets

## Root cause

The FR.223 template uses `{{ ea_category }}` (a live docxtpl Jinja2 tag — confirmed 40 tags in the template XML). `build_base_context()` in `filler.py` sets:

```python
"ea_code":          audit_set.ea_code or "",
"ea_category":      audit_set.ea_category or "",
"ea_technical_area": audit_set.ea_technical_area or "",
```

These come directly from DB columns on `AuditSet`. For ISO 22000 (FSMS) audit sets:

- `audit_set.ea_code` is **always NULL** — `_first_ea_code_from_scope()` in `service.py` only auto-populates this for `type == "ea"` entries in required_scope; FSMS entries have `type == "food"`, so they are skipped.
- `audit_set.ea_category` is **always NULL** — the frontend has no UI field for this column, so it is never sent in the create/update request. Confirmed: searching `frontend/src/app/(app)/clients/[id]/page.tsx` for `ea_category` returns zero matches.

Result: `{{ ea_code }}` and `{{ ea_category }}` render as empty strings in FR.223 for all ISO 22000 audit sets. The cells appear blank in the generated document.

The lead auditor's food chain category ("CI (ISO 22000)") IS correctly rendered in the team table via `{{ lead_auditor_codes }}`, which is computed by `build_auditor_scope_strings()` from the auditor's `scope_category` qualification field. But that result is only merged into `lead_auditor_codes`, not into the header-level `ea_code` / `ea_category`.

The food chain category codes for the audit set are already stored in `audit_set.required_scope`, e.g.:
```json
{"ISO 22000:2018": {"type": "food", "codes": ["CI"]}}
```

This is the authoritative source — it represents what the client is being certified for.

---

## The fix: `backend/audit_set/packager.py`

Add an FSMS fallback block in **two places** — both immediately after the lines:
```python
ctx.update(build_auditor_scope_strings(stage, auditor_lookup, required_scope))
```

The fallback must run after `build_auditor_scope_strings` in case that function ever sets `ea_category` in future; using `not ctx.get(...)` means it only fires when the value is still empty.

---

### Place 1 — `render_single_document` function

Current code (around line 269–272):
```python
    ctx = build_base_context(audit_set, stage, org_attendees=org_attendees)
    ctx.update(build_auditor_scope_strings(stage, auditor_lookup, required_scope))
    if not ctx.get("lead_auditor_codes"):
        ctx["lead_auditor_codes"] = audit_set.ea_code or ""
```

Replace with:
```python
    ctx = build_base_context(audit_set, stage, org_attendees=org_attendees)
    ctx.update(build_auditor_scope_strings(stage, auditor_lookup, required_scope))
    if not ctx.get("lead_auditor_codes"):
        ctx["lead_auditor_codes"] = audit_set.ea_code or ""
    # FSMS fallback: ea_code and ea_category are not stored on AuditSet for
    # ISO 22000 (required_scope uses type="food" which _first_ea_code_from_scope
    # ignores; the frontend sends no ea_category field). Derive both from the
    # food-chain codes already stored in required_scope.
    if "FSMS" in standards_codes:
        _fsms_entry = required_scope.get("ISO 22000:2018") or required_scope.get("FSMS") or {}
        _fsms_codes = _fsms_entry.get("codes") or []
        if not ctx.get("ea_code") and _fsms_codes:
            ctx["ea_code"] = ", ".join(_fsms_codes)
        if not ctx.get("ea_category") and _fsms_codes:
            ctx["ea_category"] = ", ".join(_fsms_codes)
```

---

### Place 2 — `build_audit_set_zip` function

Current code (around line 307–311):
```python
            ctx = build_base_context(audit_set, stage, org_attendees=org_attendees)
            ctx.update(build_auditor_scope_strings(stage, auditor_lookup, required_scope))
            # EA-code fallback for FR.224 display when the auditor profile is incomplete.
            if not ctx.get("lead_auditor_codes"):
                ctx["lead_auditor_codes"] = audit_set.ea_code or ""
            team = build_team_members(stage, auditor_lookup, standards_codes)
```

Replace with:
```python
            ctx = build_base_context(audit_set, stage, org_attendees=org_attendees)
            ctx.update(build_auditor_scope_strings(stage, auditor_lookup, required_scope))
            # EA-code fallback for FR.224 display when the auditor profile is incomplete.
            if not ctx.get("lead_auditor_codes"):
                ctx["lead_auditor_codes"] = audit_set.ea_code or ""
            # FSMS fallback: ea_code and ea_category are not stored on AuditSet for
            # ISO 22000 (required_scope uses type="food" which _first_ea_code_from_scope
            # ignores; the frontend sends no ea_category field). Derive both from the
            # food-chain codes already stored in required_scope.
            if "FSMS" in standards_codes:
                _fsms_entry = required_scope.get("ISO 22000:2018") or required_scope.get("FSMS") or {}
                _fsms_codes = _fsms_entry.get("codes") or []
                if not ctx.get("ea_code") and _fsms_codes:
                    ctx["ea_code"] = ", ".join(_fsms_codes)
                if not ctx.get("ea_category") and _fsms_codes:
                    ctx["ea_category"] = ", ".join(_fsms_codes)
            team = build_team_members(stage, auditor_lookup, standards_codes)
```

---

## What does NOT change

- `filler.py` — `build_base_context` signature and return dict unchanged. The `ea_code` / `ea_category` keys will still be populated from `audit_set.ea_code` / `audit_set.ea_category` when those columns are non-null (ISO 9001, ISO 14001, etc.). The FSMS fallback only fires when the context value is still empty.
- `service.py` — `_first_ea_code_from_scope` logic unchanged; it correctly skips FSMS food-type scope entries. No DB column changes needed.
- Frontend — no change. The food chain category is already stored in `required_scope` (set by `derive_required_scope()` during audit set creation). The frontend doesn't need to send `ea_category` separately.
- Templates — unchanged; `{{ ea_category }}` is already a live Jinja2 tag in the template.
- The fix works for integrated audits (e.g., ISO 22000 + ISO 9001): when the audit set already has `ea_code` set from its QMS scope, the FSMS fallback condition `not ctx.get("ea_code")` is false and the override is skipped — the QMS code takes precedence. If `ea_category` is empty but ea_code is set (QMS), `ea_category` is still derived from the FSMS food chain codes (different columns — this is the correct behaviour: QMS EA numeric code in one cell, food chain category in the other).

---

## Verification checklist (post-deploy)

1. Open any existing ISO 22000 audit set and regenerate the FR.223 Audit Plan.
2. Open the generated PDF. In the header table, confirm:
   - "EA/IAF Code" cell shows the food chain category code (e.g., "CI")
   - "Category/Subcategory" cell shows the same (e.g., "CI") — no longer blank
3. For an integrated ISO 22000 + ISO 9001 audit set:
   - "EA/IAF Code" should show the QMS EA numeric code (audit_set.ea_code)
   - "Category/Subcategory" should show the food chain category from required_scope
4. For a pure ISO 9001 audit set (no FSMS in standards_codes):
   - Confirm the FSMS fallback block is not reached (no regression)
   - ea_code and ea_category render from audit_set.ea_code / audit_set.ea_category as before

---

## Commit message suggestion

```
Portal 86: fix FR.223 empty ea_category / ea_code for ISO 22000 audit sets

packager.py: after building render context, if FSMS is in standards_codes
and ea_code/ea_category are still empty (they always are for FSMS because
_first_ea_code_from_scope skips food-type scope entries and the frontend
sends no ea_category field), derive both from required_scope food-chain
codes. Applied in both render_single_document and build_audit_set_zip.
```
