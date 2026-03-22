"""
BATUHAN — Step A: Evidence Traceability (T14)
Links extracted evidence items back to their source documents.
Flags weak/unclear items. Ensures no raw documents pass forward to Prompt B.
Only the validated ExtractedEvidence object proceeds to the next step.
"""

from __future__ import annotations
import re
import logging
from backend.schemas.models import ExtractedEvidence, EvidenceItem, ParsedDocument

logger = logging.getLogger(__name__)


def _normalise(text: str) -> str:
    """Lowercase, replace word separators with spaces, strip remaining punctuation."""
    text = text.lower()
    # Replace underscores and hyphens with spaces so filenames like
    # "quality_manual" and "quality-manual" match "quality manual" in statements
    text = text.replace("_", " ").replace("-", " ")
    return re.sub(r"[^a-z0-9 ]", "", text).strip()


def _filename_stem(filename: str) -> str:
    """Return the filename without extension, normalised (underscores → spaces)."""
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    return _normalise(stem)


def _find_source(statement: str, corpus: list[ParsedDocument]) -> str | None:
    """
    Attempt to link an evidence statement to its source document.
    Strategy:
    1. Check if the document filename stem (normalised) appears in the normalised statement.
    2. Check for a 5-word phrase overlap between statement and document text.
    Returns the filename of the best match, or None.
    """
    stmt_normalised = _normalise(statement)

    # Strategy 1: filename stem mentioned in normalised statement
    for doc in corpus:
        stem = _filename_stem(doc.filename)
        if stem and stem in stmt_normalised:
            return doc.filename

    # Strategy 2: unique phrase overlap (5-consecutive-word n-gram match)
    stmt_words = stmt_normalised.split()
    for doc in corpus:
        if not doc.text:
            continue
        doc_normalised = _normalise(doc.text)
        # Check for any 5+ consecutive word run from statement appearing in doc
        for start in range(max(1, len(stmt_words) - 4)):
            end = min(start + 5, len(stmt_words))
            phrase = " ".join(stmt_words[start:end])
            if phrase and phrase in doc_normalised:
                return doc.filename

    return None


def attach_traceability(
    evidence: ExtractedEvidence,
    corpus: list[ParsedDocument],
) -> ExtractedEvidence:
    """
    Iterate over all EvidenceItems and attempt to attach a source_filename.
    Returns the same ExtractedEvidence with source_filename populated where found.
    Items that cannot be traced remain with source_filename=None.
    """
    from backend.pipeline.step_a.evidence_parser import SECTION_FIELD_MAP

    traced = 0
    total = 0

    for field_name in SECTION_FIELD_MAP.values():
        items: list[EvidenceItem] = getattr(evidence, field_name, [])
        updated: list[EvidenceItem] = []
        for item in items:
            total += 1
            source = _find_source(item.statement, corpus)
            if source:
                traced += 1
            updated.append(EvidenceItem(
                statement=item.statement,
                source_filename=source,
                is_weak=item.is_weak,
            ))
        setattr(evidence, field_name, updated)

    logger.info(
        f"[Traceability] {traced}/{total} evidence items linked to source documents."
    )
    if traced == 0 and total > 0:
        logger.warning(
            "[Traceability] No evidence items could be traced to source documents. "
            "This may indicate very short documents or heavily paraphrased extraction."
        )

    return evidence


def build_traceability_report(evidence: ExtractedEvidence) -> str:
    """
    Build a human-readable traceability summary for the audit trail.
    Lists each section, each item, its source, and weak flag.
    """
    from backend.pipeline.step_a.evidence_parser import SECTION_FIELD_MAP

    lines = [f"TRACEABILITY REPORT — Job: {evidence.job_id}\n"]
    lines.append("=" * 60)

    for section_title, field_name in SECTION_FIELD_MAP.items():
        items: list[EvidenceItem] = getattr(evidence, field_name, [])
        lines.append(f"\n## {section_title} ({len(items)} items)")
        for i, item in enumerate(items, 1):
            src = item.source_filename or "source not identified"
            weak = " ⚠ WEAK" if item.is_weak else ""
            lines.append(f"  {i}. [{src}]{weak}")
            lines.append(f"     {item.statement}")

    traced = sum(
        1
        for field_name in SECTION_FIELD_MAP.values()
        for item in getattr(evidence, field_name, [])
        if item.source_filename
    )
    total = sum(
        len(getattr(evidence, field_name, []))
        for field_name in SECTION_FIELD_MAP.values()
    )
    weak = sum(
        1
        for field_name in SECTION_FIELD_MAP.values()
        for item in getattr(evidence, field_name, [])
        if item.is_weak
    )

    lines.append("\n" + "=" * 60)
    lines.append(f"Total items : {total}")
    lines.append(f"Traced      : {traced} ({100 * traced // max(total, 1)}%)")
    lines.append(f"Weak/unclear: {weak}")

    return "\n".join(lines)

