# Augment Prompt — Fix Audit Type + Standard Checkboxes in All Templates

## Problem

Two separate checkbox problems exist in the templates:

### Problem A — Audit Type (FR.232, FR.229, FR.231): Broken Jinja2 FORMCHECKBOX
FR.232 contains this broken pattern (both branches output identical text):
```
{{ " FORMCHECKBOX " if is_initial else " FORMCHECKBOX " }}
{{ " FORMCHECKBOX " if is_surveillance else " FORMCHECKBOX " }}
{{ " FORMCHECKBOX " if is_recertification else " FORMCHECKBOX " }}
{{ " FORMCHECKBOX " if is_special else " FORMCHECKBOX " }}
```
Since both branches output `" FORMCHECKBOX "`, the condition is ignored. Word sees the literal text "FORMCHECKBOX" and renders it strangely (underlined, or as garbled text). The intent was to show a checked/unchecked state based on the audit type.

**Fix:** Replace these with proper Unicode checkbox characters:
```
{{ "☑" if is_initial else "☐" }}
{{ "☑" if is_surveillance else "☐" }}
{{ "☑" if is_recertification else "☐" }}
{{ "☑" if is_special else "☐" }}
```

### Problem B — Standards table (FR.220, FR.221): Word form checkboxes never filled
FR.220 and FR.221 have DOCX legacy form field checkboxes (`<w:fldSimple w:instr=" FORMCHECKBOX ">`) next to each standard name. docxtpl cannot fill these. The selected standards are in the `standards` context variable (list of codes like `["QMS", "EMS"]`).

**Fix:** Use python-docx/lxml after rendering to set the correct checked state for each standard's checkbox.

---

## What to Do

### Step 1 — Fix FR.232 (all copies: base + MDQMS)

Write a Python script that uses `zipfile` + `lxml` to:
1. Unzip `word/document.xml`
2. Find `<w:t>` elements containing `FORMCHECKBOX` that are inside Jinja2 expressions
3. Replace the broken pattern with the correct Unicode checkbox expression

The text to find and replace in the XML `<w:t>` content:

| Find (raw text in `<w:t>`) | Replace with |
|---|---|
| `{{ " FORMCHECKBOX " if is_initial else " FORMCHECKBOX " }}` | `{{ "☑" if is_initial else "☐" }}` |
| `{{ " FORMCHECKBOX " if is_surveillance else " FORMCHECKBOX " }}` | `{{ "☑" if is_surveillance else "☐" }}` |
| `{{ " FORMCHECKBOX " if is_recertification else " FORMCHECKBOX " }}` | `{{ "☑" if is_recertification else "☐" }}` |
| `{{ " FORMCHECKBOX " if is_special else " FORMCHECKBOX " }}` | `{{ "☑" if is_special else "☐" }}` |
| `{{ " FORMCHECKBOX " if is_ s urveillance else " FORMCHECKBOX " }}` | `{{ "☑" if is_surveillance else "☐" }}` |
| `{{ " FORMCHECKBOX " if is_ special else " FORMCHECKBOX " }}` | `{{ "☑" if is_special else "☐" }}` |

Note: split-run merging may be needed first (the `is_surveillance` tag may be split as `is_ s urveillance`). Use the existing run-merger utility or a simple XML text search across the full document string.

**Approach:** Do a string replacement on the raw `document.xml` text (after removing `<w:proofErr>` elements and merging split runs in the relevant paragraphs), then re-zip.

Files to fix:
- `backend/uaf_blank_set/9-14-45-22-5001/Initial Certification /Stage 2/FR.232_Audit_Report_R12&09.10.2025.docx`
- `backend/uaf_blank_set/9-14-45-22-5001/Surveillance/FR.232_Audit_Report_R12&09.10.2025.docx`
- `backend/uaf_blank_set/13485/Initial Certification /Stage 2/FR.232-1_MD-QMS Audit Report R01&09.10.2025.docx`
- `backend/uaf_blank_set/13485/Surveillance/FR.232-1_MD-QMS Audit Report R01&09.10.2025.docx`

Also check FR.231 (Stage 1 Report) for the same FORMCHECKBOX pattern. If present, apply the same fix. Check all copies:
- `backend/uaf_blank_set/9-14-45-22-5001/Initial Certification /Stage 1/FR.231_Stage1_Report_R9&09.10.2025.docx`
- `backend/uaf_blank_set/13485/Initial Certification /Stage 1/FR.231-1_MDQMS_Stage1_Report_R4&09.10.2025.docx`

Also check FR.229 for FORMCHECKBOX. It didn't show them in the Jinja2 extraction but verify. File:
- `backend/uaf_blank_set/27001/Initial Certification/Stage 2/FR.229_ISMS_PIMS_Audit_Report_R8&10.06.2024.docx`
- `backend/uaf_blank_set/27001/Surveillance/FR.229_ISMS_PIMS_Audit_Report_R8&10.06.2024.docx`

---

### Step 2 — Fix FR.220 and FR.221 standard checkboxes (post-render approach)

Create a new file `backend/audit_set/postprocess.py`:

```python
"""
Post-render fixups for DOCX templates that contain Word form fields
which docxtpl cannot fill directly.
"""
from __future__ import annotations
import io, zipfile, re
from lxml import etree

NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{NS}}}"

# Map: standard code → the standard name as it appears in the template cell
STANDARD_CELL_TEXT = {
    "QMS":   "ISO 9001:2015",
    "EMS":   "ISO 14001:2015",
    "OHSMS": "ISO 45001:2018",
    "FSMS":  "ISO 22000:2018",
    "ISMS":  "ISO/IEC 27001:2022",
    "ENMS":  "ISO 50001:2018",
    "MDQMS": "ISO 13485:2016",
    "ABMS":  "ISO 37001:2016",
}

def _get_cell_text(tc_elem) -> str:
    """Extract all text from a table cell element."""
    return "".join(t.text or "" for t in tc_elem.iter(f"{W}t"))


def apply_standard_checkboxes(docx_bytes: bytes, standards_codes: list[str]) -> bytes:
    """
    Post-render fix for FR.220 and FR.221.
    Finds each standard's cell in the standards table, then finds the
    <w:checkBox> element next to it and sets checked=1 if the standard
    is in standards_codes, 0 otherwise.
    
    Falls back to replacing checkbox character (☐→☑) if <w:checkBox> not found.
    """
    buf = io.BytesIO(docx_bytes)
    out = io.BytesIO()
    
    with zipfile.ZipFile(buf, 'r') as zin, zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == 'word/document.xml':
                data = _fix_checkboxes_in_xml(data, standards_codes)
            zout.writestr(item, data)
    
    return out.getvalue()


def _fix_checkboxes_in_xml(xml_bytes: bytes, standards_codes: list[str]) -> bytes:
    tree = etree.fromstring(xml_bytes)
    
    # Strategy 1: Find <w:checkBox> elements and set their <w:default> value.
    # Each checkbox is in a cell adjacent to the standard name cell.
    # We find cells containing standard names and check the neighboring checkbox cell.
    for tc in tree.iter(f"{W}tc"):
        cell_text = _get_cell_text(tc)
        # Find which standard this cell corresponds to
        matched_code = None
        for code, name in STANDARD_CELL_TEXT.items():
            if name in cell_text or cell_text.strip() == name:
                matched_code = code
                break
        if not matched_code:
            continue
        
        is_selected = matched_code in standards_codes
        
        # Look for <w:checkBox> in this cell or its parent row's adjacent cell
        checkboxes = tc.findall(f".//{W}checkBox")
        if checkboxes:
            for cb in checkboxes:
                default = cb.find(f"{W}default")
                if default is None:
                    default = etree.SubElement(cb, f"{W}default")
                default.set(f"{W}val", "1" if is_selected else "0")
            continue
        
        # Strategy 2: Replace ☐ with ☑ (or vice versa) in text elements
        for t_elem in tc.iter(f"{W}t"):
            txt = t_elem.text or ""
            if "☐" in txt or "☑" in txt:
                if is_selected:
                    t_elem.text = txt.replace("☐", "☑")
                else:
                    t_elem.text = txt.replace("☑", "☐")
    
    return etree.tostring(tree, xml_declaration=True, encoding='UTF-8', standalone=True)
```

Then in `backend/audit_set/packager.py`, import this and apply it after rendering FR.220 and FR.221:

```python
from audit_set.postprocess import apply_standard_checkboxes

# In the render loop, after render_docx():
if fr_number in ("FR.220", "FR.221"):
    rendered_bytes = apply_standard_checkboxes(rendered_bytes, audit_set.standards or [])
```

Where `fr_number` is the FR prefix of the current template file being rendered (extract from filename with a regex: `re.match(r'(FR\.\d+)', filename)`).

---

### Step 3 — Add `is_surveillance` to context (currently missing)

In `filler.py`, `is_surveillance` is defined as:
```python
is_surveillance = audit_type.startswith("surveillance")
```

This is correct. But the FR.232 template (from the extraction) had a split-run creating `is_ s urveillance` — that's a run-merge issue in the template, not a context issue. The template fix in Step 1 handles this.

Also ensure `is_special` is in the context:
```python
"is_special": is_special,   # should already be there
```

Verify `is_surveillance`, `is_recertification`, `is_initial`, `is_special` are all exported in the return dict of `build_base_context()`. Add any that are missing.

---

### Step 4 — Verify and commit

After making all changes:

```bash
# Quick render test
cd backend
python3 -c "
from audit_set.filler import render_docx
from pathlib import Path
import json

# Simple context with is_initial=True, standards=['QMS']
ctx = {
    'is_initial': True, 'is_surveillance': False,
    'is_recertification': False, 'is_special': False,
    'standards': ['QMS'], 'plan_number': 9999,
    'company_name': 'Test', 'company_address': 'Test Addr',
    'phone': '', 'email': '', 'initial_fee': '', 'surveillance_fee': '',
}
p = Path('uaf_blank_set/9-14-45-22-5001/Initial Certification /Stage 2/FR.232_Audit_Report_R12&09.10.2025.docx')
b = render_docx(p, ctx)
print('FR.232 rendered OK:', len(b), 'bytes')
with open('/tmp/test_fr232.docx', 'wb') as f: f.write(b)
print('Saved to /tmp/test_fr232.docx')
"
```

Then git add + commit:
```bash
git add backend/uaf_blank_set/ backend/audit_set/postprocess.py backend/audit_set/packager.py
git commit -m "fix: checkbox rendering — FORMCHECKBOX→☑/☐ in FR.232/231, post-render standard selection for FR.220/221"
git push
```
