# AUGMENT PROMPT — Portal 09: Workflow Status Actions

## Context

Certiva is a certification body management platform (FastAPI backend + Next.js 14 App Router frontend).
The codebase is at the root of this repo. The live URL is compassionate-miracle-production.up.railway.app.

We just shipped an 8-prompt client portal build (Prompts 01–08). Everything works.

**CRITICAL: DO NOT BREAK THE EXISTING PORTAL. Every change is additive.**

---

## What exists today

The workflow state machine lives in `backend/audit_set/workflow_router.py`:

```
pending_review → in_planning → quotation_sent → agreement_signed
→ audit_scheduled → audit_in_progress → under_review → certified
```

`VALID_TRANSITIONS` already enforces role-gated transitions.
`PATCH /audit-sets/{id}/workflow-status` already exists and works.

The CB client detail page is `frontend/src/app/(app)/clients/[id]/page.tsx`.
It currently shows:
- Approval banner (only when `pending_review`)
- PlanOverview, CertSection
- Audit stages (StageCard components)
- ManDaySection
- Client Messages (MessageThread)
- SharedDocumentsSection (Release Document + document list)

The client overview page is `frontend/src/app/(client)/client/overview/page.tsx`.
It shows the 8-step timeline. All steps past the current one are muted/grey.

Documents router: `backend/audit_set/documents_router.py`
- `release_document()` — CB releases a file to the client
- `verify_sign_otp()` — client signs a document via OTP

---

## What to build

### 1. Backend — Auto-advance workflow on document events

In `backend/audit_set/documents_router.py`, make two document actions automatically advance the workflow status:

**A) On `release_document()` — when document_type == "quotation":**
- After committing the document row, check `audit_set.workflow_status`
- If it is `"in_planning"`, advance it to `"quotation_sent"`
- Log an `AuditSetStatusEvent(from_status="in_planning", to_status="quotation_sent", triggered_by=current_user.id, notes="Quotation document released")`
- Also notify the client via `send_client_status_update()` (swallow email errors)
- Import `AuditSetStatusEvent` from `audit_set.db_models` (already imported elsewhere in the router)

**B) On `verify_sign_otp()` — when a document is successfully signed:**
- After committing the signed doc, check `audit_set.workflow_status`
- If it is `"quotation_sent"`, advance it to `"agreement_signed"`
- Log an `AuditSetStatusEvent(from_status="quotation_sent", to_status="agreement_signed", triggered_by=current_user.id, notes="Agreement signed by client")`
- Notify client via `send_client_status_update()` (swallow email errors)

**C) On `upload_audit_document()` — when auditor uploads:**
- After committing the upload, check `audit_set.workflow_status`
- If it is `"audit_in_progress"`, advance it to `"under_review"`
- Log the event (triggered_by=current_user.id, notes="Auditor uploaded completed documents")
- Notify client via `send_client_status_update()` (swallow email errors)

For all three: `audit_set` needs to be loaded from `db` using `audit_set_id`. The `send_client_status_update` function is in `email_service.py`. Swallow all email errors with try/except.

---

### 2. Frontend CB — WorkflowStatusBar component

Create a new component `frontend/src/components/ui/WorkflowStatusBar.tsx`.

**Props:**
```typescript
interface WorkflowStatusBarProps {
  auditSetId: string
  currentStatus: string | null
  currentUserRole: string
  onAdvanced: () => void   // call this after a successful status advance to refetch
}
```

**Design:** A horizontal strip with the 8 steps shown as small numbered circles connected by a line. Completed steps: filled green (#1A4731). Current step: filled green with a pulse ring. Future steps: grey outline. Below the strip, show a status-specific **action panel** (white card) with copy and a CTA button.

**Status-specific action panels:**

| Current status | Heading | Body copy | Button label | What button does |
|---|---|---|---|---|
| `in_planning` | "Ready to send quotation?" | "Download and generate the FR.220 quotation, then release it to the client using the Shared Documents section below. Once you release a document with type 'Quotation', the status advances automatically." | (no button — action is in SharedDocumentsSection) | — |
| `quotation_sent` | "Waiting for client signature" | "The quotation has been sent. The client needs to sign it via their portal. Status will advance automatically when they sign." | (no button) | — |
| `agreement_signed` | "Agreement confirmed" | "The client has signed the agreement. Once audit dates are confirmed with the client, mark the audit as scheduled." | "Mark as Audit Scheduled" | PATCH `/audit-sets/{id}/workflow-status` body `{workflow_status: "audit_scheduled"}` |
| `audit_scheduled` | "Audit is scheduled" | "Audit dates are confirmed. When the audit begins, mark it as in progress." | "Mark as In Progress" | PATCH to `audit_in_progress` |
| `audit_in_progress` | "Audit in progress" | "The audit is underway. Status will advance automatically when the auditor uploads their completed documents." | (no button) | — |
| `under_review` | "Under review" | "Audit documents are uploaded. The certification committee can now review and issue the certificate." | "Issue Certificate" (only for roles: admin, executive) | PATCH to `certified` |
| `certified` | "Certified ✓" | "The certification has been issued." | (no button) | — |

For statuses `null` or `pending_review`: render nothing (the approval banner already handles pending_review).

**PATCH call:** Use the existing `api.patch()` wrapper. On success call `onAdvanced()`. On error show an inline red error message below the button (do not use alert()).

---

### 3. Wire WorkflowStatusBar into `/clients/[id]`

In `frontend/src/app/(app)/clients/[id]/page.tsx`:

1. Import `WorkflowStatusBar` from `@/components/ui/WorkflowStatusBar`
2. Get the current user role from `useAuth()` (it's already available in this file — check how it's used for the approveApplication mutation)
3. Add the component **between the approval banner and `<PlanOverview>`**:

```tsx
{data.workflow_status && data.workflow_status !== 'pending_review' && (
  <WorkflowStatusBar
    auditSetId={id}
    currentStatus={data.workflow_status}
    currentUserRole={currentUser.role}
    onAdvanced={invalidate}
  />
)}
```

Everything else on the page stays exactly as-is.

---

### 4. Frontend Client — Action CTAs on `/client/overview`

In `frontend/src/app/(client)/client/overview/page.tsx`, add status-specific action banners **below the timeline card** and **above the key-info grid**.

Only show a banner when the current status requires client action:

| Status | Banner | CTA |
|---|---|---|
| `quotation_sent` | "Your quotation is ready to sign." | `<Link href="/client/documents">Review & Sign Documents →</Link>` |
| `agreement_signed` | "Your agreement is confirmed. We'll notify you when your audit is scheduled." | (no button, info only) |
| `audit_scheduled` | "Your audit is scheduled. Please prepare your documentation." | (info only) |
| `certified` | "Your certificate has been issued. Download it from Documents." | `<Link href="/client/documents">View Certificate →</Link>` |

Style: green-tinted card (`bg-green-50 border border-green-200 rounded-xl p-4`) for positive states, amber-tinted for action-required states (`quotation_sent`).

---

## Verification checklist

After implementation:
1. Python compile check on modified backend files
2. TypeScript check: `cd frontend && npx tsc --noEmit`
3. Confirm `release_document` with type="quotation" updates `workflow_status` on `audit_sets` table
4. Confirm `verify_sign_otp` updates `workflow_status` on sign
5. Confirm WorkflowStatusBar renders on `/clients/[id]` only when `workflow_status` is not null/pending_review
6. Confirm "Mark as Audit Scheduled" button calls PATCH and `onAdvanced` triggers re-fetch
7. Confirm client banner appears for `quotation_sent` and links to `/client/documents`
8. Commit and push to main

## Constraint reminder
DO NOT remove, reorganize, or rename any existing component, route, or API endpoint.
All additions are purely additive. The `SharedDocumentsSection` and `MessageThread` stay where they are.
