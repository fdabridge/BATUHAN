# AUGMENT PROMPT — Portal 45: Fix GM Signing on FR.220 and FR.221

## Problem

Portal 43 reverted the FR.220/FR.221 signature slot back to `signer_role_label="cb_planner"`
to match the DOCX template key `[SIG:CB_PLANNER]`. This was the wrong fix — it means
the Planning Officer signs the quotation and agreement, but per the pipeline the
**General Manager of IFC Global** must sign FR.220 and FR.221. The planner should not
sign these documents at all.

The root cause was a mismatch between the DOCX template key and the DB slot label.
The correct fix is to update the DOCX templates, not revert the slot.

---

## Fix

### 1. Update DOCX templates — FR.220 and FR.221

In the UAF blank set, FR.220 (Certification Quotation) and FR.221 (Certification Agreement)
have a signature table with two columns:
- Left: "Signed on behalf of IFC GLOBAL LLC"
- Right: "Signed on behalf of the Organization"

The left column signature field currently uses `[SIG:CB_PLANNER]`.
**Change it to `[SIG:GM]`** in both FR.220 and FR.221 templates.

Find the template files in `backend/` (or wherever the blank set templates are stored),
open FR.220 and FR.221, and replace the `[SIG:CB_PLANNER]` tag in the IFC Global
signature cell with `[SIG:GM]`.

Do this for all standard variants of FR.220 and FR.221 (QMS, FSMS, ISMS, etc. if there
are separate files per standard).

### 2. Backend — documents_router.py

Keep (or restore) the signature slot as:
```python
signer_role_label = "gm"
```
Do NOT use `cb_planner` for FR.220 or FR.221.

### 3. Backend — viewer_router.py

Ensure the viewer maps `[SIG:GM]` template tag → `gm` slot correctly.

In `_get_field_status` and `_assert_can_sign`:
- `gm` slot can be signed by users with role `gm` or `admin`
- `gm` slot cannot be signed by `planner` — remove planner from the eligible list for `gm` slots
- Keep the `cb_planner` slot (used elsewhere) eligible for planner + admin

### 4. Planner cannot sign FR.220 / FR.221

After this fix, when a planner opens FR.220:
- The IFC Global signature box says "General Manager · Click to sign" (if logged in as GM)
  or "General Manager · Awaiting" (if logged in as planner)
- The planner cannot click it — it is not their document to sign
- Only the GM account can sign it

---

## Scope — only FR.220 and FR.221

Do not change the signing slots or template keys for any other document.
FR.218, FR.222, FR.223, FR.224, FR.225, FR.230, FR.231, FR.232 are not affected.

---

## Verification

1. Log in as planner → release FR.220 → open it → IFC Global signature box shows
   "General Manager · Awaiting" — NOT clickable for the planner
2. Log in as GM account → open FR.220 → IFC Global signature box shows
   "General Manager · Click to sign" → click → signing flow opens → sign →
   Organisation Representative slot activates
3. Same for FR.221
