# Integration Audit — Audit Set Creation to Package, End to End

Do not build anything. Do not fix anything unless it is a broken import, wrong field name, or missing function call that is provably wrong. This is a read-and-report audit. Trace every connection in the chain below and report what is wired correctly, what is broken, and what is missing.

---

## CHAIN TO TRACE

```
create_audit_set()
    → _run_calculation()         → calculator/engine.py :: calculate()
    → derive_required_scope()    → service.py keyword maps
    → _create_auto_stages()      → AuditSetStage rows

audit_set.man_day_result         → frontend ManDaySection
audit_set.required_scope         → frontend required scope chips
audit_set.stages[].audit_days    → frontend stage cards

stage card: auditor selected
    → /api/auditors/available    → auditors.py :: get_available_auditors()
    → covered_scope computed     → auditor qualifications
    → coverage panel rendered    → frontend computeCoverage()

stage saved
    → /api/audit-sets/{id}/planning → service.py :: update_planning()
    → stage rows updated

package created / download
    → /api/audit-sets/{id}/download → document assembly
    → auditor availability logged
    → audit_set.status advanced
```

---

## WHAT TO CHECK AT EACH STEP

### 1. `create_audit_set()` in `backend/audit_set/service.py`
- Does it call `derive_required_scope()` and save the result to `audit_set.required_scope`? 
- Does it derive `scope_integration_level` from `integration_level` boolean fields before calling `_run_calculation()`?
- Does `_run_calculation()` receive `scope_integration_level` and pass it to `calculate()`?
- Does `_create_auto_stages()` use the correct field names from the calculation result (`final_ph1`, `final_ph2`, `final_surv1`, `final_recert`)? Do those field names actually exist in `CalculationResult`?

### 2. `calculate()` in `backend/calculator/engine.py`
- What does `CalculationResult` look like? List every field it returns.
- Do `final_ph1`, `final_ph2`, `final_surv1`, `final_recert` exist? If the field names differ (e.g. `phase1`, `surv_days`), report the actual names — the service layer must use the real names.
- Is IAF MD 11 integration reduction applied? Are the rates 5% / 10% / 20%? Is the 50% floor enforced?
- Is the FSSC 22000 reporting surcharge (min 1.0 day) added as a separate line?

### 3. `/api/auditors/available` in `backend/api/routes/auditors.py`
- Does it accept `required_scope` as a query parameter?
- Does it compute `covered_scope` per auditor — which required codes each auditor personally covers?
- Does it return `covered_scope` in the response?
- Does it exclude auditors with zero coverage when `required_scope` is provided?
- Does it mark auditors with date conflicts as `is_available: false` and include which audit they are booked on?

### 4. `update_planning()` in `backend/audit_set/service.py`
- When a stage is saved with an auditor assigned, is that auditor's availability logged/blocked for those dates?
- Or does availability blocking only happen at package download time?
- Which endpoint triggers the availability block — `/planning` or `/download`? Confirm which and report if it is correct.

### 5. `/api/audit-sets/{id}/download` or equivalent package endpoint
- Does it exist?
- Does it check that all required stages have a lead auditor assigned before generating documents?
- Does it route to English templates for UAF and Turkish templates for TÜRKAK?
- Does it advance `audit_set.status`?
- Does it log auditor availability for the assigned dates?

### 6. Frontend data flow in `frontend/src/app/(app)/clients/[id]/page.tsx`
- When the page loads, is `data.required_scope` read and displayed without any button click?
- Is `data.man_day_result` displayed in the ManDaySection without any button click?
- Is the QuickCalcWidget still present in the file? It should be removed.
- Is the "Derive required scope" button still present? It should be removed.
- Does the stage card read `stage.audit_days` and display it as the IAF recommendation?
- Does the auditor dropdown call `/api/auditors/available` with `required_scope` as a parameter?
- Does the dropdown label show which codes each auditor covers for this specific audit?
- Does `computeCoverage()` exist and correctly compute per-code coverage across the team?
- Is Stage 2 save hard-blocked when coverage is incomplete?
- Does `auditorCount` (lead + additional only, NOT technical experts) drive the calendar days formula `ceil(stage.audit_days / auditorCount)`?
- Is there a `useEffect` that watches `auditorCount` and updates `audit_date_end` reactively?

### 7. Type consistency
- Does `AuditSetResponse` in `frontend/src/types/index.ts` include `required_scope`, `man_day_result`, `personnel`, `scope_integration_level`, `stages`?
- Does `StageResponse` include `audit_days`, `stage_type`, `stage_order`, `lead_auditor_name`, `auditors`, `technical_experts`?
- Does `AuditorAvailabilityItem` include `covered_scope`?
- Do the field names in the TypeScript types match what the backend actually returns? Check one API response shape against its Pydantic schema.

---

## REPORT FORMAT

For each numbered item above, report:

**✅ Correct** — function exists, field names match, data flows through correctly.  
**❌ Broken** — what is wrong, which file, which line. Fix only if it is a one-line correction (wrong field name, missing import, wrong key). Otherwise report it.  
**⚠️ Partial** — what works and what is missing.  
**❓ Cannot verify** — the code path exists but the logic depends on runtime behaviour that cannot be confirmed statically.

Keep the report concise. One line per finding where possible.
