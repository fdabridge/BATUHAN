# Portal 72 — "Suggest end date" reactive effect: always divide IAF man-days, not saved calendar days

## What was wrong in Portal 71 Bug 2

Portal 71 Bug 2 changed the reactive `useEffect([teamCount])` from:

```ts
if (!stage.audit_days) return    // blocked for unscheduled stages
```

to:

```ts
const baseAuditDays = stage.audit_days ?? recommended
if (!baseAuditDays) return
```

This introduced a new error: `stage.audit_days` is the number of **calendar days** previously
saved to the database — the result of an earlier "suggest end date" computation under a
*different* team size. Using it as the divisor for the new team size is wrong.

**Example:**
- Stage 2. IAF MD 5 final man-days = 9.5. Team = 1 auditor. Planner clicks "suggest end date"
  → `ceil(9.5 / 1) = 10` calendar days. Planner saves stage. `stage.audit_days = 10` in DB.
- Planner later adds a second auditor. Reactive effect fires.
- Bug 2 path: `baseAuditDays = stage.audit_days = 10`. Computes `ceil(10 / 2) = 5`. Happens
  to be correct here by coincidence.
- **Stage 1 counterexample:** IAF final = 4.5. Previously saved as `stage.audit_days = 5`
  (`ceil(4.5/1)`). With 2 auditors: `ceil(5 / 2) = 3`. Correct answer: `ceil(4.5 / 2) = 3`.
  Still OK here — but only because 5 and 4.5 are close.
- **Stale value counterexample:** If `stage.audit_days = 10` was saved from an older audit
  config for Stage 1 (before integration/reporting reductions were applied), and the real
  `recommended` is now 4.5, then `ceil(10 / 2) = 5` — wrong. Correct: `ceil(4.5 / 2) = 3`.

**The invariant:** `recommended` — derived from `man_day_result.final_ph1` (Stage 1) or
`man_day_result.final_ph2` (Stage 2) — is the IAF MD 5 final reduced man-day figure after
integration and reporting reductions. It is the **only** correct base for dividing by team
count. Any saved `stage.audit_days` value is a stale calendar-day artifact; it must never
be used as the divisor base.

---

## Fix — `frontend/src/app/(app)/clients/[id]/page.tsx`

Find the `useEffect` that watches `teamCount` (approximately line 1214, inside `StageCard`).

**BEFORE (Portal 71 Bug 2 state):**
```ts
useEffect(() => {
  if (!edit.audit_date_start) return
  const baseAuditDays = stage.audit_days ?? recommended   // ← WRONG: stage.audit_days is calendar days
  if (!baseAuditDays) return
  if (teamCount === 0) return
  const calendarDaysNeeded = Math.ceil(baseAuditDays / teamCount)
  const newEnd = suggestEndDate(edit.audit_date_start, calendarDaysNeeded)
  if (newEnd !== edit.audit_date_end) patch({ audit_date_end: newEnd })
}, [teamCount])   // eslint-disable-line react-hooks/exhaustive-deps
```

**AFTER:**
```ts
useEffect(() => {
  if (!edit.audit_date_start) return
  if (!recommended) return           // ← ONLY divide the IAF man-days, never stage.audit_days
  if (teamCount === 0) return
  const calendarDaysNeeded = Math.ceil(recommended / teamCount)
  const newEnd = suggestEndDate(edit.audit_date_start, calendarDaysNeeded)
  if (newEnd !== edit.audit_date_end) patch({ audit_date_end: newEnd })
}, [teamCount])   // eslint-disable-line react-hooks/exhaustive-deps
```

That is the **only change**. One line removed (`const baseAuditDays = ...`), one line changed
(`if (!stage.audit_days)` → `if (!recommended)`), divisor changed from `baseAuditDays` to
`recommended`.

The "Suggest end date" button (Bug 1 in Portal 71) already uses `recommended` directly and
is correct — no change needed there.

---

## Expected behaviour after fix

| Scenario | Correct base | Calendar days |
|----------|-------------|---------------|
| Stage 1, 1 auditor, recommended = 4.5 | 4.5 | `ceil(4.5/1) = 5` |
| Stage 1, 2 auditors, recommended = 4.5 | 4.5 | `ceil(4.5/2) = 3` |
| Stage 2, 1 auditor, recommended = 9.5 | 9.5 | `ceil(9.5/1) = 10` |
| Stage 2, 2 auditors, recommended = 9.5 | 9.5 | `ceil(9.5/2) = 5` |

Any stale value in `stage.audit_days` is irrelevant — the reactive effect and the button
both derive calendar days fresh from the IAF man-day figure every time.

---

## Files to change

| File | Change |
|------|--------|
| `frontend/src/app/(app)/clients/[id]/page.tsx` | `StageCard` `useEffect([teamCount])`: remove `stage.audit_days` fallback; always divide `recommended` |

No backend changes. No other files.

---

## Commit message

```
Portal 72: fix Bug 2 base — always divide IAF man-days, never saved calendar days

Portal 71 Bug 2 introduced `stage.audit_days ?? recommended` as the division
base. stage.audit_days is the calendar-day count saved from a prior team
configuration — dividing it by a new team count produces wrong results whenever
the saved value was ceiled from a different man-day figure.

The only correct base is `recommended` (man_day_result.final_ph1 or final_ph2),
which reflects the IAF MD 5 result after all integration and reporting reductions.

Fix: drop stage.audit_days entirely from the reactive effect; use recommended only.
```
