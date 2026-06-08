# Augment Prompt — Auto-Derive EA Codes + Auditor Code Fallback

## Problem

Two related issues:

1. **EA/IAF Code, Category, Technical Area show "None"** in all documents (FR.223, FR.224, etc.) — because `ea_code` is never populated unless the user explicitly clicks "derive scope". Most users don't do this.

2. **Auditor EA/IAF Code column is blank** in FR.223 and FR.224 — because `covered_codes_display` relies on `required_scope` (which is also null when derive-scope hasn't been run), and because the auditor assignment JSON has an `ea_code` field that's never used as a fallback.

---

## Fix 1 — Auto-derive scope on audit set create/update

In `backend/audit_set/service.py`, whenever an audit set is created or its scope/standards are updated, automatically run the same derivation logic that the explicit "derive scope" endpoint runs.

Find the function `create_audit_set` (or equivalent) and the update function. After saving the basic audit set data, if `scope_en` is non-empty and `standards` is non-empty, call `derive_required_scope()` and save the result:

```python
# At the end of create_audit_set() and after update_audit_set():
if audit_set.scope_en and audit_set.standards:
    _auto_derive_scope(db, audit_set)

def _auto_derive_scope(db: Session, audit_set: AuditSet) -> None:
    """Auto-run scope derivation when scope + standards are available."""
    try:
        from audit_set.service import derive_required_scope  # or wherever it lives
        result = derive_required_scope(
            scope_en=audit_set.scope_en,
            standards=audit_set.standards,
            ea_code=audit_set.ea_code,  # preserve manual override if set
        )
        # Only overwrite if not manually set by user
        if not audit_set.ea_code and result.get("ea_code"):
            audit_set.ea_code = result["ea_code"]
        if not audit_set.ea_category and result.get("ea_category"):
            audit_set.ea_category = result["ea_category"]
        if not audit_set.ea_technical_area and result.get("ea_technical_area"):
            audit_set.ea_technical_area = result["ea_technical_area"]
        if result.get("required_scope"):
            audit_set.required_scope = result["required_scope"]
        db.commit()
    except Exception as e:
        # Non-blocking: derivation failure should not prevent audit set creation
        import logging
        logging.getLogger(__name__).warning(f"Auto-derive scope failed: {e}")
```

**Important:** If `ea_code` was manually set by the user (non-null before derivation), do NOT overwrite it. The manual override wins.

Find where `derive_required_scope()` is currently defined (likely in `service.py` or `audit_set/service.py`) and call it. If it's in a route handler, extract the logic into a shared service function first.

---

## Fix 2 — Auditor `covered_codes_display` fallback to assignment ea_code

In `backend/audit_set/filler.py`, in `build_auditor_scope_strings()`:

The `AuditorAssignment` schema has an `ea_code` field. When assigning auditors in the planning stage, coordinators can enter the auditor's EA code directly in the assignment. This is stored in `stage.auditors` JSON as `[{"id": "...", "name": "...", "ea_code": "EA 3", "standard": "ISO 9001:2015"}]`.

Currently `covered_codes_display` ignores this `ea_code` field. Add a fallback:

```python
def disp(aud, assignment: dict) -> str:
    """Compute display string for auditor's covered scope.
    Falls back to assignment ea_code if computed scope is empty."""
    if not aud:
        # No auditor profile — use assignment-level ea_code directly
        return assignment.get("ea_code") or ""
    computed = _covered_codes_display(
        _compute_covered_scope(aud.standard_qualifications, required_scope)
    )
    if computed:
        return computed
    # Fallback: use the ea_code from the assignment JSON
    return assignment.get("ea_code") or ""

enriched_auditors = [
    {**a, "covered_codes_display": disp(auditor_lookup.get(a.get("id")), a)}
    for a in (stage.auditors or [])
]
enriched_tes = [
    {**te, "covered_codes_display": disp(auditor_lookup.get(te.get("id")), te)}
    for te in (stage.technical_experts or [])
]
```

For the **lead auditor**, also fall back to `audit_set.ea_code` in `packager.py`:

```python
ctx = build_base_context(audit_set, stage)
ctx.update(build_auditor_scope_strings(stage, auditor_lookup, required_scope))

# EA code fallbacks
if not ctx.get("lead_auditor_codes"):
    ctx["lead_auditor_codes"] = audit_set.ea_code or ""
```

---

## Fix 3 — Frontend: show EA code in auditor assignment UI

Currently when a coordinator assigns an auditor to a stage, there's no UI to enter `ea_code` per assignment. Add a small "EA/IAF Code" field to the auditor assignment row in the planning UI.

- **Label:** "EA/IAF Code" (optional text input, e.g. "EA 3")
- **Location:** Next to the auditor name in the assignment list
- **Saved as:** `ea_code` in the assignment JSON (`stage.auditors[n].ea_code`)

This allows coordinators to manually specify which EA code each auditor covers for this specific audit, even before the full auditor profile is set up.

---

## Fix 4 — Display EA codes in the portal

In `filler.py` context, also add:

```python
# Human-readable EA code string for templates
"ea_code_display": audit_set.ea_code or "",
"ea_category_display": audit_set.ea_category or "",
"ea_technical_area_display": audit_set.ea_technical_area or "",
```

(These already exist as `ea_code`, `ea_category`, `ea_technical_area` with `or ""` from the previous fix — just confirm they're there.)

---

## Testing

1. Create an audit set with scope "Production, packaging, storage, and sales of dried fruit and nut products" + QMS
2. **Without** clicking any "derive scope" button, download the audit package
3. Open FR.223 — "EA/IAF Code" should now show "EA 3" (auto-derived from food keywords)
4. Create an audit set, assign an auditor with ea_code "EA 7" in the assignment, download
5. Open FR.224 — auditor's EA/IAF code column should show "EA 7"

## Commit

```bash
git add backend/audit_set/service.py backend/audit_set/filler.py backend/audit_set/packager.py
git commit -m "feat: auto-derive EA codes on audit set save + auditor ea_code fallback in documents"
git push
```
