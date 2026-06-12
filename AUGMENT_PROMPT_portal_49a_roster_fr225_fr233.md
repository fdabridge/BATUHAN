# AUGMENT PROMPT — Portal 49a: Client Employee Roster, FR.225 Template Update, FR.233 Committee Portal

## Overview

Three tightly related features that must be built together because they share data models
and signing infrastructure:

1. **Client Employee Roster** — organisations manage a list of named employees with saved
   signature images. Used when signing FR.225 Opening/Closing Meeting forms.
2. **FR.225 Template Update** — convert the four static blank "Organisation Personnel" rows
   in every FR.225 template into a docxtpl Jinja2 loop so employee names/roles/signature
   placeholders are inserted at document-generation time.
3. **FR.233 Committee Portal** — the Certification Manager/Planner uploads a pre-filled
   FR.233 Review & Decision Form; committee members sign it one by one in their own portals;
   the Certification Manager signs last.

---

## Part 1 — Client Employee Roster

### 1a. DB Model  (`backend/audit_set/db_models.py`)

Add a new SQLAlchemy model `ClientOrgEmployee`:

```python
class ClientOrgEmployee(Base):
    __tablename__ = "client_org_employees"

    id            = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    # Linked to the PlatformUser whose role == "client"
    client_user_id = Column(String, nullable=False, index=True)
    full_name      = Column(String, nullable=False)
    role_title     = Column(String, nullable=False)        # e.g. "Quality Manager"
    # Storage path for their signature image (same pattern as UserSignature)
    signature_path = Column(String, nullable=True)
    is_active      = Column(Boolean, default=True)
    created_at     = Column(DateTime, default=datetime.utcnow)
    updated_at     = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

Add Alembic migration.

### 1b. Backend API  (`backend/auth/` or `backend/audit_set/employee_router.py`)

New router prefix `/org/employees`. Mount in `main.py`.

```
GET    /org/employees                    — list own employees (client role only)
POST   /org/employees                    — create employee {full_name, role_title}
PATCH  /org/employees/{id}               — update name/role/is_active
DELETE /org/employees/{id}              — soft-delete (set is_active=False)
POST   /org/employees/{id}/signature     — upload signature image (multipart)
GET    /org/employees/{id}/signature     — serve signature image
```

Authorization: `current_user.role == "client"` for all endpoints. Employees belong to
`client_user_id = current_user.id`.

Signature upload: same storage pattern as `UserSignature` — save to
`storage/org_employee_signatures/{employee_id}.png`, normalise to max 400×150 px.

### 1c. Frontend — Client Portal Employee Roster Page

Route: `/client/employees` (or a tab within the client settings area).

UI elements:
- Table: Name | Role | Signature preview (thumbnail) | Actions (edit, delete)
- "Add Employee" button → modal with fields: Full Name, Role/Title
- After creating: prompt to upload their signature image
- Signature upload: file input → preview → save (same UI pattern as user signature page)
- Each row shows whether signature is uploaded (green checkmark / orange "missing")

This page should be discoverable from the client portal nav sidebar.

---

## Part 2 — FR.225 Template Update (docxtpl Jinja2 loop for org attendees)

### Context

Every FR.225 template (`FR.225_Opening_Closing_Meeting_Form-R7&09.10.2025.docx`) has this
structure in **Table 2** (the participants table):

```
row 0 : "Organization Personnel"   [merged across 4 cols]
row 1 : "Participant" | "Role" | "Opening Signature" | "Closing Signature"
row 2 : (blank)  ← static empty rows — REPLACE THESE WITH A LOOP
row 3 : (blank)
row 4 : (blank)
row 5 : (blank)
row 6 : "Audit Team"               [merged across 4 cols]
row 7 : {{ lead_auditor_name }} | Lead Auditor | | |
row 8+: existing Jinja2 auditor/TE loops (DO NOT TOUCH)
```

### What to do

Write a Python script `backend/scripts/update_fr225_org_attendee_rows.py` that:

1. Finds every `FR.225*.docx` file recursively under both:
   - `./uaf_blank_set/`  (Turkish/English set committed in Docker)
   - `./uaf_blank_set copy/`  (English UAF working copy)
   
2. For each file, using `python-docx`:
   - Opens the document
   - Locates Table 2 (index 2)
   - **Deletes rows 2–5** (the four static blank org attendee rows)
   - **Inserts** three rows in their place using the same style as the surrounding rows:
     - Row A (loop start):  first cell = `{%tr for emp in org_attendees %}`  other cells empty
     - Row B (content):     cells = `{{ emp.name }}` | `{{ emp.role }}` | `[SIG:ORG_OPENING_{{ emp.sig_key }}]` | `[SIG:ORG_CLOSING_{{ emp.sig_key }}]`
     - Row C (loop end):    last cell = `{%tr endfor %}`  other cells empty
   - Saves the file in place (overwrites the original)
   
3. Prints a summary of which files were updated.

**Important**: match the font, paragraph spacing, and cell borders of the existing rows.
Copy the XML style from the row above (row 1 column header row) for the header cells,
and from row 7 (lead_auditor_name row) for the content row.

### FR.225 docxtpl context update  (`backend/audit_set/filler.py` or equivalent)

When rendering FR.225, build the `org_attendees` list from the `ClientOrgEmployee` table:

```python
def _build_org_attendees(audit_set_id: str, db: Session) -> list[dict]:
    # Get the client user for this audit set
    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    client = auth_db.query(PlatformUser).filter_by(
        id=audit_set.client_user_id, role="client"
    ).first()
    if not client:
        return []
    employees = db.query(ClientOrgEmployee).filter_by(
        client_user_id=client.id, is_active=True
    ).all()
    return [
        {
            "name":    e.full_name,
            "role":    e.role_title,
            "sig_key": f"ORG_EMP_{e.id}",  # unique per employee
        }
        for e in employees
    ]
```

Pass `org_attendees` into the docxtpl render context for FR.225.

### Viewer — dynamic org employee signature keys

In `viewer_router.py`, extend `_assert_can_sign` to handle `sig_key` values matching
the pattern `ORG_OPENING_ORG_EMP_{uuid}` or `ORG_CLOSING_ORG_EMP_{uuid}`:

- Requires `current_user.role == "client"`
- Extract the employee UUID from the sig_key
- Verify `ClientOrgEmployee.client_user_id == current_user.id`
- Place the employee's saved signature image at that slot

When the client clicks a `[SIG:ORG_OPENING_ORG_EMP_xxx]` field in the PDF viewer, a
picker shows the org employee roster. The client selects which person is signing, and
their saved signature image is placed. Record the signing with a new
`AuditSetMeetingAttendeeSignature` record (or reuse `AuditSetMeetingAttendee`).

---

## Part 3 — FR.233 Committee Signing Portal

### Context

FR.233 Review & Decision Form has been added to:
- `field_maps.py` as `FR233_MAP` (coordinates confirmed by template inspection)
- `resolver.py` so it is generated in the Stage_2 and Surveillance blank set ZIPs

The FR.233 template (Table 3) has these signature rows:

```
Table 3, row 1: Chairperson | [name col=1] | [ea col=3] | [sign col=5]
Table 3, row 2: Member      | [name col=1] | [ea col=3] | [sign col=5]
Table 3, row 3: Member      | [name col=1] | [ea col=3] | [sign col=5]
Table 3, row 6: Certification Manager Approval | | | [sign col=4 or 5]
```

### DB — Certification Committee model  (`backend/audit_set/db_models.py`)

This already exists as `AuditSetCommitteeMember` (from `committee_router.py`). The
`role` field holds `"reviewer"` or `"decision_maker"`. For FR.233, the committee is the
full set of appointed members.

Add a field to `AuditSet` (or a new model `AuditSetFR233Record`):

```python
class AuditSetFR233Record(Base):
    __tablename__ = "audit_set_fr233_records"
    id            = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    audit_set_id  = Column(String, ForeignKey("audit_sets.id"), nullable=False)
    document_id   = Column(String, nullable=True)       # FK to uploaded shared doc
    status        = Column(String, default="pending")   # pending → signing → complete
    created_at    = Column(DateTime, default=datetime.utcnow)
```

### Backend API  (`backend/audit_set/committee_router.py`)

Add endpoints:

```
POST   /audit-sets/{id}/fr233/generate           — CB planner: auto-generate pre-filled FR.233
                                                    from audit set data + committee members;
                                                    save to storage; attach as shared doc
GET    /audit-sets/{id}/fr233                    — get FR.233 record + signing status
POST   /audit-sets/{id}/fr233/sign/request       — committee member or CM: request visual sign
                                                    (places [SIG:COMMITTEE_CHAIR] etc. slots)
```

The generate endpoint calls the document filler with `FR233_MAP` and context:
```python
context = {
    "plan_number":            audit_set.plan_number,
    "company_name":           audit_set.company_name,
    "company_address":        audit_set.company_address,
    "standards_str":          ", ".join(audit_set.standards or []),
    "ea_code":                audit_set.ea_code,
    "audit_team_str":         build_team_string(audit_set),
    "stage_1_date":           format_date(stage1.start_date),
    "stage_2_date":           format_date(stage2.start_date),
    "stage_1_report_date":    ...,
    "stage_2_report_date":    ...,
    "decision_date":          date.today().isoformat(),
    "scope_en":               audit_set.scope_en,
    "committee_chair_name":   members[0].user_name if members else "",
    "committee_chair_ea":     members[0].ea_codes_at_appointment[0] if members else "",
    "committee_member1_name": members[1].user_name if len(members) > 1 else "",
    "committee_member1_ea":   ...,
    "committee_member2_name": members[2].user_name if len(members) > 2 else "",
    "committee_member2_ea":   ...,
}
```

### Frontend — Committee Signing Panel (CB Portal, Planner view)

Inside the audit set detail page, add a "Certification Committee" section that appears
when `workflow_status == "stage2_complete"` (or equivalent):

1. **Appoint committee members** — existing committee appointment UI from Portal 47.
   Each member must cover all required EA codes collectively.
2. **Generate FR.233** — "Generate Review & Decision Form" button → calls
   `POST /audit-sets/{id}/fr233/generate` → FR.233 appears in shared documents panel.
3. **Committee signing status** — shows each committee member as a row with name, EA,
   and signing status (signed / pending). Members sign through their own accounts
   (CB user portal, using the visual signature viewer).
4. **Certification Manager signs** — after all committee members have signed, a
   "Sign as Certification Manager" button appears for the CM user.
5. After CM signs → `workflow_status` advances to `certified`.

### Frontend — Committee Member Portal (individual CB user)

When a CB user who is a committee member opens the audit set in their portal, they see
a "FR.233 Review & Decision — Awaiting Your Signature" card. They can open the document
in the visual viewer and sign their slot (`[SIG:COMMITTEE_CHAIR]`,
`[SIG:COMMITTEE_MEMBER_1]`, or `[SIG:COMMITTEE_MEMBER_2]` depending on their row).

### Visibility Rules

- FR.233 document: CB staff only. Client and auditors cannot see it.
- Signing: committee members see only their own slot; they cannot see other members' tasks.

---

## Files to Touch

| File | Change |
|---|---|
| `backend/audit_set/db_models.py` | Add `ClientOrgEmployee`, `AuditSetFR233Record` models + migration |
| `backend/audit_set/field_maps.py` | `FR225_MAP` and `FR233_MAP` already updated — do NOT overwrite |
| `backend/audit_set/resolver.py` | FR.233 already added to Stage_2 + Surveillance — do NOT overwrite |
| `backend/audit_set/employee_router.py` | NEW — client employee roster CRUD |
| `backend/audit_set/committee_router.py` | Add FR.233 generate + sign endpoints |
| `backend/audit_set/viewer_router.py` | Add `ORG_OPENING_*` / `ORG_CLOSING_*` sig key handling |
| `backend/scripts/update_fr225_org_attendee_rows.py` | NEW — DOCX template updater script |
| `backend/main.py` | Mount `employee_router` |
| `frontend/src/app/(app)/client/employees/page.tsx` | NEW — employee roster page |
| `frontend/src/app/(app)/client/layout.tsx` | Add "Employees" nav link |
| `frontend/src/app/(app)/admin/audit-sets/[id]/page.tsx` | Add FR.233 committee section |

---

## Verification

1. Log in as client → navigate to Employees → add 2 employees, upload signature images.
2. Open an audit set that has an FR.225 generated → the document shows employee name/role
   rows in the Organisation Personnel section.
3. In the PDF viewer, click an `[SIG:ORG_OPENING_ORG_EMP_xxx]` cell → employee picker
   appears → select employee → signature image placed.
4. Log in as CB planner on a `stage2_complete` audit set → generate FR.233 → document
   appears in shared docs with committee member names pre-filled.
5. Log in as a committee member user → see FR.233 signing task → sign → signature placed.
6. Log in as Cert Manager → after all committee members signed, sign FR.233 →
   workflow advances to `certified`.
