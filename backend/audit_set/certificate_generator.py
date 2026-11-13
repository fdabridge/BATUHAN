"""Generate IFC certificate DOCX/PDF pages from approved per-standard templates."""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image, ImageDraw


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = {"w": W_NS}
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
IMAGE_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
TEMPLATE_DIR = Path(__file__).with_name("certificate_templates")
APPROVAL_SIGNATURE_PATH = TEMPLATE_DIR / "approval_signature.png"

STANDARD_SPECS = {
    "QMS": ("ISO 9001:2015", "Q"),
    "EMS": ("ISO 14001:2015", "E"),
    "OHSMS": ("ISO 45001:2018", "O"),
    "FSMS": ("ISO 22000:2018", "F"),
    "ISMS": ("ISO 27001:2022", "I"),
    "ENMS": ("ISO 50001:2018", "E"),
    "MDQMS": ("ISO 13485:2016", "M"),
    "ABMS": ("ISO 37001:2016", "A"),
}

# Page coordinates measured from the approved IFC/UAF certificate set.  The
# controlled templates do not share one lower-page geometry (FSMS, ISMS,
# MDQMS, ABMS and ENMS place their accreditation block at different heights),
# so a single percentage-based overlay cannot remain aligned across standards.
CERTIFICATE_ASSET_LAYOUTS = {
    "QMS": {
        "qr": (413.2, 640.0, 46.4, 45.8),
        "signature": (276.4, 686.9, 57.8, 45.7),
    },
    "EMS": {
        "qr": (399.8, 640.0, 68.5, 71.6),
        "signature": (275.4, 687.9, 57.8, 45.8),
    },
    # The supplied OHSMS reference predates the IAF QR.  It uses the same IFC
    # portrait grid as QMS at the lower accreditation/approval block.
    "OHSMS": {
        "qr": (413.2, 676.0, 46.4, 45.8),
        "signature": (276.4, 722.3, 57.8, 45.7),
    },
    "FSMS": {
        "qr": (433.1, 656.0, 70.9, 73.3),
        "signature": (279.1, 719.5, 57.8, 45.7),
    },
    "ISMS": {
        "qr": (427.6, 706.0, 75.3, 77.9),
        "signature": (293.3, 760.5, 57.8, 45.7),
    },
    "ENMS": {
        "qr": (430.0, 657.0, 68.7, 76.2),
        "signature": (288.5, 703.7, 57.8, 45.7),
    },
    "MDQMS": {
        "qr": (418.1, 668.0, 73.3, 66.7),
        "signature": (281.7, 692.0, 71.8, 56.8),
    },
    "ABMS": {
        "qr": (427.0, 674.0, 60.7, 59.8),
        "signature": (285.5, 726.3, 58.6, 45.7),
    },
}

_ALIASES = {
    "QMS": "QMS", "9001": "QMS", "ISO9001": "QMS",
    "EMS": "EMS", "14001": "EMS", "ISO14001": "EMS",
    "OHSMS": "OHSMS", "45001": "OHSMS", "ISO45001": "OHSMS",
    "FSMS": "FSMS", "22000": "FSMS", "ISO22000": "FSMS",
    "ISMS": "ISMS", "27001": "ISMS", "ISO27001": "ISMS", "ISOIEC27001": "ISMS",
    "ENMS": "ENMS", "50001": "ENMS", "ISO50001": "ENMS",
    "MDQMS": "MDQMS", "13485": "MDQMS", "ISO13485": "MDQMS",
    "ABMS": "ABMS", "37001": "ABMS", "ISO37001": "ABMS",
}


@dataclass(frozen=True)
class CertificateValues:
    company_name: str
    company_address: str
    scope: str
    initial_date: date
    issue_date: date
    revision: str
    validity_date: date
    expiry_date: date
    certificate_number: str
    category: str = ""
    statement_of_applicability: str = ""


def normalize_standard(value: str) -> str:
    compact = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
    compact = re.sub(r"20(?:15|16|18|22)$", "", compact)
    try:
        return _ALIASES[compact]
    except KeyError as exc:
        raise ValueError(f"Unsupported certificate standard: {value}") from exc


def normalize_standards(values: list[str] | str | None) -> list[str]:
    """Normalize and de-duplicate an audit's standards without changing order."""
    raw_values = [values] if isinstance(values, str) else list(values or [])
    result: list[str] = []
    for raw in raw_values:
        canonical = normalize_standard(str(raw))
        if canonical not in result:
            result.append(canonical)
    return result


def format_date(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def add_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, day=28)


def default_validity_date(issue_date: date) -> date:
    return add_years(issue_date, 1) - timedelta(days=1)


def default_expiry_date(initial_date: date) -> date:
    # Certificate cycles end on the day before the third anniversary.
    return add_years(initial_date, 3) - timedelta(days=1)


def certificate_number(standard: str, initial_date: date, plan_number: int) -> str:
    canonical = normalize_standard(standard)
    prefix = STANDARD_SPECS[canonical][1]
    return f"IFC-{prefix}-{initial_date.month}-{initial_date.strftime('%y')}-{plan_number}"


def qr_matrix(value: str) -> list[list[bool]]:
    """Return a standards-compliant QR module matrix without raster dependencies."""
    from reportlab.graphics.barcode.qr import QrCodeWidget

    widget = QrCodeWidget(value)
    widget.qr.make()
    return [list(row) for row in widget.qr.modules]


def approval_signature_png_bytes() -> bytes:
    """Return the fixed IFC certificate approval signature template."""
    if not APPROVAL_SIGNATURE_PATH.exists():
        raise FileNotFoundError("Certificate approval signature template is missing")
    return APPROVAL_SIGNATURE_PATH.read_bytes()


def qr_png_bytes(value: str, *, module_pixels: int = 8) -> bytes:
    """Render the IAF verification QR as a sharp, Word-safe PNG."""
    modules = qr_matrix(value)
    quiet_zone = 4
    side = (len(modules) + quiet_zone * 2) * module_pixels
    image = Image.new("RGB", (side, side), "white")
    draw = ImageDraw.Draw(image)
    for row_index, row in enumerate(modules):
        for column_index, enabled in enumerate(row):
            if not enabled:
                continue
            left = (column_index + quiet_zone) * module_pixels
            top = (row_index + quiet_zone) * module_pixels
            draw.rectangle(
                (left, top, left + module_pixels - 1, top + module_pixels - 1),
                fill="black",
            )
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _next_relationship_id(relationships: ET.Element) -> str:
    used = {
        item.get("Id", "")
        for item in relationships.findall(f"{{{REL_NS}}}Relationship")
    }
    index = 1
    while f"rId{index}" in used:
        index += 1
    return f"rId{index}"


def _append_anchored_picture(
    paragraph: ET.Element,
    *,
    relationship_id: str,
    document_property_id: int,
    name: str,
    x_points: float,
    y_points: float,
    width_points: float,
    height_points: float,
    relative_height: int,
) -> None:
    """Append a page-anchored image without disturbing template flow layout."""
    emu_per_point = 12700
    values = {
        "rid": relationship_id,
        "doc_id": str(document_property_id),
        "name": name,
        "x": str(round(x_points * emu_per_point)),
        "y": str(round(y_points * emu_per_point)),
        "cx": str(round(width_points * emu_per_point)),
        "cy": str(round(height_points * emu_per_point)),
        "height": str(relative_height),
    }
    run = ET.fromstring(
        f"""
        <w:r xmlns:w="{W_NS}"
             xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
             xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
             xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"
             xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
          <w:rPr><w:noProof/></w:rPr>
          <w:drawing>
            <wp:anchor distT="0" distB="0" distL="0" distR="0"
                       simplePos="0" relativeHeight="{values['height']}"
                       behindDoc="0" locked="1" layoutInCell="1" allowOverlap="1">
              <wp:simplePos x="0" y="0"/>
              <wp:positionH relativeFrom="page"><wp:posOffset>{values['x']}</wp:posOffset></wp:positionH>
              <wp:positionV relativeFrom="page"><wp:posOffset>{values['y']}</wp:posOffset></wp:positionV>
              <wp:extent cx="{values['cx']}" cy="{values['cy']}"/>
              <wp:effectExtent l="0" t="0" r="0" b="0"/>
              <wp:wrapNone/>
              <wp:docPr id="{values['doc_id']}" name="{values['name']}"/>
              <wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>
              <a:graphic>
                <a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
                  <pic:pic>
                    <pic:nvPicPr>
                      <pic:cNvPr id="{values['doc_id']}" name="{values['name']}"/>
                      <pic:cNvPicPr><a:picLocks noChangeAspect="1"/></pic:cNvPicPr>
                    </pic:nvPicPr>
                    <pic:blipFill>
                      <a:blip r:embed="{values['rid']}"/>
                      <a:stretch><a:fillRect/></a:stretch>
                    </pic:blipFill>
                    <pic:spPr>
                      <a:xfrm><a:off x="0" y="0"/><a:ext cx="{values['cx']}" cy="{values['cy']}"/></a:xfrm>
                      <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
                      <a:noFill/>
                    </pic:spPr>
                  </pic:pic>
                </a:graphicData>
              </a:graphic>
            </wp:anchor>
          </w:drawing>
        </w:r>
        """
    )
    paragraph.append(run)


def _fsms_category(required_scope: dict | None) -> str:
    for key, value in (required_scope or {}).items():
        try:
            if normalize_standard(key) != "FSMS" or not isinstance(value, dict):
                continue
        except ValueError:
            continue
        codes = [str(code).strip() for code in (value.get("codes") or []) if str(code).strip()]
        return ", ".join(codes)
    return ""


def values_for_audit_set(
    audit_set,
    standard: str,
    *,
    initial_date: date,
    issue_date: date,
    revision: str = "0",
    statement_of_applicability: str = "",
) -> CertificateValues:
    canonical = normalize_standard(standard)
    category = _fsms_category(getattr(audit_set, "required_scope", None))
    if canonical == "FSMS" and not category:
        category = str(getattr(audit_set, "ea_category", "") or "").strip()
    return CertificateValues(
        company_name=str(getattr(audit_set, "company_name", "") or "").strip(),
        company_address=str(getattr(audit_set, "company_address", "") or "").strip(),
        scope=str(getattr(audit_set, "scope_en", "") or getattr(audit_set, "scope_tr", "") or "").strip(),
        initial_date=initial_date,
        issue_date=issue_date,
        revision=str(revision or "0").strip(),
        validity_date=default_validity_date(issue_date),
        expiry_date=default_expiry_date(initial_date),
        certificate_number=certificate_number(canonical, initial_date, int(audit_set.plan_number)),
        category=category,
        statement_of_applicability=statement_of_applicability.strip(),
    )


def render_certificate_docx(
    standard: str,
    values: CertificateValues,
    *,
    scope_spacers_to_remove: int = 0,
    scope_font_size_half_points: int | None = None,
    verification_url: str | None = None,
) -> bytes:
    canonical = normalize_standard(standard)
    template = TEMPLATE_DIR / f"{canonical}.docx"
    if not template.exists():
        raise FileNotFoundError(f"Certificate template is missing for {canonical}")
    if scope_spacers_to_remove < 0:
        raise ValueError("scope_spacers_to_remove cannot be negative")
    if (
        scope_font_size_half_points is not None
        and not 16 <= scope_font_size_half_points <= 22
    ):
        raise ValueError("scope_font_size_half_points must be between 16 and 22")

    standard_text = STANDARD_SPECS[canonical][0]
    replacements = {
        "[[COMPANY]]": values.company_name,
        "[[ADDRESS]]": values.company_address,
        "[[STANDARD]]": standard_text,
        "[[SCOPE]]": values.scope,
        "[[CATEGORY]]": f"Category/Sub-Category: {values.category}" if values.category else "Category/Sub-Category:",
        "[[INITIAL_DATE]]": format_date(values.initial_date),
        "[[ISSUE_DATE]]": format_date(values.issue_date),
        "[[REVISION]]": values.revision,
        "[[VALIDITY_DATE]]": format_date(values.validity_date),
        "[[EXPIRY_DATE]]": format_date(values.expiry_date),
        "[[CERTIFICATE_NO]]": values.certificate_number,
        "[[SOA]]": values.statement_of_applicability or "—",
    }

    output = io.BytesIO()
    with zipfile.ZipFile(template) as source_zip, zipfile.ZipFile(output, "w") as output_zip:
        document_xml = ET.fromstring(source_zip.read("word/document.xml"))
        relationships_path = "word/_rels/document.xml.rels"
        relationships_original = source_zip.read(relationships_path)
        relationships_xml = ET.fromstring(relationships_original)
        parent_map = {child: parent for parent in document_xml.iter() for child in parent}
        found: set[str] = set()
        scope_paragraph = None
        category_paragraph = None
        for node in document_xml.findall(".//w:t", W):
            token = node.text or ""
            if token in replacements:
                found.add(token)
                node.text = replacements[token]
                if token == "[[SCOPE]]":
                    ancestor = parent_map.get(node)
                    while ancestor is not None and ancestor.tag != f"{{{W_NS}}}p":
                        ancestor = parent_map.get(ancestor)
                    scope_paragraph = ancestor
                if token == "[[CATEGORY]]":
                    ancestor = parent_map.get(node)
                    while ancestor is not None and ancestor.tag != f"{{{W_NS}}}p":
                        ancestor = parent_map.get(ancestor)
                    category_paragraph = ancestor
                if token == "[[CERTIFICATE_NO]]":
                    # The source certificate keeps the identifier on one line.
                    # Remove the template's inherited left indent from both the
                    # DrawingML and VML fallback copies of this value cell.
                    ancestor = parent_map.get(node)
                    while ancestor is not None and ancestor.tag != f"{{{W_NS}}}p":
                        ancestor = parent_map.get(ancestor)
                    if ancestor is not None:
                        # Textbox-based templates keep the number inside a
                        # table cell, where inherited cell indentation can
                        # wrap the identifier.  ENMS and MDQMS intentionally
                        # position the value with a top-level paragraph; its
                        # indent is the horizontal coordinate and must remain.
                        container = parent_map.get(ancestor)
                        inside_table_cell = False
                        while container is not None:
                            if container.tag == f"{{{W_NS}}}tc":
                                inside_table_cell = True
                                break
                            container = parent_map.get(container)
                        if inside_table_cell:
                            indent = ancestor.find("w:pPr/w:ind", W)
                            if indent is not None:
                                indent.set(f"{{{W_NS}}}left", "0")

        required = {
            "[[COMPANY]]", "[[ADDRESS]]", "[[STANDARD]]", "[[SCOPE]]",
            "[[INITIAL_DATE]]", "[[ISSUE_DATE]]", "[[REVISION]]",
            "[[VALIDITY_DATE]]", "[[EXPIRY_DATE]]", "[[CERTIFICATE_NO]]",
        }
        missing = required - found
        if missing:
            raise ValueError(f"Certificate template {canonical} is missing mapped tokens: {sorted(missing)}")

        if scope_font_size_half_points is not None and scope_paragraph is not None:
            for run in scope_paragraph.findall(".//w:r", W):
                run_properties = run.find("w:rPr", W)
                if run_properties is None:
                    run_properties = ET.Element(f"{{{W_NS}}}rPr")
                    run.insert(0, run_properties)
                for property_name in ("sz", "szCs"):
                    size = run_properties.find(f"w:{property_name}", W)
                    if size is None:
                        size = ET.SubElement(run_properties, f"{{{W_NS}}}{property_name}")
                    size.set(f"{{{W_NS}}}val", str(scope_font_size_half_points))

        # The source certificates use six empty flow paragraphs between the
        # scope and the fixed lower information block. When a scope wraps to
        # additional lines, those unused spacers can be removed one at a time
        # without changing fonts, sizes, logos or mapped content. This gives
        # the Linux PDF renderer a deterministic way to keep the controlled
        # certificate design on one page.
        spacer_anchor = (
            category_paragraph
            if category_paragraph is not None
            else scope_paragraph
        )
        if scope_spacers_to_remove and spacer_anchor is not None:
            body = parent_map.get(spacer_anchor)
            if body is not None:
                siblings = list(body)
                scope_index = siblings.index(spacer_anchor)
                removed = 0
                for paragraph in siblings[scope_index + 1:]:
                    if removed >= scope_spacers_to_remove:
                        break
                    if paragraph.tag != f"{{{W_NS}}}p":
                        break
                    text = "".join(
                        (item.text or "") for item in paragraph.findall(".//w:t", W)
                    ).strip()
                    has_positioned_content = any(
                        paragraph.find(f".//{tag}") is not None
                        for tag in (
                            f"{{{W_NS}}}drawing",
                            f"{{{W_NS}}}pict",
                            "{http://schemas.openxmlformats.org/markup-compatibility/2006}AlternateContent",
                        )
                    )
                    if text or has_positioned_content:
                        break
                    body.remove(paragraph)
                    removed += 1

        added_parts: dict[str, bytes] = {}
        if verification_url:
            approval_paragraph = next(
                (
                    parent_map.get(node)
                    for node in document_xml.findall(".//w:t", W)
                    if (node.text or "").strip().casefold() == "approval"
                ),
                None,
            )
            while (
                approval_paragraph is not None
                and approval_paragraph.tag != f"{{{W_NS}}}p"
            ):
                approval_paragraph = parent_map.get(approval_paragraph)
            if approval_paragraph is None:
                raise ValueError(f"Certificate template {canonical} is missing the Approval anchor")

            doc_property_ids = [
                int(node.get("id", "0"))
                for node in document_xml.iter()
                if node.tag.endswith("}docPr") and node.get("id", "").isdigit()
            ]
            next_doc_property_id = max(doc_property_ids, default=0) + 1

            qr_relationship_id = _next_relationship_id(relationships_xml)
            ET.SubElement(
                relationships_xml,
                f"{{{REL_NS}}}Relationship",
                {
                    "Id": qr_relationship_id,
                    "Type": IMAGE_REL_TYPE,
                    "Target": "media/certiva_iaf_qr.png",
                },
            )
            signature_relationship_id = _next_relationship_id(relationships_xml)
            ET.SubElement(
                relationships_xml,
                f"{{{REL_NS}}}Relationship",
                {
                    "Id": signature_relationship_id,
                    "Type": IMAGE_REL_TYPE,
                    "Target": "media/certiva_approval_signature.png",
                },
            )

            # Page-relative anchors make Word and PDF conversion share the same
            # visual placement instead of painting a second layout onto the PDF.
            layout = CERTIFICATE_ASSET_LAYOUTS[canonical]
            qr_x, qr_y, qr_width, qr_height = layout["qr"]
            sig_x, sig_y, sig_width, sig_height = layout["signature"]
            _append_anchored_picture(
                approval_paragraph,
                relationship_id=qr_relationship_id,
                document_property_id=next_doc_property_id,
                name="IAF CertSearch Verification QR",
                x_points=qr_x,
                y_points=qr_y,
                width_points=qr_width,
                height_points=qr_height,
                relative_height=251660292,
            )
            _append_anchored_picture(
                approval_paragraph,
                relationship_id=signature_relationship_id,
                document_property_id=next_doc_property_id + 1,
                name="IFC Approval Signature",
                x_points=sig_x,
                y_points=sig_y,
                width_points=sig_width,
                height_points=sig_height,
                relative_height=251660293,
            )
            added_parts = {
                "word/media/certiva_iaf_qr.png": qr_png_bytes(verification_url),
                "word/media/certiva_approval_signature.png": approval_signature_png_bytes(),
            }

        updated_xml = ET.tostring(document_xml, encoding="utf-8", xml_declaration=True)
        # LibreOffice (used by the production PDF converter) rejects OPC
        # relationship parts whose package namespace is emitted with an
        # arbitrary prefix (for example ``ns0:Relationships``).  Preserve the
        # package's canonical default namespace when adding the Word-only QR
        # and approval-signature relationships.
        ET.register_namespace("", REL_NS)
        updated_relationships = (
            ET.tostring(
                relationships_xml,
                encoding="utf-8",
                xml_declaration=True,
            )
            if verification_url
            else relationships_original
        )
        for info in source_zip.infolist():
            if info.filename == "word/document.xml":
                content = updated_xml
            elif info.filename == relationships_path:
                content = updated_relationships
            else:
                content = source_zip.read(info)
            output_zip.writestr(info, content)
        for filename, content in added_parts.items():
            output_zip.writestr(filename, content)
    return output.getvalue()
