"""
BATUHAN — Auditor Profile: Document extraction via Claude.

extract_auditor_from_document(file_bytes, filename) -> dict
  Accepts PDF or DOCX bytes, extracts text, then asks Claude to parse
  all auditor profile fields into a structured JSON dict.
  Returns the parsed dict (nulls allowed) or {"error": str}.
"""
from __future__ import annotations
import io
import json
import logging

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are parsing an auditor CV or IFC form (FR.201). Extract all available fields.
Return ONLY valid JSON with these keys:
  name, email, phone, mobile, role,
  education (list of {degree, institution, year}),
  languages (list of {language, level}),
  field_of_expertise,
  ea_codes (list of strings — use ONLY codes from the official IAF EA code list below),
  accreditation_bodies (list of strings like "UAF", "TURKAK"),
  standard_qualifications (list of {standard_code, accreditation_body, technical_depth, experience_years}),
  work_experience (list of {employer, position, start_date, end_date, description}),
  training_records (list of {training_date, institution, subject, duration_days, standard_code, certificate_available}).
Use null for any field not found.

OFFICIAL IAF EA CODE LIST — only use codes from this table. Format as "EA N" (e.g. "EA 3"):
EA 1  - Agriculture, forestry and fishing
EA 2  - Mining and quarrying
EA 3  - Food products, beverages and tobacco
EA 4  - Textiles and textile products
EA 5  - Leather and leather products
EA 6  - Wood and wood products
EA 7  - Pulp, paper and paper products
EA 8  - Publishing companies
EA 9  - Printing companies
EA 10 - Manufacture of coke and refined petroleum products
EA 11 - Nuclear fuel
EA 12 - Chemicals, chemical products and fibres
EA 13 - Pharmaceuticals
EA 14 - Rubber and plastic products
EA 15 - Non-metallic mineral products
EA 16 - Concrete, cement, lime, plaster and similar products
EA 17 - Basic metals and fabricated metal products
EA 18 - Machinery and equipment
EA 19 - Electrical and optical equipment
EA 20 - Shipbuilding
EA 21 - Aerospace
EA 22 - Other transport equipment
EA 23 - Manufacturing not elsewhere classified
EA 24 - Recycling
EA 25 - Electricity supply
EA 26 - Gas supply
EA 27 - Water supply
EA 28 - Construction
EA 29 - Wholesale and retail trade; repair of motor vehicles, motorcycles and personal/household goods
EA 30 - Hotels and restaurants
EA 31 - Transport, storage and communication
EA 32 - Financial intermediation, real estate, renting
EA 33 - Information technology
EA 34 - Engineering services
EA 35 - Other services
EA 36 - Public administration
EA 37 - Education
EA 38 - Health and social work
EA 39 - Other social services

STANDARD QUALIFICATIONS RULES:
- standard_code must be the ISO standard reference, e.g. "ISO 9001", "ISO 14001", "ISO 45001", "ISO 27001".
- For each qualification, include accreditation_body if mentioned (e.g. "UAF", "TURKAK", "DAkkS").
- technical_depth: one of "Lead Auditor", "Team Auditor", "Technical Expert".
- experience_years: total years of documented auditing experience for that standard (integer).
- A qualification should only be included if there is evidence of BOTH: (a) relevant training/certification AND (b) auditing experience. If only training is mentioned with no experience, still include it but set experience_years to 0.
"""


def _extract_text_docx(file_bytes: bytes) -> str:
    import docx  # python-docx
    doc = docx.Document(io.BytesIO(file_bytes))
    parts = []
    for para in doc.paragraphs:
        if para.text.strip():
            parts.append(para.text.strip())
    for table in doc.tables:
        for row in table.rows:
            row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
            if row_text:
                parts.append(row_text)
    return "\n".join(parts)


def _extract_text_pdf(file_bytes: bytes) -> str:
    import pdfplumber
    text_parts = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                text_parts.append(t)
    return "\n".join(text_parts)


def extract_auditor_from_document(file_bytes: bytes, filename: str) -> dict:
    """
    Parse an auditor document (PDF or DOCX) into a structured profile dict.
    Returns the dict (with null values for missing fields) or {"error": str}.
    """
    try:
        lower = filename.lower()
        if lower.endswith(".docx") or lower.endswith(".doc"):
            text = _extract_text_docx(file_bytes)
        elif lower.endswith(".pdf"):
            text = _extract_text_pdf(file_bytes)
        else:
            return {"error": f"Unsupported file type: {filename}. Use PDF or DOCX."}

        if not text.strip():
            return {"error": "Could not extract any text from the document."}

        from config.settings import get_settings
        import anthropic

        settings = get_settings()
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        msg = client.messages.create(
            model=settings.claude_model,
            max_tokens=2048,
            system=_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"Document text:\n\n{text[:12000]}",  # cap at ~12k chars
            }],
        )

        raw = msg.content[0].text.strip()

        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        if raw.endswith("```"):
            raw = raw[:-3].strip()

        # Use json_repair to handle any malformed JSON from Claude
        from json_repair import repair_json
        result = json.loads(repair_json(raw))

        # Validate and clean EA codes against official IAF list (EA 1–EA 39)
        VALID_EA_NUMBERS = set(range(1, 40))
        raw_ea = result.get("ea_codes") or []
        cleaned_ea = []
        for code in raw_ea:
            if isinstance(code, str):
                normalized = code.strip().upper()
                num_part = normalized[2:].strip() if normalized.startswith("EA") else normalized
                try:
                    num = int(num_part)
                    if num in VALID_EA_NUMBERS:
                        cleaned_ea.append(f"EA {num}")
                    else:
                        logger.warning("[Auditors/Extractor] Dropped invalid EA code: %s", code)
                except ValueError:
                    logger.warning("[Auditors/Extractor] Could not parse EA code: %s", code)
        result["ea_codes"] = cleaned_ea

        # Flag qualifications missing accreditation_body for human review
        for q in result.get("standard_qualifications") or []:
            if not q.get("accreditation_body"):
                q["_needs_review"] = True

        logger.info("[Auditors/Extractor] Parsed '%s' — name=%s", filename, result.get("name"))
        return result

    except Exception as exc:
        logger.error("[Auditors/Extractor] Failed on '%s': %s", filename, exc, exc_info=True)
        return {"error": str(exc)}
