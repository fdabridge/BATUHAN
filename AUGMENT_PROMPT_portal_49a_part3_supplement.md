# Portal 49a — Part 3 SUPPLEMENT: FR.233 Committee Model Clarification

This supplement answers the exact blocker Augment raised for Part 3.
Read this alongside the original `AUGMENT_PROMPT_portal_49a_roster_fr225_fr233.md`.

---

## Blocker Answer: AuditSetCommitteeMember already exists — do NOT recreate it

The model `AuditSetCommitteeMember` is already defined and in use inside
`backend/audit_set/committee_router.py`. **Do not add a duplicate to db_models.py.**

What it currently has:
```python
# Inside committee_router.py (already exists)
class AuditSetCommitteeMember(Base):
    __tablename__ = "audit_set_committee_members"
    id                        = Column(String, primary_key=True, ...)
    audit_set_id              = Column(String, ForeignKey("audit_sets.id"))
    user_id                   = Column(String, nullable=False)
    user_name                 = Column(String, nullable=False)
    role                      = Column(String)   # "reviewer" | "decision_maker"
    ea_codes_at_appointment   = Column(JSON)     # list of EA codes
    appointed_at              = Column(DateTime)
```

This is exactly the data needed for FR.233. The committee chair = the first
`decision_maker` member; subsequent members = additional `reviewer` or `decision_maker`
members covering the remaining EA codes.

---

## What Part 3 actually needs to add

### 1. New model: `AuditSetFR233Record`

Add to `backend/audit_set/db_models.py`:

```python
class AuditSetFR233Record(Base):
    __tablename__ = "audit_set_fr233_records"

    id           = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    audit_set_id = Column(String, ForeignKey("audit_sets.id"), nullable=False, unique=True)
    # ID of the generated document in the shared_documents / audit_documents table
    document_id  = Column(String, nullable=True)
    # Status flow: "pending" → "signing" → "complete"
    status       = Column(String, default="pending", nullable=False)
    created_at   = Column(DateTime, default=datetime.utcnow)
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

Add Alembic migration for this table.

### 2. Three new endpoints in `committee_router.py`

#### `POST /audit-sets/{audit_set_id}/fr233/generate`

Accessible by: CB Planner or Cert Manager.
Triggered when: `workflow_status == "stage2_complete"` (or `"committee_review"`).

What it does:
1. Queries `AuditSetCommitteeMember` for this audit_set — first `decision_maker` = chair,
   remaining members = member1, member2.
2. Builds the filler context using `FR233_MAP` fields:

```python
from audit_set.field_maps import FR233_MAP

def _build_fr233_context(audit_set, db: Session) -> dict:
    members = (
        db.query(AuditSetCommitteeMember)
        .filter_by(audit_set_id=audit_set.id)
        .order_by(AuditSetCommitteeMember.appointed_at)
        .all()
    )
    # Separate chair (decision_maker) from regular members
    chair   = next((m for m in members if m.role == "decision_maker"), None)
    regulars = [m for m in members if m != chair]

    all_stages = {s.stage_type: s for s in (audit_set.stages or [])}
    stage1 = all_stages.get("stage_1")
    stage2 = all_stages.get("stage_2")

    def fmt(d):
        return d.strftime("%d.%m.%Y") if d else ""

    lead_auditor = next(
        (p for p in (audit_set.personnel or {}).get("auditors", []) if p.get("is_lead")),
        None,
    )
    team_parts = []
    if lead_auditor:
        team_parts.append(f"{lead_auditor['name']} (Lead Auditor)")
    for a in (audit_set.personnel or {}).get("auditors", []):
        if not a.get("is_lead"):
            team_parts.append(a["name"])

    return {
        "plan_number":            audit_set.plan_number or "",
        "company_name":           audit_set.company_name or "",
        "company_address":        audit_set.company_address or "",
        "standards_str":          ", ".join(audit_set.standards or []),
        "ea_code":                audit_set.ea_code or "",
        "audit_team_str":         ", ".join(team_parts),
        "stage_1_date":           fmt(stage1.audit_date_start if stage1 else None),
        "stage_2_date":           fmt(stage2.audit_date_start if stage2 else None),
        "stage_1_report_date":    fmt(stage1.report_date if stage1 else None),
        "stage_2_report_date":    fmt(stage2.report_date if stage2 else None),
        "decision_date":          fmt(date.today()),
        "scope_en":               audit_set.scope_en or "",
        "committee_chair_name":   chair.user_name if chair else "",
        "committee_chair_ea":     (chair.ea_codes_at_appointment or [""])[0] if chair else "",
        "committee_member1_name": regulars[0].user_name if len(regulars) > 0 else "",
        "committee_member1_ea":   (regulars[0].ea_codes_at_appointment or [""])[0] if len(regulars) > 0 else "",
        "committee_member2_name": regulars[1].user_name if len(regulars) > 1 else "",
        "committee_member2_ea":   (regulars[1].ea_codes_at_appointment or [""])[0] if len(regulars) > 1 else "",
    }
```

3. Finds the correct FR.233 template path using the resolver (or directly from
   `BLANK_SET_PATH`).
4. Calls the filler to render DOCX bytes.
5. Saves to storage and creates a `SharedDocument` / `AuditDocument` record so it
   appears in the document panel.
6. Creates or updates `AuditSetFR233Record` with `document_id` and `status="signing"`.
7. Advances `workflow_status` to `"committee_review"` if not already there.

#### `GET /audit-sets/{audit_set_id}/fr233`

Returns the current `AuditSetFR233Record` plus per-member signing status.
Response shape:
```json
{
  "status": "signing",
  "document_id": "...",
  "members": [
    {"user_id": "...", "user_name": "Chair Name", "role": "decision_maker",
     "ea_codes": ["EA 3"], "signed": false},
    {"user_id": "...", "user_name": "Member Name", "role": "reviewer",
     "ea_codes": ["EA 29"], "signed": false}
  ],
  "cert_manager_signed": false
}
```

#### Signing flow (reuse existing viewer infrastructure)

**No new sign endpoint needed.** FR.233 is a shared document in the viewer.
The existing `POST /viewer/sign/confirm` handles signing.

The signature slots in Table 3 col 5 are placed as:
- `[SIG:COMMITTEE_CHAIR]`
- `[SIG:COMMITTEE_MEMBER_1]`
- `[SIG:COMMITTEE_MEMBER_2]`
- `[SIG:CERT_MANAGER_FR233]`

In `viewer_router.py`, extend `_assert_can_sign` to handle these keys:

```python
COMMITTEE_SIG_MAP = {
    "COMMITTEE_CHAIR":     "decision_maker",    # first appointed decision_maker
    "COMMITTEE_MEMBER_1":  None,                # second committee member (any role)
    "COMMITTEE_MEMBER_2":  None,                # third committee member (any role)
    "CERT_MANAGER_FR233":  "cert_manager",      # CB Cert Manager only
}

def _check_committee_sig(sig_key: str, audit_set_id: str, current_user, db: Session) -> bool:
    if sig_key not in COMMITTEE_SIG_MAP:
        return False
    members = (
        db.query(AuditSetCommitteeMember)
        .filter_by(audit_set_id=audit_set_id)
        .order_by(AuditSetCommitteeMember.appointed_at)
        .all()
    )
    if sig_key == "CERT_MANAGER_FR233":
        return current_user.role == "cert_manager"
    elif sig_key == "COMMITTEE_CHAIR":
        chair = next((m for m in members if m.role == "decision_maker"), None)
        return chair is not None and chair.user_id == current_user.id
    elif sig_key == "COMMITTEE_MEMBER_1":
        non_chairs = [m for m in members if m.role != "decision_maker"]
        return len(non_chairs) > 0 and non_chairs[0].user_id == current_user.id
    elif sig_key == "COMMITTEE_MEMBER_2":
        non_chairs = [m for m in members if m.role != "decision_maker"]
        return len(non_chairs) > 1 and non_chairs[1].user_id == current_user.id
    return False
```

**After Cert Manager signs FR.233:** advance `workflow_status` to `"certified"` and
set `AuditSetFR233Record.status = "complete"`.

This is the **only** path to `certified` — remove any existing auto-certify logic
that advances status when the CB_REVIEWER signs the audit report.

---

## Visibility rules for FR.233

FR.233 must be visible to:
- CB Planners ✓
- Cert Manager ✓
- Committee members (CB auditors/TEs who are on the committee) ✓

FR.233 must NOT be visible to:
- The client ✗
- Auditors who are NOT on the committee ✗

Implement by checking `AuditSetCommitteeMember.user_id` when a CB auditor tries to
access the document.

---

## Frontend additions

### CB Portal — Audit Set Detail Page

When `workflow_status` is `"stage2_complete"` or `"committee_review"`, show a
**"Certification Committee"** section:

1. Committee member list (already shown by Portal 47 UI) — each member with name, EA, role.
2. **"Generate FR.233"** button (Planner/CM only):
   - Calls `POST /audit-sets/{id}/fr233/generate`
   - On success, FR.233 appears in the shared documents panel
3. **Signing status table** — one row per committee member:
   ```
   | Name          | EA Code | Role     | Status   |
   |---------------|---------|----------|----------|
   | Alice Smith   | EA 3    | Chair    | ✅ Signed |
   | Bob Jones     | EA 29   | Member   | ⏳ Pending |
   ```
4. After ALL committee members sign: show **"Sign as Cert Manager"** button for CM user
   (opens FR.233 in the viewer, pre-scrolled to the CM signature slot).
5. After CM signs: status advances to `certified` automatically.

### CB User Portal — Committee Member View

When a CB user is a committee member for an audit set:

Show a card: **"FR.233 Review & Decision — Your Signature Required"**
- Audit set name, client, standards
- "Review & Sign" button → opens FR.233 in the document viewer
- Viewer highlights their specific signature slot (`[SIG:COMMITTEE_CHAIR]` etc.)
- After signing: card shows ✅ Done

---

## Files to touch (Part 3 only)

| File | Change |
|---|---|
| `backend/audit_set/db_models.py` | Add `AuditSetFR233Record` model |
| `backend/alembic/versions/xxx_add_fr233_record.py` | New migration |
| `backend/audit_set/committee_router.py` | Add `generate`, `GET` endpoints; committee sig helpers |
| `backend/audit_set/viewer_router.py` | Add `COMMITTEE_SIG_MAP`; `_check_committee_sig()`; on CM sign → `certified` |
| `frontend/.../audit-sets/[id]/page.tsx` | Add Certification Committee section |
| `frontend/.../cb-user/page.tsx` (or equivalent) | Add committee signing task card |

**Do NOT modify:**
- `field_maps.py` — `FR233_MAP` is already there
- `resolver.py` — FR.233 is already wired into Stage_2 and Surveillance
- `AuditSetCommitteeMember` — it already exists; just query it

---

## Critical: Remove the auto-certify shortcut

Currently `viewer_router.py` auto-advances to `certified` when the CB_REVIEWER signs
the audit report while `workflow_status == "under_review"` (or similar).

**This must be removed.** Certification now requires FR.233 committee signing.
The only transition to `certified` is when the Cert Manager signs `[SIG:CERT_MANAGER_FR233]`.

Search for the auto-certify block:
```bash
grep -n "certified" backend/audit_set/viewer_router.py
```
Remove or replace any line that sets `workflow_status = "certified"` outside the
FR.233 Cert Manager signing handler.
