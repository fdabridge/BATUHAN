# Portal 62 — Certification Committee: Auditor Pool Picker + FR.233 Dynamic Signing

## Context

After Stage 2, a certification committee reviews the full audit before the certificate
is issued. Currently the committee appointment UI shows ALL platform users — this is
wrong. Committee members are **auditors from the auditor pool** (same model as stage
auditors), selected so that collectively they cover the audit's standards and EA codes.

The committee signs FR.233 (Review and Decision Form). FR.233 currently has static
Chairperson/Member rows. This portal replaces them with a docxtpl loop generating one
row per selected committee member, each with a dynamic signature slot.

**What is already in place:**
- FR.233 templates exist in all blank set folders (all 6 files)
- `[SIG:CERT_MANAGER_REVIEW]` is already injected into the CM approval row (just committed)
- `document_type = "review_decision"` may already exist in the document pipeline
- Portal 49 built the basic committee appointment UI

**What needs to change:**
1. Committee picker → auditor pool with coverage validation
2. Store committee members on AuditSet (JSON array of auditor objects)
3. FR.233 template → dynamic committee rows via docxtpl
4. FR.233 packager → inject committee_members context
5. FR.233 viewer → COMMITTEE_MEMBER_RE signing

---

## Part A — Committee Picker: Replace All-Users List with Auditor Pool

### What the current picker does
Portal 49 built a committee appointment UI that lists all platform users. The planner
picks from this list. This is wrong — committee members must be auditors.

### What to build

**Backend — new endpoint: available committee members**

```
GET /audit-sets/{audit_set_id}/committee/available-auditors
```

Returns auditors from the pool who are qualified to serve on the committee for this
audit set. The response is the same structure as the auditor picker in stage planning:

```json
[
  {
    "id": "uuid",
    "full_name": "Ahmet Yıldız",
    "auditor_code": "AUD-001",
    "standards": ["ISO 9001", "ISO 14001"],
    "ea_codes": ["29", "30"],
    "covers_audit": true   // true if this auditor covers at least one of the audit's standards/EA codes
  }
]
```

Filter: all active auditors in the `auditors` table. Sort: those with `covers_audit=true`
first.

Coverage check per auditor: `auditor.standards` intersects `audit_set.standards` AND
`auditor.ea_codes` intersects `audit_set.ea_codes`.

**Backend — committee appointment endpoint**

```
POST /audit-sets/{audit_set_id}/committee/appoint
Body: {
  "chairperson_id": "auditor-uuid",
  "member_ids": ["auditor-uuid-1", "auditor-uuid-2"]
}
```

Validation: the chairperson + all members together must collectively cover ALL standards
and ALL EA codes of the audit set. If not, return 422 with a message like:
`"Missing coverage: ISO 45001 (EA code 34) — no committee member is qualified"`

Store on `AuditSet`:
```python
audit_set.committee_chairperson_id = body.chairperson_id
audit_set.committee_member_ids     = body.member_ids   # JSON array
# Or denormalized:
audit_set.committee_members = [   # JSON array of full auditor objects
    {"id": ..., "name": ..., "ea_codes": [...], "standards": [...], "role": "chairperson"},
    {"id": ..., "name": ..., "ea_codes": [...], "standards": [...], "role": "member"},
    ...
]
```

Use the denormalized version (store full auditor details) so FR.233 packager can render
the form without additional DB queries.

**If `AuditSet` doesn't have a `committee_members` column:**

Add it via `_safe_add_column`:
```python
_safe_add_column("audit_sets", "committee_members", "TEXT")
# Store as JSON string, parse with json.loads on read
```

**Frontend — replace the committee picker**

In the committee appointment page (Portal 49's UI), replace the current all-users list
with an auditor picker that mirrors the auditor team picker in stage planning:

- Left panel: available auditors from `GET /audit-sets/{id}/committee/available-auditors`
  - Show: name, auditor code, standards covered, EA codes
  - Badge "✓ covers audit" if `covers_audit=true`
  - Search/filter by name or standard
- Right panel: selected committee
  - First selected = Chairperson (label it clearly)
  - Additional selections = Members
  - Coverage indicator: show which standards/EA codes are covered by current selection
  - Warn if any standard or EA code is uncovered
- "Confirm Committee" button: calls `POST /committee/appoint`
  - Disabled if coverage is incomplete

---

## Part B — FR.233 Template: Dynamic Committee Rows

### Current structure

FR.233 committee signing table (rows 30-33):
- Row 30: Header — `Name Surname | EA/IAF Code / Category/Technical Area | Sign`
- Row 31: `Chairperson | (empty) | (empty)` ← fixed
- Row 32: `Member | (empty) | (empty)` ← fixed
- Row 33: `Member | (empty) | (empty)` ← fixed
- (Row 34: empty/spacer)
- Row 35: `To Endorse the Decision on Behalf of IFC GLOBAL LLC`
- Row 36: `Certification Manager Approval | Sign` ← already has `[SIG:CERT_MANAGER_REVIEW]`

### What to build

Replace rows 31-33 (fixed Chairperson/Member rows) with a docxtpl `{%tr for %}` loop.

**Use python-docx to transform all 6 FR.233 templates:**

```python
import zipfile, os, subprocess
from lxml import etree
from copy import deepcopy

NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
W  = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'

# For each FR.233 file:
# 1. Find the table containing the "Chairperson" row
# 2. Identify rows 31 (Chairperson), 32 (Member), 33 (Member)
# 3. Remove rows 32 and 33 (keep only one template row)
# 4. Transform row 31 into the docxtpl loop template row:
#    - Insert {%tr for member in committee_members %} control row BEFORE row 31
#    - Replace row 31 cell content:
#       col 0: "{% if loop.first %}Chairperson{% else %}Member{% endif %}\n{{ member.name }}"
#       col 1: "{{ member.ea_codes }}"
#       col 2: "[SIG:COMMITTEE_MEMBER_{{ member.id }}]"
#    - Insert {%tr endfor %} control row AFTER row 31
```

The docxtpl control rows (`{%tr for ... %}` and `{%tr endfor %}`) must be table rows
with a single paragraph containing ONLY the control tag — no other text. docxtpl strips
these rows from the output; they are not visible in the rendered document.

Example XML structure for control row:
```xml
<w:tr>
  <w:tc>
    <w:tcPr><w:tcW w:w="0" w:type="auto"/></w:tcPr>
    <w:p><w:r><w:t>{%tr for member in committee_members %}</w:t></w:r></w:p>
  </w:tc>
</w:tr>
```

After transformation, row 31 should look like:
```
cell 0 text: {% if loop.first %}Chairperson{% else %}Member{% endif %}
             {{ member.name }}
cell 1 text: {{ member.ea_codes_str }}
cell 2 text: [SIG:COMMITTEE_MEMBER_{{ member.id }}]
```

**Write a Python script** (in `backend/scripts/` or inline in the commit) that does
this transformation for all 6 FR.233 files. Run it once, commit the patched files.

Files:
- `backend/uaf_blank_set/27001/Initial Certification/Stage 2/FR.233 Review And Decision Form R5&09.10.2025.docx`
- `backend/uaf_blank_set/27001/Surveillance/FR.233 Review And Decision Form R5&09.10.2025.docx`
- `backend/uaf_blank_set/9-14-45-22-5001/Initial Certification /Stage 2/FR.233 Review And Decision Form R5&09.10.2025.docx`
- `backend/uaf_blank_set/9-14-45-22-5001/Surveillance/FR.233 Review And Decision Form R5&09.10.2025.docx`
- `backend/uaf_blank_set/13485/Initial Certification /Stage 2/FR.233 Review And Decision Form R5&09.10.2025.docx`
- `backend/uaf_blank_set/13485/Surveillance/FR.233 Review And Decision Form R5&09.10.2025.docx`

---

## Part C — FR.233 Packager: Inject Committee Members

**File:** `backend/audit_set/packager.py`

When generating FR.233, inject `committee_members` context:

```python
committee_raw = audit_set.committee_members  # JSON string from DB
committee = json.loads(committee_raw) if committee_raw else []

# Build context list for docxtpl
committee_ctx = [
    {
        "id":            m["id"],
        "name":          m["name"],
        "ea_codes_str":  ", ".join(m.get("ea_codes", [])),
        "role":          m["role"],  # "chairperson" or "member"
    }
    for m in committee
]

# Sort: chairperson first
committee_ctx.sort(key=lambda x: 0 if x["role"] == "chairperson" else 1)

FR233_CONTEXT = {
    **existing_fr233_fields,
    "committee_members": committee_ctx,
}
```

If `committee_members` is empty (committee not yet appointed), use 3 blank placeholders
so the template loop still renders readable rows:
```python
if not committee_ctx:
    committee_ctx = [
        {"id": f"BLANK_{i}", "name": "", "ea_codes_str": "", "role": "member"}
        for i in range(3)
    ]
```

---

## Part D — Viewer: COMMITTEE_MEMBER_RE Signing

**File:** `backend/audit_set/viewer_router.py`

### D1 — Add regex

```python
COMMITTEE_MEMBER_RE = re.compile(r'^COMMITTEE_MEMBER_(.+)$')
```

### D2 — Eligibility in `_shared_slot_eligible`

```python
m = COMMITTEE_MEMBER_RE.match(sig_key)
if m:
    member_id = m.group(1)
    if member_id.startswith("BLANK_"):
        return False  # placeholder row, not signable
    if current_user.role != "auditor" or not current_user.auditor_id:
        return False
    # Check this auditor is the committee member for this slot
    return current_user.auditor_id == member_id
```

### D3 — Status in `_get_field_status`

```python
m = COMMITTEE_MEMBER_RE.match(sig_key)
if m:
    member_id = m.group(1)
    if member_id.startswith("BLANK_"):
        return _result("pending", label="Awaiting committee appointment")
    if vsp and vsp.signed_at:
        return _result("signed", vsp.signature_image)
    if _shared_slot_eligible(sig_key, doc, current_user, db):
        return _result("current_user")
    # Resolve display name from committee_members on the AuditSet
    audit_set = db.query(AuditSet).filter_by(id=doc.audit_set_id).first()
    label = member_id  # fallback
    if audit_set and audit_set.committee_members:
        members = json.loads(audit_set.committee_members)
        member = next((x for x in members if x["id"] == member_id), None)
        if member:
            role_label = "Chairperson" if member["role"] == "chairperson" else "Member"
            label = f"{role_label} — {member['name']}"
    return _result("pending", label=label)
```

### D4 — No ordering gate

Committee members can all sign in parallel — no `_prior_slots_unsigned` blocking.
The CM signs `CERT_MANAGER_REVIEW` after all committee members sign (enforce this
in the workflow gate, not the viewer).

---

## Part E — Workflow Gate: All Committee Members Must Sign Before CM

**File:** `backend/audit_set/workflow_router.py`

When advancing from `committee_review` to `certification_decision`:

```python
# All COMMITTEE_MEMBER_* slots in the FR.233 document must be signed
fr233_doc = _get_doc(db, audit_set_id, "review_decision")
if fr233_doc:
    unsigned = db.query(VisualSignaturePlacement).filter(
        VisualSignaturePlacement.document_id == fr233_doc.id,
        VisualSignaturePlacement.sig_key.like("COMMITTEE_MEMBER_%"),
        VisualSignaturePlacement.signed_at == None,
    ).count()
    if unsigned > 0:
        raise HTTPException(400, f"{unsigned} committee member(s) have not signed FR.233")
```

---

## Files to change

| File | Change |
|------|--------|
| `backend/audit_set/audit_set_router.py` | Add `GET /committee/available-auditors` endpoint with coverage check |
| `backend/audit_set/audit_set_router.py` | Add `POST /committee/appoint` with coverage validation; store `committee_members` JSON on AuditSet |
| `backend/auth/db_models.py` | `_safe_add_column("audit_sets", "committee_members", "TEXT")` |
| `backend/audit_set/packager.py` | Inject `committee_members` context into FR.233 generation |
| `backend/audit_set/viewer_router.py` | `COMMITTEE_MEMBER_RE`; eligibility + status blocks; `CERT_MANAGER_REVIEW` eligibility |
| `backend/audit_set/workflow_router.py` | Gate: all `COMMITTEE_MEMBER_*` signed before CM can endorse |
| `backend/uaf_blank_set/**/FR.233 *.docx` | Dynamic committee rows via docxtpl loop (script to run + commit) |
| `frontend/.../committee/page.tsx` | Replace all-users list with auditor pool picker + coverage validation UI |

---

## Commit message

```
Portal 62: certification committee — auditor pool picker + FR.233 dynamic signing

Committee members are auditors from the auditor pool, not all platform users.
Selected team must collectively cover the audit's standards and EA codes.

- audit_set_router: GET /committee/available-auditors (auditor pool, coverage flag)
- audit_set_router: POST /committee/appoint (coverage validation, store JSON on audit_set)
- db_models: audit_sets.committee_members TEXT column (JSON)
- packager: inject committee_members into FR.233 context; blank placeholders if not yet appointed
- viewer_router: COMMITTEE_MEMBER_RE — eligibility (auditor_id match), status (signed/current_user/pending with name)
- viewer_router: CERT_MANAGER_REVIEW — eligibility: certification_manager role
- workflow_router: committee_review -> certification_decision gate checks all COMMITTEE_MEMBER_* are signed
- FR.233 templates (x6): Chairperson/Member static rows replaced with docxtpl loop;
  each row: {{ member.name }}, {{ member.ea_codes_str }}, [SIG:COMMITTEE_MEMBER_{{ member.id }}]
- Frontend committee picker: auditor pool list with coverage indicator, chairperson = first selected
```
