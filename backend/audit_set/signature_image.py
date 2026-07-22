"""Helpers for keeping signature images transparent and PDF-safe."""
from __future__ import annotations

import base64
from io import BytesIO


PNG_DATA_PREFIX = "data:image/png;base64,"
ALPHA_TRANSPARENT_CUTOFF = 12
PAPER_EDGE_SAMPLE = 8
PAPER_DISTANCE_CUTOFF = 64
TRIM_ALPHA_CUTOFF = 8
TRIM_MARGIN = 4


def _split_data_url(image_data: str) -> bytes:
    raw = image_data or ""
    if raw.startswith("data:"):
        raw = raw.split(",", 1)[1]
    return base64.b64decode(raw)


def _background_rgb(image) -> tuple[int, int, int] | None:
    """Estimate a scan/photo paper background from transparent image edges."""
    width, height = image.size
    if not width or not height:
        return None

    sample = max(1, min(PAPER_EDGE_SAMPLE, width // 3 or 1, height // 3 or 1))
    pixels = image.load()
    edge_pixels: list[tuple[int, int, int]] = []

    for x in range(width):
        for y in range(sample):
            r, g, b, a = pixels[x, y]
            if a > ALPHA_TRANSPARENT_CUTOFF:
                edge_pixels.append((r, g, b))
        for y in range(max(0, height - sample), height):
            r, g, b, a = pixels[x, y]
            if a > ALPHA_TRANSPARENT_CUTOFF:
                edge_pixels.append((r, g, b))

    for y in range(sample, max(sample, height - sample)):
        for x in range(sample):
            r, g, b, a = pixels[x, y]
            if a > ALPHA_TRANSPARENT_CUTOFF:
                edge_pixels.append((r, g, b))
        for x in range(max(0, width - sample), width):
            r, g, b, a = pixels[x, y]
            if a > ALPHA_TRANSPARENT_CUTOFF:
                edge_pixels.append((r, g, b))

    if not edge_pixels:
        return None

    edge_pixels.sort(key=lambda rgb: sum(rgb))
    bright_half = edge_pixels[len(edge_pixels) // 2 :]
    if not bright_half:
        return None

    return tuple(int(sum(rgb[i] for rgb in bright_half) / len(bright_half)) for i in range(3))


def _color_distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return sum((a[i] - b[i]) ** 2 for i in range(3)) ** 0.5


def _clean_signature_rgba(image_bytes: bytes):
    from PIL import Image

    image = Image.open(BytesIO(image_bytes)).convert("RGBA")
    background = _background_rgb(image)
    cleaned = []
    for r, g, b, a in image.getdata():
        if a <= ALPHA_TRANSPARENT_CUTOFF:
            cleaned.append((r, g, b, 0))
            continue

        channel_max = max(r, g, b)
        channel_min = min(r, g, b)
        brightness = (r + g + b) / 3
        saturation = channel_max - channel_min
        dark_ink = brightness < 175
        colored_ink = saturation > 70 and brightness < 230 and channel_min < 215
        strong_ink = dark_ink or colored_ink

        # Uploaded/scanned signatures often carry a paper-colored rectangle
        # that is not pure white after compression or anti-aliasing. Remove
        # any pixel close to the sampled edge background, but preserve dark or
        # strongly colored ink.
        white_paper = channel_min >= 232
        pale_paper = brightness >= 220 and saturation <= 55
        gray_halo = brightness >= 200 and saturation <= 25
        background_paper = (
            background is not None
            and brightness >= 145
            and _color_distance((r, g, b), background) <= PAPER_DISTANCE_CUTOFF
        )
        if not strong_ink and (white_paper or pale_paper or gray_halo or background_paper):
            cleaned.append((255, 255, 255, 0))
        else:
            cleaned.append((r, g, b, a))

    image.putdata(cleaned)
    return image


def _trim_transparent_edges(image):
    """Crop empty transparent canvas so PDF placement only covers signature ink."""
    alpha = image.getchannel("A")
    mask = alpha.point(lambda value: 255 if value > TRIM_ALPHA_CUTOFF else 0)
    bbox = mask.getbbox()
    if not bbox:
        return image

    left, top, right, bottom = bbox
    left = max(0, left - TRIM_MARGIN)
    top = max(0, top - TRIM_MARGIN)
    right = min(image.width, right + TRIM_MARGIN)
    bottom = min(image.height, bottom + TRIM_MARGIN)

    if left == 0 and top == 0 and right == image.width and bottom == image.height:
        return image
    return image.crop((left, top, right, bottom))


def normalize_signature_data_url(image_data: str) -> str:
    """Return a PNG data URL with near-white background pixels made transparent."""
    image = _clean_signature_rgba(_split_data_url(image_data))
    out = BytesIO()
    image.save(out, format="PNG")
    return PNG_DATA_PREFIX + base64.b64encode(out.getvalue()).decode("ascii")


def signature_png_bytes(image_data: str) -> bytes:
    """Return cleaned RGBA PNG bytes for libraries that preserve PNG alpha."""
    image = _trim_transparent_edges(_clean_signature_rgba(_split_data_url(image_data)))
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def signature_pdf_streams(image_data: str) -> tuple[bytes, bytes, tuple[int, int]]:
    """
    Return RGB image bytes, an explicit alpha mask, and the cleaned image size.

    Passing the alpha channel as `mask=` avoids white rectangles in downloaded
    PDFs even when the PDF library does not preserve PNG transparency from the
    main image stream.
    """
    image = _trim_transparent_edges(_clean_signature_rgba(_split_data_url(image_data)))

    rgb = image.convert("RGB")
    alpha = image.getchannel("A")

    rgb_out = BytesIO()
    mask_out = BytesIO()
    rgb.save(rgb_out, format="PNG")
    alpha.save(mask_out, format="PNG")
    return rgb_out.getvalue(), mask_out.getvalue(), image.size
