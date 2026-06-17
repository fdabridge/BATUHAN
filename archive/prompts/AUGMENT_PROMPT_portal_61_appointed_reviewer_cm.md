# Portal 61 — Appointed Reviewer = Certification Manager (Auto-Assign)

## Context

After Stage 1, the Lead Auditor signs FR.231 (Stage 1 Report) and FR.232 (Audit
Report). The second signature slot — `[SIG:APPOINTED_REVIEWER]` — must be signed by
the **Certification Manager**. There is always exactly one CM account in the system,
so no picker is needed — the system auto-assigns the CM as the appointed reviewer.

**DOCX templates are already fixed** (committed this session):
- FR.231 (3 files): Label cell changed from "Reviewed and approved by *" → "Certification Manager"
- FR.232-1 (13485, 2 files): Same label change
- FR.232 (9-14-45-22-5001, 2 files): New "Certification Manager" label row inserted before [SIG:APPOINTED_REVIEWER]
- FR.233 (6 files): [SIG:CERT_MANAGER_REVIEW] added to the CM Approval row

The sig markers (`[SIG:APPOINTED_REVIEWER]` in FR.231/FR.232, `[SIG:CERT_MANAGER_REVIEW]`
in FR.233) are already in the templates. This portal wires them correctly in the backend.

---

## Fix 1 — Viewer eligibility: APPOINTED_REVIEWER requires certification_manager role

**File:** `backend/audit_set/viewer_router.py`

Find the eligibility check for `APPOINTED_REVIEWER` in `_shared_slot_eligible` (or
wherever `SIG_TO_ROLE["APPOINTED_REVIEWER"]` resolves). Currently it may map to a
generic "reviewer" or "officer" role. Change it so only `certification_manager` can sign:

```python
# In SIG_TO_ROLE dict (or equivalent mapping):
"APPOINTED_REVIEWER": "certification_manager",
```

If eligibility is checked inline (not via SIG_TO_ROLE), find the block for
`APPOINTED_REVIEWER` and update:

```python
if sig_key == "APPOINTED_REVIEWER":
    return current_user.role == "certification_manager"
```

Also add `CERT_MANAGER_REVIEW` (new FR.233 marker) with the same rule:
```python
if sig_key == "CERT_MANAGER_REVIEW":
    return current_user.role == "certification_manager"
```

And seed it in `DOC_SIG_SLOTS`:
```python
"review_decision": [..., "cert_manager_review"],  # whatever FR.233 document_type is
```

Add `"CERT_MANAGER_REVIEW"` to `SIG_TO_ROLE` / `ROLE_TO_SIG` maps so the viewer
knows how to handle it:
```python
SIG_TO_ROLE["CERT_MANAGER_REVIEW"] = "certification_manager"
```

---

## Fix 2 — Auto-assign CM when reviewer appointment is triggered

Currently the "appoint reviewer" flow lets the planner pick any user. Since the CM
is always the reviewer, change the appointment to auto-select the CM.

**File:** wherever the "appoint reviewer" action is handled (probably
`workflow_router.py` or `audit_set_router.py`)

Find the endpoint or function that sets the appointed reviewer for an audit set.
Change it to:

```python
# Auto-assign the CM (there is always exactly one CM account)
cm = db.query(PlatformUser).filter_by(role="certification_manager", is_active=True).first()
if not cm:
    raise HTTPException(400, "No active Certification Manager account found")
audit_set.appointed_reviewer_id = cm.id  # or however the reviewer is stored
db.commit()
```

If the current model stores the reviewer differently (e.g. as a string name, or as a
stage field), adapt accordingly.

**Frontend:** Remove the user picker from the "Appoint Reviewer" UI. Replace it with
a simple confirmation button:

```
Appointed Reviewer: [Certification Manager — auto-assigned]
[Confirm appointment]
```

If the CM name should be displayed, fetch it from `GET /admin/users?role=certification_manager`
and show their name.

---

## Fix 3 — Clear the document_signature_fields cache for FR.231/FR.232/FR.233

The templates were just patched. Any documents already in the viewer cache have old
pdfplumber scan results. Run on Railway Postgres:

```sql
DELETE FROM document_signature_fields
WHERE docx_path LIKE '%FR.231%'
   OR docx_path LIKE '%FR.232%'
   OR docx_path LIKE '%FR.233%';
```

The viewer re-scans on next open, picking up the corrected "Certification Manager"
label position and the new `[SIG:CERT_MANAGER_REVIEW]` marker.

---

## Files to change

| File | Change |
|------|--------|
| `backend/audit_set/viewer_router.py` | `APPOINTED_REVIEWER` eligibility → `certification_manager` role; add `CERT_MANAGER_REVIEW` with same rule |
| `backend/audit_set/viewer_router.py` | `SIG_TO_ROLE`: add `"CERT_MANAGER_REVIEW": "certification_manager"` |
| `backend/audit_set/documents_router.py` | `DOC_SIG_SLOTS` for FR.233 document type: include `cert_manager_review` slot |
| `backend/audit_set/workflow_router.py` (or equivalent) | Auto-assign CM in reviewer appointment; remove user picker logic |
| `frontend/.../appoint-reviewer UI` | Replace user picker with CM auto-assign display + confirm button |

---

## Commit message

```
Portal 61: appointed reviewer = certification_manager auto-assign

DOCX templates already patched (this commit):
- FR.231 (x3): "Reviewed and approved by *" -> "Certification Manager"
- FR.232-1 (x2, 13485): same label change
- FR.232 (x2, 9-14-45-22-5001): inserted CM label row before [SIG:APPOINTED_REVIEWER]
- FR.233 (x6): [SIG:CERT_MANAGER_REVIEW] added to CM Approval Sign cell

Backend:
- viewer_router: APPOINTED_REVIEWER + CERT_MANAGER_REVIEW eligibility locked to
  certification_manager role
- SIG_TO_ROLE: CERT_MANAGER_REVIEW -> certification_manager
- DOC_SIG_SLOTS: FR.233 includes cert_manager_review slot
- Reviewer appointment: auto-assigns the single CM account, no picker

Frontend:
- Appoint Reviewer UI: replace user picker with CM name + confirm button
```
