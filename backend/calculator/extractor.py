"""
BATUHAN — Audit Time Calculator: Claude Extractor
Uses Claude to read uploaded application form(s) and extract all structured
data needed for the audit time calculation.

The sector classification tables are embedded directly in the system prompt
so Claude never guesses — it always maps to the hardcoded categories.
"""

from __future__ import annotations
import json
import logging
import re
from typing import Optional

import anthropic

from config.settings import get_settings
from .models import ExtractedFormData, SiteInfo, StandardClassification

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt (sector tables embedded so Claude never guesses)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an ISO audit time calculation assistant. Your sole job is to read
certification application form(s) uploaded by a user and extract specific structured data.
You must never invent, guess, or approximate values. If a value is not present, output null.

=== SECTOR CLASSIFICATION TABLES ===

You must classify each selected standard into the correct category using ONLY these tables.
Never assign a category not listed below.

--- ISO 9001 Risk Categories ---
HIGH RISK sectors: Fishing, Mining, Quarrying, Food, Beverages, Tobacco, Coke, Petroleum,
  Nuclear fuel, Chemicals, Pharmaceuticals, Rubber, Plastics, Concrete, Cement, Lime,
  Machinery/Equipment, Electrical equipment, Shipbuilding, Space, Recovery/Recycling,
  Electricity supply, Gas supply, Complex construction (load-bearing), Health/Social

MEDIUM RISK sectors: Agriculture, Wood products, Printing, Non-metallic minerals, Basic metals,
  Optical equipment, Vehicles, Other unclassified industrial, Water supply,
  Simple construction (non-load-bearing), Transport/Storage/Communication,
  Engineering services, Public administration, Entertainment/Personal services

LOW RISK sectors: Textiles/Clothing, Leather, Pulp/Paper, Publishing,
  Wholesale/Retail trade, Hotels/Restaurants, Financial/Real estate/Leasing,
  IT products, Office services, Education

--- ISO 14001 / ISO 45001 Complexity Categories ---
HIGH: Mining, Quarrying, Tanning/Leather, Pulp production, Printing, Coke/Petroleum,
  Chemicals, Non-metallic minerals, Primary metals, Shipbuilding, Coal electricity,
  Gas distribution, Complex construction, Hazardous waste, Wastewater treatment

MEDIUM: Agriculture, Food processing, Textiles (excl. tanning), Wood, Paper (excl. pulp),
  Glass/Clay, Surface treatment metals, Machinery, Electrical/Optical equipment, Vehicles,
  Recycling, Non-coal electricity/gas, Water supply, Wholesale trade,
  Hotels, Transport, Engineering services, Cleaning services, Health

LOW: Wood (excl. impregnation), Paper products (excl. pulp/printing), Publishing,
  Rubber/Plastics, Hot/cold forming metals, Machinery assemblies, Electrical assembly,
  Retail trade, Restaurants, IT products

LIMITED: Transport management (no equipment), Financial services, Real estate,
  Company HQ/holding companies, Education

--- ISO 27001 ---
Uses square root method — no complexity category needed. Classify as: ISMS

--- ISO 13485 ---
No complexity category. Classify as: N/A

--- ISO 50001 ---
No sector category — uses energy complexity formula. Classify as: EnMS
  (Requires separate EnMS form with: annual energy consumption in TJ,
   number of energy types, number of Significant Energy Uses / SEUs)

=== OUTPUT FORMAT ===

Return ONLY valid JSON matching this exact schema. No markdown, no explanation.

{
  "org_name": "string",
  "standards": ["ISO 9001", "ISO 14001", ...],
  "audit_type": "Initial" | "Transfer" | "Scope Extension" | "Recertification",
  "scope": "string — exact text from form",
  "total_employees": integer,
  "office_employees": integer,
  "repetitive_employees": integer,
  "subcontractors": integer,
  "seasonal_employees": integer,
  "employees_per_shift": integer | null,
  "sites": [
    {"address": "string", "process_description": "string", "employee_count": integer}
  ],
  "haccp_studies": integer | null,
  "integration_yes_count": integer,
  "classifications": [
    {"standard": "ISO 9001", "sector_name": "Food/Beverages", "category": "High"}
  ],
  "annual_energy_tj": number | null,
  "num_energy_types": integer | null,
  "num_seus": integer | null
}

Rules:
- "standards" must only include standards that are explicitly ticked/selected on the form.
- "audit_type" must be one of the four exact strings above.
- "classifications" must have one entry per standard using ONLY the categories defined above.
- For ISO 27001: category = "ISMS". For ISO 13485: category = "N/A". For ISO 50001: category = "EnMS".
- "integration_yes_count": count the ticked YES answers on the IMS integration page (0–8).
- "sites": list only ADDITIONAL sites beyond the HQ. HQ employees are already in total_employees.
- All integer fields default to 0 if not found. All nullable fields default to null if not found.
"""


# ---------------------------------------------------------------------------
# Extraction function
# ---------------------------------------------------------------------------

def extract_form_data(document_texts: list[dict[str, str]]) -> ExtractedFormData:
    """
    Call Claude with the content of all uploaded form files and return ExtractedFormData.

    Args:
        document_texts: List of {"filename": str, "text": str} dicts from the parser.

    Returns:
        ExtractedFormData parsed from Claude's JSON response.
    """
    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    # Build user message: concatenate all documents
    parts = []
    for doc in document_texts:
        parts.append(f"=== FILE: {doc['filename']} ===\n{doc['text']}\n")
    user_content = "\n".join(parts)

    if not user_content.strip():
        raise ValueError("No readable text found in uploaded documents.")

    logger.info(f"Sending {len(document_texts)} document(s) to Claude for extraction "
                f"({sum(len(d['text']) for d in document_texts)} chars total)")

    response = client.messages.create(
        model=settings.claude_model,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    "Read the following certification application form(s) and extract all required "
                    "data. Return ONLY valid JSON as specified in your instructions.\n\n"
                    + user_content
                ),
            }
        ],
    )

    raw = response.content[0].text.strip()
    logger.debug(f"Claude raw extraction response ({len(raw)} chars): {raw[:300]}...")

    # Strip markdown fences if present
    raw_clean = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw_clean = re.sub(r"\s*```$", "", raw_clean, flags=re.IGNORECASE).strip()

    try:
        payload = json.loads(raw_clean)
    except json.JSONDecodeError as e:
        logger.error(f"Claude returned invalid JSON: {e}\nRaw: {raw[:500]}")
        raise ValueError(f"Claude returned invalid JSON: {e}") from e

    return _parse_payload(payload, raw)


def _parse_payload(payload: dict, raw: str) -> ExtractedFormData:
    """Convert the raw JSON dict from Claude into a validated ExtractedFormData."""
    sites = [
        SiteInfo(
            address=s.get("address", ""),
            process_description=s.get("process_description", ""),
            employee_count=int(s.get("employee_count", 0)),
        )
        for s in payload.get("sites", [])
    ]

    classifications = [
        StandardClassification(
            standard=c.get("standard", ""),
            sector_name=c.get("sector_name", ""),
            category=c.get("category", "Medium"),
        )
        for c in payload.get("classifications", [])
    ]

    return ExtractedFormData(
        org_name=payload.get("org_name", ""),
        standards=payload.get("standards", []),
        audit_type=payload.get("audit_type", "Initial"),
        scope=payload.get("scope", ""),
        total_employees=int(payload.get("total_employees", 0)),
        office_employees=int(payload.get("office_employees", 0)),
        repetitive_employees=int(payload.get("repetitive_employees", 0)),
        subcontractors=int(payload.get("subcontractors", 0)),
        seasonal_employees=int(payload.get("seasonal_employees", 0)),
        employees_per_shift=_opt_int(payload.get("employees_per_shift")),
        sites=sites,
        haccp_studies=_opt_int(payload.get("haccp_studies")),
        integration_yes_count=int(payload.get("integration_yes_count", 0)),
        classifications=classifications,
        annual_energy_tj=_opt_float(payload.get("annual_energy_tj")),
        num_energy_types=_opt_int(payload.get("num_energy_types")),
        num_seus=_opt_int(payload.get("num_seus")),
        raw_extraction=raw,
    )


def _opt_int(val) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _opt_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None

