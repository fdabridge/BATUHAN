# AUGMENT PROMPT — Portal 47b: FR.218 Signing Fix (Planner + CM can't sign)

## Root Cause

`backend/audit_set/signatures_router.py` has three bugs that block both the
Planning Officer and the Certification Manager from signing FR.218 slots.

---

## Fix 1 — Add `certification_manager` to `CB_ROLES`

File: `backend/audit_set/signatures_router.py`

```python
# BEFORE (line ~25):
CB_ROLES = {"admin", "planner", "officer", "executive", "gm"}

# AFTER:
CB_ROLES = {"admin", "planner", "officer", "executive", "gm", "certification_manager"}
```

Without this, any request from a `certification_manager` user hits a 403
before any endpoint logic runs. FR.218 never appears on the CM portal.

---

## Fix 2 — `get_my_pending_signatures`: add `cb_planner` and `cb_cert_manager` to eligible_labels

File: `backend/audit_set/signatures_router.py`, function `get_my_pending_signatures`

```python
# BEFORE:
eligible_labels: list[str] = []
if current_user.role in ("admin", "executive"):
    eligible_labels.append("cb_cert_manager")
if current_user.role == "gm":
    eligible_labels.append("gm")

# AFTER:
eligible_labels: list[str] = []
if current_user.role in ("admin", "planner"):
    eligible_labels.append("cb_planner")
if current_user.role in ("admin", "executive", "certification_manager"):
    eligible_labels.append("cb_cert_manager")
if current_user.role == "gm":
    eligible_labels.append("gm")
```

---

## Fix 3 — `get_internal_signatures`: same fix to eligible_labels and can_claim

File: `backend/audit_set/signatures_router.py`, function `get_internal_signatures`

```python
# BEFORE:
eligible_labels: set[str] = set()
if current_user.role in ("admin", "executive"):
    eligible_labels.add("cb_cert_manager")
if current_user.role == "gm":
    eligible_labels.add("gm")

# AFTER:
eligible_labels: set[str] = set()
if current_user.role in ("admin", "planner"):
    eligible_labels.add("cb_planner")
if current_user.role in ("admin", "executive", "certification_manager"):
    eligible_labels.add("cb_cert_manager")
if current_user.role == "gm":
    eligible_labels.add("gm")
```

---

## Fix 4 — `sign_direct`: fix self-claim eligibility check

File: `backend/audit_set/signatures_router.py`, function `sign_direct`

```python
# BEFORE:
if sig.signer_user_id is None:
    eligible = (
        (sig.signer_role_label == "cb_cert_manager" and current_user.role in ("admin", "executive"))
        or (sig.signer_role_label == "gm" and current_user.role == "gm")
    )
    if not eligible:
        raise HTTPException(403, "You are not eligible to sign this slot")

# AFTER:
if sig.signer_user_id is None:
    eligible = (
        (sig.signer_role_label == "cb_planner"      and current_user.role in ("admin", "planner"))
        or (sig.signer_role_label == "cb_cert_manager" and current_user.role in ("admin", "executive", "certification_manager"))
        or (sig.signer_role_label == "gm"             and current_user.role == "gm")
        or (sig.signer_role_label == "cb_reviewer"    and current_user.role in ("admin", "certification_manager"))
    )
    if not eligible:
        raise HTTPException(403, "You are not eligible to sign this slot")
```

---

## What NOT to change

- Do not touch pipeline_triggers.py
- Do not touch InternalApprovalsSection.tsx — the frontend is correct; it
  shows a Sign button when `can_claim` or `is_mine` is True. The backend
  was returning `can_claim: False` for both planner and CM. After this fix
  both will see a Sign button with no frontend changes needed.
- Do not change FR.222 logic

---

## Verification

1. Log in as **Planning Officer** → open any audit set at `fr218_in_progress`
   → Internal Approvals section → Planning Officer row shows **Sign** button
   → click → confirm → row shows ✓ Signed

2. Log in as **Certification Manager** → same audit set → Internal Approvals
   loads (no 403) → Certification Manager row shows **Awaiting** (because
   order_index=2, planner must sign first) → after planner signs → row shows
   **Sign** button → CM signs → workflow auto-advances to `fr218_complete`

3. Status bar advances to "Review Done" and the "Start Stage 1" CTA appears.
