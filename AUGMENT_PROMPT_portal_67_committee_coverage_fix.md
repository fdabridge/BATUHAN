# Portal 67 — Committee Picker: Correct Coverage Logic + Hide Non-Qualifying Auditors

## Context

Two bugs remain in `CommitteePlanningCard` in `frontend/src/app/(app)/clients/[id]/page.tsx`:

1. **Coverage shows "all covered" when only EA 3 is selected, even though EA 5 is also
   required.** The coverage check uses `contributors.length > 0` (any member covers the
   standard) — it never checks whether every individual required code is covered.

2. **All 118 auditors appear in the dropdown** including ones with zero matching codes,
   shown with warning icons. They should be hidden entirely.

Both bugs exist because the committee card did NOT copy the stage picker's logic correctly.
This portal fixes both by applying the exact same patterns already used by `StageCard`.

---

## The correct patterns — already in the file, just not used in the committee card

### Pattern 1 — Dropdown filter (stage picker, ~line 1213)

```ts
const dropdownList =
  (availableAuditors && requiredScope && Object.keys(requiredScope).length > 0)
    ? availableAuditors.filter((a) => {
        const coveredTotal = Object.values(a.covered_scope ?? {}).flat().length
        return coveredTotal > 0
      })
    : allDropdown
```

Auditors with `coveredTotal === 0` are hidden entirely. Apply this same filter to
the committee dropdown `pool` variable.

### Pattern 2 — Per-code coverage check (`computeCoverage`, ~line 226)

```ts
const codeResults = rsEntry.codes.map((code) => {
  const coveringAuditor = teamAuditors.find((a) => {
    const cs = a.covered_scope?.[std]
    return cs && cs.includes(code)
  })
  return { code, coveredBy: coveringAuditor?.full_name ?? null }
})
const allCodesCovered = codeResults.every((r) => r.coveredBy !== null)
```

Every required code must be covered by at least one team member. Apply this same
logic to the committee coverage summary.

---

## Fix 1 — Filter the committee dropdown

In `CommitteePlanningCard`, find where `pool` is passed to the `<select>` dropdown
as options. Add the same `coveredTotal > 0` filter:

```ts
// Before rendering dropdown options:
const eligiblePool = pool.filter((a) => {
  const coveredTotal = Object.values(a.covered_scope ?? {}).flat().length
  return coveredTotal > 0
})
// Use eligiblePool as the dropdown source instead of pool
```

Auditors with zero covered codes do not appear in the dropdown at all.
Do not show them with warning icons — hide them completely.

---

## Fix 2 — Per-code coverage check

Replace the current `coverageSummary` computation (the block around lines 888–896
that checks `contributors.length > 0`) with the per-code logic from `computeCoverage`.

The required codes per standard come from the union of `covered_scope` across
the entire `pool` (what the backend computed as matchable codes for this audit):

```ts
// Step 1: Build required codes per standard from the pool
// (the backend only includes codes that are relevant to this audit in covered_scope)
const requiredScopeMap: Record<string, string[]> = {}
for (const a of pool) {
  for (const [std, codes] of Object.entries(a.covered_scope ?? {})) {
    requiredScopeMap[std] = [
      ...new Set([...(requiredScopeMap[std] ?? []), ...codes])
    ]
  }
}

// Step 2: For each required standard, check every required code
const coverageSummary = auditStandardsISO.map((std) => {
  const requiredCodes = requiredScopeMap[std] ?? []

  if (requiredCodes.length === 0) {
    // Standard with no code breakdown (just qualification check)
    const covered = selected.some((m) => m.standards.includes(std))
    return {
      standard: std,
      covered,
      missingCodes: [] as string[],
      coveredCodes: [] as { code: string; by: string }[],
    }
  }

  const codeResults = requiredCodes.map((code) => {
    const coveringMember = selected.find((m) =>
      (m.covered_scope?.[std] ?? []).includes(code)
    )
    return { code, coveredBy: coveringMember?.full_name ?? null }
  })

  return {
    standard: std,
    covered: codeResults.every((r) => r.coveredBy !== null),
    missingCodes: codeResults
      .filter((r) => !r.coveredBy)
      .map((r) => r.code),
    coveredCodes: codeResults
      .filter((r) => r.coveredBy !== null)
      .map((r) => ({ code: r.code, by: r.coveredBy! })),
  }
})

const coverageComplete = coverageSummary.every((s) => s.covered)
```

### Coverage display

Render the coverage block the same way as the stage picker:

**When complete (all codes covered):**
```
✓ Committee covers all required standards
  ✓ ISO 9001: EA 3 — Adil · EA 5 — Emrullah
```

**When incomplete:**
```
⚠ Coverage incomplete
  ✗ ISO 9001 — EA 5 not covered by any committee member
  ✓ ISO 9001 — EA 3 — Adil
```

### Save button

Disable "Save committee" when `coverageComplete === false`:

```tsx
<button
  onClick={handleSave}
  disabled={isPending || !coverageComplete}
>
  Save committee
</button>
```

This matches Stage 2's hard block behavior. The committee must cover all required
codes before it can be saved — same enforcement as the stage team.

---

## What NOT to change

- The `stageAuditorIdsKey` exclusion logic (Portal 64) — keep as-is
- The `selectedRef` enrichment pattern (Portal 64) — keep as-is
- The chairperson/member chip label logic (Portal 66) — keep as-is
- The backend endpoint — no changes needed; `covered_scope` already returns the
  correct per-code data; the bug is entirely frontend

---

## Files to change

| File | Change |
|------|--------|
| `frontend/src/app/(app)/clients/[id]/page.tsx` | `CommitteePlanningCard`: filter `pool` to `eligiblePool` (coveredTotal > 0); replace `coverageSummary` with per-code logic; disable Save when `!coverageComplete` |

---

## Commit message

```
Portal 67: committee picker — correct per-code coverage + hide non-qualifying auditors

Bug 1: coverage check was "any member covers the standard" — fixed to per-code:
  every required EA code must be covered by at least one committee member,
  same logic as computeCoverage() in StageCard. requiredScopeMap derived
  from union of covered_scope across the pool.

Bug 2: all 118 auditors shown with warning icons — fixed to hide auditors
  where coveredTotal === 0, same as StageCard dropdownList filter.

Save committee button disabled when coverageComplete === false (hard block,
same as Stage 2 stage save).
```
