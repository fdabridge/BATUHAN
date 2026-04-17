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

# ---------------------------------------------------------------------------
# Size limits — keep the prompt within Claude's practical sweet spot.
# Very large inputs slow inference without improving evidence quality.
# ---------------------------------------------------------------------------
_MAX_CHARS_PER_DOC   = 40_000   # ~10 k tokens per document
_MAX_CHARS_TOTAL     = 120_000  # ~30 k tokens total corpus cap


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

    Size limits (_MAX_CHARS_PER_DOC / _MAX_CHARS_TOTAL) prevent the prompt
    from growing so large that Claude inference times out or becomes very slow.
    Each document is truncated individually first, then the combined corpus
    is hard-capped to _MAX_CHARS_TOTAL.
    """
    parts: list[str] = []
    for doc in corpus:
        if not doc.text.strip():
            logger.warning(f"[CorpusBuilder] Skipping empty document: {doc.filename}")
            continue

        source_label = "[OCR-sourced]" if doc.is_ocr_sourced else "[Text-extracted]"
        text = doc.text.strip()

        # Per-document cap
        if len(text) > _MAX_CHARS_PER_DOC:
            logger.warning(
                f"[CorpusBuilder] '{doc.filename}' truncated: "
                f"{len(text):,} → {_MAX_CHARS_PER_DOC:,} chars"
            )
            text = text[:_MAX_CHARS_PER_DOC] + "\n[... truncated for prompt size ...]"

        logger.info(
            f"[CorpusBuilder] Including '{doc.filename}' {source_label} | {len(text):,} chars"
        )
        parts.append(
            f"=== DOCUMENT: {doc.filename} {source_label} ===\n"
            f"{text}\n"
            f"=== END OF DOCUMENT: {doc.filename} ==="
        )

    if not parts:
        logger.error("[CorpusBuilder] format_corpus_for_prompt: NO documents included — corpus will be empty!")
        return "[No readable content extracted from company documents]"

    combined = "\n\n".join(parts)

    # Total corpus cap
    if len(combined) > _MAX_CHARS_TOTAL:
        logger.warning(
            f"[CorpusBuilder] Total corpus truncated: "
            f"{len(combined):,} → {_MAX_CHARS_TOTAL:,} chars"
        )
        combined = combined[:_MAX_CHARS_TOTAL] + "\n\n[... corpus truncated for prompt size ...]"

    logger.info(
        f"[CorpusBuilder] Formatted corpus: {len(parts)} document(s) | "
        f"{len(combined):,} chars total (cap: {_MAX_CHARS_TOTAL:,})"
    )
    return combined

