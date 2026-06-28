# Portal 87 — FR.223 Audit Plan: fix empty `auditors[0].standard` / `technical_experts[0].standard`

## Root cause

The FR.223 template contains Jinja2 tags like:
```
{{ auditors[0].standard if auditors|length > 0 else "" }}
{{ technical_experts[0].standard if technical_experts|length > 0 else "" }}
```

These render as empty strings for every audit set.

**Why `standard` is always empty:**

`build_auditor_scope_strings()` in `filler.py` builds the `auditors` list by calling `_enrich(member)` on each item from `stage.auditors`. The `member` dict comes from the `stage.auditors` JSON column — stored by the frontend at `clients/[id]/page.tsx` line ~1723:

```typescript
patch({ auditors: [...edit.auditors, { id: found.id ?? '', name: found.name }] })
```

The frontend saves auditors as `{ id, name }` only. No `standard` field is ever sent. So `stage.auditors` is a JSON array of `{id, name}` objects — `standard` is absent from every entry.

`_enrich(member)` spreads `**member` and adds `ea_code` and `covered_codes_display`:

```python
def _enrich(member: dict) -> dict:
    codes = disp(auditor_lookup.get(member.get("id")), member)
    return {
        **member,
        "ea_code": codes or (member.get("ea_code") or ""),
        "covered_codes_display": codes,
    }
```

No `"standard"` key is ever added. When the template renders `{{ auditors[0].standard }}`, docxtpl falls back to an empty string.

**The same applies to the lead auditor.** The context dict returned by `build_auditor_scope_strings` includes `"lead_auditor_codes"` but no `"lead_auditor_standard"`, so any template tag `{{ lead_auditor_standard }}` also renders blank.

---

## The fix: `backend/audit_set/filler.py`

Modify `build_auditor_scope_strings` to derive the `standard` string for each enriched member.

The `standard` string for an auditor is the comma-joined list of ISO standard names (from `required_scope` keys) for which this auditor holds a matching qualification. If the auditor profile is unavailable or has no matching qualifications, fall back to all audit standards.

The `required_scope` dict is already passed into `build_auditor_scope_strings`. Its keys are ISO standard names (e.g., `"ISO 13485"`, `"ISO 9001:2015"`, `"ISO 22000:2018"`). The helper `_compute_covered_scope` already does the matching against `aud.standard_qualifications`. Reuse it: if the covered dict is non-empty, its keys are the standards the auditor is confirmed for. If empty (profile present but codes empty), fall back to a direct qualification scan.

### Change 1 — `_enrich` inner function inside `build_auditor_scope_strings`

Current (lines ~530–540):
```python
def _enrich(member: dict) -> dict:
    """Return the member dict with both ea_code and covered_codes_display
    guaranteed to be strings (never Python None, which docxtpl renders as 'None')."""
    codes = disp(auditor_lookup.get(member.get("id")), member)
    return {
        **member,
        # Keep ea_code as a non-None string so templates using {{ auditor.ea_code }}
        # also work correctly.
        "ea_code": codes or (member.get("ea_code") or ""),
        "covered_codes_display": codes,
    }
```

Replace with:
```python
def _enrich(member: dict) -> dict:
    """Return the member dict with ea_code, covered_codes_display, and standard
    guaranteed to be strings (never Python None, which docxtpl renders as 'None').

    `standard` is the comma-joined list of ISO standard names from required_scope
    that this auditor is qualified for, e.g. 'ISO 13485' or 'ISO 9001:2015, ISO 14001:2015'.
    Falls back to all required_scope keys when the profile is unavailable or no
    qualifications match the scope entries.
    """
    member_id = member.get("id")
    aud = auditor_lookup.get(member_id)
    codes = disp(aud, member)

    # Derive standard string from auditor qualifications matched to required_scope.
    if aud and aud.standard_qualifications:
        # Primary: use the keys from _compute_covered_scope (auditor has matching codes).
        covered_stds = list(
            _compute_covered_scope(aud.standard_qualifications, required_scope).keys()
        )
        # Secondary fallback: auditor is qualified for the standard but required_scope
        # has no specific codes to match (e.g. medical scope with empty codes list).
        if not covered_stds:
            quals = [q for q in aud.standard_qualifications if q.is_qualified is not False]
            covered_stds = [
                iso for iso in (required_scope or {}).keys()
                if any(_std_match(iso, q.standard_code or "") for q in quals)
            ]
        standard_str = ", ".join(covered_stds) if covered_stds else ", ".join((required_scope or {}).keys())
    else:
        # No auditor profile found — list all audit standards.
        standard_str = ", ".join((required_scope or {}).keys())

    return {
        **member,
        "ea_code": codes or (member.get("ea_code") or ""),
        "covered_codes_display": codes,
        "standard": standard_str,
    }
```

### Change 2 — add `lead_auditor_standard` to the returned context dict

The FR.223 template may also reference `{{ lead_auditor_standard }}`. Compute it for the lead auditor using the same logic and add it to the returned dict.

Current `return` statement (lines ~544–548):
```python
return {
    "lead_auditor_codes": disp(auditor_lookup.get(stage.lead_auditor_id)),
    "auditors": enriched_auditors,
    "technical_experts": enriched_tes,
}
```

Replace with:
```python
# Compute lead auditor standard string using the same logic as _enrich.
_lead_aud = auditor_lookup.get(stage.lead_auditor_id)
if _lead_aud and _lead_aud.standard_qualifications:
    _lead_covered = list(
        _compute_covered_scope(_lead_aud.standard_qualifications, required_scope).keys()
    )
    if not _lead_covered:
        _lead_quals = [q for q in _lead_aud.standard_qualifications if q.is_qualified is not False]
        _lead_covered = [
            iso for iso in (required_scope or {}).keys()
            if any(_std_match(iso, q.standard_code or "") for q in _lead_quals)
        ]
    _lead_standard = ", ".join(_lead_covered) if _lead_covered else ", ".join((required_scope or {}).keys())
else:
    _lead_standard = ", ".join((required_scope or {}).keys())

return {
    "lead_auditor_codes": disp(auditor_lookup.get(stage.lead_auditor_id)),
    "lead_auditor_standard": _lead_standard,
    "auditors": enriched_auditors,
    "technical_experts": enriched_tes,
}
```

---

## What does NOT change

- The frontend — no change. `{id, name}` auditor assignment is correct; the standard is derived server-side from the auditor's qualification record.
- The `AuditorAssignment` schema — `standard: Optional[str] = None` remains as-is; it just won't be used since the server derives it.
- `build_base_context` — unchanged.
- `packager.py` — unchanged; this fix is entirely in `filler.py`.
- All other templates — the new `standard` and `lead_auditor_standard` keys are additive; templates that don't reference them are unaffected.

---

## Verification checklist (post-deploy)

1. Open an ISO 13485 audit set with at least one auditor assigned to the surveillance stage.
2. Generate (or regenerate) FR.223 Audit Plan.
3. In the team table, confirm the auditor's "Standards" column shows `"ISO 13485"`.
4. For an integrated ISO 9001 + ISO 14001 audit set, confirm the auditor shows `"ISO 9001:2015, ISO 14001:2015"`.
5. For an ISO 22000 audit set, confirm the lead auditor's standard shows `"ISO 22000:2018"`.
6. For an audit set where the auditor profile does NOT have a qualifying entry for the audit's standards, confirm it falls back to listing all audit standards (not empty string).

---

## Commit message suggestion

```
Portal 87: fix FR.223 empty auditors[0].standard / lead_auditor_standard

filler.py build_auditor_scope_strings: _enrich() now derives a 'standard'
string for each auditor by matching their standard_qualifications against
required_scope keys via _compute_covered_scope. Falls back to all required
standards when no qualification match exists or auditor profile is missing.
Also adds 'lead_auditor_standard' to the returned context dict.

Root cause: frontend saves auditors as {id, name} only; 'standard' was
never populated in the member dict and never added by _enrich().
```
