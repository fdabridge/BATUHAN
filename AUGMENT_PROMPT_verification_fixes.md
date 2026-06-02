# Verification Fixes — 2 HIGH + 2 LOW

Everything in the platform is logically correct except these four items found in the logic verification audit. Fix all four.

---

## FIX 1 — HIGH — `personnel` missing from backend Pydantic schema → auto-calc never fires

**File:** `backend/audit_set/schemas.py`
**Class:** `AuditSetResponse` (~line 148)

The ORM model has `personnel` (a JSON column). The frontend TypeScript type has `personnel?: AuditSetPersonnel | null`. But the Pydantic `AuditSetResponse` schema does not declare `personnel`, so Pydantic silently drops it from every API response.

Consequence: `data.personnel` is always `undefined` in the frontend. The auto-calc `useEffect` computes `totalPersonnel = 0` every time and never fires. Legacy records (or any record where `man_day_result` is null) never auto-recalculate, even when the coordinator entered employees at creation.

**Fix — add `personnel` to `AuditSetResponse`:**

Find the `AuditSetResponse` Pydantic schema. Add this field:
```python
personnel: Optional[dict] = None
```

If the schema uses `model_config = ConfigDict(from_attributes=True)` (SQLAlchemy ORM mode), this will automatically read from `audit_set.personnel` which is a JSON column storing `{full_time, part_time, subcontractors, seasonal, unskilled}`.

Also add `unskilled` to the frontend TypeScript type:

**File:** `frontend/src/types/index.ts`
**Interface:** `AuditSetPersonnel`

```typescript
export interface AuditSetPersonnel {
  full_time?:      number
  part_time?:      number
  subcontractors?: number
  seasonal?:       number
  unskilled?:      number   // was missing — add this
}
```

---

## FIX 2 — HIGH — Query param name mismatch: frontend sends `required_scope`, backend reads `required_categories`

**File:** `frontend/src/app/(app)/clients/[id]/page.tsx` — ~line 509

The frontend builds the auditor availability query and sets:
```typescript
params.set('required_scope', reqCatStr)
```

But `backend/api/routes/auditors.py` declares the FastAPI query parameter as `required_categories`. FastAPI binds query params by name — if the name doesn't match, the backend receives `None` for `required_categories`. Consequence: `covered_scope` is empty for every auditor, the zero-coverage filter removes them all, and the dropdown is empty whenever dates are picked.

**Fix — align the parameter name in the frontend:**

Change:
```typescript
params.set('required_scope', reqCatStr)
```
To:
```typescript
params.set('required_categories', reqCatStr)
```

Do not change the backend parameter name. The frontend must match the backend.

---

## FIX 3 — LOW — `_create_auto_stages()` else branch silently handles unknown audit types

**File:** `backend/audit_set/service.py`
**Function:** `_create_auto_stages()` — the `else` branch (~line 320)

Unknown or future audit types (e.g. `"transfer"`, `"scope_extension"`) silently fall into `else` and produce Stage 1 + Stage 2. This is a fragility risk, not a live bug.

**Fix — make the else branch explicit and log a warning:**

```python
    else:
        # Recertification and any unrecognised type — default to Stage 1 + Stage 2
        logger.warning(
            "[AuditSet] Unknown audit_type=%r for id=%s — defaulting to stage_1 + stage_2",
            audit_type, audit_set.id,
        )
        stage_defs = [
            ("stage_1", 1, result.get("final_recert_ph1") if result else None),
            ("stage_2", 2, result.get("final_recert_ph2") if result else None),
        ]
```

---

## FIX 4 — LOW — ZIP generated silently with missing templates, no warning returned

**File:** `backend/audit_set/resolver.py`
**Function:** `_add()` (~line 87)

When `_find_template()` returns `None` (template file not on disk), `_add()` silently skips it. The ZIP downloads successfully but may be incomplete with no indication of what is missing.

**Fix — collect missing templates and include a manifest:**

In `build_audit_set_zip()`, track which templates were not found and add a `MISSING_TEMPLATES.txt` file to the ZIP if any are absent:

```python
missing: list[str] = []

def _add(subfolder: str, filename: str) -> None:
    template = _find_template(subfolder, filename)
    if template is None:
        missing.append(f"{subfolder}/{filename}")
        logger.warning("[Resolver] Template not found: %s/%s", subfolder, filename)
        return
    zf.write(template, arcname=f"{subfolder}/{filename}")

# ... after all _add() calls, before closing zf:
if missing:
    manifest = "The following templates were not found and are missing from this package:\n\n"
    manifest += "\n".join(f"  - {m}" for m in missing)
    zf.writestr("MISSING_TEMPLATES.txt", manifest)
```

---

## VERIFICATION

1. Create a new audit set with 30 full-time employees. Open the client page. `ManDaySection` must show calculation results immediately — no QuickCalc, no clicks. This verifies Fix 1 (personnel now serialized → auto-calc fires).

2. Select dates for a stage. Open the auditor dropdown. Auditors must appear, filtered to those covering the required scope codes, with labels showing `EA 3 (ISO 9001) | CIV CIII (ISO 22000)`. This verifies Fix 2 (param name aligned → backend receives required_categories → covered_scope computed → dropdown populated).

3. Check the audit set API response directly (`GET /api/audit-sets/{id}`). The JSON must include a `personnel` key with the stored employee counts. This verifies Fix 1 at the API level.

---

## Files changed

| File | Change |
|---|---|
| `backend/audit_set/schemas.py` | Add `personnel: Optional[dict] = None` to `AuditSetResponse` |
| `frontend/src/types/index.ts` | Add `unskilled?: number` to `AuditSetPersonnel` |
| `frontend/src/app/(app)/clients/[id]/page.tsx` | Change `params.set('required_scope', ...)` to `params.set('required_categories', ...)` |
| `backend/audit_set/service.py` | Add `logger.warning(...)` to `else` branch in `_create_auto_stages()` |
| `backend/audit_set/resolver.py` | Track missing templates, write `MISSING_TEMPLATES.txt` to ZIP if any are absent |
