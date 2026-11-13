from __future__ import annotations

import zipfile
from datetime import date
from io import BytesIO
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

from audit_set.certificate_generator import (
    APPROVAL_SIGNATURE_PATH,
    CertificateValues,
    STANDARD_SPECS,
    TEMPLATE_DIR,
    W,
    W_NS,
    approval_signature_png_bytes,
    certificate_number,
    default_expiry_date,
    default_validity_date,
    normalize_standard,
    normalize_standards,
    qr_matrix,
    render_certificate_docx,
    values_for_audit_set,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("QMS", "QMS"),
        ("ISO 9001:2015", "QMS"),
        ("ISO 14001:2015", "EMS"),
        ("ISO/IEC 27001:2022", "ISMS"),
        ("ISO 22000:2018", "FSMS"),
        ("ISO 45001:2018", "OHSMS"),
        ("ISO 50001:2018", "ENMS"),
        ("ISO 13485:2016", "MDQMS"),
        ("ISO 37001:2016", "ABMS"),
    ],
)
def test_standard_aliases_route_to_the_correct_template(raw, expected):
    assert normalize_standard(raw) == expected


def test_certificate_dates_and_number_follow_the_certificate_cycle():
    issued = date(2026, 9, 30)

    assert default_validity_date(issued) == date(2027, 9, 29)
    assert default_expiry_date(issued) == date(2029, 9, 29)
    assert certificate_number("ISO 9001:2015", issued, 1732) == "IFC-Q-9-26-1732"


def test_integrated_standard_mapping_preserves_order_and_removes_duplicates():
    assert normalize_standards([
        "ISO 9001:2015",
        "FSMS",
        "ISO/IEC 27001:2022",
        "ISO 22000:2018",
    ]) == ["QMS", "FSMS", "ISMS"]


def test_qr_matrix_is_square_and_depends_on_the_iaf_verification_url():
    first = qr_matrix("https://www.iafcertsearch.org/certification/record-one")
    second = qr_matrix("https://www.iafcertsearch.org/certification/record-two")

    assert first
    assert len(first) == len(first[0])
    assert all(len(row) == len(first) for row in first)
    assert all(isinstance(cell, bool) for row in first for cell in row)
    assert first != second


def test_fixed_approval_signature_asset_is_a_real_png():
    signature = approval_signature_png_bytes()

    assert APPROVAL_SIGNATURE_PATH.name == "approval_signature.png"
    assert signature.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(signature) > 10_000


@pytest.mark.parametrize("standard", sorted(STANDARD_SPECS))
def test_render_preserves_the_template_package_and_fills_all_slots(standard):
    values = CertificateValues(
        company_name="Example Manufacturing Limited",
        company_address="12 Certification Avenue, Istanbul, Türkiye",
        scope="Manufacture and distribution of example products",
        initial_date=date(2025, 10, 1),
        issue_date=date(2026, 10, 6),
        revision="1",
        validity_date=date(2027, 10, 5),
        expiry_date=date(2028, 9, 30),
        certificate_number=f"IFC-X-10-25-{standard}",
        category="CI, CIII",
        statement_of_applicability="01.10.2026 / Rev.1",
    )

    rendered = render_certificate_docx(standard, values)

    with zipfile.ZipFile(TEMPLATE_DIR / f"{standard}.docx") as template_zip:
        with zipfile.ZipFile(BytesIO(rendered)) as rendered_zip:
            assert template_zip.namelist() == rendered_zip.namelist()
            for name in template_zip.namelist():
                if name != "word/document.xml":
                    assert rendered_zip.read(name) == template_zip.read(name)
            xml = rendered_zip.read("word/document.xml").decode("utf-8")

    assert "[[" not in xml
    assert "Example Manufacturing Limited" in xml
    assert "12 Certification Avenue" in xml
    assert STANDARD_SPECS[standard][0] in xml
    assert "IFC-X-10-25" in xml
    if standard == "FSMS":
        assert "Category/Sub-Category: CI, CIII" in xml
    if standard == "ISMS":
        assert "01.10.2026 / Rev.1" in xml


def test_audit_set_values_use_scope_and_food_categories():
    audit_set = SimpleNamespace(
        plan_number=1801,
        company_name="Food Company",
        company_address="Food Street",
        scope_en="Production of ready-to-eat food",
        scope_tr="",
        required_scope={"ISO 22000:2018": {"type": "food", "codes": ["CI", "CIII"]}},
        ea_category=None,
    )

    values = values_for_audit_set(
        audit_set,
        "FSMS",
        initial_date=date(2026, 10, 6),
        issue_date=date(2026, 10, 6),
    )

    assert values.company_name == "Food Company"
    assert values.scope == "Production of ready-to-eat food"
    assert values.category == "CI, CIII"
    assert values.certificate_number == "IFC-F-10-26-1801"


def test_food_certificate_compaction_removes_spacers_after_category():
    values = CertificateValues(
        company_name="Food Company",
        company_address="Food Street",
        scope="Production of ready-to-eat food",
        initial_date=date(2026, 10, 1),
        issue_date=date(2026, 10, 6),
        revision="1",
        validity_date=date(2027, 10, 5),
        expiry_date=date(2029, 9, 30),
        certificate_number="IFC-F-10-26-1801",
        category="CI, CIII",
    )

    default = render_certificate_docx("FSMS", values)
    compact = render_certificate_docx("FSMS", values, scope_spacers_to_remove=2)

    def paragraph_texts(data: bytes) -> list[str]:
        with zipfile.ZipFile(BytesIO(data)) as package:
            root = ET.fromstring(package.read("word/document.xml"))
        body = root.find("w:body", W)
        assert body is not None
        return [
            "".join((node.text or "") for node in paragraph.findall(".//w:t", W)).strip()
            for paragraph in body.findall("w:p", W)
        ]

    default_texts = paragraph_texts(default)
    compact_texts = paragraph_texts(compact)
    default_category_index = default_texts.index("Category/Sub-Category: CI, CIII")
    compact_category_index = compact_texts.index("Category/Sub-Category: CI, CIII")

    def following_blank_count(texts: list[str], start: int) -> int:
        count = 0
        for text in texts[start + 1:]:
            if text:
                break
            count += 1
        return count

    default_blanks = following_blank_count(default_texts, default_category_index)
    compact_blanks = following_blank_count(compact_texts, compact_category_index)
    assert default_blanks >= 2
    assert compact_blanks == default_blanks - 2


def test_scope_font_can_be_reduced_without_changing_other_mapped_content():
    values = CertificateValues(
        company_name="Example Company",
        company_address="Example Address",
        scope="A long but controlled certification scope",
        initial_date=date(2026, 10, 1),
        issue_date=date(2026, 10, 6),
        revision="1",
        validity_date=date(2027, 10, 5),
        expiry_date=date(2029, 9, 30),
        certificate_number="IFC-Q-10-26-1801",
    )

    rendered = render_certificate_docx(
        "QMS",
        values,
        scope_font_size_half_points=18,
    )

    with zipfile.ZipFile(BytesIO(rendered)) as package:
        root = ET.fromstring(package.read("word/document.xml"))
    scope_node = next(
        node for node in root.findall(".//w:t", W)
        if node.text == values.scope
    )
    parent_map = {child: parent for parent in root.iter() for child in parent}
    run = parent_map[scope_node]
    assert run.find("w:rPr/w:sz", W).get(f"{{{W_NS}}}val") == "18"
    assert run.find("w:rPr/w:szCs", W).get(f"{{{W_NS}}}val") == "18"
    xml = ET.tostring(root, encoding="unicode")
    assert values.company_name in xml
    assert values.certificate_number in xml


def test_word_certificate_contains_the_same_qr_and_approval_signature_as_pdf():
    values = CertificateValues(
        company_name="Example Company",
        company_address="Example Address",
        scope="A controlled certification scope",
        initial_date=date(2026, 10, 1),
        issue_date=date(2026, 10, 6),
        revision="1",
        validity_date=date(2027, 10, 5),
        expiry_date=date(2029, 9, 30),
        certificate_number="IFC-Q-10-26-1801",
    )

    rendered = render_certificate_docx(
        "QMS",
        values,
        scope_spacers_to_remove=5,
        verification_url="https://www.iafcertsearch.org/certification/example-record",
    )

    with zipfile.ZipFile(BytesIO(rendered)) as package:
        names = set(package.namelist())
        relationships = package.read("word/_rels/document.xml.rels").decode("utf-8")
        document_xml = package.read("word/document.xml").decode("utf-8")
        qr_png = package.read("word/media/certiva_iaf_qr.png")
        signature_png = package.read("word/media/certiva_approval_signature.png")

    assert "word/media/certiva_iaf_qr.png" in names
    assert "word/media/certiva_approval_signature.png" in names
    assert "media/certiva_iaf_qr.png" in relationships
    assert "media/certiva_approval_signature.png" in relationships
    assert "<Relationships xmlns=" in relationships
    assert "ns0:Relationships" not in relationships
    assert "IAF CertSearch Verification QR" in document_xml
    assert "IFC Approval Signature" in document_xml
    assert qr_png.startswith(b"\x89PNG\r\n\x1a\n")
    assert signature_png == approval_signature_png_bytes()


def test_mdqms_certificate_number_keeps_its_positioning_indent():
    values = CertificateValues(
        company_name="Example Medical Devices Limited",
        company_address="Example Address",
        scope="Design and manufacture of medical devices",
        initial_date=date(2026, 10, 1),
        issue_date=date(2026, 10, 6),
        revision="1",
        validity_date=date(2027, 10, 5),
        expiry_date=date(2029, 9, 30),
        certificate_number="IFC-M-10-26-1801",
    )

    rendered = render_certificate_docx("MDQMS", values)
    with zipfile.ZipFile(BytesIO(rendered)) as package:
        root = ET.fromstring(package.read("word/document.xml"))

    number_node = next(
        node
        for node in root.findall(".//w:t", W)
        if (node.text or "") == values.certificate_number
    )
    parent_map = {child: parent for parent in root.iter() for child in parent}
    paragraph = parent_map[number_node]
    while paragraph.tag != f"{{{W_NS}}}p":
        paragraph = parent_map[paragraph]
    indent = paragraph.find("w:pPr/w:ind", W)

    assert indent is not None
    assert int(indent.get(f"{{{W_NS}}}left", "0")) > 0
