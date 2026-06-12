# Portal 49a — Part 2 SUPPLEMENT: FR.225 Template Engine Clarification

This supplement answers the exact blocker Augment raised for Part 2.
Read this alongside the original `AUGMENT_PROMPT_portal_49a_roster_fr225_fr233.md`.

---

## Blocker Answer: The template engine is docxtpl (Jinja2-for-Word)

**Confirmed from `backend/audit_set/filler.py` line 23:**
```python
from docxtpl import DocxTemplate
```

**Confirmed render path (`filler.py` line ~535):**
```python
def render_docx(template_path: str | Path, context: dict) -> bytes:
    doc = DocxTemplate(template_path)
    doc.render(context)
    ...
    return buf.getvalue()
```

All DOCX templates use Jinja2 syntax (`{{ variable }}`, `{%tr for x in list %}`, etc.).
The FR.225 template's auditor rows already use `{%tr if auditors|length > 0 %}` loops —
the org attendee rows need the same treatment.

---

## Where to add `org_attendees` to the filler context

In `filler.py`, the render context is built inside `_build_render_context()`.
Around line 396, you'll find:
```python
"auditors":          stage.auditors or [],
"technical_experts": stage.technical_experts or [],
```

Add `org_attendees` in the same block:
```python
"org_attendees": _build_org_attendees(audit_set.id, db),
```

The helper function (add near the other context helpers in filler.py):
```python
def _build_org_attendees(audit_set_id: str, db: Session) -> list[dict]:
    """Return org employee list for FR.225 docxtpl loop."""
    from audit_set.db_models import AuditSet, ClientOrgEmployee
    audit_set = db.query(AuditSet).filter_by(id=audit_set_id).first()
    if not audit_set or not audit_set.client_user_id:
        return []
    employees = db.query(ClientOrgEmployee).filter_by(
        client_user_id=audit_set.client_user_id, is_active=True
    ).order_by(ClientOrgEmployee.created_at).all()
    return [
        {
            "name":    e.full_name,
            "role":    e.role_title,
            "sig_key": f"ORG_EMP_{e.id}",
        }
        for e in employees
    ]
```

> **Note:** `org_attendees` is only used by FR.225. It's fine to add it to the general
> context — it's just an empty list for all other forms.

---

## What the FR.225 template currently looks like (Table 2)

Run this to inspect the actual rows before editing:
```bash
cd /path/to/project
python3 - <<'EOF'
from docx import Document
import glob

files = glob.glob("uaf_blank_set copy/**/FR.225*.docx", recursive=True)
for path in files[:1]:
    doc = Document(path)
    t = doc.tables[2]
    for i, row in enumerate(t.rows):
        texts = [c.text.strip()[:40] for c in row.cells]
        print(f"  row {i}: {texts}")
    break
EOF
```

Expected output:
```
row 0: ['Organization Personnel', '', '', '']
row 1: ['Participant', 'Role', 'Opening Signature', 'Closing Signature']
row 2: ['', '', '', '']   ← static blank — REPLACE these 4
row 3: ['', '', '', '']
row 4: ['', '', '', '']
row 5: ['', '', '', '']
row 6: ['Audit Team', '', '', '']
row 7: ['{{ lead_auditor_name }}', 'Lead Auditor', '', '']
row 8: ...  ← existing Jinja2 auditor/TE loops — DO NOT TOUCH
```

---

## The script: `backend/scripts/update_fr225_org_attendee_rows.py`

This script **replaces rows 2–5** (the 4 static blank org attendee rows) with a
3-row docxtpl loop block. Run once; commit the modified templates.

```python
#!/usr/bin/env python3
"""
Replace the 4 static blank org-attendee rows in every FR.225 template
with a docxtpl {%tr for emp in org_attendees %} loop.

Run from the project root:
    python backend/scripts/update_fr225_org_attendee_rows.py
"""
import copy
import glob
from pathlib import Path
from lxml import etree
from docx import Document
from docx.oxml.ns import qn

SEARCH_ROOTS = [
    "uaf_blank_set copy",
    "backend/uaf_blank_set",
]


def _cell_text(cell, text: str):
    """Clear a cell and set its text, preserving paragraph style."""
    para = cell.paragraphs[0]
    for run in para.runs:
        run.text = ""
    if para.runs:
        para.runs[0].text = text
    else:
        para.add_run(text)


def _remove_rows(table, start_idx: int, count: int):
    """Remove `count` rows starting at index `start_idx` from a table."""
    tbl = table._tbl
    rows = tbl.findall(qn("w:tr"))
    for row in rows[start_idx : start_idx + count]:
        tbl.remove(row)


def _insert_row_after(table, after_idx: int, source_row_xml):
    """Insert a copied row element after row index `after_idx`."""
    tbl = table._tbl
    rows = tbl.findall(qn("w:tr"))
    ref_row = rows[after_idx]
    new_row = copy.deepcopy(source_row_xml)
    ref_row.addnext(new_row)


def process_file(docx_path: str) -> bool:
    path = Path(docx_path)
    doc = Document(docx_path)

    # FR.225 participants table is always table index 2
    if len(doc.tables) < 3:
        print(f"  SKIP (fewer than 3 tables): {path.name}")
        return False

    table = doc.tables[2]
    rows = table.rows

    # Sanity check: rows 2-5 should be blank and row 6 should be "Audit Team"
    if len(rows) < 8:
        print(f"  SKIP (too few rows in table 2): {path.name}")
        return False

    row6_text = rows[6].cells[0].text.strip().lower()
    if "audit team" not in row6_text and "denetim" not in row6_text:
        print(f"  SKIP (row 6 is not 'Audit Team'): {path.name} → '{row6_text}'")
        return False

    # Use row 7 (lead auditor content row) as the XML template for the content row
    content_row_xml = copy.deepcopy(rows[7]._tr)
    # Use row 1 (column header row) style for structural reference
    header_row_xml  = copy.deepcopy(rows[1]._tr)

    # Remove rows 2–5 (4 static blank rows)
    _remove_rows(table, 2, 4)

    # After removal, row 6 (Audit Team separator) is now at index 2.
    # We insert three new rows BEFORE it (i.e., after the header row at index 1).
    # Insert in reverse order so each addnext lands correctly.

    # Row C — loop end: {%tr endfor %}
    row_c = copy.deepcopy(header_row_xml)
    cells_c = row_c.findall(".//" + qn("w:tc"))
    for i, tc in enumerate(cells_c):
        for p in tc.findall(qn("w:p")):
            for r in p.findall(qn("w:r")):
                for t in r.findall(qn("w:t")):
                    t.text = "{%tr endfor %}" if i == 0 else ""

    # Row B — content: {{ emp.name }} | {{ emp.role }} | sig | sig
    row_b = copy.deepcopy(content_row_xml)
    cells_b = row_b.findall(".//" + qn("w:tc"))
    content_values = [
        "{{ emp.name }}",
        "{{ emp.role }}",
        "[SIG:ORG_OPENING_{{ emp.sig_key }}]",
        "[SIG:ORG_CLOSING_{{ emp.sig_key }}]",
    ]
    for i, tc in enumerate(cells_b[:4]):
        for p in tc.findall(qn("w:p")):
            for r in p.findall(qn("w:r")):
                for t in r.findall(qn("w:t")):
                    t.text = content_values[i] if i < len(content_values) else ""

    # Row A — loop start: {%tr for emp in org_attendees %}
    row_a = copy.deepcopy(header_row_xml)
    cells_a = row_a.findall(".//" + qn("w:tc"))
    for i, tc in enumerate(cells_a):
        for p in tc.findall(qn("w:p")):
            for r in p.findall(qn("w:r")):
                for t in r.findall(qn("w:t")):
                    t.text = "{%tr for emp in org_attendees %}" if i == 0 else ""

    # After removal, the header row is at index 1. Insert after it:
    tbl = table._tbl
    current_rows = tbl.findall(qn("w:tr"))
    header_row_element = current_rows[1]
    # Insert C, then B, then A after header (each addnext pushes the previous down)
    header_row_element.addnext(row_c)
    header_row_element.addnext(row_b)
    header_row_element.addnext(row_a)

    doc.save(docx_path)
    print(f"  UPDATED: {docx_path}")
    return True


def main():
    updated = 0
    skipped = 0
    for root in SEARCH_ROOTS:
        pattern = f"{root}/**/FR.225*.docx"
        files = glob.glob(pattern, recursive=True)
        for f in sorted(files):
            if "~$" in f:
                continue
            result = process_file(f)
            if result:
                updated += 1
            else:
                skipped += 1
    print(f"\nDone. Updated: {updated}, Skipped: {skipped}")


if __name__ == "__main__":
    main()
```

### How to run it

```bash
cd /path/to/certiva-project-root
pip install python-docx lxml --break-system-packages
python backend/scripts/update_fr225_org_attendee_rows.py
```

After running, open one of the updated templates in Word and verify:
- Table 2 should show `{%tr for emp in org_attendees %}` / content row / `{%tr endfor %}`
- The Audit Team separator row is still in place below
- Existing auditor/TE rows below are untouched

Then commit the modified templates:
```bash
git add "uaf_blank_set copy/" backend/uaf_blank_set/
git commit -m "feat: update FR.225 templates with org_attendees docxtpl loop"
```

---

## Viewer: handling `ORG_OPENING_*` and `ORG_CLOSING_*` signature keys

In `viewer_router.py`, extend `_assert_can_sign` (or the signature key dispatch logic)
to handle patterns like `ORG_OPENING_ORG_EMP_{uuid}` and `ORG_CLOSING_ORG_EMP_{uuid}`:

```python
import re as _re

ORG_SIG_RE = _re.compile(
    r"^ORG_(OPENING|CLOSING)_ORG_EMP_([0-9a-f-]{36})$", _re.IGNORECASE
)

def _check_org_employee_sig(sig_key: str, current_user, db: Session) -> bool:
    """Returns True if current_user (client) may sign this org employee slot."""
    m = ORG_SIG_RE.match(sig_key)
    if not m:
        return False
    if current_user.role != "client":
        return False
    employee_id = m.group(2)
    from audit_set.db_models import ClientOrgEmployee
    emp = db.query(ClientOrgEmployee).filter_by(
        id=employee_id, is_active=True
    ).first()
    if emp is None:
        return False
    # Employee must belong to this client
    return emp.client_user_id == current_user.id
```

When the client signs, place the **employee's saved signature image** (from
`storage/org_employee_signatures/{employee_id}.png`) at the signature slot —
not the client user's own signature. This is the key difference from other slots.

```python
def _get_signature_for_org_emp_slot(sig_key: str, db: Session) -> bytes | None:
    m = ORG_SIG_RE.match(sig_key)
    if not m:
        return None
    employee_id = m.group(2)
    from audit_set.db_models import ClientOrgEmployee
    emp = db.query(ClientOrgEmployee).filter_by(id=employee_id).first()
    if emp is None or not emp.signature_path:
        return None
    sig_path = Path(emp.signature_path)
    return sig_path.read_bytes() if sig_path.exists() else None
```

---

## Summary of what Part 2 needs to touch

| File | Change |
|---|---|
| `backend/audit_set/filler.py` | Add `_build_org_attendees()` helper; add `"org_attendees": _build_org_attendees(...)` to context |
| `backend/audit_set/viewer_router.py` | Add `ORG_SIG_RE` pattern; `_check_org_employee_sig()`; `_get_signature_for_org_emp_slot()` |
| `backend/scripts/update_fr225_org_attendee_rows.py` | NEW script (content above) |
| `uaf_blank_set copy/**/FR.225*.docx` | Run the script to update templates |
| `backend/uaf_blank_set/**/FR.225*.docx` | Same (script covers both) |

**Do NOT modify** `field_maps.py` or `resolver.py` — they are already correct.
