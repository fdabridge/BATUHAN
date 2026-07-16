"""Generate a signed PDF certificate for an impartiality declaration."""
from __future__ import annotations
import io
import os
from datetime import datetime
from typing import Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from audit_set.signature_image import signature_png_bytes


DECLARATION_LINES = [
    "I have no personal, financial, or professional interest in the outcome of this audit.",
    "I have no relationships with the auditee that could compromise my impartiality.",
    "I will conduct the audit objectively and in accordance with audit procedures.",
    "I will maintain confidentiality of all information obtained during the audit.",
    "I acknowledge that any conflict of interest must be disclosed immediately to the CB.",
]


def generate_declaration_pdf(
    *,
    member_name: str,
    member_role: str,
    stage_type: str,
    audit_plan_number: Optional[int],
    company_name: str,
    signed_at: datetime,
    signature_image_b64: Optional[str],
    output_path: str,
) -> None:
    """Render a declaration signing certificate to output_path."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    W, H = A4

    margin = 20 * mm
    y = H - margin

    # Header
    c.setFont("Helvetica-Bold", 14)
    c.drawString(margin, y, "IFC Global LLC — Certiva")
    y -= 8 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin, y, "FR.215  Impartiality Declaration — Signing Certificate")
    y -= 6 * mm
    c.setStrokeColorRGB(0.1, 0.28, 0.19)
    c.setLineWidth(1)
    c.line(margin, y, W - margin, y)
    y -= 8 * mm

    # Audit details
    c.setFont("Helvetica", 10)
    ref = f"#{audit_plan_number}" if audit_plan_number else "N/A"
    for label, value in [
        ("Audit Set",  f"{ref} — {company_name}"),
        ("Stage",      stage_type.replace("_", " ").title()),
        ("Declarant",  member_name),
        ("Role",       member_role),
    ]:
        c.setFont("Helvetica-Bold", 10)
        c.drawString(margin, y, f"{label}:")
        c.setFont("Helvetica", 10)
        c.drawString(margin + 38 * mm, y, value)
        y -= 6 * mm
    y -= 4 * mm

    # Declaration text
    c.setFont("Helvetica-Bold", 10)
    c.drawString(margin, y, f"I, {member_name}, hereby declare that:")
    y -= 7 * mm
    c.setFont("Helvetica", 9)
    for line in DECLARATION_LINES:
        c.drawString(margin + 4 * mm, y, f"\u2713  {line}")
        y -= 5.5 * mm
    y -= 6 * mm

    # Confirmation line
    c.setFont("Helvetica", 10)
    c.drawString(margin, y, "The above declaration has been confirmed and accepted by the declarant.")
    y -= 10 * mm

    # Signature box
    c.setFont("Helvetica-Bold", 10)
    c.drawString(margin, y, "Digital Signature:")
    y -= 4 * mm
    box_h = 22 * mm
    c.rect(margin, y - box_h, 60 * mm, box_h)
    if signature_image_b64:
        try:
            img_buf = io.BytesIO(signature_png_bytes(signature_image_b64))
            c.drawImage(
                ImageReader(img_buf),
                margin + 2 * mm, y - box_h + 2 * mm,
                width=56 * mm,
                height=box_h - 4 * mm,
                preserveAspectRatio=True,
                anchor="c",
                mask="auto",
            )
        except Exception:
            c.setFont("Helvetica-Oblique", 8)
            c.drawString(margin + 4 * mm, y - box_h / 2, "(signature image unavailable)")

    # Date and name below signature box
    c.setFont("Helvetica", 9)
    date_str = signed_at.strftime("%d %B %Y, %H:%M UTC")
    c.drawString(margin, y - box_h - 5 * mm, f"Signed:  {member_name}")
    c.drawString(margin, y - box_h - 10 * mm, f"Date:    {date_str}")

    c.showPage()
    c.save()

    with open(output_path, "wb") as f:
        f.write(buf.getvalue())
