from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest

from audit_set.documents_router import _build_certificate_pdf


def _audit_set():
    return SimpleNamespace(
        id="certificate-test-audit-set",
        plan_number=1801,
        company_name="Example Manufacturing Limited",
        company_address="12 Certification Avenue, Istanbul, Türkiye",
        scope_en="Manufacture and distribution of example products",
        scope_tr="",
        required_scope={"QMS": {"type": "ea", "codes": ["18"]}},
        ea_category="Machinery and equipment",
    )


def _write_source_pdf(path: Path, page_texts: list[list[str]]) -> str:
    document = fitz.open()
    try:
        for lines in page_texts:
            page = document.new_page(width=595, height=842)
            for line_number, line in enumerate(lines):
                y = 570 if line == "Initial Date" else 70 + line_number * 18
                page.insert_text((60, y), line, fontsize=10)
        document.save(path)
    finally:
        document.close()
    return str(path)


def _generate(
    monkeypatch: pytest.MonkeyPatch,
    source_pdf: str,
    *,
    fitted_pdf: str | None = None,
) -> tuple[bytes, date]:
    monkeypatch.setattr(
        "audit_set.documents_router.render_certificate_docx",
        lambda standard, values, scope_spacers_to_remove=0,
        scope_font_size_half_points=None, verification_url=None: (
            f"spacers={scope_spacers_to_remove};font={scope_font_size_half_points}".encode()
        ),
    )

    def fake_convert(docx_path: str) -> str:
        spacer_count = int(
            Path(docx_path).read_text().split(";", 1)[0].split("=", 1)[1]
        )
        if fitted_pdf and spacer_count >= 5:
            return fitted_pdf
        return source_pdf

    monkeypatch.setattr(
        "audit_set.doc_converter.convert_docx_to_pdf",
        fake_convert,
    )
    return _build_certificate_pdf(
        _audit_set(),
        ["QMS"],
        initial_date=date(2024, 9, 3),
        issue_date=date(2026, 10, 13),
        revision="2",
        statement_of_applicability="",
        verification_urls={
            "QMS": "https://www.iafcertsearch.org/certification/test-record",
        },
    )


def test_libreoffice_overflow_is_rerendered_with_unused_scope_spacers_removed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    source_pdf = _write_source_pdf(
        tmp_path / "overflow.pdf",
        [
            ["IFC-Q-9-24-1801", "Example Manufacturing Limited"],
            [
                "Head Office and Key Location: IFC GLOBAL LLC | 22198 Clocktower Way",
                "+1 (305) 412-1890 info@ifcglobal.us | www.ifcglobal.us",
                "Approval",
            ],
        ],
    )
    fitted_pdf = _write_source_pdf(
        tmp_path / "fitted.pdf",
        [[
            "IFC-Q-9-24-1801",
            "Example Manufacturing Limited",
            "Initial Date",
            "Approval",
        ]],
    )

    pdf_bytes, expiry_date = _generate(
        monkeypatch,
        source_pdf,
        fitted_pdf=fitted_pdf,
    )

    with fitz.open(stream=pdf_bytes, filetype="pdf") as generated:
        assert generated.page_count == 1
        text = generated[0].get_text("text")
        assert "IFC-Q-9-24-1801" in text
        assert "Example Manufacturing Limited" in text
        assert "Approval" in text
    assert expiry_date == date(2027, 9, 2)


def test_substantive_certificate_overflow_is_never_silently_discarded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    source_pdf = _write_source_pdf(
        tmp_path / "substantive-overflow.pdf",
        [
            ["IFC-Q-9-24-1801", "Example Manufacturing Limited"],
            [
                "Head Office and Key Location: IFC GLOBAL LLC",
                "Scope content continued onto this page",
            ],
        ],
    )

    with pytest.raises(ValueError, match="does not fit on one page"):
        _generate(monkeypatch, source_pdf)


def test_production_image_installs_metric_compatible_certificate_fonts():
    dockerfile = (Path(__file__).resolve().parents[2] / "Dockerfile").read_text()

    assert "fonts-crosextra-carlito" in dockerfile
    assert "fonts-crosextra-caladea" in dockerfile
