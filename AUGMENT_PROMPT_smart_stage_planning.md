# Augment Task: Man-Day-Driven Stage Planning + Auditor Availability

## Context

This is Certiva — a Next.js 14 (App Router) + FastAPI platform for ISO certification bodies.

The backend already has a fully working IAF MD 5 audit time calculator (`backend/calculator/engine.py`).
When an audit set is created and the application form is uploaded, the calculator runs and stores its
output in `audit_sets.audit_set.man_day_result` (a JSON dict of type `CalculationResult`).

**The problem**: the stage planning form completely ignores this calculation. A planner can manually
type any start/end date for any stage with no guidance on how many days are required, and can pick
any auditor regardless of their qualifications or existing bookings.

**What needs to be built**: smart stage planning that (a) shows the recommended man-days from the
existing calculation, (b) warns if the date range doesn't match, and (c) filters the auditor dropdown
to only show auditors who are qualified AND available on those dates.

---

## What Already Exists (do not break these)

- `backend/calculator/engine.py` — IAF MD 5 calculation engine. Already working.
- `backend/calculator/models.py` — `CalculationResult` schema with fields:
  - `final_ph1` — recommended Stage 1 days (initial certification)
  - `final_ph2` — recommended Stage 2 days (initial certification)
  - `final_surv1`, `final_surv2` — recommended surveillance days (each)
  - `final_recert_ph1`, `final_recert_ph2` — recertification days
  - `final_total`, `final_recert`, `total_employees`, `eps`, `standards`, `audit_type`
- `backend/audit_set/db_models.py` — `AuditSet` model has:
  - `man_day_result` (JSON, nullable) — the full `CalculationResult` dict
  - `effective_employees` (Integer, nullable)
  - `ea_code` (String, nullable) — e.g. `"EA 3"`
  - `standards` (JSON) — e.g. `["ISO 9001", "ISO 14001"]`
  - `audit_type` (String) — `"initial"` | `"surveillance"` | `"recertification"`
- `backend/audit_set/db_models.py` — `AuditSetStage` model has:
  - `stage_type` — `"stage_1"` | `"stage_2"` | `"surveillance"`
  - `audit_days` (Float, nullable) — already stored, just not pre-filled from calculator
  - `audit_date_start`, `audit_date_end` (Date, nullable)
  - `lead_auditor_id`, `lead_auditor_name` (String, nullable)
  - `auditors` (JSON, nullable) — list of `{id, name, ea_code, standard}`
- `backend/api/routes/audit_sets.py` — `PUT /audit-sets/{id}/planning` updates stages
- `backend/api/routes/auditors.py` — `GET /auditors/` returns `AuditorSummarySchema` list
- `frontend/src/app/(app)/clients/[id]/page.tsx` — `StageCard` component handles stage editing.
  Currently it fetches all active auditors from `GET /auditors/?active_only=true` and shows
  them in a dropdown regardless of qualification or availability.
- `frontend/src/types/index.ts` — `AuditSetResponse` includes `man_day_result`, `ea_code`,
  `standards`, `audit_type`, `effective_employees`.

---

## Task 1 — Backend: Auditor Availability Endpoint

**File:** `backend/api/routes/auditors.py`

Add a new route **before** the `/{auditor_id}` route to avoid FastAPI path conflicts:

```
GET /auditors/available
```

**Query parameters:**
- `date_start: str` — ISO date string `YYYY-MM-DD`
- `date_end: str` — ISO date string `YYYY-MM-DD`
- `standard_code: str | None = None` — e.g. `"ISO 9001"` (optional filter)
- `ea_code: str | None = None` — e.g. `"EA 3"` (optional filter)

**Logic:**
1. Fetch all active auditors from `auditors.db`.
2. If `standard_code` is provided, keep only auditors who have a `standard_qualifications` entry where `standard_code` matches (case-insensitive partial match) and `is_qualified` is not False.
3. If `ea_code` is provided, keep only auditors whose `ea_codes` list contains a code that matches the provided code (normalize: strip "EA ", compare integer part).
4. For each remaining auditor, query `audit_sets.db` for any `AuditSetStage` where:
   - `lead_auditor_id == auditor.id` OR the auditor's id appears in the `auditors` JSON field
   - AND `audit_date_start <= date_end` AND `audit_date_end >= date_start` (overlap check)
   - AND `status != "cancelled"` (if that field exists, otherwise skip this filter)
5. Mark auditors with overlapping bookings as `available: False` and include the conflict detail.

**Cross-DB access:** Both `auditors.db` and `audit_sets.db` use SQLite. Import both sessions directly:
```python
from auditors.models import get_db as get_auditors_db, Auditor, AuditorStandardQualification
from audit_set.db_models import get_db as get_sets_db, AuditSetStage
```
Call each in sequence (not concurrently — SQLite is synchronous).

**Response schema** — add to `auditors/schemas.py`:
```python
class AuditorAvailabilityItem(BaseModel):
    id: str
    name: str
    role: Optional[str]
    ea_codes: list[str]
    standard_qualifications: list[dict]   # [{standard_code, technical_depth}]
    available: bool
    conflict_detail: Optional[str]        # e.g. "Booked 2026-06-10 to 2026-06-12 (Client ABC)"
```

**Return:** `list[AuditorAvailabilityItem]`, sorted available first, then unavailable.

---

## Task 2 — Frontend: Man-Day Display in Stage Card

**File:** `frontend/src/app/(app)/clients/[id]/page.tsx`

### 2a. Pass man-day context down to StageCard

The parent `AuditDetailPage` (or wherever `StageCard` is rendered) fetches the `AuditSet` response.
This response includes `man_day_result`, `audit_type`, `standards`, and `ea_code`.

Currently `StageCard` receives: `stage`, `label`, `allStages`, `auditSetId`, `onSuccess`, `auditors`, `auditorsLoading`.

Add three more props:
```typescript
manDayResult: Record<string, number> | null   // the man_day_result JSON dict
auditType: string | null                       // "initial" | "surveillance" | "recertification"
eaCode: string | null                          // e.g. "EA 3"
standards: string[]                            // e.g. ["ISO 9001"]
```

Pass these from wherever `StageCard` is instantiated.

### 2b. Compute recommended days for this stage

Inside `StageCard`, add a helper:

```typescript
function recommendedDays(
  stageType: string,
  manDayResult: Record<string, number> | null,
  auditType: string | null
): number | null {
  if (!manDayResult) return null
  if (auditType === 'initial' || auditType === 'Initial') {
    if (stageType === 'stage_1') return manDayResult.final_ph1 ?? null
    if (stageType === 'stage_2') return manDayResult.final_ph2 ?? null
  }
  if (auditType === 'surveillance') {
    return manDayResult.final_surv1 ?? null
  }
  if (auditType === 'recertification') {
    if (stageType === 'stage_1') return manDayResult.final_recert_ph1 ?? null
    if (stageType === 'stage_2') return manDayResult.final_recert_ph2 ?? null
    return manDayResult.final_recert ?? null
  }
  return null
}
```

### 2c. Show recommended days banner

At the top of the `StageCard` edit form (before the lead auditor field), add:

```tsx
{recommended != null && (
  <div className="mb-3 rounded-md px-3 py-2 text-sm" style={{ background: '#F0FAF4', color: '#1A4731' }}>
    <span className="font-medium">IAF MD 5 calculated:</span> {recommended} audit days recommended for this stage.
    {stage.audit_days != null && stage.audit_days !== recommended && (
      <span className="ml-2" style={{ color: '#92400E' }}>
        (Currently saved: {stage.audit_days} days)
      </span>
    )}
  </div>
)}
```

### 2d. Date range validation

When both `audit_date_start` and `audit_date_end` are filled, compute working days in the range
(count Mon–Fri, excluding weekends — no holiday calendar needed):

```typescript
function workingDaysBetween(start: string, end: string): number {
  const s = new Date(start), e = new Date(end)
  let count = 0
  const d = new Date(s)
  while (d <= e) {
    const day = d.getDay()
    if (day !== 0 && day !== 6) count++
    d.setDate(d.getDate() + 1)
  }
  return count
}
```

If `recommended != null` and the computed working days differ from `recommended` by more than 0.5:

```tsx
<div className="mt-2 rounded-md px-3 py-2 text-sm" style={{ background: '#FEF3C7', color: '#92400E' }}>
  ⚠ Date range covers {workingDays} working day(s), but IAF MD 5 recommends {recommended}.
  {workingDays > recommended
    ? ' This exceeds the recommended duration.'
    : ' This is shorter than the recommended duration.'}
</div>
```

Do NOT block saving — this is a warning only. The planner can override.

---

## Task 3 — Frontend: Auditor Availability Filter

**File:** `frontend/src/app/(app)/clients/[id]/page.tsx`

### 3a. Add type to frontend/src/types/index.ts

```typescript
export interface AuditorAvailabilityItem {
  id: string
  name: string
  role: string | null
  ea_codes: string[]
  standard_qualifications: { standard_code: string; technical_depth: string }[]
  available: boolean
  conflict_detail: string | null
}
```

### 3b. Replace static auditor list with availability query

Remove the existing static `GET /auditors/?active_only=true` query from the stage area.
Instead, inside `StageCard`, add a **local** React Query that fires when both `audit_date_start`
and `audit_date_end` are non-empty:

```typescript
const primaryStandard = standards[0] ?? null

const { data: availableAuditors, isFetching: loadingAvailability } = useQuery<AuditorAvailabilityItem[]>({
  queryKey: ['auditor-availability', edit.audit_date_start, edit.audit_date_end, primaryStandard, eaCode],
  queryFn: () => {
    const params = new URLSearchParams({
      date_start: edit.audit_date_start,
      date_end: edit.audit_date_end,
    })
    if (primaryStandard) params.set('standard_code', primaryStandard)
    if (eaCode) params.set('ea_code', eaCode)
    return api.get<AuditorAvailabilityItem[]>(`/auditors/available?${params}`).then(r => r.data)
  },
  enabled: !!edit.audit_date_start && !!edit.audit_date_end,
  staleTime: 30_000,
})
```

### 3c. Update lead auditor dropdown

Replace the current lead auditor `<select>` to use `availableAuditors` when dates are selected,
otherwise fall back to the existing `auditors` prop (all active auditors):

```tsx
<div>
  <label className={lblCls}>Lead auditor</label>
  {loadingAvailability && (
    <p className="text-xs text-gray-400 mb-1">Checking availability…</p>
  )}
  <select
    className={inputCls}
    value={edit.lead_auditor_name}
    onChange={(e) => patch({ lead_auditor_name: e.target.value })}
  >
    <option value="">— Select —</option>
    {(availableAuditors ?? auditors).map((a) => {
      const avail = availableAuditors?.find(x => x.name === a.name)
      const isUnavailable = avail && !avail.available
      return (
        <option
          key={a.id ?? a.name}
          value={a.name}
          disabled={isUnavailable}
        >
          {a.name}
          {isUnavailable ? ' — Unavailable' : ''}
        </option>
      )
    })}
  </select>
  {availableAuditors && (() => {
    const selected = availableAuditors.find(a => a.name === edit.lead_auditor_name)
    if (selected?.conflict_detail) {
      return <p className="mt-1 text-xs text-red-500">{selected.conflict_detail}</p>
    }
    return null
  })()}
</div>
```

### 3d. Show availability summary above the auditor dropdown

When dates are selected and `availableAuditors` is loaded, show a small info line:

```tsx
{availableAuditors && (
  <p className="mb-2 text-xs text-gray-500">
    {availableAuditors.filter(a => a.available).length} of {availableAuditors.length} auditors
    qualified & available for {primaryStandard ?? 'this standard'} on selected dates.
  </p>
)}
```

---

## Task 4 — Also surface man-day result in the read-only stage display

**File:** `frontend/src/app/(app)/clients/[id]/page.tsx`

The stage card already shows `{stage.audit_days} days` in read-only mode (line ~240).
Extend this to also show the recommended value if different:

```tsx
{stage.audit_days != null && (
  <div className="text-xs text-gray-500">
    {stage.audit_days} days audited
    {recommended != null && stage.audit_days !== recommended && (
      <span className="ml-1" style={{ color: '#92400E' }}>
        (recommended: {recommended})
      </span>
    )}
  </div>
)}
{stage.audit_days == null && recommended != null && (
  <div className="text-xs" style={{ color: '#92400E' }}>
    {recommended} days recommended — not yet scheduled
  </div>
)}
```

---

## IAF MD 5 Reference

- An audit day = 8 hours (IAF MD 5 §1.8)
- The calculation of recommended days per stage already exists in `man_day_result` — do not reimplement it

---

## API Route Summary

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/auditors/available` | New — filtered by date, standard, EA code |

All other endpoints already exist. The availability route must be registered before `/{auditor_id}`
in `backend/api/routes/auditors.py` to avoid FastAPI matching the literal string "available" as an ID.

---

## Files to Change

- `backend/api/routes/auditors.py` — add `GET /auditors/available` route
- `backend/auditors/schemas.py` — add `AuditorAvailabilityItem` schema
- `frontend/src/app/(app)/clients/[id]/page.tsx` — StageCard improvements
- `frontend/src/types/index.ts` — add `AuditorAvailabilityItem` type

## Do Not Change

- `backend/calculator/` — do not touch the existing calculator engine or tables
- `backend/audit_set/` — do not change DB models or existing routes
- `frontend/src/lib/api.ts`
- `frontend/src/lib/auth.tsx`
- `frontend/src/components/layout/`
- Any other backend files not listed above
- No new npm packages

---

## Priority Order

1. Task 1 (backend availability endpoint) — foundation for everything else
2. Task 2 (man-day display in stage card) — highest user-visible value, small change
3. Task 3 (availability-filtered auditor dropdown) — depends on Task 1
4. Task 4 (read-only display improvement) — cosmetic, do last
