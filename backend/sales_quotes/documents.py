from __future__ import annotations

from io import BytesIO
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor


GREEN = RGBColor(26, 71, 49)


def _money(value: Any, currency: str) -> str:
    try:
        return f"{float(value):,.2f} {currency}"
    except (TypeError, ValueError):
        return f"0.00 {currency}"


def _base_document(title: str, reference: str) -> Document:
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Inches(0.55)
    section.bottom_margin = Inches(0.55)
    section.left_margin = Inches(0.65)
    section.right_margin = Inches(0.65)
    normal = doc.styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(9)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("IFC GLOBAL LLC")
    run.bold = True
    run.font.name = "Arial"
    run.font.size = Pt(14)
    run.font.color.rgb = GREEN
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(title.upper())
    run.bold = True
    run.font.name = "Arial"
    run.font.size = Pt(16)
    run.font.color.rgb = GREEN
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run(reference).italic = True
    return doc


def _info_table(doc: Document, rows: list[tuple[str, str]]) -> None:
    table = doc.add_table(rows=0, cols=2)
    table.style = "Table Grid"
    for label, value in rows:
        cells = table.add_row().cells
        cells[0].text = label
        cells[1].text = value
        cells[0].paragraphs[0].runs[0].bold = True


def build_quotation(case: Any) -> bytes:
    app = case.application_data or {}
    commercial = case.commercial_details or {}
    pricing = case.pricing or {}
    currency = pricing.get("currency", "USD")
    revision = case.quotation_revision
    reference = f"SQ-{case.id[:8].upper()}-R{revision}"
    doc = _base_document("Certification Services Quotation", reference)
    _info_table(doc, [
        ("Organization", case.company_name),
        ("Contact", f"{case.representative_name} · {case.representative_email}".strip(" ·")),
        ("Address", ", ".join(filter(None, [app.get("company_address"), app.get("city"), app.get("country")]))),
        ("Standards", ", ".join(app.get("standards", []))),
        ("Certification scope", app.get("scope_description", "")),
        ("Quotation coverage", commercial.get("coverage_label", commercial.get("coverage", "Custom"))),
        ("Solicitation source", commercial.get("solicitation_source", "")),
        ("Solicitation reference", commercial.get("solicitation_reference", "")),
    ])

    doc.add_heading("Audit duration and professional fees", level=2)
    table = doc.add_table(rows=1, cols=5)
    table.style = "Table Grid"
    for cell, text in zip(table.rows[0].cells, ["Activity", "Recommended days", "Quoted days", "Day rate", "Amount"]):
        cell.text = text
        cell.paragraphs[0].runs[0].bold = True
    line_items = pricing.get("line_items", [])
    days_by_key = {item.get("key"): item for item in (case.day_breakdown or [])}
    for item in line_items:
        day = days_by_key.get(item.get("key"), {})
        row = table.add_row().cells
        row[0].text = str(item.get("label", item.get("key", "Service")))
        row[1].text = str(day.get("recommended_days", "—"))
        row[2].text = str(day.get("quoted_days", "—"))
        row[3].text = _money(item.get("day_rate", 0), currency)
        row[4].text = _money(item.get("amount", 0), currency)

    doc.add_paragraph()
    _info_table(doc, [
        ("Audit fees subtotal", _money(pricing.get("audit_subtotal", 0), currency)),
        ("Additional fees", _money(pricing.get("additional_fees_total", 0), currency)),
        ("Discount", _money(pricing.get("discount", 0), currency)),
        ("Total (excluding applicable taxes)", _money(pricing.get("grand_total", 0), currency)),
    ])
    doc.add_paragraph("Commercial notes")
    doc.add_paragraph(commercial.get("notes") or "No additional commercial notes were recorded.")
    doc.add_paragraph(
        "This editable sales quotation is a commercial record only. It does not create a certification application, "
        "reserve an auditor, notify a planner, or constitute a certification decision."
    )
    doc.add_paragraph("Prepared by: ____________________     Accepted by: ____________________")
    out = BytesIO()
    doc.save(out)
    return out.getvalue()


def build_agreement(case: Any) -> bytes:
    app = case.application_data or {}
    pricing = case.pricing or {}
    currency = pricing.get("currency", "USD")
    reference = f"SA-{case.id[:8].upper()}-R{case.quotation_revision}"
    doc = _base_document("Certification Services Agreement", reference)
    _info_table(doc, [
        ("Organization", case.company_name),
        ("Authorized representative", case.representative_name),
        ("Email", case.representative_email),
        ("Standards", ", ".join(app.get("standards", []))),
        ("Scope", app.get("scope_description", "")),
        ("Agreed commercial value", _money(pricing.get("grand_total", 0), currency)),
        ("Accepted quotation", f"Revision {case.quotation_revision}"),
    ])
    doc.add_heading("Agreement", level=2)
    doc.add_paragraph(
        "The parties agree that certification services will be provided in accordance with IFC Global's applicable "
        "certification rules, the accepted quotation, and the agreed certification scope. Any certification activity "
        "will begin only after a separate application is formally submitted into the certification workflow."
    )
    doc.add_paragraph("For IFC Global LLC: ____________________     Date: __________")
    doc.add_paragraph("For the organization: ____________________     Date: __________")
    out = BytesIO()
    doc.save(out)
    return out.getvalue()
