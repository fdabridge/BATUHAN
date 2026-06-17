# Portal 55 — Reviewer Signs Stage Reports + Auditor Upload Flow

## Context: What the Smoke Test Revealed

We ran the first end-to-end smoke test of the full 14-phase initial certification pipeline. It reached Phase 8 (Stage 1 Audit) before breaking. The issues found in this batch are:

- FR.231 (Stage 1 Audit Report) has a **committee/reviewer signature field inside the document template**, but the system only seeds one slot (`lead_auditor`) — the reviewer slot is never assigned or shown
- The "Audit Plan (FR.223)" is uploaded from the **Planner side** but it should be uploaded by the **Lead Auditor** from their portal
- There is **no upload UI for FR.225 (Opening/Closing Meeting Form)** in the auditor portal
- The "Attendees" tab in the auditor portal appears to be the old OTP-based meeting attendee system, which is no longer the intended flow
- The FSMS/ISMS reviewer slot code for stage reports has a bug — it sets CB management slots instead of auditor slots

This prompt fixes all of these in one pass.

---

## Issue A — Bug in FSMS/ISMS reviewer slot for stage reports

### Root cause

`backend/audit_set/documents_router.py`, around line 304:

```python
if document_type in ("stage1_report", "stage2_report") and _needs_reviewer(audit_set):
    # BUG: this sets FR.218-style CB slots, NOT audit report slots
    slot_labels = ["cb_planner", "cb_reviewer", "cb_cert_manager"]
```

This is copy-pasted from the FR.218 logic and is completely wrong for audit reports.
`cb_planner` and `cb_cert_manager` have no business signing FR.231 or FR.232.
The equivalent fix appears at approximately line 621 as well — both occurrences must be fixed.

---

## Issue B — Appointed reviewer must sign FR.231 and FR.232

### Business rule

Every stage report (FR.231, FR.232) requires two signatures:
1. **Lead Auditor** — the person who conducted the audit
2. **Appointed Reviewer** — a committee member with `role = "reviewer"` appointed to this audit set

The reviewer is appointed via the existing `Committee` section (which already supports
`role: "reviewer" | "decision_maker"` on `AuditSetCommitteeMember`). The reviewer signs
FR.231 and FR.232 as a quality gate. They also later participate in FR.233 (the certification
committee decision). These are not two separate people — the same person appointed as
committee reviewer signs both the reports AND the FR.233.

### Current state

`DOC_SIG_SLOTS["stage1_report"] = ["lead_auditor"]` and same for stage2_report.
There is no `appointed_reviewer` slot anywhere. The committee model already has the
`role` field needed to identify the reviewer.

### Fix — `backend/audit_set/documents_router.py`

**Replace the entire FSMS/ISMS block for stage reports (both occurrences) with:**

```python
# DOC_SIG_SLOTS — update the base definitions
"stage1_report":   ["lead_auditor", "appointed_reviewer"],
"stage2_report":   ["lead_auditor", "appointed_reviewer"],
```

And remove the old FSMS/ISMS special-case block for stage reports (lines ~304-308 and ~621-623):
```python
# DELETE THESE — they were wrong:
if document_type in ("stage1_report", "stage2_report") and _needs_reviewer(audit_set):
    slot_labels = ["cb_planner", "cb_reviewer", "cb_cert_manager"]
```

The `appointed_reviewer` slot should ALWAYS exist on stage reports. If no reviewer is
appointed yet when the document is uploaded, the slot will be seeded but marked
`"not_applicable"` (logic below). Once a reviewer is appointed, it becomes active.

### Fix — `backend/audit_set/viewer_router.py`

Add handling for `"appointed_reviewer"` sig key in `_shared_slot_eligible`:

```python
if role_label == "appointed_reviewer":
    # The appointed reviewer is the committee member with role="reviewer"
    reviewer_member = (
        db.query(AuditSetCommitteeMember)
        .filter_by(audit_set_id=audit_set.id, role="reviewer")
        .first()
    )
    if not reviewer_member:
        return False
    return current_user.id == reviewer_member.user_id
```

Add handling in `_get_field_status` for `"appointed_reviewer"` key — check if a
committee member with `role="reviewer"` exists on this audit set:

```python
if role_label == "appointed_reviewer":
    reviewer_member = (
        db.query(AuditSetCommitteeMember)
        .filter_by(audit_set_id=audit_set.id, role="reviewer")
        .first()
    )
    if not reviewer_member:
        return _result("not_applicable")
    # Is it this user's turn?
    if current_user.id == reviewer_member.user_id:
        return _result("current_user")
    # Is it signed?
    if vsp and vsp.signed_at:
        return _result("signed", vsp.signature_image)
    return _result("pending")
```

Make sure `AuditSetCommitteeMember` is imported in `viewer_router.py`.

### Signing order

The `appointed_reviewer` slot is blocked until `lead_auditor` signs first.
The existing gate logic in `_get_field_status` (checking that all prior required slots
are signed before enabling `current_user`) should handle this if the slots are seeded
in order `["lead_auditor", "appointed_reviewer"]`.

---

## Issue C — FR.223 (Audit Plan) must be uploaded by Lead Auditor

### Current state

The Planner's "Release Document" dropdown in `SharedDocumentsSection.tsx` includes
`audit_plan` as an option (line 27). The Planner uploads FR.223 on behalf of the auditor.
This is incorrect — the Lead Auditor should upload FR.223 themselves.

The backend already allows this: `audit_plan` is in `AUDITOR_VISIBLE_TYPES`. The
`/audit-sets/{id}/documents/upload` endpoint accepts any document type but currently the
frontend doesn't send `document_type=audit_plan` from the auditor side.

### Fix — Auditor portal (`frontend/src/app/(auditor)/auditor/audit/[id]/page.tsx`)

Replace the generic "Upload Documents" tab content with typed uploads. The tab currently
has a plain label + file input that posts without a `document_type`. Add two specific
upload sections above the generic one:

**Section 1 — Audit Plan (FR.223):**
```tsx
{/* Audit Plan — FR.223 */}
<div className="rounded-lg border border-amber-100 bg-amber-50 p-4">
  <p className="text-sm font-semibold text-amber-900 mb-3">Audit Plan (FR.223)</p>
  <div className="space-y-2">
    <select value={auditPlanStage} onChange={e => setAuditPlanStage(e.target.value)}
      className="w-full rounded border text-sm px-2 py-1.5">
      <option value="stage_1">Stage 1</option>
      <option value="stage_2">Stage 2</option>
    </select>
    <input type="file" accept=".pdf,.docx" onChange={e => setAuditPlanFile(e.target.files?.[0] ?? null)} />
    <button onClick={handleAuditPlanUpload} disabled={!auditPlanFile || uploadingPlan}
      className="rounded-lg bg-[#1A4731] px-3 py-1.5 text-xs text-white disabled:opacity-40">
      {uploadingPlan ? 'Uploading…' : 'Upload Audit Plan'}
    </button>
  </div>
</div>
```

The upload posts to:
```
POST /audit-sets/{id}/documents/upload
  ?label=FR.223 Audit Plan — Stage 1
  &document_type=audit_plan
  &stage_type=stage_1
  &upload_date=YYYY-MM-DD
```

The backend `upload_shared_document` endpoint already accepts `stage_type` and 
`document_type` as query params — verify this is true and add them if not.

**Section 2 — Opening/Closing Meeting Form (FR.225):**
```tsx
{/* Meeting Form — FR.225 */}
<div className="rounded-lg border border-amber-100 bg-amber-50 p-4">
  <p className="text-sm font-semibold text-amber-900 mb-3">Opening / Closing Meeting Form (FR.225)</p>
  <div className="space-y-2">
    <select value={meetingStage} onChange={e => setMeetingStage(e.target.value)}
      className="w-full rounded border text-sm px-2 py-1.5">
      <option value="stage_1">Stage 1</option>
      <option value="stage_2">Stage 2</option>
    </select>
    <input type="file" accept=".pdf,.docx" onChange={e => setMeetingFile(e.target.files?.[0] ?? null)} />
    <button onClick={handleMeetingUpload} disabled={!meetingFile || uploadingMeeting}
      className="rounded-lg bg-[#1A4731] px-3 py-1.5 text-xs text-white disabled:opacity-40">
      {uploadingMeeting ? 'Uploading…' : 'Upload Meeting Form'}
    </button>
  </div>
</div>
```

Posts to:
```
POST /audit-sets/{id}/documents/upload
  ?label=FR.225 Opening/Closing Meeting — Stage 1
  &document_type=meeting_form
  &stage_type=stage_1
  &upload_date=YYYY-MM-DD
```

### Fix — Planner side (`SharedDocumentsSection.tsx`)

Remove `audit_plan` from the "Release Document" type dropdown. The Planner should no
longer upload FR.223. They can still VIEW it once the Lead Auditor uploads it (it will
appear in the shared docs list, visible to CB per `CLIENT_VISIBLE_TYPES`).

Find the `DOC_TYPE_OPTIONS` or equivalent dropdown list in `SharedDocumentsSection.tsx`
and remove:
```typescript
{ value: 'audit_plan', label: 'Audit Plan (FR.223)' },
```

---

## Issue D — Remove/repurpose the old "Attendees" tab

The "Attendees" tab in the auditor portal renders `MeetingAttendeesSection` which is
the old OTP email-invite attendee system. This is no longer the intended flow. The
org employee signing for FR.225 now comes from the client's employee roster (already
built in Portal 49a) — employees are embedded in the FR.225 template via docxtpl loop
and signed via `[SIG:ORG_OPENING_ORG_EMP_{uuid}]` keys.

**Remove the "Attendees" tab** from the auditor portal tab list and its rendered content.
The tab label array at line 967 includes `'attendees'` — remove it from there and from
the `tab === 'attendees'` render block.

The equivalent section in the Planner's client detail page (if `MeetingAttendeesSection`
is rendered there) should also be removed or made read-only.

---

## Files to change

| File | Change |
|------|--------|
| `backend/audit_set/documents_router.py` | `DOC_SIG_SLOTS`: `stage1_report` + `stage2_report` → `["lead_auditor", "appointed_reviewer"]`; delete FSMS/ISMS override block for stage reports |
| `backend/audit_set/viewer_router.py` | `_shared_slot_eligible`: add `"appointed_reviewer"` check; `_get_field_status`: add `"appointed_reviewer"` handling returning `not_applicable` if no reviewer appointed |
| `frontend/src/app/(auditor)/auditor/audit/[id]/page.tsx` | Add FR.223 and FR.225 typed upload sections in the Upload tab |
| `frontend/src/components/ui/SharedDocumentsSection.tsx` | Remove `audit_plan` from the planner's Release Document dropdown |
| `frontend/src/app/(auditor)/auditor/audit/[id]/page.tsx` | Remove "Attendees" tab |

---

## Commit message

```
Portal 55: reviewer signs stage reports + auditor upload flow

- Fix DOC_SIG_SLOTS bug: stage1/2_report FSMS block was setting CB slots
  (cb_planner/cb_reviewer/cb_cert_manager) — completely wrong for audit reports
- Add appointed_reviewer slot to stage1_report and stage2_report: committee
  member with role="reviewer" must sign after lead_auditor
- viewer_router: handle appointed_reviewer eligibility + status
  (not_applicable if no reviewer appointed, current_user if it's them)
- Auditor portal: add typed FR.223 (audit_plan) and FR.225 (meeting_form)
  upload sections by stage — planner no longer uploads FR.223
- Remove Attendees tab from auditor portal (old OTP system, replaced by
  employee-roster-based FR.225 signing)
```
