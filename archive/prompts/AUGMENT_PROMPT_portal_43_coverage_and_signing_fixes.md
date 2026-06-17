# AUGMENT PROMPT — Portal 43: TE Coverage Fix + Planner/GM Signing Fix

---

## Bug 1 — Technical Experts Not Counted in EA Code Coverage

### Problem

The coverage panel only checks auditors and the lead auditor for EA code / scope category
coverage. Technical experts assigned to a stage are NOT included in the coverage
calculation. This means if EA 5 is only covered by a TE, the panel still shows ✗ EA 5
— not covered.

Per IAF MD 11:2023: the FULL audit team (lead auditor + auditors + technical experts +
observers) collectively covers all required codes/categories. TEs are explicitly part of
the team and their qualifications count.

### Fix

In the coverage calculation (frontend and/or backend), include technical experts alongside
auditors when computing which codes are covered.

Wherever the coverage is computed — e.g.:

```js
// WRONG — only checks lead + auditors
const team = [leadAuditor, ...auditors];

// CORRECT — includes technical experts too
const team = [leadAuditor, ...auditors, ...technicalExperts];
```

Each person in the team contributes their `covered_scope` (EA codes / food chain
categories / TAs per standard) to the collective coverage.

The coverage panel display should show TE names the same way auditor names are shown:
```
✓ EA 5 — Mehmet Yılmaz (TE)
```

Apply this fix in both:
1. The frontend coverage calculation (if done client-side)
2. The backend `/auditors/available` or stage-save endpoint (if coverage is validated
   server-side on save)

---

## Bug 2 — Planner/GM Cannot Click Their Own Signature Slot

### Problem

When the Planner releases FR.220 (Quotation) and then tries to sign their own slot, the
sign box shows "Planning Officer · Awaiting" but clicking it does nothing — the signing
flow does not open.

Same issue will affect the GM account trying to sign the gm slot on FR.220/FR.221 after
Portal 42.

### Root Cause (likely)

The sign button is probably gated by a condition like:

```js
// blocks the current user if they released/created the document
if (doc.released_by === currentUser.id) return <DisabledBox />;
// OR
if (slot.signer_user_id !== currentUser.id) return <DisabledBox />;
```

Either the release-blocking guard is too broad, or the slot's `signer_user_id` is null
(unassigned, GM self-claims) and the frontend doesn't allow clicking unassigned slots.

### Fix

The sign button for a slot must be clickable if the current user's role matches
`signer_role_label` — regardless of who released the document.

Logic:

```js
const canSign = (slot, currentUser) => {
  // Already signed — not clickable
  if (slot.signed_at) return false;

  // Slot assigned to a specific user
  if (slot.signer_user_id) return slot.signer_user_id === currentUser.id;

  // Unassigned slot — any user with matching role can claim and sign
  const roleMap = {
    cb_planner: ['planner', 'admin'],
    gm: ['gm'],
    certification_manager: ['certification_manager', 'admin'],
    lead_auditor: ['lead_auditor'],
    // add others as needed
  };
  return (roleMap[slot.signer_role_label] ?? []).includes(currentUser.role);
};
```

When `canSign` is true, the dashed box is clickable and opens the signing flow.
When false, it stays greyed out with "Waiting for prior signer" or "Awaiting" text.

Also ensure: releasing a document does NOT set a flag that prevents the releasing user
from also being a signer. The same person can release and sign — these are independent
actions.

Apply this fix to all document types: FR.220, FR.221, FR.218, FR.222, FR.224, FR.225,
FR.230, FR.231, FR.232, FR.229.

---

## What NOT to change

- Do not modify auditor models, qualification schemas, or the bulk import endpoint
- Do not change the overall signing order logic (Organisation Representative still waits
  for the prior CB signer to complete before their slot activates)
- Do not modify PIPELINE_REFERENCE.md or SIGNATURE_MATRIX.md

---

## Verification

1. **TE coverage**: Add a technical expert who has EA 5 for ISO 9001 to a stage where
   EA 5 is required but no auditor covers it. Coverage panel should show ✓ EA 5 — [TE name] (TE).

2. **Planner signing**: Log in as planner, release FR.220, click the Planning Officer
   signature box → signing flow opens → sign → slot shows as signed.

3. **GM signing**: Log in as GM user, open FR.220 → click the GM signature box → signing
   flow opens → sign → Organisation Representative slot activates.
