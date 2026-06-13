# AUGMENT PROMPT — Portal 50a: FR.224 Full Flow Fix (Phase 6 — Audit Team Information)

## Context

Two bugs break Phase 6 of the pipeline. Both are confirmed by reading source code.
This prompt fixes both root causes, adds a one-time DB repair, and verifies the
complete end-to-end chain so no secondary bugs remain.

The full FR.224 flow is:

```
CB Planner uploads FR.224 for each team member
  → selects stage + assigned auditor from dropdown
  → document saved with assigned_auditor_id

Each auditor logs in → "My Audit Assignments" shows the audit
  → opens audit → Documents tab
  → own FR.224 shown in amber card → "Open to Sign"
  → viewer opens → [SIG:ASSIGNED_AUDITOR] slot visible
  → auditor signs → signature burned in
```

Both bugs interrupt this chain before the upload step can even work correctly.

---

## Bug 1 — Lead auditor missing from FR.224 "Assigned auditor" dropdown

### Root cause

`frontend/src/app/(app)/clients/[id]/page.tsx`, function `buildStageEdit()`:

```typescript
function buildStageEdit(s: StageResponse): StageEdit {
  return {
    lead_auditor_id:   '',          // ← always '' regardless of s.lead_auditor_id
    lead_auditor_name: s.lead_auditor_name ?? '',
    ...
  }
}
```

Every time the edit form is opened and "Save stage" is clicked, `lead_auditor_id = ''`
is written to the database — overwriting the correct value.

In `SharedDocumentsSection.tsx`, `stageTeam()` builds the FR.224 assigned-auditor
dropdown from the API stage data:

```typescript
push(stage.lead_auditor_id ?? undefined, stage.lead_auditor_name ?? undefined)
```

`push()` early-returns when `!id` — and empty string is falsy — so the lead auditor
is silently dropped from the dropdown.

**Downstream effect:** There is no way to upload an FR.224 for the lead auditor.
Her `lead_auditor_id` in the DB is also `''`, so `_stage_matches_auditor` in
`auditor_router.py` will never match her, and her auditor portal shows 0 assignments.

### Fix — frontend (one line)

**File:** `frontend/src/app/(app)/clients/[id]/page.tsx`

```typescript
// BEFORE
function buildStageEdit(s: StageResponse): StageEdit {
  return {
    lead_auditor_id:   '',
    lead_auditor_name: s.lead_auditor_name ?? '',
    audit_date_start:  s.audit_date_start  ?? '',
    audit_date_end:    s.audit_date_end    ?? '',
    auditors:          parseTeamMembers(s.auditors as unknown[]),
    technical_experts: parseTeamMembers(s.technical_experts as unknown[]),
  }
}

// AFTER
function buildStageEdit(s: StageResponse): StageEdit {
  return {
    lead_auditor_id:   s.lead_auditor_id   ?? '',   // ← preserve from API response
    lead_auditor_name: s.lead_auditor_name ?? '',
    audit_date_start:  s.audit_date_start  ?? '',
    audit_date_end:    s.audit_date_end    ?? '',
    auditors:          parseTeamMembers(s.auditors as unknown[]),
    technical_experts: parseTeamMembers(s.technical_experts as unknown[]),
  }
}
```

### Fix — DB repair script (run once after deploy)

Existing audit set stages have `lead_auditor_id = ''` because of the bug above.
Create `backend/scripts/repair_lead_auditor_ids.py`:

```python
#!/usr/bin/env python3
"""
One-time repair: restore lead_auditor_id on AuditSetStage rows where it is
blank but lead_auditor_name is present.

Run from the project root (backend container or locally with DB access):
    python backend/scripts/repair_lead_auditor_ids.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from audit_set.db_models import AuditSetStage, get_db

# Import the Auditor model — adjust the import path if your auditors module differs
try:
    from auditors.db_models import Auditor
except ImportError:
    from audit_set.db_models import Auditor  # fallback if co-located

def repair():
    db = next(get_db())
    stages = db.query(AuditSetStage).all()

    fixed = 0
    skipped = 0
    for stage in stages:
        # Only repair stages where lead_auditor_id is missing but name is present
        if stage.lead_auditor_id or not stage.lead_auditor_name:
            skipped += 1
            continue

        auditor = (
            db.query(Auditor)
            .filter(Auditor.name == stage.lead_auditor_name)
            .first()
        )
        if auditor:
            stage.lead_auditor_id = auditor.id
            fixed += 1
            print(f"  FIXED stage {stage.id[:8]}… "
                  f"({stage.stage_type}): '{stage.lead_auditor_name}' → {auditor.id[:8]}…")
        else:
            print(f"  WARN  stage {stage.id[:8]}… "
                  f"({stage.stage_type}): no auditor record found for "
                  f"'{stage.lead_auditor_name}'")

    db.commit()
    print(f"\nDone. Fixed: {fixed}  Skipped (already OK or no name): {skipped}")

if __name__ == "__main__":
    repair()
```

---

## Bug 2 — Technical Experts show 0 assignments in auditor portal

### Root cause

`backend/audit_set/auditor_router.py`, function `_stage_matches_auditor()`:

```python
def _stage_matches_auditor(stage: AuditSetStage, auditor_id: str) -> tuple[bool, bool]:
    is_lead = stage.lead_auditor_id == auditor_id
    is_team = any(
        isinstance(a, dict) and a.get("id") == auditor_id
        for a in (stage.auditors or [])   # ← technical_experts never checked
    )
    return (is_lead or is_team, is_lead)
```

Any team member stored in `stage.technical_experts` never matches, so
`_get_auditor_assignments` returns an empty list for TEs and they see
"0 audits assigned."

Note: `_auditor_is_assigned()` in `documents_router.py` already checks
`technical_experts` correctly. This fix is only needed in `auditor_router.py`.

### Fix — backend (two lines)

**File:** `backend/audit_set/auditor_router.py`

```python
# BEFORE
def _stage_matches_auditor(stage: AuditSetStage, auditor_id: str) -> tuple[bool, bool]:
    """Return (is_assigned, is_lead) for this auditor on the given stage."""
    is_lead = stage.lead_auditor_id == auditor_id
    is_team = any(
        isinstance(a, dict) and a.get("id") == auditor_id
        for a in (stage.auditors or [])
    )
    return (is_lead or is_team, is_lead)

# AFTER
def _stage_matches_auditor(stage: AuditSetStage, auditor_id: str) -> tuple[bool, bool]:
    """Return (is_assigned, is_lead) for this auditor on the given stage.
    Checks lead auditor, regular auditors, AND technical experts.
    """
    is_lead = bool(stage.lead_auditor_id) and stage.lead_auditor_id == auditor_id
    all_members = list(stage.auditors or []) + list(stage.technical_experts or [])
    is_team = any(
        isinstance(a, dict) and a.get("id") == auditor_id
        for a in all_members
    )
    return (is_lead or is_team, is_lead)
```

---

## What is already correct — do NOT change

The rest of the FR.224 signing chain is already implemented correctly in 49b.
Verify this by reading each piece before touching it:

**`documents_router.py` — `_auditor_is_assigned()`**: Already checks
`stage.lead_auditor_id` AND `stage.auditors` AND `stage.technical_experts`.
The `GET /audit-sets/{id}/documents` endpoint uses this to gate auditor access.

**`documents_router.py` — `_visible_docs_for_user()` auditor branch**: Correctly
returns `team_info` docs where `d.assigned_auditor_id == current_user.auditor_id`.
Each auditor sees only their own FR.224.

**`viewer_router.py` — `assigned_auditor` sig key check** (line ~300):
```python
if role_label == "assigned_auditor":
    return (
        role == "auditor"
        and current_user.auditor_id is not None
        and doc.assigned_auditor_id == current_user.auditor_id
    )
```
Correctly gates signing to the assigned auditor only.

**`frontend/src/components/ui/SharedDocumentsSection.tsx` — `stageTeam()`**:
Already includes lead auditor, auditors, and TEs — it was just receiving an
empty `lead_auditor_id` from the API because the DB had `''`. After the bug fix
and DB repair, it will work without changes.

**`frontend/src/app/(auditor)/auditor/audit/[id]/page.tsx` — `AuditorSharedDocsView`**:
Already fetches `GET /audit-sets/{id}/documents`, filters `team_info` docs for
the current auditor, and shows them in an amber card with "Open to Sign" → 
`/auditor/viewer/shared_doc/{id}`. No changes needed.

**`frontend/src/app/(auditor)/auditor/viewer/[type]/[id]/page.tsx`**: Auditor viewer
route exists and handles `shared_doc` type. No changes needed.

---

## Files to touch

| File | Change |
|---|---|
| `frontend/src/app/(app)/clients/[id]/page.tsx` | `buildStageEdit()`: `lead_auditor_id: s.lead_auditor_id ?? ''` |
| `backend/audit_set/auditor_router.py` | `_stage_matches_auditor()`: include `technical_experts` |
| `backend/scripts/repair_lead_auditor_ids.py` | NEW — one-time DB repair script |

**Do NOT touch:**
- `documents_router.py` — already correct
- `viewer_router.py` — already correct for `assigned_auditor` sig key
- `SharedDocumentsSection.tsx` — already correct
- `auditor/audit/[id]/page.tsx` — already correct

---

## Complete end-to-end verification

After deploying both fixes and running the repair script, verify this exact sequence:

### As CB Planner

1. Open audit set → Shared Documents → "+ Release Document"
2. Type = "Audit Team Info (FR.224)" → Stage = "Stage 1"
3. **"Assigned auditor" dropdown must now show ALL stage members:**
   - Aslı Abay (lead auditor)
   - Altuğ Solmaz (TE)
   - Any additional auditors on the stage
4. Upload FR.224 for Aslı Abay → select her from dropdown → Release
5. Upload FR.224 for Altuğ Solmaz → select him from dropdown → Release
6. Confirm both documents appear in the shared docs list

### As Altuğ Solmaz (Technical Expert auditor account)

1. Log in → "My Audit Assignments" must show the audit set (was: 0 assignments)
2. Open the audit → "Documents" tab
3. FR.224 form must appear in an **amber card** at the top:
   - Title: the label CB gave it (e.g. "FR.224 Audit Team Info — Altuğ Solmaz")
   - Subtitle: "Your audit team information form · stage 1 — please review and sign."
   - Button: "Open to Sign"
4. Click "Open to Sign" → viewer opens → Page 2 shows his name with "Awaiting signature" slot
5. Sign using saved signature → slot fills → "Download Signed PDF" works
6. Back in Documents tab: FR.224 card shows ✓ Signed (status updated)

### As Aslı Abay (Lead Auditor account)

1. Log in → "My Audit Assignments" must show the audit set
   *(requires DB repair script to have run — her lead_auditor_id must be populated)*
2. Open the audit → "Documents" tab
3. Her FR.224 must appear in amber card → "Open to Sign"
4. Sign → slot fills → done
5. Her FR.224 does **NOT** appear in Altuğ's portal (and vice versa — each sees only their own)

### Isolation check (negative test)

1. Log in as any auditor on this audit set
2. Documents tab must NOT show any other auditor's FR.224
3. Attempting to open another auditor's FR.224 viewer URL directly must return 403

### CB can see both

1. Log in as CB Planner → shared documents list shows both FR.224 documents
2. Both show correct "Signed" status after each auditor signs

---

## Prerequisite: auditor_id linkage (PlatformUser → Auditor)

Before any of the above works, each auditor's PlatformUser account must have
`auditor_id` set. This is done via the Admin → Users page link UI (Portal 48).

If either account still has `auditor_id = null`:
- Their portal will show 0 assignments even after these fixes
- The viewer will reject their signing attempt (403)

Verify in the DB:
```sql
SELECT u.full_name, u.role, u.auditor_id
FROM platform_users u
WHERE u.role = 'auditor';
```

Any row with `auditor_id = null` needs to be linked via Admin → Users → "Link to auditor profile".
