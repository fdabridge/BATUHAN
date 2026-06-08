"""One-time repair: replace broken FORMCHECKBOX Jinja patterns in audit-type
cells with clean Unicode ☑/☐ expressions.

Affected templates: FR.232 (Stage 2 + Surveillance), FR.231 (Stage 1),
FR.229 (Stage 2 + Surveillance ISMS variants).

Pattern in source:
  <w:p>
    {{ "    [FORMCHECKBOX widget]    " if is_initial else "    [FORMCHECKBOX widget]    " }} Initial Certification
    {{ "    [FORMCHECKBOX widget]    " if is_recertification else "    [FORMCHECKBOX widget]    " }} Recertification
    ...
  </w:p>

After fix:
  <w:p>
    {{ "☑" if is_initial else "☐" }} Initial Certification  {{ "☑" if is_recertification else "☐" }} Recertification ...
  </w:p>
"""
from __future__ import annotations
import io
import re
import sys
import zipfile
from pathlib import Path
from lxml import etree

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{W_NS}}}"
XML_NS = "http://www.w3.org/XML/1998/namespace"

VALID_TOKENS = ("is_initial", "is_surveillance", "is_recertification", "is_special")

# Normalise split/whitespace-corrupted tokens (e.g. "is_ s urveillance") to canonical form.
TOKEN_HINTS = (
    ("ecertification", "is_recertification"),
    ("urveillance",    "is_surveillance"),
    ("pecial",         "is_special"),
    ("nitial",         "is_initial"),
)

EXPR_RE = re.compile(
    r'\{\{\s*"[^"]*"\s*if\s+([^\s]+(?:\s+[a-z])?[a-z]+)\s+else\s+"[^"]*"\s*\}\}\s*([^{]*)',
    re.DOTALL,
)


def _canonicalise_token(raw: str) -> str | None:
    cleaned = raw.replace(" ", "")
    if cleaned in VALID_TOKENS:
        return cleaned
    for needle, canon in TOKEN_HINTS:
        if needle in cleaned.lower():
            return canon
    return None


def _para_text(p) -> str:
    parts = []
    for el in p.iter():
        if el.tag in (f"{W}t", f"{W}instrText"):
            parts.append(el.text or "")
    return "".join(parts)


def _rewrite_paragraph(p) -> bool:
    full = _para_text(p)
    if "FORMCHECKBOX" not in full or "{{" not in full:
        return False
    segments: list[tuple[str, str]] = []
    for m in EXPR_RE.finditer(full):
        token = _canonicalise_token(m.group(1))
        if not token:
            continue
        label = m.group(2).strip().rstrip("}").strip()
        segments.append((token, label))
    if not segments:
        return False
    pPr = p.find(f"{W}pPr")
    for child in list(p):
        if child.tag != f"{W}pPr":
            p.remove(child)
    new_text = "  ".join(
        f'{{{{ "☑" if {tok} else "☐" }}}} {lbl}'.rstrip()
        for tok, lbl in segments
    )
    r = etree.SubElement(p, f"{W}r")
    t_el = etree.SubElement(r, f"{W}t")
    t_el.set(f"{{{XML_NS}}}space", "preserve")
    t_el.text = new_text
    return True


def fix_docx(path: Path) -> int:
    with zipfile.ZipFile(path) as zin:
        xml_bytes = zin.read("word/document.xml")
        rest = {name: zin.read(name) for name in zin.namelist() if name != "word/document.xml"}
    tree = etree.fromstring(xml_bytes)
    count = sum(1 for p in tree.iter(f"{W}p") if _rewrite_paragraph(p))
    if count == 0:
        return 0
    new_xml = etree.tostring(tree, xml_declaration=True, encoding="UTF-8", standalone=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        zout.writestr("word/document.xml", new_xml)
        for name, data in rest.items():
            zout.writestr(name, data)
    path.write_bytes(buf.getvalue())
    return count


TARGETS = [
    "backend/uaf_blank_set/9-14-45-22-5001/Initial Certification /Stage 2/FR.232_Audit_Report_R12&09.10.2025.docx",
    "backend/uaf_blank_set/9-14-45-22-5001/Surveillance/FR.232_Audit_Report_R12&09.10.2025.docx",
    "backend/uaf_blank_set/13485/Initial Certification /Stage 2/FR.232-1_MD-QMS Audit Report R01&09.10.2025.docx",
    "backend/uaf_blank_set/13485/Surveillance/FR.232-1_MD-QMS Audit Report R01&09.10.2025.docx",
    "backend/uaf_blank_set/9-14-45-22-5001/Initial Certification /Stage 1/FR.231_Stage1_Report_R9&09.10.2025.docx",
    "backend/uaf_blank_set/13485/Initial Certification /Stage 1/FR.231-1_MD-QMS Stage 1 Report R1&09.10.2025.docx",
    "backend/uaf_blank_set/27001/Initial Certification/Stage 1/FR.231_Stage1_Report_R9&09.10.2025.docx",
    "backend/uaf_blank_set/27001/Initial Certification/Stage 2/FR.229_ISMS_PIMS_Audit_Report_R8&10.06.2024.docx",
    "backend/uaf_blank_set/27001/Surveillance/FR.229_ISMS_PIMS_Audit_Report_R8&10.06.2024.docx",
]


if __name__ == "__main__":
    repo = Path(__file__).resolve().parents[2]
    for rel in TARGETS:
        p = repo / rel
        if not p.exists():
            print(f"  SKIP (missing): {rel}")
            continue
        n = fix_docx(p)
        print(f"  {'FIXED' if n else 'no change':10s} ({n} paragraphs) — {p.name}")
