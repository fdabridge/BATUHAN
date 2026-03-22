"""
BATUHAN — Sample Report Style Extractor (T11)
Parses sample reports to extract ONLY style, tone, and structure guidance.
NEVER passes company names, document names, data, or sentences to Prompt B.
Builds a StyleGuidance object that is safe to inject into the prompt.
"""

from __future__ import annotations
import re
import logging
from pathlib import Path
from schemas.models import StyleGuidance, ParsedDocument
from parsers.text_extractor import extract_text

logger = logging.getLogger(__name__)

# Patterns that indicate content that must be blocked from style guidance
_BLOCKED_PATTERNS = [
    r"\b[A-Z][a-z]+ (Ltd|LLC|GmbH|Inc|Corp|S\.A\.|A\.Ş\.)\b",  # company names
    r"\b(ISO|EN|BS) \d{4,5}(:\d{4})?\b",                         # standard refs with year
    r"\b\d{4}-\d{2}-\d{2}\b",                                     # dates
    r"\b[A-Z]{2,}-\d{3,}\b",                                      # document codes
]

# Sentence-level indicators of audit writing style
_STYLE_INDICATORS = [
    "the audit team",
    "it was confirmed",
    "evidence was observed",
    "the organisation demonstrated",
    "records were reviewed",
    "the auditor confirmed",
    "based on the documented",
    "the available evidence",
    "limited documented evidence",
    "the management review",
    "internal audit",
    "nonconformity",
    "corrective action",
    "continual improvement",
    "top management",
    "interested parties",
    "risk and opportunity",
]

# Structure/section logic phrases (safe to note as style)
_STRUCTURE_INDICATORS = [
    "scope of certification",
    "audit objectives",
    "audit findings",
    "audit conclusion",
    "areas of strength",
    "opportunities for improvement",
    "conformity",
    "nonconformity",
    "observation",
]


def _contains_blocked_content(text: str) -> bool:
    for pattern in _BLOCKED_PATTERNS:
        if re.search(pattern, text):
            return True
    return False


def _extract_style_notes(text: str) -> list[str]:
    """Find sentences that demonstrate audit writing style."""
    notes: list[str] = []
    sentences = re.split(r"(?<=[.!?])\s+", text)
    for sentence in sentences:
        s = sentence.strip()
        if len(s) < 20 or len(s) > 300:
            continue
        if _contains_blocked_content(s):
            continue
        lower = s.lower()
        if any(indicator in lower for indicator in _STYLE_INDICATORS):
            notes.append(s)
    return notes[:20]  # Cap at 20 style examples


def _extract_structure_notes(text: str) -> list[str]:
    """Find section-logic phrases that indicate report structure."""
    notes: list[str] = []
    lower = text.lower()
    for indicator in _STRUCTURE_INDICATORS:
        if indicator in lower:
            notes.append(f"Section type observed: '{indicator}'")
    return list(set(notes))


def _extract_blocked_names(text: str) -> list[str]:
    """Extract company names from sample to add to the block list."""
    blocked: list[str] = []
    for pattern in [r"\b[A-Z][a-z]+ (Ltd|LLC|GmbH|Inc|Corp|S\.A\.|A\.Ş\.)\b"]:
        matches = re.findall(pattern, text)
        blocked.extend(matches)
    return list(set(blocked))


def extract_style_from_sample(parsed_doc: ParsedDocument) -> StyleGuidance:
    """Extract safe style guidance from a single parsed sample report."""
    text = parsed_doc.text
    tone_notes = _extract_style_notes(text)
    structure_notes = _extract_structure_notes(text)
    blocked_names = _extract_blocked_names(text)

    logger.info(
        f"Style extracted from '{parsed_doc.filename}': "
        f"{len(tone_notes)} tone notes, {len(structure_notes)} structure notes, "
        f"{len(blocked_names)} company names blocked."
    )
    return StyleGuidance(
        tone_notes=tone_notes,
        structure_notes=structure_notes,
        blocked_company_names=blocked_names,
        blocked_phrases=[],
    )


def build_style_guidance(sample_paths: list[str]) -> StyleGuidance:
    """
    Process all sample report files and merge into a single StyleGuidance object.
    Safe to pass directly to Prompt B.
    """
    merged = StyleGuidance()
    for path in sample_paths:
        filename = Path(path).name
        text = extract_text(path)
        if not text.strip():
            logger.warning(f"No text extracted from sample report: {filename}")
            continue
        doc = ParsedDocument(filename=filename, text=text, char_count=len(text))
        guidance = extract_style_from_sample(doc)
        merged.tone_notes.extend(guidance.tone_notes)
        merged.structure_notes.extend(guidance.structure_notes)
        merged.blocked_company_names.extend(guidance.blocked_company_names)

    # Deduplicate
    merged.tone_notes = list(dict.fromkeys(merged.tone_notes))[:30]
    merged.structure_notes = list(dict.fromkeys(merged.structure_notes))
    merged.blocked_company_names = list(set(merged.blocked_company_names))

    logger.info(
        f"Final StyleGuidance: {len(merged.tone_notes)} tone notes, "
        f"{len(merged.blocked_company_names)} blocked company names."
    )
    return merged


def format_style_guidance_for_prompt(guidance: StyleGuidance) -> str:
    """Format StyleGuidance as a safe string for injection into Prompt B."""
    lines = ["STYLE GUIDANCE (from sample reports — for tone and structure only):\n"]
    if guidance.tone_notes:
        lines.append("Tone examples (do NOT copy — use as style reference only):")
        for note in guidance.tone_notes[:10]:
            lines.append(f"  - {note}")
    if guidance.structure_notes:
        lines.append("\nSection structure observed in samples:")
        for note in guidance.structure_notes:
            lines.append(f"  - {note}")
    if guidance.blocked_company_names:
        lines.append("\nDO NOT use these company names (from samples — blocked):")
        for name in guidance.blocked_company_names:
            lines.append(f"  - {name}")
    return "\n".join(lines)

