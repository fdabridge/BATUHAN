"""
BATUHAN — Document Corpus Builder
Merges text extraction (T8) and OCR (T9) outputs into a single
unified document corpus ready for Prompt A injection.
"""

from __future__ import annotations
import logging
from backend.schemas.models import ParsedDocument
from backend.parsers.text_extractor import parse_documents
from backend.parsers.ocr_pipeline import run_ocr_pipeline

logger = logging.getLogger(__name__)


def build_corpus(file_paths: list[str]) -> list[ParsedDocument]:
    """
    Build the full document corpus from a list of file paths.
    - Text files (PDF/DOCX/TXT) → text_extractor
    - Image files and scanned PDFs → ocr_pipeline
    - Merges both into a single deduplicated list by filename.
    Returns list of ParsedDocument sorted by filename.
    """
    # Step 1: Standard text extraction (skips images)
    text_docs = parse_documents(file_paths)

    # Step 2: OCR for images and scanned PDFs
    ocr_docs = run_ocr_pipeline(file_paths)

    # Step 3: Merge — OCR results override text results for same filename
    # (in case a scanned PDF was also attempted by text extractor)
    merged: dict[str, ParsedDocument] = {}
    for doc in text_docs:
        merged[doc.filename] = doc
    for doc in ocr_docs:
        if doc.filename in merged and not merged[doc.filename].text.strip():
            # Replace empty text-extracted doc with OCR result
            merged[doc.filename] = doc
        elif doc.filename not in merged:
            merged[doc.filename] = doc

    corpus = sorted(merged.values(), key=lambda d: d.filename)

    total_chars = sum(d.char_count for d in corpus)
    ocr_count = sum(1 for d in corpus if d.is_ocr_sourced)
    logger.info(
        f"Corpus built: {len(corpus)} documents, "
        f"{ocr_count} OCR-sourced, {total_chars:,} total chars."
    )
    return corpus


def format_corpus_for_prompt(corpus: list[ParsedDocument]) -> str:
    """
    Format the document corpus as a string for injection into Prompt A.
    Each document is clearly labelled with its filename and OCR flag.
    """
    parts: list[str] = []
    for doc in corpus:
        if not doc.text.strip():
            logger.warning(f"Skipping empty document from corpus: {doc.filename}")
            continue
        source_label = f"[OCR-sourced]" if doc.is_ocr_sourced else "[Text-extracted]"
        parts.append(
            f"=== DOCUMENT: {doc.filename} {source_label} ===\n"
            f"{doc.text.strip()}\n"
            f"=== END OF DOCUMENT: {doc.filename} ==="
        )

    if not parts:
        return "[No readable content extracted from company documents]"

    return "\n\n".join(parts)

