# Portal 83 — Surveillance: add FR.234 to SharedDocumentsSection release dropdown

## Root cause

`SharedDocumentsSection.tsx` contains a hardcoded `DOC_TYPES` array:

```typescript
const DOC_TYPES = [
  { value: 'quotation',       label: 'Quotation (FR.220)' },
  { value: 'agreement',       label: 'Agreement (FR.221)' },
  { value: 'fr218_review',    label: 'Application Review (FR.218)' },
  { value: 'audit_programme', label: 'Audit Programme (FR.222)' },
  { value: 'team_info',       label: 'Audit Team Info (FR.224)' },
  { value: 'certificate',     label: 'Certificate' },
]
```

`surveillance_notification` is not in this list.
Result: the planner cannot select FR.234 in the "Release Document" form → can't release it → it never appears in the document list → the client can never see or sign it → the surveillance pipeline is blocked at `in_planning`.

Additionally, the component currently receives no `auditType` prop, so it shows every type regardless of audit type — quotation, agreement, FR.218, FR.222 all appear for surveillance audits (confusing; those documents have no meaning in surveillance).

## Status advance on release (not on signing)

Portal 82 auto-advances the workflow from `in_planning → notification_sent` when the CB **releases** FR.234 (inside `documents_router.release_document`). This is the correct design — no changes are needed in `viewer_router.py`. The client can sign the notification for record-keeping purposes (org_rep slot), but signing does NOT drive the pipeline; the release does.

## Change 1 — `frontend/src/components/ui/SharedDocumentsSection.tsx`

### 1a. Add `auditType` prop

```typescript
export function SharedDocumentsSection({
  auditSetId,
  stages = [],
  auditType = null,          // ← add
}: {
  auditSetId: string
  stages?: StageResponse[]
  auditType?: string | null  // ← add
}) {
```

### 1b. Replace the static `DOC_TYPES` with a computed, audit-type-aware list

Remove the top-level `const DOC_TYPES = [...]` declaration and replace with a helper computed inside the component (after the prop destructuring):

```typescript
// Document types available in the release form, filtered by audit type.
const DOC_TYPES = (() => {
  const isSurveillance = (auditType ?? '').startsWith('surveillance')
  if (isSurveillance) {
    return [
      { value: 'surveillance_notification', label: 'Surveillance Notification (FR.234)' },
      { value: 'team_info',                 label: 'Audit Team Info (FR.224)' },
      { value: 'certificate',               label: 'Certificate' },
    ]
  }
  // Initial certification / recertification / unset
  return [
    { value: 'quotation',       label: 'Quotation (FR.220)' },
    { value: 'agreement',       label: 'Agreement (FR.221)' },
    { value: 'fr218_review',    label: 'Application Review (FR.218)' },
    { value: 'audit_programme', label: 'Audit Programme (FR.222)' },
    { value: 'team_info',       label: 'Audit Team Info (FR.224)' },
    { value: 'certificate',     label: 'Certificate' },
  ]
})()
```

### 1c. Reset `docType` default to the first entry in the computed list

The `useState` initialiser for `docType` is currently `'quotation'`. For surveillance this would be an invalid default. Change it to derive from the list:

```typescript
const [docType, setDocType] = useState(() => {
  const isSurveillance = (auditType ?? '').startsWith('surveillance')
  return isSurveillance ? 'surveillance_notification' : 'quotation'
})
```

### 1d. `STAGE_SCOPED_TYPES` — no change needed

`STAGE_SCOPED_TYPES = new Set(['team_info'])` is already correct. FR.224 (team_info) needs a stage selector; FR.234 (surveillance_notification) does not.

---

## Change 2 — `frontend/src/app/(app)/clients/[id]/page.tsx`

Pass `auditType` to `SharedDocumentsSection`:

```tsx
<SharedDocumentsSection
  auditSetId={id}
  stages={data.stages ?? []}
  auditType={data.audit_type ?? null}   {/* ← add */}
/>
```

---

## Backend verification (no code changes, but confirm these are in place from Portal 82)

Before shipping, confirm the following Portal 82 changes are present — if any are missing, add them now:

### `backend/audit_set/documents_router.py`

1. `ALLOWED_DOC_TYPES` includes `"surveillance_notification"`
2. `CLIENT_VISIBLE_TYPES` includes `"surveillance_notification"`
3. `DOC_SIG_SLOTS` has `"surveillance_notification": ["org_rep"]` — seeds one signature slot so the client can sign the notification for record-keeping (optional, does not gate workflow advance)
4. Inside `release_document`, after the document is committed and signature slots are seeded:
   ```python
   if document_type == "surveillance_notification":
       _auto_advance_workflow(
           db, auth_db, audit_set,
           expected_from="in_planning",
           to_status="notification_sent",
           triggered_by=current_user.id,
           notes="Surveillance Notification (FR.234) released to client",
       )
   ```
5. `"notification_sent"` is in `STATUS_ORDER` (between `"in_planning"` and `"quotation_sent"`)
6. The `fr218_complete` gate for `team_info` is bypassed for surveillance audit types

### `backend/audit_set/workflow_router.py`

1. `VALID_TRANSITIONS` has `("in_planning", "notification_sent")` and `("notification_sent", "audit_scheduled")`
2. `"notification_sent"` is in `VALID_JUMP_STATUSES`

---

## Result after this fix

1. Planner opens the client audit set page (surveillance type)
2. Shared Documents → Release Document → Type dropdown shows "Surveillance Notification (FR.234)" as the first option
3. Planner uploads the filled FR.234 DOCX, clicks "Release to Client"
4. Backend stores the document; auto-advances `workflow_status` from `in_planning → notification_sent`
5. Client opens their portal → sees the notification in Shared Documents → can open in viewer and sign (org_rep slot) for acknowledgment
6. WorkflowStatusBar updates to show "Notified" step as current
7. Planner clicks "Mark as Audit Scheduled" (CTA in `notification_sent` panel) → proceeds

---

## What is NOT changing

- The existing `DOC_TYPES` for initial/recertification audit types — unchanged
- `STAGE_SCOPED_TYPES` — unchanged (`team_info` still requires stage selection)
- `viewer_router.py` — no changes; org_rep signing saves the placement but does not drive workflow status (advance already happened at release time)
- All existing signing logic for FR.223, FR.224, FR.225, FR.230, FR.232, FR.233 — unchanged

## Commit message suggestion

```
Portal 83: add surveillance_notification to SharedDocumentsSection release dropdown

- SharedDocumentsSection: accept auditType prop; compute DOC_TYPES conditionally —
  surveillance shows FR.234/FR.224/Certificate, initial shows existing 6 types
- page.tsx: pass auditType to SharedDocumentsSection
- (backend) confirm Portal 82 surveillance_notification entries in ALLOWED_DOC_TYPES,
  CLIENT_VISIBLE_TYPES, DOC_SIG_SLOTS, release_document auto-advance, STATUS_ORDER
```
