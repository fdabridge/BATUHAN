# Prompt 33 — Date Override / Retroactive Mode

## Context

The retroactive operation will bulk-enter ~100 historical clients whose certifications
happened over the past year. Every date recorded by the system defaults to "now" —
application date, workflow transition timestamps, stage dates. Stage dates and cert dates
are already editable (StageCard, CertSection). The remaining blockers are:

1. **Application date** — when the client actually applied. Currently `AuditSet.created_at`
   is set on creation and can't be changed. A separate `application_date` field is needed.

2. **Workflow transition dates** — when each `workflow_status` transition happened.
   Currently always `datetime.utcnow()`. The WorkflowStatusBar CTA needs a date picker
   so the planner can record the actual historical date of each transition.

3. **Retroactive Mode banner** — a persistent amber notice visible to all CB staff on
   the client audit set page, making it clear the system is in historical-data-entry mode.
   **No off switch** — will be removed in a future prompt once the operation is complete.

**Nothing else changes.** Signing flows, document generation, OTP removal, Stage 1/2
workflow paths, and all other recent work are untouched.

---

## Summary of changes

| File | What changes |
|------|-------------|
| `backend/audit_set/db_models.py` | New `application_date DATE` column on `AuditSet`; safe migration added to `create_tables()` |
| `backend/audit_set/schemas.py` | `application_date` field added to `AuditSetUpdatePlanningSchema` and `AuditSetResponse` |
| `backend/audit_set/service.py` | Apply `data.application_date` in `update_planning()` |
| `backend/audit_set/workflow_router.py` | `WorkflowUpdateSchema`: optional `effective_date`; `AuditSetStatusEvent.triggered_at` uses it when provided |
| `frontend/src/components/ui/WorkflowStatusBar.tsx` | Add `effectiveDate` state + date input below each CTA button; send `effective_date` in PATCH body |
| `frontend/src/app/(app)/clients/[id]/page.tsx` | `RetroactiveBanner` component at top of audit set page; `application_date` field in `PlanOverview` |

---

## Change 1 — `backend/audit_set/db_models.py`

### 1a — New column on `AuditSet`

Add `application_date` to the `AuditSet` class. Place it under the `# ── Timestamps ──`
section, just before `created_at`:

```python
# ── Application / Retroactive ─────────────────────────────────────────────
application_date = Column(Date, nullable=True)   # when the client actually applied (set during retroactive entry)
```

Make sure `Date` is already imported from `sqlalchemy` (it is — used by `cert_issued_date`
and `cert_expiry_date`).

### 1b — Safe migration in `create_tables()`

In `create_tables()`, after the existing `_safe_add_column` calls, add:

```python
# Prompt 33 — retroactive operation support
_safe_add_column("audit_sets", "application_date DATE")
```

---

## Change 2 — `backend/audit_set/schemas.py`

### 2a — `AuditSetUpdatePlanningSchema`

Add one field (keep all existing fields unchanged):

```python
class AuditSetUpdatePlanningSchema(BaseModel):
    # ... existing fields unchanged ...
    application_date: Optional[date] = None     # ← ADD
```

`date` is already imported at the top of the file (used by `AuditSetCertUpdateSchema`).
If not, add `from datetime import date` to the imports.

### 2b — `AuditSetResponse`

Add one field (keep all existing fields unchanged):

```python
class AuditSetResponse(BaseModel):
    # ... existing fields unchanged ...
    application_date: Optional[date] = None     # ← ADD
```

Place it near `cert_issued_date` / `cert_expiry_date` for logical grouping.

---

## Change 3 — `backend/audit_set/service.py`

In `update_planning()`, after the existing field-update block (the series of
`if data.xxx is not None:` statements), add:

```python
if data.application_date is not None:
    audit_set.application_date = data.application_date
```

No other changes to this function.

---

## Change 4 — `backend/audit_set/workflow_router.py`

### 4a — Imports

Add `from datetime import date, datetime` at the top of the file (after the existing
`from __future__ import annotations` and before the `fastapi` imports):

```python
from datetime import date, datetime
```

### 4b — `WorkflowUpdateSchema`

Add the optional `effective_date` field:

```python
class WorkflowUpdateSchema(BaseModel):
    workflow_status: str
    notes: Optional[str] = None
    effective_date: Optional[date] = None    # ← ADD — override the transition timestamp
```

### 4c — `update_workflow_status` — use effective_date for the event timestamp

In `update_workflow_status`, just before the `AuditSetStatusEvent(...)` constructor,
add the timestamp resolution:

```python
# Retroactive mode: use caller-supplied date if provided, else record now.
if payload.effective_date:
    effective_ts = datetime(
        payload.effective_date.year,
        payload.effective_date.month,
        payload.effective_date.day,
    )
else:
    effective_ts = datetime.utcnow()

event = AuditSetStatusEvent(
    audit_set_id=audit_set_id,
    from_status=from_status,
    to_status=to_status,
    triggered_by=current_user.id,
    triggered_at=effective_ts,          # ← was implicit default
    notes=payload.notes,
)
```

The existing line that creates `AuditSetStatusEvent(...)` without a `triggered_at`
argument must be **replaced** with this version (the `triggered_at` column's Python-side
`default=datetime.utcnow` is only used when the value is omitted at construction, so
passing it explicitly always wins).

---

## Change 5 — `frontend/src/components/ui/WorkflowStatusBar.tsx`

### 5a — Add `effectiveDate` state

In the component body, after the existing `errMsg` state, add:

```typescript
// Retroactive mode — date picker for recording when transitions actually happened.
const [effectiveDate, setEffectiveDate] = useState<string>(
  () => new Date().toISOString().slice(0, 10)   // YYYY-MM-DD, defaults to today
)
```

### 5b — Update the mutation to accept an object

The mutation currently takes `nextStatus: string` as its argument. Change it to accept
an object so we can pass both `nextStatus` and `effectiveDate`:

```typescript
const { mutate: advance, isPending } = useMutation({
  mutationFn: ({ nextStatus, date }: { nextStatus: string; date: string }) =>
    api.patch(`/audit-sets/${auditSetId}/workflow-status`, {
      workflow_status: nextStatus,
      notes: 'Advanced from workflow status bar',
      effective_date: date,
    }),
  onSuccess: () => { setErrMsg(null); onAdvanced() },
  onError: (e: unknown) => {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    setErrMsg(detail || 'Could not advance status')
  },
})
```

### 5c — Update the CTA click handler

Change the `onClick` of the CTA button from:

```typescript
onClick={() => advance(panel.cta!.nextStatus)}
```

to:

```typescript
onClick={() => advance({ nextStatus: panel.cta!.nextStatus, date: effectiveDate })}
```

### 5d — Add the date picker below the CTA button

After the CTA button (still inside the `{panel.cta && ctaAllowed && (...)}` block),
add the date input:

```tsx
{panel.cta && ctaAllowed && (
  <div>
    <button
      type="button"
      disabled={isPending}
      onClick={() => advance({ nextStatus: panel.cta!.nextStatus, date: effectiveDate })}
      className="mt-3 rounded-lg px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60"
      style={{ background: '#1A4731' }}
    >
      {isPending ? 'Saving…' : panel.cta.label}
    </button>

    {/* Retroactive date picker — always visible, no off switch */}
    <div className="mt-2 flex items-center gap-2">
      <label className="text-xs text-gray-500">Effective date:</label>
      <input
        type="date"
        value={effectiveDate}
        onChange={e => setEffectiveDate(e.target.value)}
        className="rounded border border-gray-200 px-2 py-0.5 text-xs text-gray-700 focus:border-[#1A4731] focus:outline-none"
      />
    </div>
  </div>
)}
```

> **Note:** The old single-button block must be replaced by this new block. Do not
> render the button twice.

---

## Change 6 — `frontend/src/app/(app)/clients/[id]/page.tsx`

### 6a — `RetroactiveBanner` component

Add this new component **before** the `PlanOverview` function (or anywhere in the file,
but not inside another component):

```tsx
function RetroactiveBanner() {
  return (
    <div className="mb-4 flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
      <span className="mt-0.5 text-base leading-none text-amber-500">⚠</span>
      <div>
        <p className="text-sm font-semibold text-amber-800">Retroactive Operation Mode</p>
        <p className="mt-0.5 text-xs text-amber-700">
          Historical data entry is active. Use the <strong>Effective date</strong> field
          next to each workflow button to record when transitions actually occurred.
          Stage dates and certificate dates are already freely editable.
        </p>
      </div>
    </div>
  )
}
```

### 6b — Render the banner at the top of the audit set content

The page renders `<WorkflowStatusBar>` and `<PlanOverview>` and `<CertSection>` etc.
Find the top of the main content render area and insert `<RetroactiveBanner />` as the
very first element:

```tsx
{/* Retroactive mode — always shown, no off switch */}
<RetroactiveBanner />

{/* Existing content follows: WorkflowStatusBar, PlanOverview, etc. */}
```

> Place it before `<WorkflowStatusBar>` — it should be the topmost element in the
> content area so it's impossible to miss.

### 6c — Application Date field in `PlanOverview`

In the `PlanOverview` function, add state and a mutation for `application_date`.

**Add state** (alongside the other state declarations at the top of `PlanOverview`):

```typescript
const [appDate, setAppDate] = useState<string>(
  data.application_date ? String(data.application_date) : ''
)
const [appDateSaved, setAppDateSaved] = useState(false)

// Keep in sync after invalidation
useEffect(() => {
  setAppDate(data.application_date ? String(data.application_date) : '')
}, [data.application_date])
```

**Add mutation** (alongside `saveFees` and `saveNac`):

```typescript
const { mutate: saveAppDate, isPending: savingAppDate } = useMutation({
  mutationFn: () =>
    api.put(`/audit-sets/${auditSetId}/planning`, {
      application_date: appDate || null,
    }),
  onSuccess: () => {
    onInvalidate()
    setAppDateSaved(true)
    setTimeout(() => setAppDateSaved(false), 2000)
  },
})
```

**Add UI** — insert this block inside the `PlanOverview` return, near the top of the
rendered content (just below the `<p>Plan overview</p>` header, before the integration
level selector or fee inputs):

```tsx
{/* Application date — retroactive override */}
<div className="mb-4 flex flex-wrap items-center gap-3">
  <label className="text-xs font-medium text-gray-600">Application date</label>
  <input
    type="date"
    value={appDate}
    onChange={e => setAppDate(e.target.value)}
    className="rounded border border-gray-200 px-2 py-1 text-sm focus:border-[#1A4731] focus:outline-none"
  />
  <button
    type="button"
    onClick={() => saveAppDate()}
    disabled={savingAppDate}
    className="rounded-lg bg-[#1A4731] px-3 py-1 text-xs font-medium text-white hover:bg-[#143828] disabled:opacity-50"
  >
    {appDateSaved ? 'Saved ✓' : savingAppDate ? 'Saving…' : 'Save'}
  </button>
  {data.application_date && (
    <span className="text-xs text-gray-400">
      Currently: {new Date(data.application_date).toLocaleDateString('en-GB', {
        day: 'numeric', month: 'short', year: 'numeric',
      })}
    </span>
  )}
</div>
```

---

## Verification Checklist

- [ ] After Railway deploy, open any audit set → amber **Retroactive Operation Mode**
  banner appears at the top of the page ✅
- [ ] Workflow status CTA (e.g. "Schedule Stage 1") shows an **Effective date** picker
  below it, pre-filled with today ✅
- [ ] Change the effective date to a historical date (e.g. 2024-11-01) → click the CTA
  → `GET /audit-sets/{id}/status-history` shows `triggered_at` = 2024-11-01T00:00:00 ✅
- [ ] Leave effective date at today → click CTA → `triggered_at` ≈ now ✅
- [ ] PlanOverview shows **Application date** field with a date input and Save button ✅
- [ ] Enter a historical date, click Save → `PUT /audit-sets/{id}/planning` → field
  persists across page reload ✅
- [ ] `GET /audit-sets/{id}` response includes `application_date` field ✅
- [ ] Stage dates (StageCard) still freely editable — no regression ✅
- [ ] Certificate dates (CertSection) still freely editable — no regression ✅
- [ ] Surveillance audit set page → banner visible, effective date picker works ✅
