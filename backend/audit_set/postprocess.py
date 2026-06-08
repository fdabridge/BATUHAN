"""
BATUHAN — Audit Set: DOCX post-processing helpers.

Visual marking that docxtpl alone can't express:
  * `apply_standard_highlighting` — green-shade the table cells whose ISO
    standard is part of this audit (FR.220 / FR.221 grid).
  * `apply_audit_type_highlighting` — green-shade the audit-type cell that
    matches the audit's `audit_type` ("initial" / "surveillance*" /
    "recertification").

Both functions take rendered DOCX bytes and return new DOCX bytes. Failures
are swallowed and the original bytes returned, so a styling glitch never
breaks the whole package.
"""
from __future__ import annotations

import io
import logging
import zipfile

from lxml import etree

logger = logging.getLogger(__name__)

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

# Short code → ISO substring as it appears in FR.220/221 cells.
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

SELECTED_FILL = "A8D5A2"   # light green — clear on print
UNSELECTED_FILL = "FFFFFF"  # white


def _cell_text(tc) -> str:
    return "".join(t.text or "" for t in tc.iter(f"{{{_W}}}t"))


def _set_cell_shading(tc, fill_hex: str) -> None:
    """Add or replace <w:shd> on the cell's <w:tcPr>."""
    tcPr = tc.find(f"{{{_W}}}tcPr")
    if tcPr is None:
        tcPr = etree.SubElement(tc, f"{{{_W}}}tcPr")
        tc.insert(0, tcPr)
    shd = tcPr.find(f"{{{_W}}}shd")
    if shd is None:
        shd = etree.SubElement(tcPr, f"{{{_W}}}shd")
    shd.set(f"{{{_W}}}val", "clear")
    shd.set(f"{{{_W}}}color", "auto")
    shd.set(f"{{{_W}}}fill", fill_hex)


def _rewrite_docx(docx_bytes: bytes, mutate_tree) -> bytes:
    """Open the DOCX, run `mutate_tree(root_element)` on document.xml, repack."""
    try:
        zin = zipfile.ZipFile(io.BytesIO(docx_bytes))
        contents = {n: zin.read(n) for n in zin.namelist()}
        root = etree.fromstring(contents["word/document.xml"])
        mutate_tree(root)
        contents["word/document.xml"] = etree.tostring(
            root, xml_declaration=True, encoding="UTF-8", standalone=True
        )
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zo:
            for n, data in contents.items():
                zo.writestr(n, data)
        return out.getvalue()
    except Exception:  # pragma: no cover — never break the package
        logger.warning("[Postprocess] DOCX rewrite failed", exc_info=True)
        return docx_bytes


def apply_standard_highlighting(docx_bytes: bytes, standards_codes: list) -> bytes:
    """Shade selected standards green, unselected white, in the FR.220/221 grid."""
    selected = set(standards_codes or [])

    def _mutate(root):
        for tc in root.iter(f"{{{_W}}}tc"):
            text = _cell_text(tc)
            for code, iso_substr in STANDARD_CELL_TEXT.items():
                if iso_substr in text:
                    fill = SELECTED_FILL if code in selected else UNSELECTED_FILL
                    _set_cell_shading(tc, fill)
                    break

    return _rewrite_docx(docx_bytes, _mutate)


# Audit-type → keyword the matching cell must contain.
_AUDIT_TYPE_KEYWORD = {
    "initial":         "Initial",
    "surveillance":    "Initial",
    "surveillance_1":  "Initial",
    "surveillance_2":  "Initial",
    "recertification": "Recertification",
    "special":         "Initial",
}


def apply_audit_type_highlighting(docx_bytes: bytes, audit_type: str) -> bytes:
    """Shade the cell matching this audit's type ("Initial" / "Recertification")."""
    selected_keyword = _AUDIT_TYPE_KEYWORD.get(audit_type or "", "Initial")

    def _mutate(root):
        for tc in root.iter(f"{{{_W}}}tc"):
            text = _cell_text(tc)
            has_initial = "Initial" in text
            has_recert = "Recertification" in text
            if has_initial and not has_recert:
                fill = SELECTED_FILL if selected_keyword == "Initial" else UNSELECTED_FILL
                _set_cell_shading(tc, fill)
            elif has_recert and not has_initial:
                fill = SELECTED_FILL if selected_keyword == "Recertification" else UNSELECTED_FILL
                _set_cell_shading(tc, fill)

    return _rewrite_docx(docx_bytes, _mutate)
