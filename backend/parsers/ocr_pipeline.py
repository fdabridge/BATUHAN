"""
BATUHAN — OCR Pipeline (T9)
Handles text extraction from images (PNG, JPG, TIFF) and scanned PDFs.
Flags all output as OCR-sourced for traceability.
"""

from __future__ import annotations
import logging
from pathlib import Path
from schemas.models import ParsedDocument

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp"}

# Tesseract language string — English + Turkish.
# tesseract-ocr-tur must be installed in the Docker image (it is, see Dockerfile).
# Using both avoids garbled output for Turkish characters (ş, ı, ğ, ü, ö, ç).
_OCR_LANG = "eng+tur"


def _ocr_image_file(path: str) -> str:
    """Run Tesseract OCR on a single image file."""
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(path)
        text = pytesseract.image_to_string(img, lang=_OCR_LANG)
        return text.strip()
    except ImportError:
        logger.error("pytesseract or Pillow not installed. OCR unavailable.")
        return ""
    except Exception as e:
        logger.error(f"OCR failed for {path}: {e}")
        return ""


def _is_scanned_pdf(path: str) -> bool:
    """
    Heuristic: if pdfplumber extracts very little text from a PDF,
    treat it as scanned and run OCR on its pages.
    Both page_count and total_chars are computed inside the `with` block
    while the file is still open, so the page list is always valid.
    """
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            pages = pdf.pages
            page_count = max(1, len(pages))
            total_chars = sum(len(page.extract_text() or "") for page in pages)
        # If fewer than 100 chars per page on average, likely scanned
        is_scanned = (total_chars / page_count) < 100
        logger.debug(
            f"[OCR] Scanned-PDF check: {Path(path).name} | "
            f"{page_count} pages | {total_chars} chars | scanned={is_scanned}"
        )
        return is_scanned
    except Exception as e:
        logger.warning(f"[OCR] _is_scanned_pdf check failed for {Path(path).name}: {e}")
        return False


def _ocr_scanned_pdf(path: str) -> str:
    """Convert each page of a scanned PDF to image and OCR it."""
    try:
        import fitz  # PyMuPDF
        import pytesseract
        from PIL import Image
        import io

        doc = fitz.open(path)
        texts: list[str] = []
        for page in doc:
            pix = page.get_pixmap(dpi=200)
            img_bytes = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_bytes))
            text = pytesseract.image_to_string(img, lang=_OCR_LANG)
            if text.strip():
                texts.append(text.strip())
        doc.close()
        return "\n".join(texts)
    except ImportError:
        logger.error("PyMuPDF or pytesseract not installed. Scanned PDF OCR unavailable.")
        return ""
    except Exception as e:
        logger.error(f"Scanned PDF OCR failed for {path}: {e}")
        return ""


def ocr_file(path: str) -> ParsedDocument | None:
    """
    Run OCR on a single file if it is an image or a scanned PDF.
    Returns a ParsedDocument flagged as OCR-sourced, or None if not applicable.
    """
    suffix = Path(path).suffix.lower()
    filename = Path(path).name

    if suffix in IMAGE_EXTENSIONS:
        text = _ocr_image_file(path)
        return ParsedDocument(
            filename=filename,
            text=text,
            is_ocr_sourced=True,
            char_count=len(text),
        )

    if suffix == ".pdf" and _is_scanned_pdf(path):
        logger.info(f"Detected scanned PDF, running OCR: {filename}")
        text = _ocr_scanned_pdf(path)
        return ParsedDocument(
            filename=filename,
            text=text,
            is_ocr_sourced=True,
            char_count=len(text),
        )

    return None  # Not an OCR candidate


def run_ocr_pipeline(file_paths: list[str]) -> list[ParsedDocument]:
    """
    Process all files that require OCR.
    Returns list of ParsedDocument objects flagged as OCR-sourced.
    Non-OCR files are silently skipped (handled by text_extractor).
    """
    results: list[ParsedDocument] = []
    for path in file_paths:
        doc = ocr_file(path)
        if doc is not None:
            if doc.text:
                logger.info(f"OCR extracted {doc.char_count} chars from: {doc.filename}")
            else:
                logger.warning(f"OCR returned empty text for: {doc.filename}")
            results.append(doc)
    return results

