# Portal 71 — Stage Planning: Three Fixes

## Context

IAF MD 5 §6.3: when multiple auditors work simultaneously, required calendar time
reduces proportionally. Total person-days is fixed; calendar days = total / team size.
The platform has partial support for this — `teamCount` and the IAF banner are correct —
but two gaps prevent it from working in practice. A third unrelated bug exists in the
certification committee coverage check.

---

## Bug 1 — "Suggest end date" ignores team size

**File:** `frontend/src/app/(app)/clients/[id]/page.tsx`
**Location:** the `<button>` that reads "Suggest end date (X working days from start)"
— approximately line 1436–1444.

**Current broken code:**
```ts
onClick={() => patch({ audit_date_end: suggestEndDate(edit.audit_date_start, recommended) })}
// ...
Suggest end date ({recommended} working days from start)
```

No matter how many auditors are on the team, the button always suggests `recommended`
calendar days — the single-auditor number. With 2 auditors on a 9.5-day audit, the
correct suggestion is `ceil(9.5 / 2) = 5` calendar days, not 9.5.

**Fix:**

```ts
// Compute team-adjusted calendar days (fall back to 1 when no one assigned yet)
const calendarDaysNeeded = recommended != null
  ? Math.ceil(recommended / Math.max(1, teamCount))
  : null

// Button (replace the two lines above with):
onClick={() => {
  if (calendarDaysNeeded != null) {
    patch({ audit_date_end: suggestEndDate(edit.audit_date_start, calendarDaysNeeded) })
  }
}}
// ...
Suggest end date ({calendarDaysNeeded} working days from start)
{teamCount > 1 && (
  <span className="ml-1 opacity-70">
    ({recommended} person-days ÷ {teamCount} auditors)
  </span>
)}
```

---

## Bug 2 — Reactive team-size effect is silenced for unscheduled stages

**File:** `frontend/src/app/(app)/clients/[id]/page.tsx`
**Location:** the `useEffect` that watches `teamCount` — approximately line 1206–1216.

**Current broken code:**
```ts
useEffect(() => {
  if (!edit.audit_date_start) return
  if (!stage.audit_days) return    // ← BLOCKS when stage not yet saved to DB
  if (teamCount === 0) return
  const calendarDaysNeeded = Math.ceil(stage.audit_days / teamCount)
  const newEnd = suggestEndDate(edit.audit_date_start, calendarDaysNeeded)
  if (newEnd !== edit.audit_date_end) patch({ audit_date_end: newEnd })
}, [teamCount])
```

`stage.audit_days` is the DB-persisted value — it is `null` for stages that have not
yet been scheduled. The `if (!stage.audit_days) return` guard silences the reactive
update for exactly those stages where it is most needed (new, unscheduled stages).

`recommended` (derived from `man_day_result.final_ph1 / final_ph2`) is always available
when the man-day calculation has been run, regardless of whether the stage has dates.

**Fix:** fall back to `recommended` when `stage.audit_days` is null:

```ts
useEffect(() => {
  if (!edit.audit_date_start) return
  const baseAuditDays = stage.audit_days ?? recommended   // ← use recommendation when not yet scheduled
  if (!baseAuditDays) return
  if (teamCount === 0) return
  const calendarDaysNeeded = Math.ceil(baseAuditDays / teamCount)
  const newEnd = suggestEndDate(edit.audit_date_start, calendarDaysNeeded)
  if (newEnd !== edit.audit_date_end) patch({ audit_date_end: newEnd })
}, [teamCount])   // eslint-disable-line react-hooks/exhaustive-deps
```

---

## Bug 3 — Committee coverage check: EA codes not cross-standard

**File:** `frontend/src/app/(app)/clients/[id]/page.tsx`
**Location:** inside `CommitteePlanningCard`, the per-code `coveringMember` search
— approximately line 961.

**Business rule (from IAF MD 11, same as TEs):**
> The audit team — and by extension the certification committee — shall have
> *collective* competence to cover all management system standards. An auditor's
> sector expertise (EA code) is not standard-specific; competence in EA 5 (food)
> applies whether the standard being certified is ISO 9001, ISO 14001, or ISO 45001.

**Current broken code:**
```ts
const coveringMember = selected.find((m) =>
  (m.covered_scope?.[std] ?? []).includes(code)
)
```

`covered_scope` is keyed by standard. A committee member with
`covered_scope = { "ISO 9001": ["EA 5"], "ISO 14001": ["EA 5"] }` but no
ISO 45001 qualification will show `EA 5 — not covered` for ISO 45001, even though
their EA 5 sector expertise is standard-agnostic.

This is the same root cause as the TE fix in Portal 70 (committed `39fd603`).
Apply the identical cross-standard extension here:

```ts
const coveringMember = selected.find((m) => {
  // Direct coverage: member explicitly covers this standard + code
  if ((m.covered_scope?.[std] ?? []).includes(code)) return true
  // Cross-standard: sector expertise (EA code) spans all audit standards —
  // if the member covers this EA code for ANY standard, they cover it here too.
  return Object.values(m.covered_scope ?? {}).some((codes) => codes.includes(code))
})
```

---

## Summary of changes

All three changes are in `frontend/src/app/(app)/clients/[id]/page.tsx` only.
No backend changes. No other files.

| # | Location | Change |
|---|----------|--------|
| 1 | `StageCard` — "Suggest end date" button | Divide `recommended` by `teamCount`; update label |
| 2 | `StageCard` — `useEffect([teamCount])` | Fall back to `recommended` when `stage.audit_days` is null |
| 3 | `CommitteePlanningCard` — `coveringMember` find | Cross-standard EA code check (same as Portal 70 TE fix) |

---

## Expected behaviour after fix

**Stage with 1 auditor, 9.5 person-days required:**
```
Suggest end date (10 working days from start)
```
*(unchanged — 1 auditor = full calendar days)*

**Stage with 2 auditors, 9.5 person-days required:**
```
Suggest end date (5 working days from start)  (9.5 person-days ÷ 2 auditors)
```
Adding a second auditor also immediately recalculates and updates the end date field.

**Committee — Emrullah (EA 5: ISO 9001 ✓, ISO 14001 ✓) + audit has ISO 45001:**
```
Before: ✗ ISO 45001 — EA 5 not covered
After:  ✓ ISO 45001 — EA 5 — Emrullah
```

---

## Commit message

```
Portal 71: stage planning — teamCount calendar day reduction + committee EA fix

Bug 1: "Suggest end date" always used raw `recommended` (single-auditor days).
  Now divides by teamCount: 2 auditors on a 9.5-day audit → 5 calendar days.
  Label updated to show the breakdown "(9.5 person-days ÷ 2 auditors)".

Bug 2: reactive useEffect([teamCount]) was silenced by `if (!stage.audit_days)`
  — null for unscheduled stages. Now falls back to `recommended` so end date
  auto-adjusts when auditors are added even before the stage is first saved.

Bug 3: committee coveringMember check was standard-specific (covered_scope[std]).
  Same cross-standard fix as Portal 70 TE rule: sector expertise (EA code) spans
  all management system standards. Emrullah's EA 5 now covers ISO 45001 too.

All changes in page.tsx only — no backend, no other files.
```
