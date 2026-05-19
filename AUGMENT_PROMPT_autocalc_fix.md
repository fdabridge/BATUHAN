# Fix: Auto-calculation must fire from stored personnel, not from effective_employees

## Context

When a client is created through the application form, all personnel data (full_time, part_time, subcontractors, seasonal) is stored in `audit_set.personnel`. The man-day calculation must run automatically and show results on the client detail page without any user interaction.

Currently it does not. The frontend has an auto-calc `useEffect` that is supposed to trigger the calculation, but it checks the wrong field and sends incomplete data. Here are the two exact fixes.

---

## FIX 1 — Auto-calc useEffect: wrong guard + wrong payload

**File:** `frontend/src/app/(app)/clients/[id]/page.tsx`

**Find this block (around line 1130):**
```typescript
  // Auto-calculate man-days on page load if result is missing but employees are known
  const autoCalcFired = useRef(false)
  useEffect(() => {
    if (!data || data.man_day_result || autoCalcFired.current) return
    if (!data.effective_employees || data.effective_employees <= 0) return
    autoCalcFired.current = true
    api.post(`/audit-sets/${id}/quick-calculate`, {
      scope_integration_level: data.scope_integration_level ?? 'Medium',
    }).then(() => queryClient.invalidateQueries({ queryKey: ['client', id] })).catch(() => {})
  }, [data?.id, data?.man_day_result])   // eslint-disable-line react-hooks/exhaustive-deps
```

**Replace it with:**
```typescript
  // Auto-calculate man-days on page load if result is missing but personnel is stored
  const autoCalcFired = useRef(false)
  useEffect(() => {
    if (!data || data.man_day_result || autoCalcFired.current) return
    const p = data.personnel
    const totalPersonnel = (p?.full_time || 0) + (p?.part_time || 0) + (p?.subcontractors || 0) + (p?.seasonal || 0) + (p?.unskilled || 0)
    if (totalPersonnel <= 0) return  // genuinely no personnel entered — show QuickCalcWidget
    autoCalcFired.current = true
    api.post(`/audit-sets/${id}/quick-calculate`, {
      personnel: {
        full_time:      p?.full_time      || 0,
        part_time:      p?.part_time      || 0,
        subcontractors: p?.subcontractors || 0,
        seasonal:       p?.seasonal       || 0,
        unskilled:      p?.unskilled      || 0,
      },
      scope_integration_level: data.scope_integration_level ?? 'Medium',
    }).then(() => queryClient.invalidateQueries({ queryKey: ['client', id] })).catch(() => {})
  }, [data?.id, data?.man_day_result])   // eslint-disable-line react-hooks/exhaustive-deps
```

**Why:** `effective_employees` is only populated after a calculation has already run. If `man_day_result` is null (calculation never ran or failed), `effective_employees` is also null, so the guard always blocks. We must read from `data.personnel` — the raw data entered in the application form — instead.

---

## FIX 2 — QuickCalcWidget: pre-fill fields from stored personnel

The widget opens with blank fields even when personnel data is stored on the audit set. The user should never have to re-enter data they already submitted.

**File:** `frontend/src/app/(app)/clients/[id]/page.tsx`

**Find the QuickCalcWidget component signature (around line 1034):**
```typescript
function QuickCalcWidget({ auditSetId, onSuccess }: { auditSetId: string; onSuccess: () => void }) {
  const [open, setOpen] = useState(true)
  const [fullTime,  setFullTime]  = useState('')
  const [partTime,  setPartTime]  = useState('')
  const [subcontr,  setSubcontr]  = useState('')
  const [seasonal,  setSeasonal]  = useState('')
```

**Replace with:**
```typescript
function QuickCalcWidget({ auditSetId, onSuccess, initialPersonnel }: {
  auditSetId: string
  onSuccess: () => void
  initialPersonnel?: { full_time?: number; part_time?: number; subcontractors?: number; seasonal?: number; unskilled?: number } | null
}) {
  const [open, setOpen] = useState(true)
  const [fullTime,  setFullTime]  = useState(String(initialPersonnel?.full_time      || ''))
  const [partTime,  setPartTime]  = useState(String(initialPersonnel?.part_time      || ''))
  const [subcontr,  setSubcontr]  = useState(String(initialPersonnel?.subcontractors || ''))
  const [seasonal,  setSeasonal]  = useState(String(initialPersonnel?.seasonal       || ''))
```

**Then find where QuickCalcWidget is rendered (around line 1244):**
```typescript
      {!data.man_day_result && (
        <QuickCalcWidget auditSetId={id} onSuccess={invalidate} />
      )}
```

**Replace with:**
```typescript
      {!data.man_day_result && (
        <QuickCalcWidget auditSetId={id} onSuccess={invalidate} initialPersonnel={data.personnel} />
      )}
```

---

## Result after these two fixes

**Client created with personnel (normal application form flow):**
- Page loads → `useEffect` reads `data.personnel` → total > 0 → fires `quick-calculate` with the stored personnel → `man_day_result` is saved → page refreshes → man-day section shows results
- No QuickCalcWidget shown (man_day_result is now populated)
- Zero user interaction required

**Client created without personnel (e.g., manual/legacy test records):**
- Page loads → `useEffect` reads `data.personnel` → total = 0 → does not fire auto-calc
- QuickCalcWidget opens pre-filled with 0s (or whatever is stored)
- User enters personnel once → clicks Calculate → done

---

## Files changed

| File | Change |
|---|---|
| `frontend/src/app/(app)/clients/[id]/page.tsx` | (1) Auto-calc useEffect: check `data.personnel` total instead of `data.effective_employees`; pass full personnel object in the API call body. (2) QuickCalcWidget: add `initialPersonnel` prop and pre-fill state from it. (3) QuickCalcWidget render call: pass `initialPersonnel={data.personnel}`. |

No backend changes. No other files.
