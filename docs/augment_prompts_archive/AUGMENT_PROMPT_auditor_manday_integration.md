# Fix: Man-day ÷ auditors = calendar days (reactive, live)

## The rule

```
required calendar days = ceil(stage.audit_days / total_auditors_on_team)
```

Examples:
- 2 audit-days, 1 auditor → 2 calendar days
- 2 audit-days, 2 auditors → 1 calendar day
- 3 audit-days, 2 auditors → 2 calendar days  (ceil(3/2) = 2)
- 4 audit-days, 3 auditors → 2 calendar days  (ceil(4/3) = 2)

When the user adds or removes an auditor, the end date must update automatically to match the new required calendar days. This is the core of the stage planning workflow.

---

## What already exists (do not change)

In `frontend/src/app/(app)/clients/[id]/page.tsx`, inside the stage card component, these variables are already computed correctly:

```typescript
const teamCount = (edit.lead_auditor_name ? 1 : 0) + edit.auditors.length + edit.technical_experts.length
const manDaysCovered = workingDays != null && teamCount > 0 ? workingDays * teamCount : null
const manDayShortfall = stage.audit_days != null && manDaysCovered != null && manDaysCovered < stage.audit_days
```

The warning banner already shows when `manDayShortfall` is true. Keep all of this.

---

## What is missing — add this

### 1. Reactive end-date recalculation when team changes

**File:** `frontend/src/app/(app)/clients/[id]/page.tsx`
**Location:** Inside the stage card component, after the existing mount `useEffect` (the one with `[]` deps that suggests initial dates)

Add this new `useEffect`:

```typescript
// Reactive: when team size changes and a start date exists, recompute end date
// so that: calendar days = ceil(audit_days / teamCount)
useEffect(() => {
  if (!edit.audit_date_start) return           // no start date yet — nothing to do
  if (!stage.audit_days) return                // no IAF recommendation — nothing to base on
  if (teamCount === 0) return                  // no auditors yet — keep existing date
  const calendarDaysNeeded = Math.ceil(stage.audit_days / teamCount)
  const newEnd = suggestEndDate(edit.audit_date_start, calendarDaysNeeded)
  if (newEnd !== edit.audit_date_end) {
    patch({ audit_date_end: newEnd })
  }
}, [teamCount])   // eslint-disable-line react-hooks/exhaustive-deps — intentionally watches teamCount only
```

This fires every time `teamCount` changes (auditor added or removed). It recomputes how many calendar days are needed and updates the end date field automatically. The user sees the end date shift in real time.

**Important:** This effect only fires when `teamCount` changes. It does NOT fire when the user manually edits the start or end date — do not add those to the dependency array.

### 2. Update the IAF banner to show the live math

**Find this existing banner (around line 660):**
```tsx
      {/* IAF MD 5 banner */}
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

**Replace with:**
```tsx
      {/* IAF MD 5 banner — shows live calendar days based on team size */}
      {recommended != null && (
        <div className="mb-3 rounded-md px-3 py-2 text-sm" style={{ background: '#F0FAF4', color: '#1A4731' }}>
          <span className="font-medium">IAF MD 5:</span>{' '}
          {recommended} audit-days for this stage.
          {teamCount > 0 && (
            <span className="ml-2 font-medium">
              {' '}÷ {teamCount} auditor{teamCount > 1 ? 's' : ''} ={' '}
              <span style={{ color: '#1A4731' }}>
                {Math.ceil(recommended / teamCount)} calendar day{Math.ceil(recommended / teamCount) > 1 ? 's' : ''}
              </span>
            </span>
          )}
          {teamCount === 0 && (
            <span className="ml-1 text-xs" style={{ color: '#92400E' }}>— assign auditors to see calendar days</span>
          )}
        </div>
      )}
```

This makes the banner show, live:
- **0 auditors:** "IAF MD 5: 2 audit-days for this stage. — assign auditors to see calendar days"
- **1 auditor:** "IAF MD 5: 2 audit-days for this stage. ÷ 1 auditor = 2 calendar days"
- **2 auditors:** "IAF MD 5: 2 audit-days for this stage. ÷ 2 auditors = 1 calendar day"
- **3 auditors, 4 days:** "IAF MD 5: 4 audit-days for this stage. ÷ 3 auditors = 2 calendar days"

---

## What the user sees — the full interaction

1. Stage card opens. Banner shows "IAF MD 5: 2 audit-days — assign auditors to see calendar days."
2. User picks start date. Suggested end date is set to start + 2 calendar days (1 auditor assumed by default).
3. User selects Lead Auditor. `teamCount` becomes 1.
   - Banner updates: "÷ 1 auditor = 2 calendar days"
   - End date stays at start + 2 (correct for 1 auditor)
4. User adds a second auditor from the "Add auditor" dropdown. `teamCount` becomes 2.
   - Banner updates instantly: "÷ 2 auditors = 1 calendar day"
   - End date automatically shifts to start + 1 calendar day
5. User adds a third auditor. `teamCount` becomes 3.
   - Banner updates: "÷ 3 auditors = 1 calendar day" (ceil(2/3) = 1)
   - End date stays at start + 1
6. User removes the second auditor. `teamCount` drops to 2.
   - Banner: "÷ 2 auditors = 1 calendar day"
   - End date stays at start + 1

---

## Files changed

| File | Change |
|---|---|
| `frontend/src/app/(app)/clients/[id]/page.tsx` | (1) Add one `useEffect` watching `teamCount` that recomputes `audit_date_end = suggestEndDate(start, ceil(stage.audit_days / teamCount))`. (2) Replace the IAF banner JSX to show the live "X audit-days ÷ Y auditors = Z calendar days" formula. |

No backend changes. No other files.
