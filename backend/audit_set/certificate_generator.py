"""Generate IFC certificate DOCX/PDF pages from approved per-standard templates."""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = {"w": W_NS}
TEMPLATE_DIR = Path(__file__).with_name("certificate_templates")

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


def render_certificate_docx(standard: str, values: CertificateValues) -> bytes:
    canonical = normalize_standard(standard)
    template = TEMPLATE_DIR / f"{canonical}.docx"
    if not template.exists():
        raise FileNotFoundError(f"Certificate template is missing for {canonical}")

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
        found: set[str] = set()
        for node in document_xml.findall(".//w:t", W):
            if (node.text or "") in replacements:
                found.add(node.text or "")
                node.text = replacements[node.text or ""]

        required = {
            "[[COMPANY]]", "[[ADDRESS]]", "[[STANDARD]]", "[[SCOPE]]",
            "[[INITIAL_DATE]]", "[[ISSUE_DATE]]", "[[REVISION]]",
            "[[VALIDITY_DATE]]", "[[EXPIRY_DATE]]", "[[CERTIFICATE_NO]]",
        }
        missing = required - found
        if missing:
            raise ValueError(f"Certificate template {canonical} is missing mapped tokens: {sorted(missing)}")

        updated_xml = ET.tostring(document_xml, encoding="utf-8", xml_declaration=True)
        for info in source_zip.infolist():
            content = updated_xml if info.filename == "word/document.xml" else source_zip.read(info)
            output_zip.writestr(info, content)
    return output.getvalue()
