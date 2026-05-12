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
You are parsing an auditor CV or IFC form (FR.201). Extract all available fields. \
Return ONLY valid JSON with these keys:
name, email, phone, mobile, role, \
education (list of {degree, institution, year}), \
languages (list of {language, level}), \
field_of_expertise, \
ea_codes (list of strings like "EA 3", "EA 18"), \
accreditation_bodies (list of strings like "UAF", "TURKAK"), \
standard_qualifications (list of {standard_code, technical_depth, experience_years}), \
work_experience (list of {employer, position, start_date, end_date, description}), \
training_records (list of {training_date, institution, subject, duration_days, standard_code, certificate_available}).
Use null for any field not found. \
EA codes are often inferred from the expertise/scope description — look for sector codes, \
NACE/EA codes, or technical scope mentions.\
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

        result = json.loads(raw)
        logger.info("[Auditors/Extractor] Parsed '%s' — name=%s", filename, result.get("name"))
        return result

    except Exception as exc:
        logger.error("[Auditors/Extractor] Failed on '%s': %s", filename, exc, exc_info=True)
        return {"error": str(exc)}
