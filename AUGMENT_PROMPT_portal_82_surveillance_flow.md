# Portal 82 — Surveillance Pipeline: Skip Quotation/Agreement/FR.218/FR.222, Start from FR.234

## Context

Surveillance audits currently ride the `STANDARD_STEPS` pipeline:
`in_planning → quotation_sent → agreement_signed → audit_scheduled → audit_in_progress → under_review → certified`

This is wrong. Surveillance does NOT need a new quotation (FR.220), a new agreement (FR.221), an application review (FR.218), or an audit programme (FR.222). Those belong to initial certification only.

The correct surveillance flow starts with the **Surveillance Notification Form (FR.234)**, then proceeds directly through the audit and committee review.

**Target surveillance pipeline:**
```
pending_review → in_planning → notification_sent → audit_scheduled → audit_in_progress → under_review → certified
```

The document resolver (`_build_surveillance`) is already correct — it produces:
FR.234, FR.223, FR.224, FR.225, FR.230, FR.232/FR.232-1/FR.229, FR.211, FR.233.
Do NOT touch `resolver.py`.

The signing flow for the documents that ARE in surveillance (FR.223, FR.224, FR.225, FR.230, FR.232, FR.211, FR.233) must not change at all.

---

## Change 1 — `backend/audit_set/workflow_router.py`

### 1a. Add surveillance transitions to VALID_TRANSITIONS

After the existing `("in_planning", "quotation_sent")` line, add:

```python
# ── Surveillance: notification replaces quotation + agreement ─────────────
("in_planning",          "notification_sent"):  {"admin", "planner"},
("notification_sent",    "audit_scheduled"):    {"admin", "planner"},
```

The existing transitions `quotation_sent → agreement_signed → audit_scheduled` remain unchanged (initial/recertification still uses them).

### 1b. Add `notification_sent` to VALID_JUMP_STATUSES

```python
VALID_JUMP_STATUSES = {
    "in_planning",
    "notification_sent",       # ← add
    "quotation_sent",
    "agreement_signed",
    ...
}
```

### 1c. Add `notification_sent` option to the jump-panel `<select>` in WorkflowStatusBar (frontend, handled in Change 4 below)

---

## Change 2 — `backend/audit_set/documents_router.py`

### 2a. Add `surveillance_notification` to ALLOWED_DOC_TYPES

```python
ALLOWED_DOC_TYPES = {
    ...
    "surveillance_notification",   # FR.234 — Surveillance Notification Form
}
```

### 2b. Add `surveillance_notification` to CLIENT_VISIBLE_TYPES

```python
CLIENT_VISIBLE_TYPES = {
    "quotation", "agreement", "audit_plan", "meeting_form",
    "nc_form", "assessment", "auditor_assessment", "certificate",
    "surveillance_notification",   # ← add
}
```

### 2c. Add `notification_sent` to STATUS_ORDER

Insert it after `"in_planning"` and before `"quotation_sent"`:

```python
STATUS_ORDER = [
    "pending_review",
    "in_planning",
    "notification_sent",    # ← add
    "quotation_sent",
    "agreement_signed",
    ...
]
```

### 2d. Auto-advance to `notification_sent` when FR.234 is released

In the `release_document` endpoint, after the `db.commit()` / `db.refresh(doc)` block (after sig_ids are built and the document is committed), add:

```python
# Surveillance path: releasing FR.234 notification auto-advances to notification_sent.
if document_type == "surveillance_notification":
    _auto_advance_workflow(
        db, auth_db, audit_set,
        expected_from="in_planning",
        to_status="notification_sent",
        triggered_by=current_user.id,
        notes="Surveillance Notification (FR.234) released to client",
    )
```

This uses the existing `_auto_advance_workflow` helper. It is idempotent — if the set is already past `in_planning` it is a no-op.

### 2e. Bypass the `fr218_complete` gate for surveillance when uploading `team_info`

Current gate (around line 291-297):
```python
if document_type in ("audit_programme", "team_info"):
    if not _status_at_least(audit_set.workflow_status, "fr218_complete"):
        raise HTTPException(409,
            f"Cannot upload {document_type} before the application review "
            f"(FR.218) is complete (current: {audit_set.workflow_status})")
```

Replace with:

```python
is_surveillance = (audit_set.audit_type or "").lower().startswith("surveillance")
if document_type in ("audit_programme", "team_info") and not is_surveillance:
    if not _status_at_least(audit_set.workflow_status, "fr218_complete"):
        raise HTTPException(409,
            f"Cannot upload {document_type} before the application review "
            f"(FR.218) is complete (current: {audit_set.workflow_status})")
```

Rationale: surveillance never reaches `fr218_complete` (FR.218 is not part of its flow), but the planner must still upload FR.224 (`team_info`) during `notification_sent`. The gate would permanently block them. `audit_programme` (FR.222) is also not in the surveillance resolver, so no surveillance set should ever try to upload it — but the bypass is harmless.

---

## Change 3 — `backend/audit_set/pipeline_triggers.py`

### 3a. Seed declarations and assessments for surveillance stages

Currently `_trigger_stage_start` only seeds for `stage_1` and `stage_2`. Surveillance has a stage with `stage_type="surveillance"` but its team is never seeded for `AuditSetImpartialityDeclaration` / `AuditSetAuditorAssessment`.

In `fire_phase_triggers`, after the existing `stage2_scheduled/stage2_in_progress` branch, add:

```python
elif new_status in ("audit_scheduled", "audit_in_progress"):
    # Surveillance / recertification single-stage path.
    # Seed FR.224 declarations + FR.211 assessments for the surveillance stage.
    _seed_stage_declarations_and_assessments(audit_set, "surveillance", db)
```

`_seed_stage_declarations_and_assessments` is already idempotent (deduplicates by member name + stage_type), so double-firing on both statuses is safe.

---

## Change 4 — `frontend/src/components/ui/WorkflowStatusBar.tsx`

### 4a. Add SURVEILLANCE_STEPS

```typescript
const SURVEILLANCE_STEPS = [
  { key: 'pending_review',    label: 'Pending'    },
  { key: 'in_planning',       label: 'Planning'   },
  { key: 'notification_sent', label: 'Notified'   },
  { key: 'audit_scheduled',   label: 'Scheduled'  },
  { key: 'audit_in_progress', label: 'In Progress'},
  { key: 'under_review',      label: 'Review'     },
  { key: 'certified',         label: 'Continued'  },
]
```

### 4b. Add SURVEILLANCE_PANELS

```typescript
const SURVEILLANCE_PANELS: Record<string, ActionPanel> = {
  in_planning: {
    heading: 'Prepare surveillance notification',
    body: 'Download and generate FR.234 (Surveillance Notification Form), fill in audit dates and team, then release it to the client using the Shared Documents section below. Status advances automatically when you release it.',
  },
  notification_sent: {
    heading: 'Client notified — confirm audit dates',
    body: 'FR.234 has been released to the client. Upload FR.224 (Team Information) and FR.223 (Audit Plan) for the surveillance stage. Once dates are confirmed, mark the audit as scheduled.',
    cta: { label: 'Mark as Audit Scheduled', nextStatus: 'audit_scheduled', allowedRoles: ['admin', 'planner'] },
  },
  audit_scheduled: {
    heading: 'Surveillance audit is scheduled',
    body: 'Audit dates are confirmed. Mark as in progress when the surveillance audit begins.',
    cta: { label: 'Mark as In Progress', nextStatus: 'audit_in_progress' },
  },
  audit_in_progress: {
    heading: 'Surveillance audit in progress',
    body: 'The audit is underway. The auditor uploads FR.232 (Audit Report), FR.225, and FR.230 via their portal. Status advances to Under Review automatically when documents are uploaded.',
  },
  under_review: {
    heading: 'Under review — committee decision',
    body: 'Audit documents are complete. Generate FR.233 (Review & Decision Form) in the panel below so the committee can sign. Once the decision is issued, mark certification as continued.',
    cta: { label: 'Issue Continuation Certificate', nextStatus: 'certified', allowedRoles: ['admin', 'executive'] },
  },
  certified: {
    heading: 'Surveillance completed ✓',
    body: 'Surveillance audit is closed. The continuation certificate has been issued.',
  },
}
```

### 4c. Update `getSteps` and `getPanels`

```typescript
function isSurveillanceAudit(auditType: string | null): boolean {
  return auditType != null && auditType.startsWith('surveillance')
}

function getSteps(auditType: string | null) {
  if (auditType === 'initial') return INITIAL_STEPS
  if (isSurveillanceAudit(auditType)) return SURVEILLANCE_STEPS
  return STANDARD_STEPS
}

function getPanels(auditType: string | null) {
  if (auditType === 'initial') return INITIAL_PANELS
  if (isSurveillanceAudit(auditType)) return SURVEILLANCE_PANELS
  return STANDARD_PANELS
}
```

### 4d. Fix step-alias logic for surveillance

The current alias code:
```typescript
const stepKey = (auditType === 'initial' && currentStatus && INITIAL_STEP_ALIAS[currentStatus]) || currentStatus
```

This is fine — surveillance has no aliases needed. The alias lookup only applies when `auditType === 'initial'`, which is already scoped correctly.

### 4e. Add `notification_sent` to jump panel `<select>`

In the jump panel (workflow not started yet), add:
```tsx
<option value="notification_sent">Notification Sent</option>
```
Place it between `in_planning` and `quotation_sent`.

---

## Change 5 — `frontend/src/components/ui/InternalApprovalsSection.tsx`

The Internal Approvals section shows FR.222 (Audit Programme) signature slots. FR.222 is not part of the surveillance flow. If shown for surveillance, it confusingly says "Upload the Audit Programme DOCX via Shared Documents to initiate signing."

### 5a. Add `auditType` prop and hide for surveillance

```typescript
export function InternalApprovalsSection({
  auditSetId,
  workflowStatus,
  auditType,          // ← add
}: {
  auditSetId: string
  workflowStatus: string | null
  auditType?: string | null   // ← add
}) {
  // ... existing state ...

  // Surveillance audits do not use FR.222 — hide section entirely.
  if (auditType && auditType.startsWith('surveillance')) return null

  // ... rest of existing logic unchanged ...
}
```

---

## Change 6 — `frontend/src/app/(app)/clients/[id]/page.tsx`

### 6a. Pass `auditType` to `InternalApprovalsSection`

```tsx
<InternalApprovalsSection
  auditSetId={id}
  workflowStatus={data.workflow_status ?? null}
  auditType={data.audit_type ?? null}   {/* ← add */}
/>
```

### 6b. Hide `FR218ReviewerPicker` for surveillance

Wrap the existing `FR218ReviewerPicker` block:

```tsx
{needsFr218Reviewer((data.standards ?? []) as string[]) &&
 !(data.audit_type ?? '').startsWith('surveillance') && (
  <div className="mt-4 rounded-xl border bg-white p-4">
    <h3 ...>Application Reviewer (FR.218) — Required for FSMS / ISMS</h3>
    ...
    <FR218ReviewerPicker ... />
  </div>
)}
```

---

## What is NOT changing

- `resolver.py` — `_build_surveillance` is already correct; no change.
- `_assert_stage_entry_gate` — only fires for `stage_1`, which surveillance never reaches.
- `_assert_stage1_complete_gate` — only fires for `stage2_in_progress`, not used by surveillance.
- `committee_router.py` — FR.233 generate already accepts `under_review` as a valid entry state (line 522: `"stage2_complete", "committee_review", "under_review"`). Surveillance reaches `under_review`, so FR.233 can be generated there. No change needed.
- `FR233Panel.tsx` — already shows at `under_review`. Surveillance will show it correctly. No change needed.
- `CommitteePlanningCard` — already used for all audit types with stages. Surveillance stage exists in `data.stages`, so it works. No change needed.
- Signing logic for FR.223, FR.224, FR.225, FR.230, FR.232, FR.211, FR.233 — all unchanged.
- `viewer_router.py` — auto-advance from `audit_in_progress → under_review` on auditor upload (line 674) already handles surveillance. No change needed.

---

## Commit message suggestion

```
Portal 82: surveillance pipeline — FR.234 notification replaces quotation/agreement/FR.218/FR.222

- workflow_router: add in_planning→notification_sent and notification_sent→audit_scheduled transitions
- documents_router: add surveillance_notification doc type; auto-advance to notification_sent on FR.234 release; bypass fr218_complete gate for team_info on surveillance sets; add notification_sent to STATUS_ORDER
- pipeline_triggers: seed surveillance stage declarations+assessments on audit_scheduled/audit_in_progress
- WorkflowStatusBar: SURVEILLANCE_STEPS + SURVEILLANCE_PANELS, isSurveillanceAudit() helper
- InternalApprovalsSection: accept auditType prop, hide for surveillance
- page.tsx: pass auditType to InternalApprovalsSection; hide FR218ReviewerPicker for surveillance
```
