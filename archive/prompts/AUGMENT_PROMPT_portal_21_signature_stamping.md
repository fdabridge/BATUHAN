# Prompt 21 — Signature Placeholder Injection: Stamping [SIG:PARTY] into DOCX Templates

## Context

This is the Certiva platform. We are building a DocuSign-like signing layer where every document opened in the in-portal viewer shows a clickable signature box at the exact position where each party must sign. Documents are visual PDFs, not downloads.

The 6-prompt plan is:
- **Prompt 21 (this one)**: Inject `[SIG:PARTY]` placeholder text into the correct cells of every DOCX template in `backend/uaf_blank_set copy/`. One-shot Python script, run and committed.
- Prompt 22: `user_signatures` table + signature profile page (draw or upload personal signature)
- Prompt 23: DOCX → PDF conversion pipeline, pdfplumber coordinate extraction at upload time
- Prompt 24: In-portal PDF viewer with clickable signature overlay boxes
- Prompt 25: Visual signing + OTP commit, guest FR.225 inline signing
- Prompt 26: PDF flattening + final document delivery

**Why placeholders?** After LibreOffice converts a DOCX to PDF, pdfplumber scans the PDF and finds the exact bounding box of the `[SIG:CB_PLANNER]` text. That coordinate becomes the centre of the signature overlay box in the viewer. Without a detectable text marker we would have to hardcode pixel offsets per-template per-page — fragile. With a marker, coordinates are found dynamically even if content shifts the signature table by one page.

The placeholder text is styled as 8pt light-gray italic — barely visible in print, but reliably present in the PDF text stream for pdfplumber.

---

## Confirmed existing state (verified by live inspection)

All table structures below were verified by running `python-docx` against the actual files in `backend/uaf_blank_set copy/`. The table index, row, and column numbers are exact.

| Form file prefix | Last table shape | Signer(s) and cell(s) |
|---|---|---|
| `FR.220_` | 4R × 2C | Row 3 Col 0 → `CB_PLANNER` · Row 3 Col 1 → `CLIENT` |
| `FR.221_` | 4R × 2C | Row 3 Col 0 → `CB_PLANNER` · Row 3 Col 1 → `CLIENT` |
| `FR.222_` | 2R × 2C | Row 1 Col 0 → `CB_PLANNER` · Row 1 Col 1 → `CB_CERT_MANAGER` |
| `FR.223_` | 3R × 3C | Row 2 Col 2 → `CLIENT` |
| `FR.218_` | 3R × 3C | Row 1 Col 0 → `CB_PLANNER` · Row 1 Col 1 → `CB_REVIEWER` · Row 1 Col 2 → `CB_CERT_MANAGER` |
| `FR.230_` | 1R × 4C | Row 0 Col 1 → `CLIENT` · Row 0 Col 3 → `LEAD_AUDITOR` |
| `FR.231_` | 4R × 2C | Row 3 Col 0 → `LEAD_AUDITOR` · Row 3 Col 1 → `CB_REVIEWER` |
| `FR.231-1_` | 4R × 2C | Row 3 Col 0 → `LEAD_AUDITOR` · Row 3 Col 1 → `CB_REVIEWER` |
| `FR.229_` | 4R × 2C | Row 3 Col 0 → `LEAD_AUDITOR` · Row 3 Col 1 → `CB_REVIEWER` |
| `FR.232_` | 4R × 1C | Row 3 Col 0 → `CB_REVIEWER` |
| `FR.232-1_` | 4R × 2C | Row 3 Col 0 → `LEAD_AUDITOR` · Row 3 Col 1 → `CB_REVIEWER` |
| `FR.211_` | 2R × 2C | Row 1 Col 1 → `CLIENT` |
| `FR.224_` | 4R × 3C | Row 3 Col 1 → `AUDITOR_MEMBER` |

Notes on specific forms:
- **FR.220/221 Row 3**: The cell text is already "Sign:" — the placeholder is appended as a new paragraph inside the same cell, so the cell reads "Sign:" + `[SIG:CB_PLANNER]` on the next line.
- **FR.222 Row 1**: The cell text is "Signature" — same append approach.
- **FR.230 Row 0 Col 1 / Col 3**: These are the empty value cells between the fixed label cells ("Organisation Representative\nDate & Sign" and "Auditor/Sign {{ lead_auditor_name }}"). They are currently empty — the placeholder is set as the cell's content directly.
- **FR.218 Row 1**: All three value cells are empty — placeholder set directly.
- **FR.223 Row 2**: All three value cells are empty — Col 2 gets the placeholder.
- **FR.231/231-1/229/232-1 Row 3**: These are the blank cells below the "Signature" label row (Row 2) — the actual drawing area. Empty — placeholder set directly.
- **FR.232_ Row 3**: Single-column form (only a CB reviewer approves). Empty cell — placeholder set directly.
- **FR.224 Row 3 Col 1**: Each FR.224 file is generated per-auditor with `{{ assessed_person_name }}` in Col 0. Col 1 is their signature cell — placeholder set directly.
- **FR.225** (Meeting Attendance): Skipped in this prompt. Its attendee rows are dynamically rendered from Jinja2 `{%tr if ... %}` blocks and the guest-token signing flow (already built in Prompt 17) handles it differently. Will be addressed in Prompt 25.
- **FR.234** (Notification): No signing flow. Skip.

---

## File to create: `scripts/add_signature_placeholders.py`

Create this file at `scripts/add_signature_placeholders.py` in the repo root. The script is run once to modify the templates in-place, then the changes are committed as binary DOCX updates.

```python
#!/usr/bin/env python3
"""
Inject [SIG:PARTY] placeholder text into UAF blank-set DOCX templates.

Run once from the repo root:
    python3 scripts/add_signature_placeholders.py

Each DOCX in backend/uaf_blank_set copy/ is modified in-place.
Commit all resulting .docx changes as a single binary-update commit.

Purpose
-------
After LibreOffice converts a filled DOCX to PDF, pdfplumber scans the PDF
text stream and locates the bounding box of each [SIG:...] token. That
coordinate drives the signature overlay box in the in-portal viewer. The
marker is 8pt light-gray italic — invisible in print, present in the PDF
content stream.

Placeholder → signer mapping (used by Prompt 23 coordinate extractor):
  [SIG:CB_PLANNER]       CB Planning Officer
  [SIG:CB_REVIEWER]      Committee Reviewer (appointed for this audit set)
  [SIG:CB_CERT_MANAGER]  Certification Manager
  [SIG:LEAD_AUDITOR]     Lead Auditor
  [SIG:CLIENT]           Client Organisation Representative
  [SIG:AUDITOR_MEMBER]   Audit-team member (FR.224 per-person copy)
"""
import glob
import os
import sys
from pathlib import Path

from docx import Document
from docx.shared import Pt, RGBColor

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PLACEHOLDER_FONT_SIZE = Pt(8)
PLACEHOLDER_COLOR = RGBColor(180, 180, 180)  # light gray — barely visible in print

BASE_DIR = Path(__file__).parent.parent / "backend" / "uaf_blank_set copy"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _append_sig(cell, sig_key: str) -> None:
    """
    Add [SIG:KEY] as a new paragraph at the end of a cell that already has
    text (e.g. "Sign:" or "Signature").  Keeps the existing label intact.
    """
    para = cell.add_paragraph()
    run = para.add_run(f"[SIG:{sig_key}]")
    run.font.size = PLACEHOLDER_FONT_SIZE
    run.font.color.rgb = PLACEHOLDER_COLOR
    run.font.italic = True


def _set_sig(cell, sig_key: str) -> None:
    """
    Set [SIG:KEY] as the content of an empty cell.  Uses the cell's first
    existing paragraph so we don't create a spurious blank line above.
    """
    para = cell.paragraphs[0] if cell.paragraphs else cell.add_paragraph()
    run = para.add_run(f"[SIG:{sig_key}]")
    run.font.size = PLACEHOLDER_FONT_SIZE
    run.font.color.rgb = PLACEHOLDER_COLOR
    run.font.italic = True


# ---------------------------------------------------------------------------
# Per-form processors  (all use doc.tables[-1] = the last/signature table)
# ---------------------------------------------------------------------------

def _fr220_fr221(doc: Document) -> None:
    """FR.220 Quotation / FR.221 Agreement — 4R × 2C, Row 3 = Sign row."""
    t = doc.tables[-1]
    _append_sig(t.rows[3].cells[0], "CB_PLANNER")   # IFC GLOBAL LLC side
    _append_sig(t.rows[3].cells[1], "CLIENT")        # Organisation side


def _fr222(doc: Document) -> None:
    """FR.222 Audit Programme — 2R × 2C, Row 1 = Signature row."""
    t = doc.tables[-1]
    _append_sig(t.rows[1].cells[0], "CB_PLANNER")
    _append_sig(t.rows[1].cells[1], "CB_CERT_MANAGER")


def _fr223(doc: Document) -> None:
    """FR.223 Audit Plan — 3R × 3C, Row 2 = value row, Col 2 = Signature."""
    t = doc.tables[-1]
    _set_sig(t.rows[2].cells[2], "CLIENT")


def _fr218(doc: Document) -> None:
    """FR.218 Application Review — 3R × 3C, Row 1 = value row (3 signers)."""
    t = doc.tables[-1]
    _set_sig(t.rows[1].cells[0], "CB_PLANNER")
    _set_sig(t.rows[1].cells[1], "CB_REVIEWER")
    _set_sig(t.rows[1].cells[2], "CB_CERT_MANAGER")


def _fr230(doc: Document) -> None:
    """FR.230 NC Form — 1R × 4C, Col 1 = client val, Col 3 = LA val."""
    t = doc.tables[-1]  # == doc.tables[1]; only 2 tables in this file
    _set_sig(t.rows[0].cells[1], "CLIENT")
    _set_sig(t.rows[0].cells[3], "LEAD_AUDITOR")


def _fr231_fr229(doc: Document) -> None:
    """
    FR.231 Stage 1 Report / FR.231-1 MD-QMS Stage 1 Report / FR.229 ISMS Report
    All share: 4R × 2C, Row 3 = actual signature area (below "Signature" label).
    """
    t = doc.tables[-1]
    _set_sig(t.rows[3].cells[0], "LEAD_AUDITOR")
    _set_sig(t.rows[3].cells[1], "CB_REVIEWER")


def _fr232_single(doc: Document) -> None:
    """FR.232_ Audit Report (generic) — 4R × 1C, single reviewer."""
    t = doc.tables[-1]
    _set_sig(t.rows[3].cells[0], "CB_REVIEWER")


def _fr232_double(doc: Document) -> None:
    """FR.232-1_ MD-QMS Audit Report — 4R × 2C, LA + Reviewer."""
    t = doc.tables[-1]
    _set_sig(t.rows[3].cells[0], "LEAD_AUDITOR")
    _set_sig(t.rows[3].cells[1], "CB_REVIEWER")


def _fr211(doc: Document) -> None:
    """FR.211 Auditor Assessment — 2R × 2C, Row 1 Col 1 = Signature."""
    t = doc.tables[-1]
    _set_sig(t.rows[1].cells[1], "CLIENT")


def _fr224(doc: Document) -> None:
    """
    FR.224 Impartiality Declaration — 4R × 3C.
    Row 3 Col 0 = {{ assessed_person_name }} (Jinja2, rendered per auditor).
    Row 3 Col 1 = signature cell.
    """
    t = doc.tables[-1]
    _set_sig(t.rows[3].cells[1], "AUDITOR_MEMBER")


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

PROCESSORS = [
    # (startswith prefix, handler) — order matters: more specific prefixes first
    ("FR.220", _fr220_fr221),
    ("FR.221", _fr220_fr221),
    ("FR.222", _fr222),
    ("FR.223", _fr223),
    ("FR.218", _fr218),
    ("FR.230", _fr230),
    ("FR.231", _fr231_fr229),   # catches both FR.231_ and FR.231-1_
    ("FR.229", _fr231_fr229),
    ("FR.232-1", _fr232_double), # must come BEFORE FR.232_ check
    ("FR.232_", _fr232_single),
    ("FR.211", _fr211),
    ("FR.224", _fr224),
    # FR.225 and FR.234 are intentionally omitted (see script docstring)
]


def process_file(path: str) -> str:
    basename = os.path.basename(path)
    for prefix, handler in PROCESSORS:
        if basename.startswith(prefix):
            doc = Document(path)
            handler(doc)
            doc.save(path)
            return f"  OK    {basename}"
    return f"  SKIP  {basename}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    pattern = str(BASE_DIR / "**" / "*.docx")
    files = sorted(glob.glob(pattern, recursive=True))

    if not files:
        print(f"ERROR: No DOCX files found under:\n  {BASE_DIR}")
        print("Make sure you're running from the repo root and the path is correct.")
        sys.exit(1)

    print(f"Processing {len(files)} DOCX files in: {BASE_DIR}\n")
    skipped = 0
    updated = 0
    for path in files:
        result = process_file(path)
        print(result)
        if result.startswith("  OK"):
            updated += 1
        else:
            skipped += 1

    print(f"\nSummary: {updated} updated, {skipped} skipped.")
    print("Run `git diff --stat` to verify. Commit all modified .docx files.")


if __name__ == "__main__":
    main()
```

---

## After writing the script — run it

From the repo root, run:

```bash
pip install python-docx   # if not already available
python3 scripts/add_signature_placeholders.py
```

Expected output: every FR.218_, FR.220_, FR.221_, FR.222_, FR.223_, FR.224_, FR.229_, FR.230_, FR.231_, FR.232_, FR.211_ file should print `OK`. FR.225_, FR.234_, and any other forms should print `SKIP`.

Verify the modifications are correct for at least two forms:

```python
# Quick verification — paste into a python3 session in the repo root
from docx import Document

# FR.220 — should show [SIG:CB_PLANNER] in Row 3 Col 0
doc = Document("backend/uaf_blank_set copy/9-14-45-22-5001/Initial Certification /Stage 1/FR.220_Quotation_Form_R15&09.10.2025.docx")
t = doc.tables[-1]
print("FR.220 Row3 Col0:", repr(t.rows[3].cells[0].text))
print("FR.220 Row3 Col1:", repr(t.rows[3].cells[1].text))

# FR.218 — should show [SIG:CB_PLANNER] etc in Row 1
doc2 = Document("backend/uaf_blank_set copy/9-14-45-22-5001/Initial Certification /Stage 1/FR.218_Application_Review_Form_R8&09.10.2025.docx")
t2 = doc2.tables[-1]
print("FR.218 Row1:", [repr(c.text) for c in t2.rows[1].cells])
```

Each cell should contain the placeholder. For cells that previously had "Sign:" or "Signature", the text will be e.g. `"Sign:\n[SIG:CB_PLANNER]"`.

---

## What is NOT changing

- No backend routes, no DB tables, no frontend components.
- No changes to any `.py` file in `backend/` — this is purely a template modification.
- No changes to files outside `backend/uaf_blank_set copy/` and the new `scripts/` file.
- `FR.225` and `FR.234` DOCX files are not touched.

---

## Verification checklist

1. Script runs without errors.
2. `git diff --stat` shows only `.docx` file modifications under `backend/uaf_blank_set copy/` plus the new `scripts/add_signature_placeholders.py`.
3. Quick verification snippet above confirms correct cell content for FR.220 and FR.218.
4. No `.py` file other than `scripts/add_signature_placeholders.py` is changed.

---

## Commit message

```
feat(templates): inject [SIG:PARTY] placeholders into UAF blank-set DOCX templates (Prompt 21)

- Add scripts/add_signature_placeholders.py — one-shot python-docx script that
  locates the correct table/row/col in each FR.2xx form and appends an 8pt
  light-gray [SIG:KEY] marker to the signing cell
- Modify all FR.218/220/221/222/223/224/229/230/231/232/211 templates under
  backend/uaf_blank_set copy/ (all three standard variants: 9001 bundle,
  27001, 13485)
- Placeholders: CB_PLANNER · CB_REVIEWER · CB_CERT_MANAGER · LEAD_AUDITOR ·
  CLIENT · AUDITOR_MEMBER
- FR.225 (meeting/guest) and FR.234 (notification) intentionally skipped
- These markers are detected by pdfplumber in Prompt 23 to produce signature
  field coordinates; they are whited-out or replaced during PDF flattening in Prompt 26
```
