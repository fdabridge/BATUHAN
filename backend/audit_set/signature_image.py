"""Helpers for keeping signature images transparent and PDF-safe."""
from __future__ import annotations

import base64
from io import BytesIO


PNG_DATA_PREFIX = "data:image/png;base64,"


def _split_data_url(image_data: str) -> bytes:
    raw = image_data or ""
    if raw.startswith("data:"):
        raw = raw.split(",", 1)[1]
    return base64.b64decode(raw)


def _clean_signature_rgba(image_bytes: bytes):
    from PIL import Image

    image = Image.open(BytesIO(image_bytes)).convert("RGBA")
    cleaned = []
    for r, g, b, a in image.getdata():
        if a == 0:
            cleaned.append((r, g, b, 0))
            continue

        light = min(r, g, b) >= 220
        pale_neutral = (r + g + b) >= 690 and (max(r, g, b) - min(r, g, b)) <= 45
        if light or pale_neutral:
            cleaned.append((255, 255, 255, 0))
        else:
            cleaned.append((r, g, b, a))

    image.putdata(cleaned)
    return image


def normalize_signature_data_url(image_data: str) -> str:
    """Return a PNG data URL with near-white background pixels made transparent."""
    image = _clean_signature_rgba(_split_data_url(image_data))
    out = BytesIO()
    image.save(out, format="PNG")
    return PNG_DATA_PREFIX + base64.b64encode(out.getvalue()).decode("ascii")


def signature_png_bytes(image_data: str) -> bytes:
    """Return cleaned RGBA PNG bytes for libraries that preserve PNG alpha."""
    image = _clean_signature_rgba(_split_data_url(image_data))
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def signature_pdf_streams(image_data: str) -> tuple[bytes, bytes]:
    """
    Return RGB image bytes plus an explicit alpha mask for PyMuPDF.

    Passing the alpha channel as `mask=` avoids white rectangles in downloaded
    PDFs even when the PDF library does not preserve PNG transparency from the
    main image stream.
    """
    image = _clean_signature_rgba(_split_data_url(image_data))

    rgb = image.convert("RGB")
    alpha = image.getchannel("A")

    rgb_out = BytesIO()
    mask_out = BytesIO()
    rgb.save(rgb_out, format="PNG")
    alpha.save(mask_out, format="PNG")
    return rgb_out.getvalue(), mask_out.getvalue()
