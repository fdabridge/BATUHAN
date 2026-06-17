# Portal 69 — Committee Picker: Restore Saved Members on Page Refresh

## Root cause

`CommitteePlanningCard` in `frontend/src/app/(app)/clients/[id]/page.tsx` uses a
**lazy `useState` initializer** (a function passed to `useState(...)`) to seed the
`selected` array from the `initialCommittee` prop:

```ts
// Line ~821 — BUG: lazy initializer runs ONCE on first render only
const [selected, setSelected] = useState<AvailableCommitteeAuditor[]>(() => {
  if (!initialCommittee) return []
  return initialCommittee.map((m) => ({ ... }))
})
```

`initialCommittee` is `data.committee_members` from the parent page, which is
fetched asynchronously. On the **first render** (while data is loading) `initialCommittee`
is `undefined` → the initializer returns `[]`. When the API call resolves and
`initialCommittee` becomes the saved array, **React does not re-run the initializer** —
so `selected` stays `[]` forever after a page refresh.

The existing pool-fetch `useEffect` tries to enrich `selectedRef.current`, but since
`selectedRef.current === []` at resolution time, nothing gets restored.

---

## Fix — inside `CommitteePlanningCard`

Two changes, no other code touched:

### Change 1 — Replace lazy initializer with plain `useState([])`

```ts
// BEFORE (line ~821):
const [selected, setSelected] = useState<AvailableCommitteeAuditor[]>(() => {
  if (!initialCommittee) return []
  return initialCommittee.map((m) => ({
    id: m.id, full_name: m.name, email: m.email ?? '',
    ea_codes: m.ea_codes, standards: m.standards,
    covers_audit: true, covered_scope: {},
  }))
})

// AFTER:
const [selected, setSelected] = useState<AvailableCommitteeAuditor[]>([])
```

### Change 2 — Add a `useEffect` + ref guard that fires when `initialCommittee` arrives

Insert this immediately after the `selectedRef` assignment (around line ~840, after the
pool/saving/error state declarations):

```ts
// Ref guard: initializes selected from the saved committee exactly once,
// even though initialCommittee arrives asynchronously after first render.
const hasInitializedRef = useRef(false)

useEffect(() => {
  if (hasInitializedRef.current) return          // already initialized — don't overwrite user edits
  if (!initialCommittee || initialCommittee.length === 0) return   // nothing saved yet

  hasInitializedRef.current = true

  const restored: AvailableCommitteeAuditor[] = initialCommittee.map((m) => ({
    id:           m.id,
    full_name:    m.name ?? '',       // backend stores "name"; UI expects "full_name"
    email:        m.email ?? '',
    ea_codes:     m.ea_codes ?? [],
    standards:    m.standards ?? [],
    covers_audit: true,
    covered_scope: {},                // enriched by pool-fetch useEffect when pool arrives
  }))

  setSelected(restored)

  // If the pool has already loaded (race condition: pool resolved before data),
  // also remove the restored members from the dropdown pool.
  const restoredIds = new Set(restored.map((r) => r.id))
  setPool((prev) => prev.filter((a) => !restoredIds.has(a.id)))
}, [initialCommittee])
```

### Why this is safe

- The `hasInitializedRef.current` guard ensures the effect only runs once — it will
  not overwrite the user's in-progress edits if `initialCommittee` prop object changes
  for unrelated reasons (e.g. parent re-render).
- The existing pool-fetch `useEffect` already handles `covered_scope` enrichment:
  - **If pool resolves BEFORE `initialCommittee` arrives**: pool enriches `[]` (no-op),
    then this effect runs, sets `selected`, and filters the pool via `setPool(prev => ...)`.
  - **If pool resolves AFTER `initialCommittee` arrives**: this effect runs first, sets
    `selected`; pool-fetch then sees `selectedRef.current = restored` and enriches
    `covered_scope` + filters pool. ✓
- No changes to `handleSave`, `addMember`, `removeMember`, `coverageSummary`, or any
  backend endpoints.

---

## What the user sees after this fix

1. Plan committee (e.g. Chairperson: Ahmet, Member: Fatma) and click "Save committee".
2. Refresh the page.
3. CommitteePlanningCard renders with Ahmet and Fatma already in the chip list,
   coverage shows ✓ all covered, "Save committee" button is active (not disabled).

---

## Files to change

| File | Change |
|------|--------|
| `frontend/src/app/(app)/clients/[id]/page.tsx` | `CommitteePlanningCard`: replace lazy `useState(() => {...})` with `useState([])`; add `hasInitializedRef` + `useEffect` that fires when `initialCommittee` changes |

---

## Commit message

```
Portal 69: committee picker — restore saved members on page refresh

useState lazy initializer fires only on first render (when data is still
loading and initialCommittee is undefined), so saved committee members
were lost on every page refresh.

Fix: replace lazy initializer with useState([]) + a useEffect that fires
once when initialCommittee arrives asynchronously. A hasInitializedRef
guard prevents overwriting in-progress user edits. The existing pool-fetch
useEffect already handles covered_scope enrichment — no changes there.
```
