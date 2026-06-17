# Portal 63 — CM Signing Fix (FR.231/232) + FR.225 Clickable Signature Boxes

## Context

Two signing flows are broken in the smoke test:

1. **CM cannot sign FR.231 (Stage 1 Report)** even though the Lead Auditor has uploaded
   and signed it. The `APPOINTED_REVIEWER` slot is visible in the PDF but the CM sees
   no clickable button.

2. **FR.225 Opening/Closing Meeting Form shows sig marker text (`[SIG:ORG_OPENING_LEAD_AUDITOR]`
   etc.) but no clickable signature boxes**, even though the same mechanism works correctly
   in the quotation document for client employees.

---

## Fix 1 — CM Signing FR.231/FR.232: Pure Role Check, No Appointment Required

### Root cause

Portal 61 changed `APPOINTED_REVIEWER` eligibility to `certification_manager` role, but
the eligibility check also requires `audit_set.appointed_reviewer_id` to be set. The
"Appoint Reviewer" action that sets this field was never triggered in the smoke test —
so the CM sees no button.

### What to look at

Look at how **FR.218** (application/quotation form) handles CM signing. It works without
any appointment step — the CM can sign directly because eligibility is a pure role check,
not a role + pre-assigned-ID check. Apply exactly the same pattern to `APPOINTED_REVIEWER`.

### Fix in `backend/audit_set/viewer_router.py`

Find the eligibility block for `APPOINTED_REVIEWER` in `_shared_slot_eligible`
(or `_check_committee_sig` or wherever it is resolved). Replace any check involving
`audit_set.appointed_reviewer_id` with a pure role check:

```python
if sig_key == "APPOINTED_REVIEWER":
    return current_user.role in {"certification_manager", "admin"}
```

No lookup of `audit_set.appointed_reviewer_id`. No appointment action required.
If the user is the CM, they can sign. Full stop.

### Remove the "Appoint Reviewer" button from the frontend

The appointment step is now implicit. Remove any UI button, modal, or action that
triggers `POST /committee/appoint` (or equivalent) for the reviewer role. The CM
opens FR.231/FR.232 and sees a clickable button immediately.

### Also: no ordering gate change needed

The Lead Auditor's `LEAD_AUDITOR` slot and the CM's `APPOINTED_REVIEWER` slot can
be signed in any order. Do not add a gate requiring the Lead Auditor to sign first
(the Lead Auditor already uploads the document, so by the time the CM opens it,
the Lead Auditor has already signed).

---

## Fix 2 — FR.225: Render Clickable Boxes for ORG_OPENING_* / ORG_CLOSING_* Slots

### Root cause

The backend (Portal 59) correctly detects `[SIG:ORG_OPENING_LEAD_AUDITOR]` and returns
`status: "current_user"` for the Lead Auditor. But the **frontend** has a rendering
gate that checks the sig_key prefix before deciding whether to render a clickable
button or plain text. `ORG_OPENING_` and `ORG_CLOSING_` are not in this list, so
the field renders as text only.

The quotation document works because `ORG_REP` IS in the list.

### Fix in the frontend viewer component

File: wherever the document viewer renders signature overlay elements
(likely `SignatureOverlay.tsx`, `DocumentViewer.tsx`, or `PdfViewer.tsx`).

Find the logic that decides whether to render a clickable button vs. display text
for a sig field. It will look something like one of these:

```tsx
// Pattern A — whitelist of key prefixes
const CLICKABLE_PREFIXES = ['ORG_REP', 'LEAD_AUDITOR', 'ASSIGNED_AUDITOR', ...]
const isClickable = CLICKABLE_PREFIXES.some(p => field.sig_key.startsWith(p))

// Pattern B — status-driven (correct pattern)
const isClickable = field.status === 'current_user'
```

**If Pattern A:** Add `'ORG_OPENING_'` and `'ORG_CLOSING_'` and `'COMMITTEE_MEMBER_'`
to the list. But also consider switching to Pattern B entirely — the backend already
does the eligibility check and returns the correct status; the frontend should trust it.

**If Pattern B is already used but boxes still don't appear:** The bug is backend-side —
the backend is not returning `status: "current_user"` for these keys. In that case,
add a Railway log check: open the document as the Lead Auditor and look for
`[ORG_TEAM]` log lines in the friendly-fulfillment deployment logs. The Portal 59
diagnostic logging will show exactly why eligibility is returning False
(missing `auditor_id`, NULL `lead_auditor_id`, etc.).

### Preferred fix: status-driven rendering

Refactor the frontend so that **any** field with `status === "current_user"` renders
a clickable button, regardless of the sig_key. The backend is the authority on
eligibility — the frontend should not second-guess it with a prefix whitelist.

```tsx
// Clean pattern — no whitelist needed
if (field.status === 'current_user') {
  return <SignButton onClick={() => openSignModal(field)} />
} else if (field.status === 'signed') {
  return <SignedStamp image={field.signature_image} />
} else {
  return <PendingLabel label={field.label} />
}
```

This also makes `COMMITTEE_MEMBER_*` and any future dynamic sig keys work
automatically without needing frontend changes.

---

## Files to change

| File | Change |
|------|--------|
| `backend/audit_set/viewer_router.py` | `APPOINTED_REVIEWER` eligibility → pure `role == certification_manager` check, remove `appointed_reviewer_id` lookup |
| `frontend/.../appoint-reviewer UI` | Remove the Appoint Reviewer button/action entirely |
| `frontend/.../SignatureOverlay.tsx` (or equivalent) | Switch from prefix whitelist to `status === "current_user"` for button rendering; add `ORG_OPENING_`, `ORG_CLOSING_`, `COMMITTEE_MEMBER_` if still using whitelist |

---

## Commit message

```
Portal 63: CM signing fix + FR.225 clickable boxes

Fix 1 — APPOINTED_REVIEWER eligibility: pure role check (certification_manager),
  no appointed_reviewer_id gate required. CM opens FR.231/FR.232 and signs
  immediately, same as how CM signing works on FR.218. Remove Appoint Reviewer
  button from frontend.

Fix 2 — FR.225 frontend: render clickable signature buttons for any field
  with status == "current_user" regardless of sig_key prefix. Removes the
  prefix whitelist gate that was blocking ORG_OPENING_* / ORG_CLOSING_*
  slots from rendering as buttons. Also covers COMMITTEE_MEMBER_* for free.
```
