# Portal 54 — Two Pipeline Blockers: Stage Gate Roles + Committee Picker

## Bug 1 — "Stage 1 appropriate" button never appears for Certification Manager

### Root cause

`backend/audit_set/workflow_router.py` line 66:
```python
("stage1_complete", "stage2_in_progress"): {"admin", "executive"},
```

`frontend/src/components/ui/WorkflowStatusBar.tsx` `stage1_complete` entry:
```typescript
cta: { label: 'Stage 1 appropriate — Begin Stage 2', nextStatus: 'stage2_in_progress', allowedRoles: ['admin', 'executive'] },
```

`certification_manager` is in neither set. The CM's dashboard never renders
the CTA button because `allowedRoles` excludes their role. The backend also
rejects their PATCH if they somehow reach it.

The same problem exists for `stage2_complete → committee_review`: only
`{"admin", "planner"}` can trigger it. The CM should drive this gate too.

### Fix — backend (`workflow_router.py`)

```python
# BEFORE
("stage1_complete",    "stage2_in_progress"): {"admin", "executive"},
("stage2_complete",    "committee_review"):   {"admin", "planner"},

# AFTER
("stage1_complete",    "stage2_in_progress"): {"admin", "executive", "certification_manager"},
("stage2_complete",    "committee_review"):   {"admin", "planner", "certification_manager"},
```

### Fix — frontend (`WorkflowStatusBar.tsx`)

```typescript
// BEFORE
stage1_complete: {
  heading: 'Stage 1 complete — Certification Manager review',
  body: '...',
  cta: { label: 'Stage 1 appropriate — Begin Stage 2', nextStatus: 'stage2_in_progress', allowedRoles: ['admin', 'executive'] },
},

// AFTER
stage1_complete: {
  heading: 'Stage 1 complete — Certification Manager review',
  body: '...',
  cta: { label: 'Stage 1 appropriate — Begin Stage 2', nextStatus: 'stage2_in_progress', allowedRoles: ['admin', 'executive', 'certification_manager'] },
},
```

Also find the `stage2_complete` entry in `WorkflowStatusBar.tsx` and add
`'certification_manager'` to its `allowedRoles` list.

### CM portal visibility

Confirm the CM's dashboard (`/app/dashboard` or `/app/applications`) already
shows audit sets where they have a pending action — if not, the `WorkflowStatusBar`
must also render for `certification_manager` role (not just `admin`/`planner`).
Read the dashboard page component to verify; if `certification_manager` is
excluded from the sidebar or applications list, add it.

---

## Bug 2 — Committee picker only shows CB staff, not auditors

### Root cause

`backend/audit_set/committee_router.py`, `get_eligible_users()`:

```python
cb_users = (
    auth_db.query(PlatformUser)
    .filter(
        PlatformUser.role.in_(CB_ROLES),   # ← CB_ROLES = {"admin","planner","officer","executive","gm","certification_manager"}
        PlatformUser.is_active == True,
    )
    .all()
)
```

`CB_ROLES` contains only CB management roles. `"auditor"` is not in it. So
external auditors (who cover the relevant EA codes and should be committee
reviewers) never appear in the picker.

### Fix — `committee_router.py`

Extend the query to also include users with role `"auditor"` who have an
`auditor_id` set (i.e., are linked to an auditor profile). Then apply the same
EA-code filtering already in place.

Replace the `cb_users` query block with:

```python
from audit_set.db_models import AuditSet
from auditors.models import Auditor as AuditorModel

# All eligible candidate users: CB roles AND auditors with a linked profile
candidate_users = (
    auth_db.query(PlatformUser)
    .filter(
        PlatformUser.is_active == True,
        or_(
            PlatformUser.role.in_(CB_ROLES),
            and_(
                PlatformUser.role == "auditor",
                PlatformUser.auditor_id.isnot(None),
            ),
        ),
    )
    .all()
)
```

Then update the loop to use `candidate_users` instead of `cb_users`. The rest
of the loop (EA code lookup, `on_audit_team` exclusion, `ea_match` check) is
already correct — it reads `u.auditor_id` and looks up the `Auditor` record.

Add the required SQLAlchemy imports at the top of the function:
```python
from sqlalchemy import or_, and_
```

### Expected result

After this fix the committee picker shows:
- CB staff (GM, CM, Planner, etc.) who are NOT on the audit team
- External auditors with a linked auditor profile who cover the relevant EA codes
- Auditors already on the audit team are still excluded (existing logic)
- Users already appointed are still excluded (existing logic)
- `ea_match: true` rows sorted first (existing sort order)

---

## Files changed

| File | Change |
|------|--------|
| `backend/audit_set/workflow_router.py` | Add `certification_manager` to stage1_complete→stage2_in_progress and stage2_complete→committee_review allowed roles |
| `frontend/src/components/ui/WorkflowStatusBar.tsx` | Add `'certification_manager'` to `allowedRoles` for stage1_complete and stage2_complete CTAs |
| `backend/audit_set/committee_router.py` | Extend eligible-users query to include `auditor` role users with `auditor_id` |

---

## Commit message

```
Portal 54: fix stage gate roles + committee picker

- workflow_router: add certification_manager to stage1_complete→stage2
  and stage2_complete→committee_review allowed role sets
- WorkflowStatusBar: show Stage 1 gate CTA for certification_manager
- committee/eligible-users: include auditor-role users with auditor
  profiles; CB-only filter was blocking external auditor committee members
```
