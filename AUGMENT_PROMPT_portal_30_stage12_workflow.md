# Prompt 30 — Stage 1 / Stage 2 Workflow Split

## Context

Currently the workflow treats every audit the same:
`agreement_signed → audit_scheduled → audit_in_progress → under_review → certified`

ISO 17021-1 requires **initial certification** to have two distinct audit stages:
- **Stage 1** — document review, readiness assessment
- **Stage 2** — full on-site certification audit

Surveillance and recertification audits have **no Stage 1** — they follow the existing
single-audit path unchanged.

The `AuditSetStage` table already supports `stage_type = "stage_1" | "stage_2" | "surveillance"`.
Each `AuditSetStage` row already has its own `lead_auditor_id`/`lead_auditor_name`, so
different auditors per stage are already handled — no new DB columns needed.

The DB is empty (no existing records to migrate).

**What this prompt adds:**
1. New workflow statuses for the initial certification path in `VALID_TRANSITIONS`
2. A side-effect: when advancing to `stage1_complete`, mark the Stage 1 `AuditSetStage` row as `status="complete"`
3. Updated `WorkflowStatusBar` that shows the correct step strip and action cards depending on `audit_type`
4. Updated status-gate allowlists in all section components

**Nothing else changes** — signing flows, document handling, auditor assignment, FR218/FR222,
committees, NC forms are all untouched.

---

## New workflow paths

### Initial certification (`audit_type == "initial"`)
```
pending_review → in_planning → quotation_sent → agreement_signed
  → stage1_scheduled → stage1_in_progress → stage1_complete
  → stage2_scheduled → stage2_in_progress
  → under_review → certified
```

### Surveillance and recertification (unchanged)
```
pending_review → in_planning → quotation_sent → agreement_signed
  → audit_scheduled → audit_in_progress
  → under_review → certified
```

Both paths share the same `pending_review → agreement_signed` opening and the same
`under_review → certified` closing. The split is only in the middle.

---

## Change 1 — `backend/audit_set/workflow_router.py`

### 1a — Add new transitions

Add these six entries to `VALID_TRANSITIONS`:

```python
# Initial certification — Stage 1
("agreement_signed",   "stage1_scheduled"):   {"admin", "planner"},
("stage1_scheduled",   "stage1_in_progress"): {"admin", "planner", "auditor"},
("stage1_in_progress", "stage1_complete"):    {"admin", "planner", "auditor"},
# Initial certification — Stage 2
("stage1_complete",    "stage2_scheduled"):   {"admin", "planner"},
("stage2_scheduled",   "stage2_in_progress"): {"admin", "planner", "auditor"},
("stage2_in_progress", "under_review"):       {"admin", "planner", "auditor"},
```

Keep all existing entries exactly as they are — surveillance/recertification uses the
existing `audit_scheduled` / `audit_in_progress` entries unchanged.

### 1b — Side effect: mark Stage 1 complete on the AuditSetStage row

In `update_workflow_status`, after `audit_set.workflow_status = to_status`, add:

```python
# When Stage 1 is marked complete, close out the Stage 1 AuditSetStage row.
if to_status == "stage1_complete":
    stage1_row = (
        db.query(AuditSetStage)
        .filter_by(audit_set_id=audit_set_id, stage_type="stage_1")
        .first()
    )
    if stage1_row:
        stage1_row.status = "complete"
```

Add `AuditSetStage` to the `audit_set.db_models` import at the top of the file if not
already present.

### 1c — Update the workflow_status comment in `backend/audit_set/db_models.py`

Update the `workflow_status` inline comment block to list all valid values:

```python
# Valid values:
#   pending_review    → client submitted application, CB reviewing
#   in_planning       → CB approved, doing man-days/auditor assignment
#   quotation_sent    → FR.220 released to client portal
#   agreement_signed  → FR.220 + FR.221 both signed by client
#
#   --- Initial certification only ---
#   stage1_scheduled   → Stage 1 audit dates confirmed
#   stage1_in_progress → Stage 1 audit underway
#   stage1_complete    → Stage 1 done, gate to Stage 2
#   stage2_scheduled   → Stage 2 audit dates confirmed
#   stage2_in_progress → Stage 2 audit underway
#
#   --- Surveillance / Recertification only ---
#   audit_scheduled   → audit dates confirmed by both sides
#   audit_in_progress → audit underway
#
#   --- Shared closing ---
#   under_review      → auditor uploaded docs, CB technical review
#   certified         → certificate issued
```

---

## Change 2 — `frontend/src/components/ui/WorkflowStatusBar.tsx`

### 2a — Add `auditType` prop

```typescript
interface WorkflowStatusBarProps {
  auditSetId:      string
  currentStatus:   string | null
  currentUserRole: string
  auditType:       string | null   // ← ADD: "initial" | "surveillance" | "recertification" | null
  onAdvanced:      () => void
}
```

### 2b — Replace `STEPS` with a function

```typescript
const INITIAL_STEPS = [
  { key: 'pending_review',    label: 'Pending'    },
  { key: 'in_planning',       label: 'Planning'   },
  { key: 'quotation_sent',    label: 'Quotation'  },
  { key: 'agreement_signed',  label: 'Agreement'  },
  { key: 'stage1_scheduled',  label: 'Stage 1'    },
  { key: 'stage1_in_progress',label: 'S1 Audit'   },
  { key: 'stage1_complete',   label: 'S1 Done'    },
  { key: 'stage2_scheduled',  label: 'Stage 2'    },
  { key: 'stage2_in_progress',label: 'S2 Audit'   },
  { key: 'under_review',      label: 'Review'     },
  { key: 'certified',         label: 'Certified'  },
]

const STANDARD_STEPS = [
  { key: 'pending_review',    label: 'Pending'    },
  { key: 'in_planning',       label: 'Planning'   },
  { key: 'quotation_sent',    label: 'Quotation'  },
  { key: 'agreement_signed',  label: 'Agreement'  },
  { key: 'audit_scheduled',   label: 'Scheduled'  },
  { key: 'audit_in_progress', label: 'In Progress'},
  { key: 'under_review',      label: 'Review'     },
  { key: 'certified',         label: 'Certified'  },
]

function getSteps(auditType: string | null) {
  return auditType === 'initial' ? INITIAL_STEPS : STANDARD_STEPS
}
```

### 2c — Replace `PANELS` with two records and a getter

```typescript
const INITIAL_PANELS: Record<string, ActionPanel> = {
  in_planning: {
    heading: 'Ready to send quotation?',
    body: "Download and generate the FR.220 quotation, then release it to the client using the Shared Documents section below. Once you release a Quotation document, the status advances automatically.",
  },
  quotation_sent: {
    heading: 'Waiting for client signature',
    body: 'The quotation has been sent. The client needs to sign it via their portal. Status will advance automatically when they sign.',
  },
  agreement_signed: {
    heading: 'Agreement confirmed — ready for Stage 1',
    body: 'The client has signed the agreement. Schedule the Stage 1 (document review) audit dates to proceed.',
    cta: { label: 'Schedule Stage 1', nextStatus: 'stage1_scheduled' },
  },
  stage1_scheduled: {
    heading: 'Stage 1 scheduled',
    body: 'Stage 1 dates are confirmed. Mark as in progress when the Stage 1 audit begins.',
    cta: { label: 'Mark Stage 1 In Progress', nextStatus: 'stage1_in_progress' },
  },
  stage1_in_progress: {
    heading: 'Stage 1 audit in progress',
    body: 'Stage 1 is underway. Once the Stage 1 readiness assessment is complete and the client is cleared for Stage 2, mark it as done.',
    cta: { label: 'Mark Stage 1 Complete', nextStatus: 'stage1_complete' },
  },
  stage1_complete: {
    heading: 'Stage 1 complete ✓',
    body: 'Stage 1 is done. Schedule the Stage 2 (on-site) audit when dates are agreed.',
    cta: { label: 'Schedule Stage 2', nextStatus: 'stage2_scheduled' },
  },
  stage2_scheduled: {
    heading: 'Stage 2 scheduled',
    body: 'Stage 2 dates are confirmed. Mark as in progress when the on-site audit begins.',
    cta: { label: 'Mark Stage 2 In Progress', nextStatus: 'stage2_in_progress' },
  },
  stage2_in_progress: {
    heading: 'Stage 2 audit in progress',
    body: 'Stage 2 is underway. Status will advance to Under Review when the auditor uploads their completed documents.',
  },
  under_review: {
    heading: 'Under review',
    body: 'Audit documents are uploaded. The certification committee can now review and issue the certificate.',
    cta: { label: 'Issue Certificate', nextStatus: 'certified', allowedRoles: ['admin', 'executive'] },
  },
  certified: {
    heading: 'Certified ✓',
    body: 'The certification has been issued.',
  },
}

const STANDARD_PANELS: Record<string, ActionPanel> = {
  in_planning: {
    heading: 'Ready to send quotation?',
    body: "Download and generate the FR.220 quotation, then release it to the client using the Shared Documents section below. Once you release a Quotation document, the status advances automatically.",
  },
  quotation_sent: {
    heading: 'Waiting for client signature',
    body: 'The quotation has been sent. The client needs to sign it via their portal. Status will advance automatically when they sign.',
  },
  agreement_signed: {
    heading: 'Agreement confirmed',
    body: 'The client has signed the agreement. Once audit dates are confirmed, mark the audit as scheduled.',
    cta: { label: 'Mark as Audit Scheduled', nextStatus: 'audit_scheduled' },
  },
  audit_scheduled: {
    heading: 'Audit is scheduled',
    body: 'Audit dates are confirmed. Mark as in progress when the audit begins.',
    cta: { label: 'Mark as In Progress', nextStatus: 'audit_in_progress' },
  },
  audit_in_progress: {
    heading: 'Audit in progress',
    body: 'The audit is underway. Status will advance automatically when the auditor uploads their completed documents.',
  },
  under_review: {
    heading: 'Under review',
    body: 'Audit documents are uploaded. The certification committee can now review and issue the certificate.',
    cta: { label: 'Issue Certificate', nextStatus: 'certified', allowedRoles: ['admin', 'executive'] },
  },
  certified: {
    heading: 'Certified ✓',
    body: 'The certification has been issued.',
  },
}

function getPanels(auditType: string | null) {
  return auditType === 'initial' ? INITIAL_PANELS : STANDARD_PANELS
}
```

### 2d — Update the component body to use the new getters

```typescript
export function WorkflowStatusBar({ auditSetId, currentStatus, currentUserRole, auditType, onAdvanced }: WorkflowStatusBarProps) {
  // ...existing state and mutation...

  const STEPS    = getSteps(auditType)
  const PANELS   = getPanels(auditType)

  if (!currentStatus || currentStatus === 'pending_review') return null

  const currentIdx = STEPS.findIndex((s) => s.key === currentStatus)
  const panel      = PANELS[currentStatus]
  // ...rest of render unchanged...
}
```

---

## Change 3 — `frontend/src/app/(app)/clients/[id]/page.tsx`

Pass `auditType` to `WorkflowStatusBar`. The audit set data is already fetched on this
page as part of the `AuditSetResponse`. Find where `<WorkflowStatusBar>` is rendered
and add the `auditType` prop:

```tsx
// Find this in the page (existing):
<WorkflowStatusBar
  auditSetId={auditSet.id}
  currentStatus={auditSet.workflow_status}
  currentUserRole={currentUser.role}
  onAdvanced={refetch}
/>

// Change to:
<WorkflowStatusBar
  auditSetId={auditSet.id}
  currentStatus={auditSet.workflow_status}
  currentUserRole={currentUser.role}
  auditType={auditSet.audit_type ?? null}
  onAdvanced={refetch}
/>
```

---

## Change 4 — Update status-gate allowlists in section components

Every component that gates visibility on a set of workflow statuses must include the
new Stage 1/2 statuses so those sections remain visible during initial certification audits.

The general rule: wherever `audit_scheduled` or `audit_in_progress` appears in an
allowlist, also add `stage1_scheduled`, `stage1_in_progress`, `stage1_complete`,
`stage2_scheduled`, `stage2_in_progress`.

Apply the following specific changes:

### `frontend/src/components/ui/CommitteeSection.tsx`

```typescript
// BEFORE:
const COMMITTEE_STAGES = ['agreement_signed', 'audit_scheduled', 'audit_in_progress', 'under_review', 'certified']

// AFTER:
const COMMITTEE_STAGES = [
  'agreement_signed',
  'stage1_scheduled', 'stage1_in_progress', 'stage1_complete',
  'stage2_scheduled', 'stage2_in_progress',
  'audit_scheduled', 'audit_in_progress',
  'under_review', 'certified',
]
```

### `frontend/src/components/ui/MeetingAttendeesSection.tsx`

Same change as CommitteeSection:
```typescript
// BEFORE:
const MEETING_STAGES = ['agreement_signed', 'audit_scheduled', 'audit_in_progress', 'under_review', 'certified']

// AFTER:
const MEETING_STAGES = [
  'agreement_signed',
  'stage1_scheduled', 'stage1_in_progress', 'stage1_complete',
  'stage2_scheduled', 'stage2_in_progress',
  'audit_scheduled', 'audit_in_progress',
  'under_review', 'certified',
]
```

### `frontend/src/components/ui/InternalApprovalsSection.tsx`

```typescript
// BEFORE:
const FR222_STAGES = ['audit_scheduled', 'audit_in_progress', 'under_review', 'certified']

// AFTER:
const FR222_STAGES = [
  'stage1_scheduled', 'stage1_in_progress', 'stage1_complete',
  'stage2_scheduled', 'stage2_in_progress',
  'audit_scheduled', 'audit_in_progress',
  'under_review', 'certified',
]
```

### All other section components

Search the codebase for any component that contains a status allowlist array referencing
`'audit_scheduled'` or `'audit_in_progress'` — for example `AuditReportSection`,
`NCFormManagementSection`, `AssessmentManagementSection`, `DeclarationManagementSection`.
For each one found, add the same five new statuses to its allowlist using the same
pattern above.

---

## Verification Checklist

- [ ] Create an **initial certification** audit set → advance from `agreement_signed` → `stage1_scheduled` — works ✅
- [ ] Advance `stage1_scheduled` → `stage1_in_progress` → `stage1_complete` — works; the Stage 1 `AuditSetStage` row has `status="complete"` ✅
- [ ] Advance `stage1_complete` → `stage2_scheduled` → `stage2_in_progress` → `under_review` → `certified` — works ✅
- [ ] Initial certification: `WorkflowStatusBar` shows 11-step strip with Stage 1 / Stage 2 labels ✅
- [ ] Create a **surveillance** audit set → advance from `agreement_signed` → `audit_scheduled` (old path) — still works ✅
- [ ] Surveillance: `WorkflowStatusBar` shows 8-step strip (unchanged) ✅
- [ ] At `stage1_scheduled`: CommitteeSection, MeetingAttendeesSection, FR222 are visible ✅
- [ ] Attempting invalid transition (e.g. `stage1_in_progress → stage2_scheduled`, skipping `stage1_complete`) → 400 error ✅
- [ ] Attempting initial-certification-only transition on a surveillance set still fails (the transition isn't invalid per se, but the planner should use `audit_scheduled` — no enforcement needed at this point) ✅
