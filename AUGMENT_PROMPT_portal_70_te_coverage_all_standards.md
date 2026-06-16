# Portal 70 — TE EA Codes Cover All Audit Standards

## Business rule

A Technical Expert (TE) on the audit team provides subject matter expertise in their
EA code area — that expertise applies to **every standard in the audit**, not only the
standard they hold a formal auditor qualification for.

**Example (this smoke test):** Altuğ Solmaz is a TE with EA 5. The audit has ISO 9001,
ISO 14001, and ISO 45001. The system currently shows:

```
✓ ISO 9001  ✓ EA 3 — Aslı Abay   ✓ EA 5 — Altuğ Solmaz (TE)
✗ ISO 14001 ✓ EA 3 — Aslı Abay   ✗ EA 5 — not covered
✗ ISO 45001 ✓ EA 3 — Aslı Abay   ✗ EA 5 — not covered
```

Expected result after this fix:
```
✓ ISO 9001  ✓ EA 3 — Aslı Abay   ✓ EA 5 — Altuğ Solmaz (TE)
✓ ISO 14001 ✓ EA 3 — Aslı Abay   ✓ EA 5 — Altuğ Solmaz (TE)
✓ ISO 45001 ✓ EA 3 — Aslı Abay   ✓ EA 5 — Altuğ Solmaz (TE)
```

---

## Root cause

In `frontend/src/app/(app)/clients/[id]/page.tsx`, the `computeCoverage` function
checks whether a required EA code is covered using `covered_scope`:

```ts
// Current code — lines ~229-232
const coveringAuditor = teamAuditors.find((a) => {
  const cs = a.covered_scope?.[std]
  return cs && cs.includes(code)
})
```

`covered_scope` is `{ iso_std: string[] }` — keyed by standard. It comes from the
backend `available-auditors` endpoint which builds it from auditor qualifications.

Altuğ's `covered_scope` is `{ "ISO 9001": ["EA 5"] }` because he only has an ISO 9001
qualification record in the database. For ISO 14001 and ISO 45001, `covered_scope["ISO 14001"]`
is `undefined` → the check returns false → "not covered".

The `teNames` set (already passed into `computeCoverage` as the last parameter) contains
the names of all Technical Experts on the team. The `labelName` helper already uses it to
append "(TE)" to display names. We just need to also use it in the coverage check.

---

## Fix — `computeCoverage` in `frontend/src/app/(app)/clients/[id]/page.tsx`

Find the per-code `coveringAuditor` block inside `computeCoverage` (inside the
`if (rsEntry && rsEntry.codes.length > 0)` branch). Replace it:

```ts
// BEFORE (~line 229):
const coveringAuditor = teamAuditors.find((a) => {
  const cs = a.covered_scope?.[std]
  return cs && cs.includes(code)
})

// AFTER:
const coveringAuditor = teamAuditors.find((a) => {
  // Standard path: this auditor covers the code for this specific standard
  const cs = a.covered_scope?.[std]
  if (cs && cs.includes(code)) return true
  // TE path: a Technical Expert's EA code applies to ALL audit standards,
  // not just the standard(s) they hold a formal auditor qualification for.
  if (teNames?.has(a.name ?? '')) {
    return Object.values(a.covered_scope ?? {}).some((codes) => codes.includes(code))
  }
  return false
})
```

That is the **only change**. The `labelName(coveringAuditor?.name ?? null)` call that
follows already appends "(TE)" for TE names, so the display label works automatically.

---

## Fallback branch — also fix for consistency

The fallback per-standard check (the `else` branch below `if (rsEntry && rsEntry.codes.length > 0)`)
uses `standard_qualifications` to find a covering team member. A TE who only has ISO 9001
in their qualifications won't match ISO 14001 there either.

Apply the same TE extension to the fallback `cover` find:

```ts
// BEFORE (fallback branch, ~line 249):
const cover = teamAuditors.find((a) => {
  const qual = a.standard_qualifications.find((q) => {
    ...
  })
  if (!qual) return false
  ...
})

// AFTER: add a TE short-circuit before the qualification lookup
const cover = teamAuditors.find((a) => {
  // TE short-circuit: if this auditor is a TE and covers the client EA code
  // in any standard, they satisfy this standard's coverage requirement.
  if (teNames?.has(a.name ?? '') && scopeType === 'ea' && clientEACode) {
    const clientNum = clientEACode.replace(/[^0-9]/g, '')
    const coversEA = Object.values(a.covered_scope ?? {}).some((codes) =>
      codes.some((c) => c.replace(/[^0-9]/g, '') === clientNum)
    )
    if (coversEA) return true
  }

  const qual = a.standard_qualifications.find((q) => {
    const qNorm = q.standard_code.toLowerCase().replace('iso ', '').replace(/\s/g, '')
    return qNorm === stdNorm || qNorm.startsWith(stdNorm) || stdNorm.startsWith(qNorm)
  })
  if (!qual) return false
  if (scopeType === 'ea') {
    if (!clientEACode) return true
    const qualEA = qual.ea_codes
    if (!qualEA || qualEA.length === 0) return true
    const clientNum = clientEACode.replace(/[^0-9]/g, '')
    return qualEA.some((c) => c.replace(/[^0-9]/g, '') === clientNum)
  }
  return true
})
```

---

## What NOT to change

- The backend `available-auditors` endpoint — no change. `covered_scope` continues to
  reflect the auditor's actual qualification records. The TE extension is purely a
  **frontend display rule**, not a qualification system change.
- The committee picker coverage (`CommitteePlanningCard`) — committee members are not
  TEs; no change needed there.
- `labelName` helper — already appends "(TE)" correctly.
- Any other part of `computeCoverage` or `StageCard`.

---

## Files to change

| File | Change |
|------|--------|
| `frontend/src/app/(app)/clients/[id]/page.tsx` | `computeCoverage`: per-code branch — add TE cross-standard check; fallback branch — add TE short-circuit before qualification lookup |

---

## Commit message

```
Portal 70: TE EA codes cover all audit standards in coverage check

Business rule: a Technical Expert's EA code expertise spans every
standard in the audit, not only the standard they hold a formal
auditor qualification for.

Before: covered_scope keyed by standard — Altuğ (TE, EA 5) only
  matched ISO 9001, not ISO 14001 or ISO 45001.
After: if teNames.has(auditor.name), check EA code across all
  covered_scope values, not just covered_scope[std].

Change is frontend-only in computeCoverage — two findcalls updated.
Backend covered_scope unchanged.
```
