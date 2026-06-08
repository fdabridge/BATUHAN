# Logic Verification Audit — Does everything connect in the right order?

Do not fix anything. Read the code and answer every question below with YES or NO and one sentence of evidence (file + line or field name). If the answer is "it depends" or "partially", say so and explain why.

The goal: confirm that every piece of data exists at the moment it is needed, every function receives what it requires, and every UI element has its data before it renders.

---

## CHAPTER 1 — Creation: does the right data exist by the time the page first loads?

When `create_audit_set()` finishes and the coordinator opens the client detail page:

1. Is `audit_set.required_scope` non-null? (Was `derive_required_scope()` called during creation?)
2. Is `audit_set.man_day_result` non-null? (Was `_run_calculation()` called and did it succeed for a client with employees > 0?)
3. Are `audit_set.stages` populated with the correct number of records? (Initial = 2, Surveillance = 1, Recertification = 1?)
4. Does each stage record have `audit_days` set? (Did `_create_auto_stages()` assign `final_ph1`, `final_ph2`, `final_surv1` etc. from the calculation result?)
5. Is `audit_set.scope_integration_level` set? (Was the boolean field count computed before `_run_calculation()`?)
6. Does the API response for `GET /audit-sets/{id}` include all of the above fields — `required_scope`, `man_day_result`, `stages[].audit_days`, `scope_integration_level`, `personnel`?
7. Does the frontend `AuditSetResponse` type include all of those fields so TypeScript does not strip them?

---

## CHAPTER 2 — Page render: does the UI have what it needs before the coordinator touches anything?

When `clients/[id]/page.tsx` renders with `data` from the API:

8. Does `ManDaySection` receive a non-null `result` prop for a client with employees? (Is `data.man_day_result` passed in and non-null?)
9. Does `ManDaySection` open by default? (Is `useState(true)` inside it?)
10. Does the required scope section render `data.required_scope` directly without waiting for a button click?
11. For each standard in `required_scope`, does the frontend display the correct chip type — EA chips for ISO 9001/14001/45001/27001, amber food chips for ISO 22000/FSSC, purple TA chips for ISO 13485, blue sector for ISO 37001/37301?
12. Does each stage card render with `stage.audit_days` already populated? (If `_create_auto_stages()` ran correctly, these should be non-null from the start.)
13. Is the QuickCalcWidget absent from the file entirely?
14. Is the "Derive required scope" button absent from the file entirely?

---

## CHAPTER 3 — Stage card: does the auditor selection have what it needs?

When the coordinator selects auditors in a stage card:

15. Is `auditorCount` computed as lead auditor (1 if selected, else 0) + additional auditors count — and does it explicitly EXCLUDE technical experts?
16. Is the required calendar days formula `Math.ceil(stage.audit_days / auditorCount)` used when `auditorCount > 0`?
17. Is there a `useEffect` that watches `auditorCount` and updates `audit_date_end` when it changes?
18. Does the IAF banner display the live formula: "{audit_days} audit-days ÷ {auditorCount} auditors = {calDays} calendar days"?
19. When `auditorCount` is 0, does the banner still show (without dividing by zero) with a prompt to assign auditors?

---

## CHAPTER 4 — Auditor dropdown: does it show the right people with the right labels?

When dates are selected and the dropdown loads:

20. Does the stage card call `/api/auditors/available` with both `date_start`/`date_end` AND `required_categories` (the audit set's `required_scope`)?
21. Does the call only fire when `audit_date_start` and `audit_date_end` are both set? (Not before dates are picked.)
22. Does the backend `/available` endpoint exclude auditors whose `covered_scope` is empty across all standards when `required_categories` is provided?
23. Does each auditor option label show their covered codes grouped by standard — e.g. `EA 3 (ISO 9001) | CIV CIII (ISO 22000)` — not a flat list?
24. Do auditors with `is_available: false` appear in the list but visually distinguished (greyed, note about which audit they are on)?

---

## CHAPTER 5 — Coverage validation: is the team check correct?

As auditors are added to the stage:

25. Does `computeCoverage()` receive the current team (lead + additional + technical experts) as input?
26. Does it use `requiredScope` (the audit set's derived scope codes) as the standard to check against — not the auditor's full profile?
27. Does the coverage panel update live as auditors are added and removed (i.e., is it derived from `edit.auditors` + `edit.lead_auditor_name` which are in React state)?
28. Is Stage 2 save hard-blocked when any required code is uncovered? (Does the mutation throw before the API call?)
29. Is Stage 1 save allowed with incomplete coverage but with a visible warning?

---

## CHAPTER 6 — Save and confirmation: does the data persist correctly?

When the coordinator clicks "Save stage":

30. Does `update_planning()` in `service.py` receive and persist `lead_auditor_name`, `auditors[]`, `audit_date_start`, `audit_date_end` for the correct stage?
31. After saving, does the `/available` endpoint correctly identify those dates as occupied for the assigned auditors — i.e., will a second audit on the same dates show those auditors as `is_available: false`?
32. Does the stage card refresh its local state after a successful save (so the saved data is reflected in the UI without a full page reload)?

---

## CHAPTER 7 — Package generation: does download work end to end?

When the coordinator clicks "Download audit package":

33. Does the endpoint check that at least one stage has a lead auditor before generating? (Returns 400 if not.)
34. Does the endpoint use `audit_set.accreditation_body` to decide between English (UAF) and Turkish (TÜRKAK) folder names and template files?
35. Does `audit_type.startswith("surveillance")` correctly handle both `"surveillance_1"` and `"surveillance_2"` in the resolver?
36. Does `audit_set.status` advance to `"active"` after successful generation and get committed to the database?
37. Does the generated ZIP actually contain files (not an empty archive) for a fully planned audit set?

---

## CHAPTER 8 — Edge cases: does the logic hold under realistic conditions?

38. **Single standard, no integration reduction:** If only ISO 9001 is selected, does the engine skip MD 11 entirely and return `md11_floor_applied: false` and `integration_reduction: 0`?
39. **Two standards, fully integrated:** ISO 9001 + ISO 14001 with High integration level — does the engine apply exactly 20% reduction (no more)?
40. **Surveillance audit:** Does a `surveillance_1` audit set produce exactly one stage card (not two), and does that stage use `final_surv1` for `audit_days`?
41. **FSSC 22000:** Does `man_day_result` include `fssc_reporting_surcharge` as a non-zero separate field, and does `ManDaySection` render it as a distinct line item?
42. **No personnel entered:** If `audit_set.personnel` is all zeros, does the auto-calc `useEffect` skip silently (not crash), and does the page still render with scope codes visible (just no man-day result)?
43. **Auditor covers only one of two required standards:** Does they appear in the dropdown (covered_scope non-empty), correctly labelled for only the standard they cover, and does the coverage panel show a gap for the other standard?

---

## REPORT FORMAT

Answer each numbered question: **YES**, **NO**, or **PARTIAL — [reason]**.

Group by chapter. At the end, list all NO and PARTIAL answers as action items with the file and line where the gap exists.

No fixes. No code changes. Read and report only.
