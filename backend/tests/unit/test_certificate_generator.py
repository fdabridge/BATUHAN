from __future__ import annotations

import zipfile
from datetime import date
from io import BytesIO
from types import SimpleNamespace

import pytest

from audit_set.certificate_generator import (
    APPROVAL_SIGNATURE_PATH,
    CertificateValues,
    STANDARD_SPECS,
    TEMPLATE_DIR,
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
