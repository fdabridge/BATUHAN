"""
BATUHAN — Document Corpus Builder
Merges text extraction (T8) and OCR (T9) outputs into a single
unified document corpus ready for Prompt A injection.
"""

from __future__ import annotations
import logging
from schemas.models import ParsedDocument
from parsers.text_extractor import parse_documents
from parsers.ocr_pipeline import run_ocr_pipeline

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

    # Step 3: Merge — keep the result with the higher char_count for each filename.
    # This ensures scanned PDFs (where pdfplumber returns a few garbage chars) are
    # overridden by the high-quality OCR result rather than the other way around.
    merged: dict[str, ParsedDocument] = {}
    for doc in text_docs:
        merged[doc.filename] = doc
    for doc in ocr_docs:
        existing = merged.get(doc.filename)
        if existing is None:
            merged[doc.filename] = doc
        elif doc.char_count > existing.char_count:
            logger.info(
                f"[CorpusBuilder] OCR ({doc.char_count:,} chars) > text-extract "
                f"({existing.char_count:,} chars) for '{doc.filename}' — preferring OCR."
            )
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
            logger.warning(f"[CorpusBuilder] Skipping empty document: {doc.filename}")
            continue
        source_label = "[OCR-sourced]" if doc.is_ocr_sourced else "[Text-extracted]"
        logger.info(
            f"[CorpusBuilder] Including '{doc.filename}' {source_label} | {doc.char_count:,} chars"
        )
        parts.append(
            f"=== DOCUMENT: {doc.filename} {source_label} ===\n"
            f"{doc.text.strip()}\n"
            f"=== END OF DOCUMENT: {doc.filename} ==="
        )

    if not parts:
        logger.error("[CorpusBuilder] format_corpus_for_prompt: NO documents included — corpus will be empty!")
        return "[No readable content extracted from company documents]"

    total_chars = sum(len(p) for p in parts)
    logger.info(
        f"[CorpusBuilder] Formatted corpus: {len(parts)} document(s) | ~{total_chars:,} chars total"
    )
    return "\n\n".join(parts)

