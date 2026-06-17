# Prompt 36 — System Integrity Audit & Repair

## Purpose

After 35 prompts of incremental feature work, this prompt is a **top-to-bottom connection
audit** of the entire BATUHAN / Certiva platform. It reads every layer of the system,
finds gaps, dead ends, inconsistencies, and known bugs — then fixes all of them.

This is NOT a feature addition. It is a correctness and completeness pass.

---

## Part A — Known Bugs to Fix First (confirmed from code review)

These are concrete defects found before any new reading begins. Fix them immediately.

---

### A1 — Duplicate column definition in `backend/audit_set/db_models.py`

The `application_data` column is defined **twice** in the `AuditSet` class (it was added
once in the model and the safe-migration comment block was accidentally duplicated by the
Prompt 35 implementation). SQLAlchemy emits a deprecation warning and uses the last
definition, which is fragile. The duplicate must be removed.

**Find:** inside the `AuditSet` class, there are two identical consecutive blocks:

```python
# ── Standard-specific application data ────────────────────────────────────
application_data = Column(JSON, nullable=True)   # EnMS/FSMS/ISMS inputs from application form

# ── Standard-specific application data ────────────────────────────────────
application_data = Column(JSON, nullable=True)   # EnMS/FSMS/ISMS inputs from application form
```

**Fix:** Remove the second block entirely. Keep only one:

```python
# ── Standard-specific application data ────────────────────────────────────
application_data = Column(JSON, nullable=True)   # EnMS/FSMS/ISMS inputs from application form
```

---

### A2 — Duplicate migration call in `create_tables()`

Also in `db_models.py`, inside `create_tables()`, the same migration line appears twice:

```python
# Prompt 35 — standard-specific application data
_safe_add_column("audit_sets", "application_data JSON")
# Prompt 35 — standard-specific application data
_safe_add_column("audit_sets", "application_data JSON")
```

**Fix:** Remove the duplicate. Only one line:

```python
# Prompt 35 — standard-specific application data
_safe_add_column("audit_sets", "application_data JSON")
```

---

### A3 — Inline `import math` inside `_run_calculation()` in `backend/audit_set/service.py`

Prompt 35 added `import math as _math` inside the function body. This works but is
non-idiomatic and will trigger linter warnings. 

**Fix:** Check if `import math` exists at the top of `service.py`. If not, add it to
the import block at the top of the file (after the stdlib imports):

```python
import math
```

Then, inside `_run_calculation()`, replace `_math.ceil(...)` with `math.ceil(...)` and
remove the inline `import math as _math` line.

---

### A4 — `_writeback_personnel_split()` ignores FTE conversion

`_writeback_personnel_split()` computes `total_employees` without applying the
`part_time_fte_factor` from `application_data`. This means the written-back
`office_employees` and `repetitive_employees` values are inconsistent with what
`_run_calculation()` computed (which DOES apply FTE conversion per Prompt 35).

**Fix:** Update `_writeback_personnel_split()` to mirror the FTE conversion logic:

```python
def _writeback_personnel_split(audit_set: AuditSet) -> None:
    """Merge derived office_employees + repetitive_employees back into the
    personnel JSON so downstream document generation can read them directly.
    Mirrors the FTE conversion logic in _run_calculation()."""
    p = dict(audit_set.personnel or {})
    full_time      = int(p.get("full_time", 0))
    part_time      = int(p.get("part_time", 0))
    subcontractors = int(p.get("subcontractors", 0))
    seasonal       = int(p.get("seasonal", 0))
    unskilled      = int(p.get("unskilled", 0))

    # Apply same FTE conversion as _run_calculation()
    app_data = audit_set.application_data or {}
    pt_factor = float(app_data.get("part_time_fte_factor", 0.5))
    subcontractors_in_scope = bool(app_data.get("subcontractors_in_scope", True))

    pt_fte   = math.ceil(part_time * pt_factor)
    sub_eff  = subcontractors if subcontractors_in_scope else 0
    total_employees      = full_time + pt_fte + sub_eff + seasonal + unskilled
    repetitive_roles     = p.get("repetitive_roles", [])
    repetitive_employees = sum(r.get("employee_count", 0) for r in repetitive_roles)
    office_employees     = max(0, total_employees - repetitive_employees)

    p["office_employees"]     = office_employees
    p["repetitive_employees"] = repetitive_employees
    audit_set.personnel = p
    flag_modified(audit_set, "personnel")
```

---

## Part B — Layer-by-Layer Connection Audit

For each layer below, **read the relevant files**, check the listed connections, and
**fix any issue found**. Document every fix made.

---

### Layer 1 — Database ↔ ORM (`db_models.py`)

**Read:** `backend/audit_set/db_models.py`

**Check and fix:**

1. **Column completeness**: Every column that the service layer reads with `audit_set.xxx`
   must be defined as a `Column(...)` in the `AuditSet` class. Walk through `service.py`,
   `workflow_router.py`, `apply_router.py`, `schemas.py`, and the resolver/filler — list
   every `audit_set.xxx` attribute access and confirm each has a matching column
   definition. Report any attribute that is accessed but not a proper Column.

2. **`AuditSetStage` completeness**: Read `audit_set/db_models.py` for `AuditSetStage`
   class. Read `service.py` and `audit_set/schemas.py` for every field accessed on stage
   objects. Confirm all are defined columns.

3. **Migration completeness**: Verify that every Column in `AuditSet` that is NOT in the
   original `Base.metadata.create_all()` definition (i.e., was added after first deploy)
   has a corresponding `_safe_add_column(...)` call in `create_tables()`. The
   `_safe_add_column` pattern uses `ALTER TABLE ... ADD COLUMN` which is idempotent.
   Add any missing migration lines.

4. **visual_signature_placements table**: Check that the `_safe_add_column` calls for
   `otp_hash`, `otp_expires`, `signed_ip` reference the correct table name as it exists
   in the signing ORM models.

---

### Layer 2 — ORM ↔ Pydantic Schemas (`schemas.py`)

**Read:** `backend/audit_set/schemas.py`

**Check and fix:**

1. **`AuditSetResponse.model_config`**: The response schema MUST have
   `model_config = ConfigDict(from_attributes=True)` so that SQLAlchemy ORM objects
   can be serialized via `AuditSetResponse.model_validate(orm_obj)`. If it is missing
   or only has `orm_mode = True` (Pydantic v1 style), update it to the Pydantic v2
   form: `model_config = ConfigDict(from_attributes=True)`. Import `ConfigDict` from
   `pydantic` if not already imported.

2. **`ApplicationDataSchema` completeness**: After Prompt 35, `ApplicationDataSchema`
   must exist in `schemas.py` with all the fields defined in Prompt 35. Verify it is
   present. If missing, add the full class definition as specified in Prompt 35 Change 2.

3. **`AuditSetResponse` field coverage**: The frontend's `types/index.ts` TypeScript
   interface must match `AuditSetResponse`. Walk through every field in `AuditSetResponse`
   and verify it is either (a) in the TypeScript type already, or (b) added below in
   Layer 7.

4. **`Optional` and `date` imports**: Confirm `from typing import Optional` and
   `from datetime import date, datetime` are present at the top of `schemas.py`.

5. **`AuditSetCreateSchema` ↔ `create_audit_set()`**: Every field in
   `AuditSetCreateSchema` must be read by `create_audit_set()`. Walk through the schema
   fields and the service function together. Report and fix any field defined in the
   schema but silently ignored in the service.

---

### Layer 3 — Service layer (`service.py`)

**Read:** `backend/audit_set/service.py` (full file)

**Check and fix:**

1. **`_run_calculation()` field mapping completeness**: `ExtractedFormData` has these
   fields that must all be explicitly set in the `form_data = ExtractedFormData(...)`
   call:
   - `org_name`, `standards`, `audit_type`, `scope`
   - `total_employees`, `office_employees`, `repetitive_employees`
   - `subcontractors`, `seasonal_employees`
   - `employees_per_shift` (from `personnel.shift_1_count` or `shift_count`)
   - `sites` (as SiteInfo list)
   - `haccp_studies` (from `application_data.fsms_haccp_studies`)
   - `integration_yes_count`
   - `classifications` (default to Medium; sector-specific as future improvement)
   - `annual_energy_tj`, `num_energy_types`, `num_seus`
   - `scope_integration_level`
   - `food_chain_categories`
   - `fsms_offsite_storage_count` (NEW — from `application_data`)
   - `fsms_separate_head_office` (NEW — from `application_data`)
   
   **Specifically check**: Is `haccp_studies` being passed? It exists in both
   `ExtractedFormData` and `application_data`. Add it to the `form_data` constructor:
   ```python
   haccp_studies=int(app_data.get("fsms_haccp_studies") or 0) or None,
   ```
   (Use None if 0 to preserve the "not provided" semantics of the model.)

2. **`quick_calculate()` scope priority**: In `quick_calculate()`, after the personnel
   patch, if `audit_set.application_data` has EnMS or FSMS data, the calculation will
   correctly pick those up from the existing column — no change needed. But verify that
   if a user updates `application_data` via `update_planning()` and then calls
   `quick_calculate()`, the new `application_data` is used. Since both operations commit
   to DB and `_run_calculation()` reads from the ORM object (which was refreshed or
   will be), this should work. Confirm and document.

3. **`derive_required_scope()` ↔ `application_data` priority**: When
   `application_data.fsms_food_chain_categories` is non-empty, `_run_calculation()`
   uses those explicit categories instead of the keyword-derived ones. However,
   `required_scope` (the DB column) still holds the old keyword-derived data.
   This inconsistency won't affect calculation (priority logic is correct) but WILL
   affect any code that reads `required_scope` directly for display. Check if any
   resolver or template filler reads `required_scope.ISO 22000.codes` for document
   content. If yes, add logic to override `required_scope` with `application_data`
   food chain categories when both are present.

4. **Standard code normalization**: In `_run_calculation()`, `standards = [_CODE_TO_ISO.get(s, s) for s in ...]`. Verify `_CODE_TO_ISO` contains mappings for ALL 8 codes used by the form:
   - `QMS` → `ISO 9001` ✓
   - `EMS` → `ISO 14001` ✓  
   - `OHSMS` → `ISO 45001` ✓
   - `FSMS` → `ISO 22000` ✓
   - `ISMS` → `ISO 27001` ✓
   - `ENMS` → `ISO 50001` ✓
   - `MDQMS` → `ISO 13485` ✓
   - `ABMS` → `ISO 37001` — **this standard has no engine handler** (see Layer 4 below)

---

### Layer 4 — Calculator engine (`calculator/engine.py` + `models.py`)

**Read:** `backend/calculator/engine.py`, `backend/calculator/models.py`,
`backend/calculator/tables.py`

**Check and fix:**

1. **ISO 37001 (ABMS) — missing engine handler**: `_lookup_standard()` has no branch
   for `ISO 37001`. If ABMS is selected, the `else: raise ValueError(...)` branch fires,
   `_run_calculation()` catches it and returns `None`, and the audit set gets no
   man_day_result. This is a silent dead end.

   **Fix**: Add a fallback branch for ISO 37001 that uses the ISO 9001 Medium Risk table
   as a proxy (ISO 37001 audit time is not specified in IAF MD5; using QMS Medium is
   the standard CB practice). Add the following branch **before** the `else: raise
   ValueError(...)`:

   ```python
   elif _std_match(standard, "ISO 37001") or _std_match(standard, "ISO 37301"):
       # IAF MD5 does not define a specific table for ABMS/CMS.
       # Use ISO 9001 Medium Risk table as proxy — standard CB practice.
       table = ISO9001_TABLES.get("Medium", ISO9001_TABLES["Medium"])
       row = lookup_eps(table, eps)
       if not row:
           raise ValueError(f"EPS {eps} out of range for {standard}")
       _, _, init_t, ph1, ph2, surv, recert_t, r_ph1, r_ph2 = row
       return StandardAuditResult(
           standard=standard, category="Anti-Bribery / Compliance", eps=eps,
           base_init=init_t, base_ph1=ph1, base_ph2=ph2,
           base_surv=surv, base_recert=recert_t,
           base_recert_ph1=r_ph1, base_recert_ph2=r_ph2,
       )
   ```

2. **`ExtractedFormData` default values**: Confirm that `fsms_offsite_storage_count`
   defaults to `0` (not `None`) and `fsms_separate_head_office` defaults to `False`
   (not `None`) in the model. The engine code does `if data.fsms_offsite_storage_count
   and data.fsms_offsite_storage_count > 0:` — this requires an int, not None.

3. **`FSSC 22000` engine matching**: The engine branch is:
   ```python
   elif _std_match(standard, "ISO 22000") or _std_match(standard, "FSSC 22000"):
   ```
   But on the application forms the standard code is `FSMS` (not `FSSC`). In
   `_CODE_TO_ISO`, `FSMS` maps to `"ISO 22000"`. So `FSSC 22000` as a standard name
   would only appear if the CB manually adds it or if `fsms_fssc22000=True` in
   `application_data`. The current design is correct: FSSC 22000 is an add-on to FSMS
   (`ISO 22000`), not a separate standard. The boolean `fsms_fssc22000` in
   `application_data` should trigger the `fssc_reporting_surcharge` output.

   **Fix**: In the `calculate()` function, update the FSSC surcharge detection to also
   check `application_data` for `fsms_fssc22000`:

   Find this code:
   ```python
   fssc_surcharge: float | None = None
   if any(_std_match(s, "FSSC 22000") for s in data.standards):
       fssc_surcharge = FSSC_REPORTING_SURCHARGE_DAYS
   ```

   Add an additional check via a new field on `ExtractedFormData`. The cleanest approach:
   add `fsms_fssc22000: bool = False` to `ExtractedFormData` in `models.py`, and in
   `service.py`'s `_run_calculation()`, pass:
   ```python
   fsms_fssc22000=bool(app_data.get("fsms_fssc22000", False)),
   ```
   Then in `engine.py`, update:
   ```python
   fssc_surcharge: float | None = None
   has_fssc = (
       any(_std_match(s, "FSSC 22000") for s in data.standards)
       or data.fsms_fssc22000
   )
   if has_fssc:
       fssc_surcharge = FSSC_REPORTING_SURCHARGE_DAYS
   ```

4. **All `ExtractedFormData` fields flow to `calculate()`**: Walk through every field
   in `ExtractedFormData` and confirm `calculate()` or `_lookup_standard()` uses it.
   Fields that are extracted but not used should either be documented as "reserved" or
   removed. In particular:
   - `employees_per_shift`: Is this used? If not, document that it is collected but
     currently has no effect on the calculation (reserved for future shift-reduction logic).
   - `haccp_studies`: The ISO22000 table comment says "TFSMS + THACCP combined into
     a single row" — meaning the table already includes HACCP time. Document this
     explicitly in a code comment so future maintainers don't try to add a HACCP
     addition that would double-count.

---

### Layer 5 — API routes (`main.py` + all `*_router.py`)

**Read:** `backend/main.py`, and the following router files:
- `backend/audit_set/apply_router.py`
- `backend/audit_set/workflow_router.py`
- `backend/audit_set/client_router.py` (if it exists)
- All other routers included by `main.py`

**Check and fix:**

1. **Route registration**: Confirm every router is imported and registered via
   `app.include_router(...)` in `main.py`. List all registered routes and their prefixes.
   Verify the frontend's `api.ts` or `lib/api.ts` uses the correct base URL and the
   path prefixes match.

2. **`Optional` import in `apply_router.py`**: Prompt 35 added `Optional[float]` etc.
   to `ClientApplicationSchema`. Confirm `from typing import Optional` is present at
   the top of `apply_router.py`. If missing, add it.

3. **`apply_router.py` ↔ `AuditSet` constructor**: After Prompt 35, `submit_application()`
   builds an `AuditSet(...)` with an `application_data=` argument. Confirm the `AuditSet`
   ORM model accepts this column (it does — see A1/A2 fix above). Also confirm the
   `AuditSet(...)` constructor doesn't include the old `total_employees: payload.total_employees`
   line (which no longer exists in the schema). The new logic uses `ft = payload.full_time_employees
   or payload.total_employees` — verify this is correct: if `full_time_employees=0` and
   `total_employees=50`, the old-style form submission still works.

4. **Workflow transition completeness** (`workflow_router.py`): Read the `VALID_TRANSITIONS`
   dict. Verify:
   - Every status that can be a `from_status` also has at least one valid `to_status`
   - There is no status that can only be transitioned INTO and never out of (unless it is
     a terminal state like `certified`)
   - The `certified` status is the only terminal status (verify no other status is a dead end)
   - The `VALID_JUMP_STATUSES` set matches all statuses that can appear as `workflow_status`
     values (compare to the comments in `db_models.py` workflow_status column)

5. **`WorkflowUpdateSchema` ↔ event creation**: The `update_workflow_status` endpoint
   creates an `AuditSetStatusEvent` with `triggered_at=effective_ts`. Confirm
   `AuditSetStatusEvent` has a `triggered_at` column (it should from Prompt 33).
   Confirm the `AuditSetStatusEvent` ORM model is imported in `workflow_router.py`.

---

### Layer 6 — Document pipeline (`resolver.py`, `filler.py`)

**Read:** `backend/audit_set/resolver.py`, `backend/audit_set/filler.py`
(and any other file involved in template variable resolution)

**Check and fix:**

1. **`application_data` in resolver**: Check if any template variable (e.g.,
   `{{ energy_consumption_tj }}`, `{{ food_chain_categories }}`) is resolved in
   `resolver.py`. If such fields exist but the resolver reads from `required_scope`
   only (not `application_data`), add a fallback:
   - For food chain: prefer `application_data.fsms_food_chain_categories` over
     `required_scope["ISO 22000"]["codes"]` when available
   - For EnMS: prefer `application_data.enms_annual_energy_tj` over `sites[0].energy_tj`
     when available

2. **`man_day_result` field coverage**: The resolver likely reads from
   `audit_set.man_day_result` (a JSON dict of `CalculationResult`). Verify that every
   field the resolver reads (e.g., `final_total`, `final_ph1`, `final_ph2`,
   `final_surv1`, `enms_k`, `enms_complexity`, `fssc_reporting_surcharge`) exists in
   `CalculationResult` and is populated by `calculate()`. Add any missing fields to the
   resolver's null-safe fallback logic.

3. **`personnel` JSON writeback**: Document generation reads `personnel.office_employees`
   and `personnel.repetitive_employees`. These are populated by `_writeback_personnel_split()`
   (now fixed in A4). Confirm the resolver has null-safe access: if these keys are
   missing (legacy rows created before `_writeback_personnel_split()` existed), fall
   back to computing them inline from `full_time` + `part_time`.

---

### Layer 7 — Frontend TypeScript types (`frontend/src/types/index.ts`)

**Read:** `frontend/src/types/index.ts`

**Check and fix:**

1. **Add `application_data` field to `AuditSetResponse`**: After Prompt 35, the backend
   response includes `application_data`. The TypeScript type must reflect this:

   ```typescript
   application_data?: {
     // ISO 50001 — EnMS
     enms_annual_energy_tj?: number | null
     enms_num_energy_types?: number | null
     enms_num_seus?: number | null
     // ISO 22000 / FSSC 22000
     fsms_food_chain_categories?: string[]
     fsms_haccp_studies?: number | null
     fsms_offsite_storage_count?: number
     fsms_separate_head_office?: boolean
     fsms_fssc22000?: boolean
     fsms_seasonal_production?: boolean
     // ISO 27001
     isms_technical_area?: string | null
     isms_data_role?: string | null
     isms_it_complexity?: string | null
     isms_business_complexity?: string | null
     // ISO 13485
     mdqms_device_classes?: string[]
     mdqms_regulatory_territories?: string[]
     // Personnel
     part_time_fte_factor?: number
     subcontractors_in_scope?: boolean
   } | null
   ```

2. **Existing fields completeness**: Walk through `AuditSetResponse` in `schemas.py`
   and compare to the TypeScript `AuditSetResponse` interface. Add any field present in
   the Python schema but missing from the TypeScript type. Pay attention to:
   - `application_date?: string | null` (added in Prompt 33)
   - `application_data` (added in Prompt 35, now being added above)
   - `workflow_status?: string | null`
   - `submitted_via_portal?: boolean`
   - `scope_integration_level?: string | null`
   - `man_day_result?: Record<string, unknown> | null`
   - `required_scope?: Record<string, unknown> | null`

3. **`AuditSetStage` type**: Verify the TypeScript type for `AuditSetStage` (if it
   exists in `types/index.ts`) includes `shift_same_process` from the personnel JSON
   if it needs to be displayed. (This may not need a type change — just confirm.)

---

### Layer 8 — Frontend component null-safety sweep

**Read:** the following frontend components:
- `frontend/src/app/(app)/clients/[id]/page.tsx`
- `frontend/src/components/ui/WorkflowStatusBar.tsx`
- `frontend/src/app/(app)/clients/new/page.tsx`

**Check and fix:**

1. **`WorkflowStatusBar` null/undefined guards**: The component receives `currentStatus`
   which can be `null` (internally created sets) or a valid workflow status string.
   After Prompts 33/34, there are guards for `null` and `pending_review`. Verify all
   other statuses have a rendered panel in the step-strip. If any status maps to an
   empty/missing panel, add it or add a fallback "Unknown status" display.

2. **`application_data` in `clients/[id]/page.tsx`**: If the plan overview or any section
   reads from `data.application_data`, ensure it is null-safe:
   ```typescript
   const appData = data.application_data ?? {}
   ```
   No crashes if `application_data` is null (legacy rows before Prompt 35).

3. **`clients/new/page.tsx` — Step2 panel visibility**: The new standard-specific panels
   (EnMS, FSMS, ISMS, MDQMS) added in Prompt 35 Check 8 are gated by
   `standards.includes('ENMS')` etc. Verify `standards` is correctly passed as a prop
   from `NewClientPage` to `Step2`. The original code passes `standards={s1.standards}`.
   Confirm this is still in place after Prompt 35 modifications.

4. **`apply/page.tsx` — form submission null safety**: Verify that optional number
   fields (`enms_annual_energy_tj`, `enms_num_energy_types`, etc.) are not sent as empty
   strings `""` to the backend. The `pFloat("")` helper should return `null`, and
   `pInt("")` returns `0`. Confirm the conditional spread (`...(hasStd('ENMS') && {...})`)
   correctly excludes the EnMS block when ISO 50001 is not selected, so the backend
   receives no EnMS fields (rather than `null` values) for non-EnMS applications.

---

### Layer 9 — Standard code consistency audit

**Check all 8 standard codes are consistent across the entire system:**

Read all files that define or use standard codes. Build a verification table.
Fix any mismatch found.

The canonical codes are: `QMS`, `EMS`, `OHSMS`, `FSMS`, `ISMS`, `ENMS`, `MDQMS`, `ABMS`

Files to check:
- `apply_router.py` → `ALLOWED_STANDARDS` set
- `service.py` → `_CODE_TO_ISO` dict
- `calculator/engine.py` → `_std_match()` usage (uses ISO names not codes)
- `calculator/extractor.py` → `SYSTEM_PROMPT` standard names
- `frontend/src/app/apply/page.tsx` → `STANDARDS` array `code` values
- `frontend/src/app/(app)/clients/new/page.tsx` → `STANDARDS_GRID` array `code` values
- `frontend/src/components/ui/WorkflowStatusBar.tsx` → any standard-conditional logic

**Verify**:
1. `ALLOWED_STANDARDS` in apply_router includes all 8 codes
2. `_CODE_TO_ISO` maps all 8 codes to their correct ISO names
3. The ISO 37001 branch now exists in `engine.py` (added in Layer 4)
4. Both frontend forms have the same 8 standards in the same order
5. No standard code is used in one file but misspelled in another

---

### Layer 10 — JSON field key consistency

**Read:** all places that write or read the three key JSON columns.

#### `personnel` JSON — key consistency

Writers:
- `apply_router.py`: writes `full_time`, `part_time`, `subcontractors`, `seasonal`, `unskilled=0`, `shift_count`, `shift_same_process`, `repetitive_roles=[]`
- `clients/new/page.tsx` → `POST /audit-sets/`: writes `full_time`, `part_time`, `subcontractors`, `seasonal`, `shift_1_count`, `shift_2_count`, `shift_3_count`, `shift_same_process`

Readers:
- `service.py` `_run_calculation()`: reads `full_time`, `part_time`, `subcontractors`, `seasonal`, `unskilled`, `repetitive_roles`
- `service.py` `quick_calculate()`: reads all personnel keys
- `service.py` `_writeback_personnel_split()`: reads same keys

**Fix**: The internal form sends `shift_1_count`, `shift_2_count`, `shift_3_count` separately (from the 3-shift breakdown UI). The apply form sends `shift_count` (a single integer). `_run_calculation()` reads `shift_count` (via `employees_per_shift`). Verify `_run_calculation()` correctly handles BOTH formats:
- If `shift_count` is set, use it
- If `shift_1_count` etc. are set but `shift_count` is missing, derive `shift_count` from which shift counts are > 0

Add this normalization in `_run_calculation()`:
```python
shift_count = int(p.get("shift_count", 0)) or (
    (1 if p.get("shift_1_count", 0) > 0 else 0) +
    (1 if p.get("shift_2_count", 0) > 0 else 0) +
    (1 if p.get("shift_3_count", 0) > 0 else 0)
) or 1
```
Then pass `employees_per_shift` to `ExtractedFormData` as:
```python
employees_per_shift=int(p.get("shift_1_count") or p.get("employees_per_shift") or 0) or None,
```

#### `integration_level` JSON — key consistency

Writers:
- `clients/new/page.tsx` → `deriveIntegrationLevel()`: returns `document_management`, `management_review`, `internal_audit`, `policy_objectives`, `process_approach`, `improvement_mechanism`, `management_support`, `risk_based_thinking`
- `service.py` `create_audit_set()`: stores `data.integration_level.model_dump()`

Readers:
- `service.py` `_run_calculation()`: `il = audit_set.integration_level or {}; integration_yes_count = sum(1 for v in il.values() if v)`

**Verify** the 8 keys above exactly match the boolean fields in `AuditSetIntegrationSchema` (in `schemas.py`). If any key is different, fix.

#### `application_data` JSON — key consistency

Writers:
- `apply_router.py`: writes `enms_annual_energy_tj`, `enms_num_energy_types`, `enms_num_seus`, `fsms_food_chain_categories`, `fsms_haccp_studies`, `fsms_offsite_storage_count`, `fsms_separate_head_office`, `fsms_fssc22000`, `fsms_seasonal_production`, `isms_technical_area`, `isms_data_role`, `mdqms_device_classes`, `part_time_fte_factor`, `subcontractors_in_scope`
- `clients/new/page.tsx`: writes same keys (from Prompt 35 Change 8e)
- `service.py` `update_planning()`: writes `data.application_data.model_dump()`

Readers:
- `service.py` `_run_calculation()`: reads `enms_annual_energy_tj`, `enms_num_energy_types`, `enms_num_seus`, `fsms_food_chain_categories`, `fsms_offsite_storage_count`, `fsms_separate_head_office`, `fsms_haccp_studies`, `fsms_fssc22000`, `part_time_fte_factor`, `subcontractors_in_scope`
- `service.py` `_writeback_personnel_split()`: reads `part_time_fte_factor`, `subcontractors_in_scope`

**Verify** every key written by a writer is read by a reader with the EXACT same spelling (snake_case). Fix any mismatch.

---

### Layer 11 — Email / Auth flow

**Read:** `backend/email_service.py`, `backend/auth/` directory (routers + models)

**Check:**

1. **`send_client_welcome()`**: Called in `apply_router.py` after successful application.
   Verify the function signature matches the call: `send_client_welcome(to=..., full_name=..., temp_password=..., audit_set_id=...)`.

2. **Email failure handling**: The `apply_router.py` calls `send_client_welcome()` without
   a try/except. If email fails, the entire transaction would fail. Verify there is either
   a try/except around the email call OR the function itself catches exceptions internally.
   If email failure can crash the endpoint, wrap it:
   ```python
   try:
       send_client_welcome(to=..., full_name=..., temp_password=..., audit_set_id=audit_set.id)
   except Exception as e:
       logger.warning("Welcome email failed (non-fatal): %s", e)
   ```

3. **Auth DB vs Audit DB**: `apply_router.py` uses TWO database sessions:
   `audit_db` and `auth_db`. Verify the commit order is correct: `audit_db.commit()` →
   `audit_db.refresh(audit_set)` → `auth_db.commit()`. If `auth_db.commit()` fails,
   the audit set exists but the user does not, leaving an orphan. Assess if this is
   acceptable (it is for now — CB staff can manually create the user). Add a comment
   documenting this known limitation.

---

## Part C — Add a System Health Check Endpoint

After all fixes, add a health check endpoint that verifies the full pipeline is wired
correctly. Add this to `backend/main.py` or a new `health_router.py`.

**Endpoint**: `GET /health/full`

This endpoint is admin-only and performs the following live checks:

```python
@router.get("/health/full")
def full_health_check(current_user = Depends(get_current_user)):
    """System integrity health check — admin only."""
    if current_user.role != "admin":
        raise HTTPException(403, "Admin only")

    results = {}

    # 1. Database connectivity
    try:
        from audit_set.db_models import engine as audit_engine
        with audit_engine.connect() as conn:
            conn.execute(sa.text("SELECT 1"))
        results["db_audit"] = "ok"
    except Exception as e:
        results["db_audit"] = f"error: {e}"

    # 2. Calculator — test with a known input
    try:
        from calculator.engine import calculate
        from calculator.models import ExtractedFormData, StandardClassification
        test_data = ExtractedFormData(
            org_name="Health Check Co",
            standards=["ISO 9001"],
            audit_type="Initial",
            scope="Software development",
            total_employees=50,
            office_employees=50,
            repetitive_employees=0,
            classifications=[StandardClassification(standard="ISO 9001", sector_name="IT", category="Low")],
        )
        result = calculate(test_data)
        results["calculator_iso9001"] = f"ok (final_total={result.final_total})"
    except Exception as e:
        results["calculator_iso9001"] = f"error: {e}"

    # 3. Calculator — ISO 50001 with energy data
    try:
        test_enms = ExtractedFormData(
            org_name="EnMS Check",
            standards=["ISO 50001"],
            audit_type="Initial",
            scope="Manufacturing",
            total_employees=100,
            office_employees=100,
            repetitive_employees=0,
            annual_energy_tj=100.0,
            num_energy_types=3,
            num_seus=5,
            classifications=[StandardClassification(standard="ISO 50001", sector_name="EnMS", category="EnMS")],
        )
        result_enms = calculate(test_enms)
        results["calculator_iso50001"] = f"ok (k={result_enms.enms_k}, level={result_enms.enms_complexity})"
    except Exception as e:
        results["calculator_iso50001"] = f"error: {e}"

    # 4. Calculator — ISO 22000 with FSMS surcharges
    try:
        test_fsms = ExtractedFormData(
            org_name="FSMS Check",
            standards=["ISO 22000"],
            audit_type="Initial",
            scope="Food manufacturing",
            total_employees=80,
            office_employees=80,
            repetitive_employees=0,
            food_chain_categories=["CIV"],
            fsms_offsite_storage_count=2,
            fsms_separate_head_office=True,
            classifications=[StandardClassification(standard="ISO 22000", sector_name="Food", category="Medium")],
        )
        result_fsms = calculate(test_fsms)
        results["calculator_iso22000"] = f"ok (final_total={result_fsms.final_total}, addon={result_fsms.standard_results[0].haccp_addition})"
    except Exception as e:
        results["calculator_iso22000"] = f"error: {e}"

    # 5. Calculator — ISO 37001 (ABMS) — previously a dead end
    try:
        test_abms = ExtractedFormData(
            org_name="ABMS Check",
            standards=["ISO 37001"],
            audit_type="Initial",
            scope="Corporate services",
            total_employees=30,
            office_employees=30,
            repetitive_employees=0,
            classifications=[StandardClassification(standard="ISO 37001", sector_name="ABMS", category="Medium")],
        )
        result_abms = calculate(test_abms)
        results["calculator_iso37001"] = f"ok (final_total={result_abms.final_total})"
    except Exception as e:
        results["calculator_iso37001"] = f"error: {e}"

    # 6. All standards supported
    all_standards = ["ISO 9001", "ISO 14001", "ISO 45001", "ISO 22000", "ISO 27001", "ISO 50001", "ISO 13485", "ISO 37001"]
    for std in all_standards:
        if std not in [r for r in results if "calculator" in r]:
            try:
                extra_kwargs = {}
                if std == "ISO 50001":
                    extra_kwargs = {"annual_energy_tj": 50.0, "num_energy_types": 2, "num_seus": 3}
                td = ExtractedFormData(
                    org_name="Test", standards=[std], audit_type="Initial",
                    scope="Test", total_employees=50, office_employees=50,
                    repetitive_employees=0,
                    classifications=[StandardClassification(standard=std, sector_name="Test", category="Medium" if std not in ("ISO 27001", "ISO 50001", "ISO 13485") else ("ISMS" if "27001" in std else ("EnMS" if "50001" in std else "N/A")))],
                    **extra_kwargs,
                )
                r = calculate(td)
                results[f"calculator_{std.replace(' ', '_').replace('/', '_')}"] = f"ok (final_total={r.final_total})"
            except Exception as e:
                results[f"calculator_{std.replace(' ', '_').replace('/', '_')}"] = f"error: {e}"

    all_ok = all("error" not in v for v in results.values())
    return {"status": "ok" if all_ok else "degraded", "checks": results}
```

Mount the health router in `main.py`:
```python
from audit_set.health_router import router as health_router
app.include_router(health_router, prefix="/health", tags=["health"])
```

Create the file `backend/audit_set/health_router.py` with the endpoint above. Import all
needed dependencies from the existing codebase.

---

## Part D — Final Verification Pass

After making all fixes from Parts A, B, and C:

1. **Run the health check endpoint** against the running server (or simulate it):
   Call `GET /health/full` and verify every check returns `"ok"`.

2. **Review the full list of changes made** and produce a structured summary:

   ```
   === SYSTEM INTEGRITY REPORT ===

   FIXED BUGS:
   - A1: Removed duplicate application_data Column() definition in db_models.py
   - A2: Removed duplicate _safe_add_column() call in create_tables()
   - A3: Moved math import to module level in service.py
   - A4: Fixed _writeback_personnel_split() to apply FTE conversion
   - Layer 4: Added ISO 37001 engine handler (was silent dead end)
   - Layer 4: Added fsms_fssc22000 to ExtractedFormData + engine detection
   - Layer [X]: [describe every other fix made]

   VERIFIED OK (no changes needed):
   - [list every connection that was verified clean]

   REMAINING KNOWN LIMITATIONS (not bugs, by design):
   - ISO 37001 uses ISO 9001 Medium Risk proxy table (no IAF standard table exists)
   - calculator/extractor.py PDF extraction does not extract application_data fields
     (by design — these come from web form, not PDF upload)
   - Dual-DB architecture in apply_router: if auth_db commit fails after audit_db commit,
     an orphan AuditSet row will exist with no linked PlatformUser
   ```

---

## What NOT to change

- Do not change any existing workflow transitions or portal stages
- Do not change any template files (DOCX, PDF)
- Do not change the signing / OTP flows
- Do not change the PDF viewer or document generation pipeline
- Do not add new features — this is a correctness pass only
- Do not change the public-facing application form design (already done in Prompt 35)
