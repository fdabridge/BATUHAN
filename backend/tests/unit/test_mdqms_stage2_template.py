from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from docx import Document


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_NAME = "FR.232-1_MD-QMS Audit Report R01&09.10.2025.docx"
TEMPLATES = (
    ROOT / "uaf_blank_set" / "13485" / "Initial Certification " / "Stage 2" / TEMPLATE_NAME,
    ROOT / "uaf_blank_set" / "13485" / "Surveillance" / TEMPLATE_NAME,
)
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{W_NS}}}"


def _document_xml(path: Path) -> bytes:
    with zipfile.ZipFile(path) as archive:
        return archive.read("word/document.xml")


def _all_xml(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        return "\n".join(
            archive.read(name).decode("utf-8", "ignore")
            for name in archive.namelist()
            if name.endswith(".xml")
        )


def test_mdqms_stage2_templates_are_kept_in_sync():
    assert TEMPLATES[0].read_bytes() == TEMPLATES[1].read_bytes()


def test_mdqms_stage2_template_has_information_and_signature_handles():
    document = Document(TEMPLATES[0])
    text = "\n".join(
        cell.text
        for table in document.tables
        for row in table.rows
        for cell in row.cells
    )

    for handle in (
        "{{ company_name }}",
        "{{ scope_en }}",
        "{{ standards_str }}",
        "{{ audit_dates }}",
        "{{ lead_auditor_name }}",
        "[SIG:LEAD_AUDITOR]",
        "[SIG:CB_CERT_MANAGER]",
    ):
        assert handle in text
    assert "[SIG:APPOINTED_REVIEWER]" not in text

    all_xml = _all_xml(TEMPLATES[0])
    assert "FR.232-1" in all_xml
    assert "FR.231-1" not in all_xml


def test_mdqms_stage2_signature_handles_are_white():
    root = ET.fromstring(_document_xml(TEMPLATES[0]))
    markers = {}
    for run in root.iter(f"{W}r"):
        text = "".join(node.text or "" for node in run.iter(f"{W}t"))
        if text.startswith("[SIG:"):
            color = run.find(f"{W}rPr/{W}color")
            markers[text] = color.get(f"{W}val") if color is not None else None

    assert markers == {
        "[SIG:LEAD_AUDITOR]": "FFFFFF",
        "[SIG:CB_CERT_MANAGER]": "FFFFFF",
    }
