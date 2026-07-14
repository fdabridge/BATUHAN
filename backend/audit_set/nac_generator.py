"""
BATUHAN — AI generation of suggested Non-Applicable Clauses (NAC).

Uses Claude to analyse the organisation scope + selected ISO standards and
return a list of clauses that are likely structurally non-applicable, each
with a justification.  The result is *suggested* only — the caller does not
persist it; the user reviews and explicitly saves via the planning endpoint.
"""
from __future__ import annotations
import json
import logging
import re

from audit_set.db_models import AuditSet
from config.clause_configs.loader import load_clause_config
from config.clause_configs.schema import Applicability
from config.settings import get_settings

logger = logging.getLogger(__name__)

# Standard abbr (as stored in audit_set.standards) → human-readable ISO name
_STD_TO_ISO: dict[str, str] = {
    "QMS":        "ISO 9001:2015",
    "EMS":        "ISO 14001:2015",
    "OHSMS":      "ISO 45001:2018",
    "FSMS":       "ISO 22000:2018",
    "FSSC 22000": "FSSC 22000 v6",
    "ISMS":       "ISO/IEC 27001:2022",
    "MDMS":       "ISO 13485:2016",
    "MDQMS":      "ISO 13485:2016",
    "ENMS":       "ISO 50001:2018",
    "EnMS":       "ISO 50001:2018",
    "ABMS":       "ISO 37001:2016",
    "CMS":        "ISO 37301:2021",
}

_ISO_TO_CODE: dict[str, str] = {
    "ISO 9001:2015": "QMS",
    "ISO 14001:2015": "EMS",
    "ISO 45001:2018": "OHSMS",
    "ISO 22000:2018": "FSMS",
    "FSSC 22000 v6": "FSMS",
    "ISO/IEC 27001:2022": "ISMS",
    "ISO 13485:2016": "MDQMS",
    "ISO 50001:2018": "ENMS",
    "ISO 37001:2016": "ABMS",
}


def _na_candidate_map(standards: list[str]) -> dict[str, dict[str, str]]:
    """Return the only clauses the AI is allowed to suggest as N/A."""
    result: dict[str, dict[str, str]] = {}
    for abbr in standards or []:
        iso = _STD_TO_ISO.get(abbr, abbr)
        code = _ISO_TO_CODE.get(iso) or abbr
        try:
            config = load_clause_config(code)
        except Exception as exc:
            logger.warning("[NAC] Clause config unavailable for %s/%s: %s", abbr, iso, exc)
            continue
        allowed = {
            c.clause_id: c.title
            for c in config.clauses
            if c.applicability in (Applicability.SCOPE_CONDITIONAL, Applicability.OPTIONAL)
        }
        if allowed:
            result[config.standard_name or iso] = allowed
    return result


def _candidate_prompt_block(candidates: dict[str, dict[str, str]]) -> str:
    if not candidates:
        return "No system-approved N/A candidate clauses are configured. Return no suggestions."
    lines: list[str] = []
    for standard, clauses in candidates.items():
        lines.append(f"{standard}:")
        for clause_id, title in clauses.items():
            lines.append(f"  - {clause_id}: {title}")
    return "\n".join(lines)


def _filter_suggestions(suggestions: list, candidates: dict[str, dict[str, str]]) -> list[dict]:
    if not candidates:
        return []
    candidate_by_standard = {
        standard.lower().replace("iso/iec", "iso").replace(" ", ""): clauses
        for standard, clauses in candidates.items()
    }
    all_candidate_ids = {
        clause_id
        for clauses in candidates.values()
        for clause_id in clauses.keys()
    }
    filtered: list[dict] = []
    for item in suggestions:
        if not isinstance(item, dict):
            continue
        clause = str(item.get("clause") or "").strip()
        standard = str(item.get("standard") or "").strip()
        if not clause:
            continue
        std_key = standard.lower().replace("iso/iec", "iso").replace(" ", "")
        allowed_for_std = candidate_by_standard.get(std_key)
        if allowed_for_std is not None:
            if clause not in allowed_for_std:
                continue
            item["title"] = item.get("title") or allowed_for_std[clause]
        elif clause not in all_candidate_ids:
            continue
        filtered.append(item)
    return filtered


def generate_nac_ai(audit_set: AuditSet) -> dict:
    """Ask Claude which clauses are likely N/A for this audit set's scope.

    Returns: {"suggestions": [ {clause, standard, title, justification, confidence} ], "nac_text": str}
    Always returns a dict; on any error returns empty suggestions + empty nac_text.
    """
    standards = audit_set.standards or []
    standards_str = ", ".join(_STD_TO_ISO.get(c, c) for c in standards) or "Not specified"
    candidates = _na_candidate_map(standards)
    candidate_block = _candidate_prompt_block(candidates)

    prompt = f"""You are an experienced ISO certification auditor working for IFC Global LLC, a UAF-accredited certification body.

An organization has applied for certification to: {standards_str}

Organization scope of certification:
"{audit_set.scope_en or audit_set.scope_tr or 'Not specified'}"

Industry sector (EA code): {audit_set.ea_code or 'Not specified'}
Number of employees: {audit_set.effective_employees or 'Not specified'}

Your task: Identify which standard clauses are likely NOT APPLICABLE (N/A) for this organization, based on their scope of activities.

System-approved N/A candidate clauses:
{candidate_block}

Rules:
1. A clause is N/A only if it is STRUCTURALLY impossible for the organization to apply it given their activities (not just because they choose not to implement it)
2. For ISO 9001, clause 8.3 (Design and Development) is N/A if the organization only manufactures to external specifications and does not design products
3. For ISO 9001, clause 7.1.5.2 (Measurement Traceability) is N/A only if the organization uses no measurement equipment whose calibration affects product conformity
4. N/A exclusions must be justified
5. Do NOT exclude clauses that are difficult to implement — only those that genuinely don't apply to this activity
6. Only suggest clauses from the System-approved N/A candidate clauses list above. Never suggest an always-applicable clause.

For each suggested N/A clause, provide:
- Clause number
- Clause title
- Brief justification (1-2 sentences) based on the scope

Format your response as a JSON object:
{{
  "suggestions": [
    {{
      "clause": "8.3",
      "standard": "ISO 9001:2015",
      "title": "Design and Development of Products and Services",
      "justification": "The organization produces [product] to customer-provided specifications and does not design or develop new products.",
      "confidence": "high"
    }}
  ],
  "nac_text": "8.3 (ISO 9001:2015): Organization manufactures to external specifications — no design/development activities; ..."
}}

If no clauses are clearly N/A, return an empty suggestions list and an empty nac_text.
Be conservative — it's better to include fewer N/A exclusions than too many.
Return ONLY the JSON object, no surrounding prose.
"""

    try:
        import anthropic
        settings = get_settings()
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        message = client.messages.create(
            model=settings.claude_model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        response_text = message.content[0].text
    except Exception as exc:
        logger.warning("[NAC] Claude call failed for audit_set=%s: %s", audit_set.id, exc)
        return {"suggestions": [], "nac_text": ""}

    # Strip ```json fences if present then locate the JSON object
    cleaned = re.sub(r"^```(?:json)?\s*", "", response_text.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)
    json_match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not json_match:
        logger.warning("[NAC] No JSON object in Claude response for audit_set=%s", audit_set.id)
        return {"suggestions": [], "nac_text": ""}

    try:
        result = json.loads(json_match.group())
    except json.JSONDecodeError as exc:
        logger.warning("[NAC] JSON decode failed for audit_set=%s: %s", audit_set.id, exc)
        return {"suggestions": [], "nac_text": ""}

    suggestions = result.get("suggestions") or []
    nac_text = result.get("nac_text") or ""
    if not isinstance(suggestions, list):
        suggestions = []
    suggestions = _filter_suggestions(suggestions, candidates)
    if not isinstance(nac_text, str):
        nac_text = ""
    if suggestions:
        nac_text = "; ".join(
            f"{s.get('clause')} ({s.get('standard') or ''}): {s.get('justification') or s.get('title') or ''}".strip()
            for s in suggestions
        )
    else:
        nac_text = ""
    return {"suggestions": suggestions, "nac_text": nac_text}
