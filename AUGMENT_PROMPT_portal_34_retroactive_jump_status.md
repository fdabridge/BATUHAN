# Prompt 34 — Retroactive Jump-to-Status

## Context

Internally-created audit sets (created by CB admin, not submitted via the client portal)
start with `workflow_status = NULL`. The normal transition table has no path from `NULL`
for admin/planner — only `system` can do `NULL → pending_review`. This means the
WorkflowStatusBar currently returns `null` for these sets and the portal workflow cannot
be activated.

For the retroactive operation (~100 historical clients), each client needs to land at
`certified` (or whatever status they are currently at). Stepping through all 10+
intermediate transitions with date overrides would take ~1000 clicks. What's needed is
a single admin action: "activate portal workflow at this status, on this historical date."

This prompt adds:
1. A **jump endpoint** — admin/planner can set `workflow_status` to any target value
   directly, bypassing transition rules, with a historical effective date.
2. A **"Start Workflow" panel** in WorkflowStatusBar — shown when `workflow_status = null`
   for admin/planner; includes a status dropdown (defaulting to `certified`) and a date
   picker (defaulting to today).

**Nothing else changes.** Signing flows, OTP removal, Stage 1/2 workflow, date override
CTA pickers, retroactive banner — all untouched.

---

## Summary of changes

| File | What changes |
|------|-------------|
| `backend/audit_set/workflow_router.py` | New `POST /audit-sets/{id}/workflow-status/jump` endpoint — admin/planner only, no transition validation |
| `frontend/src/components/ui/WorkflowStatusBar.tsx` | When `currentStatus = null` + role is admin/planner, render "Start Workflow" panel instead of returning `null` |

---

## Change 1 — `backend/audit_set/workflow_router.py`

### 1a — New schema

Add after `WorkflowUpdateSchema`:

```python
# The full set of statuses that can be set via the jump endpoint.
VALID_JUMP_STATUSES = {
    "in_planning",
    "quotation_sent",
    "agreement_signed",
    "stage1_scheduled",
    "stage1_in_progress",
    "stage1_complete",
    "stage2_scheduled",
    "stage2_in_progress",
    "audit_scheduled",
    "audit_in_progress",
    "under_review",
    "certified",
}

class WorkflowJumpSchema(BaseModel):
    target_status: str
    effective_date: Optional[date] = None   # defaults to now if omitted
```

### 1b — New endpoint

Add after the `update_workflow_status` endpoint:

```python
@router.post("/{audit_set_id}/workflow-status/jump")
def jump_workflow_status(
    audit_set_id: str,
    payload: WorkflowJumpSchema,
    db: Session = Depends(get_audit_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """
    Retroactive operation: set workflow_status directly, bypassing transition rules.
    Admin and planner only. Creates a single status event with the supplied date.
    Does NOT fire the side effects of normal transitions (FR.218 seeding, etc.).
    """
    if current_user.role not in {"admin", "planner"}:
        raise HTTPException(403, "Only admin and planner can jump workflow status")

    if payload.target_status not in VALID_JUMP_STATUSES:
        raise HTTPException(400, f"Unknown status: {payload.target_status}")

    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set:
        raise HTTPException(404, "Audit set not found")

    from_status = audit_set.workflow_status
    if from_status == payload.target_status:
        raise HTTPException(400, "Audit set is already at that status")

    audit_set.workflow_status = payload.target_status

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
        to_status=payload.target_status,
        triggered_by=current_user.id,
        triggered_at=effective_ts,
        notes="Retroactive jump — set by admin",
    )
    db.add(event)
    db.commit()
    db.refresh(audit_set)

    return {"id": audit_set.id, "workflow_status": audit_set.workflow_status}
```

---

## Change 2 — `frontend/src/components/ui/WorkflowStatusBar.tsx`

### 2a — New state for the jump panel

Add inside the `WorkflowStatusBar` function, after the existing `effectiveDate` state:

```typescript
// Jump panel — used when workflow_status is null (internal audit sets)
const [jumpStatus,   setJumpStatus]   = useState('certified')
const [jumpDate,     setJumpDate]     = useState(() => new Date().toISOString().slice(0, 10))
const [jumpPending,  setJumpPending]  = useState(false)
const [jumpErr,      setJumpErr]      = useState<string | null>(null)
```

### 2b — New jump handler

Add after the mutation declaration:

```typescript
async function handleJump() {
  setJumpPending(true)
  setJumpErr(null)
  try {
    await api.post(`/audit-sets/${auditSetId}/workflow-status/jump`, {
      target_status: jumpStatus,
      effective_date: jumpDate,
    })
    onAdvanced()
  } catch (err: unknown) {
    const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    setJumpErr(detail || 'Failed to set status')
  } finally {
    setJumpPending(false)
  }
}
```

### 2c — Replace the early-return for null status

Find this line:

```typescript
if (!currentStatus || currentStatus === 'pending_review') return null
```

Replace it with:

```typescript
if (currentStatus === 'pending_review') return null

if (!currentStatus) {
  // Workflow not started yet. Show jump panel for admin/planner only.
  if (currentUserRole !== 'admin' && currentUserRole !== 'planner') return null

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5 mb-2">
      <p className="text-sm font-semibold text-gray-800">Portal workflow not started</p>
      <p className="mt-1 text-xs text-gray-500">
        This audit set was created internally. Set its current workflow status to activate
        the portal view — use a historical date for retroactive clients.
      </p>

      <div className="mt-4 flex flex-wrap items-end gap-3">
        {/* Status selector */}
        <div>
          <label className="mb-1 block text-xs font-medium text-gray-600">
            Current status
          </label>
          <select
            value={jumpStatus}
            onChange={e => setJumpStatus(e.target.value)}
            className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm text-gray-800 focus:border-[#1A4731] focus:outline-none"
          >
            <option value="in_planning">In Planning</option>
            <option value="quotation_sent">Quotation Sent</option>
            <option value="agreement_signed">Agreement Signed</option>
            <option value="stage1_scheduled">Stage 1 Scheduled</option>
            <option value="stage1_in_progress">Stage 1 In Progress</option>
            <option value="stage1_complete">Stage 1 Complete</option>
            <option value="stage2_scheduled">Stage 2 Scheduled</option>
            <option value="stage2_in_progress">Stage 2 In Progress</option>
            <option value="audit_scheduled">Audit Scheduled</option>
            <option value="audit_in_progress">Audit In Progress</option>
            <option value="under_review">Under Review</option>
            <option value="certified">Certified ✓</option>
          </select>
        </div>

        {/* Date picker */}
        <div>
          <label className="mb-1 block text-xs font-medium text-gray-600">
            Effective date
          </label>
          <input
            type="date"
            value={jumpDate}
            onChange={e => setJumpDate(e.target.value)}
            className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-700 focus:border-[#1A4731] focus:outline-none"
          />
        </div>

        {/* Apply button */}
        <button
          type="button"
          onClick={handleJump}
          disabled={jumpPending}
          className="rounded-lg px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-60"
          style={{ background: '#1A4731' }}
        >
          {jumpPending ? 'Applying…' : 'Activate Workflow'}
        </button>
      </div>

      {jumpErr && (
        <p className="mt-2 text-xs text-red-500">{jumpErr}</p>
      )}
    </div>
  )
}
```

No other changes to the component. The rest of the existing logic (step strip, action
panel, CTA + effective date picker) remains exactly as-is.

---

## Verification Checklist

- [ ] Create an audit set via the CB admin interface (not portal) → open its page → see
  "Portal workflow not started" panel with status dropdown (default: `certified`) and
  date picker ✅
- [ ] Select `certified`, enter a historical date (e.g. 2024-03-15), click
  "Activate Workflow" → page refreshes → WorkflowStatusBar shows the normal certified
  step strip with all steps marked done ✅
- [ ] `GET /audit-sets/{id}/status-history` → one event: `from_status: null`,
  `to_status: certified`, `triggered_at: 2024-03-15T00:00:00` ✅
- [ ] Select `under_review` instead → WorkflowStatusBar shows 10-of-11 steps done,
  "Issue Certificate" CTA panel visible ✅
- [ ] Auditor or client role viewing the same page → panel does not render (returns null
  for them) ✅
- [ ] On an audit set that ALREADY has a `workflow_status` (e.g. `in_planning`) → the
  jump panel does NOT appear; normal WorkflowStatusBar renders as before ✅
- [ ] After jump to `certified`: CertSection, StageCard still visible and editable ✅
- [ ] `POST /jump` with an invalid status string → 400 error ✅
- [ ] Auditor calling `POST /jump` → 403 error ✅
