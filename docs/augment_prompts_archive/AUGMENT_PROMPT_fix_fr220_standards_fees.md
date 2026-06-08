# Fix FR.220: Standards Visual Marking, Currency Symbol, Audit Type Checkbox

## Context

FR.220 (Quotation/Offer form) has three problems visible in a rendered document:

1. **Standards table (4×2 grid):** All 8 possible standards are listed as plain text. For an audit with only ISO 9001 + ISO 14001 + ISO 45001, there is NO visual indicator of which standards are selected. The user cannot tell from the document which standards apply.

2. **Fees table:** Fees show as `500.0` and `300.0` — raw Python floats with no currency symbol. Should be `$500` or `USD 500`.

3. **Audit Type table:** Contains cells "Initial Certification / Surveillance" and "Recertification" with no indicator of which applies to this audit.

The render context in `audit_set/filler.py` already provides:
- `qms_selected`, `ems_selected`, `ohsms_selected`, `fsms_selected`, `isms_selected`, `mdqms_selected`, `abms_selected`, `enms_selected` (booleans)
- `is_initial`, `is_surveillance`, `is_recertification` (booleans)
- `certification_fee`, `surveillance_fee` (floats or `""`)

A `postprocess.py` may exist in `audit_set/` — check it. If it has `apply_standard_checkboxes()`, verify it is actually being called from `packager.py` or wherever FR.220 is rendered.

## Task

### Step 1 — Inspect FR.220 template XML to understand the standards table structure

```bash
cd backend
python3 - <<'EOF'
import zipfile, re

path = "uaf_blank_set/FR.220 Quotation Form.docx"
with zipfile.ZipFile(path) as z:
    xml = z.read("word/document.xml").decode("utf-8", errors="replace")

# Print all Jinja2 expressions
for e in re.findall(r'\{\{.*?\}\}|\{%.*?%\}', xml):
    print(e)

# Find the standards table — look for cells containing standard names
import re as _re
cells = _re.findall(r'<w:tc>.*?</w:tc>', xml, _re.DOTALL)
for i, cell in enumerate(cells):
    if 'ISO' in cell or 'Jinja' in cell or '{{' in cell:
        print(f"\n--- Cell {i} ---")
        print(cell[:500])
EOF
```

Note: the template path might differ. Check `uaf_blank_set/` for the exact FR.220 filename.

### Step 2 — Fix the standards table: shade selected standard cells

Use lxml post-processing after docxtpl renders FR.220. The approach: find the table cell containing each standard name, and if that standard is selected, add a blue/green background shading element (`<w:shd w:val="clear" w:color="auto" w:fill="BFDFBF"/>` — light green).

Add or update `apply_standard_highlighting(docx_bytes: bytes, standards_codes: list) -> bytes` in `audit_set/postprocess.py`:

```python
from lxml import etree
import io
import zipfile
import shutil

NSMAP = {
    'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
}

# Map short code → full ISO name as it appears in the FR.220 template
STANDARD_CELL_TEXT = {
    "QMS":   "ISO 9001",
    "EMS":   "ISO 14001",
    "OHSMS": "ISO 45001",
    "FSMS":  "ISO 22000",
    "ISMS":  "ISO/IEC 27001",
    "MDQMS": "ISO 13485",
    "ABMS":  "ISO 37001",
    "ENMS":  "ISO 50001",
}

SELECTED_FILL = "A8D5A2"   # light green — stands out clearly, print-friendly
UNSELECTED_FILL = "FFFFFF"  # plain white for non-selected

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _get_cell_text(tc_elem) -> str:
    """Extract all text from a table cell element."""
    return "".join(
        t.text or "" for t in tc_elem.iter(f"{{{W}}}t")
    )


def _set_cell_shading(tc_elem, fill_hex: str):
    """Add or update <w:shd> background color on a table cell's <w:tcPr>."""
    tcPr = tc_elem.find(f"{{{W}}}tcPr")
    if tcPr is None:
        tcPr = etree.SubElement(tc_elem, f"{{{W}}}tcPr")
        tc_elem.insert(0, tcPr)

    shd = tcPr.find(f"{{{W}}}shd")
    if shd is None:
        shd = etree.SubElement(tcPr, f"{{{W}}}shd")

    shd.set(f"{{{W}}}val", "clear")
    shd.set(f"{{{W}}}color", "auto")
    shd.set(f"{{{W}}}fill", fill_hex)


def apply_standard_highlighting(docx_bytes: bytes, standards_codes: list) -> bytes:
    """
    Post-process FR.220 DOCX bytes to shade selected standards green.
    Works by scanning every table cell for ISO standard name substrings.
    """
    buf = io.BytesIO(docx_bytes)

    with zipfile.ZipFile(buf, "r") as zin:
        names = zin.namelist()
        contents = {name: zin.read(name) for name in names}

    xml_bytes = contents.get("word/document.xml", b"")
    tree = etree.fromstring(xml_bytes)

    # Find all table cells
    for tc in tree.iter(f"{{{W}}}tc"):
        cell_text = _get_cell_text(tc)
        for code, iso_substr in STANDARD_CELL_TEXT.items():
            if iso_substr in cell_text:
                fill = SELECTED_FILL if code in standards_codes else UNSELECTED_FILL
                _set_cell_shading(tc, fill)
                break

    contents["word/document.xml"] = etree.tostring(tree, xml_declaration=True, encoding="UTF-8", standalone=True)

    out_buf = io.BytesIO()
    with zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in contents.items():
            zout.writestr(name, data)

    return out_buf.getvalue()
```

### Step 3 — Fix the audit type visual marking

Add a similar function (or extend the one above) to shade the correct Audit Type cell:

```python
def apply_audit_type_highlighting(docx_bytes: bytes, audit_type: str) -> bytes:
    """Shade the correct audit type cell in FR.220's Audit Type table."""
    buf = io.BytesIO(docx_bytes)
    with zipfile.ZipFile(buf, "r") as zin:
        names = zin.namelist()
        contents = {name: zin.read(name) for name in names}

    xml_bytes = contents.get("word/document.xml", b"")
    tree = etree.fromstring(xml_bytes)

    # Cells to highlight based on audit type
    # The template has "Initial Certification / Surveillance" and "Recertification"
    type_map = {
        "initial":         "Initial",
        "surveillance":    "Initial",    # "Initial Certification / Surveillance" covers both
        "surveillance_1":  "Initial",
        "surveillance_2":  "Initial",
        "recertification": "Recertification",
    }
    selected_keyword = type_map.get(audit_type, "Initial")

    for tc in tree.iter(f"{{{W}}}tc"):
        cell_text = _get_cell_text(tc)
        if "Initial" in cell_text and "Recertification" not in cell_text:
            fill = SELECTED_FILL if selected_keyword == "Initial" else UNSELECTED_FILL
            _set_cell_shading(tc, fill)
        elif "Recertification" in cell_text and "Initial" not in cell_text:
            fill = SELECTED_FILL if selected_keyword == "Recertification" else UNSELECTED_FILL
            _set_cell_shading(tc, fill)

    contents["word/document.xml"] = etree.tostring(tree, xml_declaration=True, encoding="UTF-8", standalone=True)

    out_buf = io.BytesIO()
    with zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in contents.items():
            zout.writestr(name, data)

    return out_buf.getvalue()
```

### Step 4 — Fix currency display in filler.py

In `audit_set/filler.py`, inside `build_base_context()`, update the fee formatting:

```python
def _fmt_fee(val) -> str:
    """Format a fee as '$X,XXX' or '' if unset."""
    if val is None or val == "":
        return ""
    try:
        return f"${float(val):,.0f}"
    except (TypeError, ValueError):
        return str(val)

# Then in the returned context dict, replace:
"certification_fee": audit_set.certification_fee if audit_set.certification_fee is not None else "",
"initial_fee":       audit_set.certification_fee if audit_set.certification_fee is not None else "",
"surveillance_fee":  audit_set.surveillance_fee  if audit_set.surveillance_fee  is not None else "",
# With:
"certification_fee": _fmt_fee(audit_set.certification_fee),
"initial_fee":       _fmt_fee(audit_set.certification_fee),
"surveillance_fee":  _fmt_fee(audit_set.surveillance_fee),
```

Define `_fmt_fee` at module level (top of filler.py) or as a local function inside `build_base_context`.

### Step 5 — Wire postprocess functions into the render pipeline

Find where FR.220 is rendered (likely in `packager.py` or `service.py`). After rendering FR.220 bytes, apply both post-processing functions:

```python
from audit_set.postprocess import apply_standard_highlighting, apply_audit_type_highlighting

# After rendering FR.220:
docx_bytes = render_docx(template_path, context)
if "FR.220" in str(template_path):
    docx_bytes = apply_standard_highlighting(docx_bytes, audit_set.standards or [])
    docx_bytes = apply_audit_type_highlighting(docx_bytes, audit_set.audit_type or "")
```

Check if an existing `postprocess.py` already has a similar function that handles FR.220/221 and is already wired in — if so, UPDATE that function instead of adding a new one. Don't duplicate.

### Step 6 — Apply same fix to FR.221 if it has the same standards table

FR.221 (Offer Acceptance Form) may have the same issue. After fixing FR.220, check FR.221 for the same standards table structure and apply the same postprocessing.

### Step 7 — Commit and push

Commit with message: `fix(FR.220/221): shade selected standards green, add currency symbol to fees, mark audit type`

Push to main.

## Files to edit
- `backend/audit_set/filler.py` — format fees with `$` prefix (Step 4)
- `backend/audit_set/postprocess.py` — add/update `apply_standard_highlighting` and `apply_audit_type_highlighting` (Steps 2–3)
- `backend/audit_set/packager.py` (or wherever FR.220 is rendered) — call postprocess functions after render (Step 5)
