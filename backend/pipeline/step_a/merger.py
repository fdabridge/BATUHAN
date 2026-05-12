"""
BATUHAN — Step A Evidence Merger
Consolidates per-standard evidence extractions into a single unified
ExtractedEvidence for integrated audits (2+ standards).
"""

from __future__ import annotations
import json
import logging
import re

from anthropic import Anthropic
from schemas.models import ExtractedEvidence, EvidenceItem

logger = logging.getLogger(__name__)

_CATEGORIES = [
    "company_overview",
    "scope_of_activities",
    "documented_information",
    "key_processes_and_functions",
    "evidence_of_system_implementation",
    "audit_relevant_records",
    "identified_gaps",
]


def merge_per_standard_evidence(
    per_standard_evidence: dict,  # {standard_code: ExtractedEvidence}
    client: Anthropic,
    model: str,
    max_tokens: int,
    temperature: float,
    job_id: str = "",
) -> ExtractedEvidence:
    """
    Takes per-standard evidence extractions and merges them into a single
    unified ExtractedEvidence. Shared clauses get unified treatment.
    Called only for integrated audits (2+ standards).
    """
    if len(per_standard_evidence) == 1:
        return list(per_standard_evidence.values())[0]

    # Build a text summary of all per-standard evidence for the merge prompt
    evidence_blocks = []
    for std_code, evidence in per_standard_evidence.items():
        block = f"=== {std_code} ===\n"
        for category in _CATEGORIES:
            items = getattr(evidence, category, [])
            if items:
                block += f"\n[{category}]\n"
                for item in items:
                    tag = f" [SOURCE: {item.source_filename}]" if item.source_filename else ""
                    weak = " [WEAK]" if item.is_weak else ""
                    block += f"- {item.statement}{tag}{weak}\n"
        evidence_blocks.append(block)

    combined_text = "\n\n".join(evidence_blocks)

    prompt = f"""You are merging evidence from multiple ISO standard audits into \
a single unified evidence set for an integrated audit report.

The evidence below was extracted separately for each standard. Your job is to:
1. Consolidate duplicate or overlapping evidence items (same fact cited in multiple standards)
2. Keep standard-specific evidence that is unique to one standard
3. For shared evidence (e.g. leadership, context, documented information), \
   write one unified statement that covers all relevant standards
4. Preserve ALL source filenames and weak flags

PER-STANDARD EVIDENCE:
{combined_text[:8000]}

Return the merged evidence in the exact same 7-category JSON format:

{{
  "company_overview": [
    {{"statement": "...", "source_filename": "...", "is_weak": false}}
  ],
  "scope_of_activities": [...],
  "documented_information": [...],
  "key_processes_and_functions": [...],
  "evidence_of_system_implementation": [...],
  "audit_relevant_records": [...],
  "identified_gaps": [...]
}}

Rules:
- Never invent evidence not present in the input
- Preserve is_weak=true for any item flagged weak in any standard
- Keep source_filename from the original item
- Aim for 30-60 items total across all categories
- Do not include empty arrays — omit categories with no evidence
"""

    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        raw = re.sub(r'^```json\s*', '', raw)
        raw = re.sub(r'^```\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        parsed = json.loads(raw)
        return _dict_to_evidence(parsed, job_id=job_id, raw_output=raw)

    except Exception as e:
        logger.warning(
            f"Evidence merge failed: {e}. "
            f"Falling back to concatenated evidence from all standards."
        )
        return _concatenate_evidence(per_standard_evidence, job_id=job_id)


def _evidence_to_dict(evidence: ExtractedEvidence) -> dict:
    return {cat: getattr(evidence, cat, []) for cat in _CATEGORIES}


def _dict_to_evidence(
    parsed: dict,
    job_id: str = "",
    raw_output: str = "",
) -> ExtractedEvidence:
    def parse_items(raw_list):
        items = []
        for item in (raw_list or []):
            items.append(EvidenceItem(
                statement=item.get("statement", ""),
                source_filename=item.get("source_filename") or None,
                is_weak=item.get("is_weak", False),
            ))
        return items

    return ExtractedEvidence(
        job_id=job_id,
        raw_output=raw_output,
        company_overview=parse_items(parsed.get("company_overview")),
        scope_of_activities=parse_items(parsed.get("scope_of_activities")),
        documented_information=parse_items(parsed.get("documented_information")),
        key_processes_and_functions=parse_items(parsed.get("key_processes_and_functions")),
        evidence_of_system_implementation=parse_items(parsed.get("evidence_of_system_implementation")),
        audit_relevant_records=parse_items(parsed.get("audit_relevant_records")),
        identified_gaps=parse_items(parsed.get("identified_gaps")),
    )


def _concatenate_evidence(
    per_standard_evidence: dict,
    job_id: str = "",
) -> ExtractedEvidence:
    """Fallback: simple concatenation of all per-standard evidence."""
    merged: dict[str, list] = {cat: [] for cat in _CATEGORIES}
    for evidence in per_standard_evidence.values():
        for cat in _CATEGORIES:
            merged[cat].extend(getattr(evidence, cat, []))
    return ExtractedEvidence(
        job_id=job_id,
        raw_output="[concatenated fallback — merge Claude call failed]",
        **merged,
    )
