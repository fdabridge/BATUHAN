"""Shared geometry helpers for hiding visual-signature positioning markers.

The document templates intentionally contain ``[SIG:KEY]`` text so the PDF
preparation step can discover signing coordinates.  Long keys may wrap across
multiple lines, which makes a normal full-string PDF search unreliable.  This
module returns tight per-line boxes around the marker text and deliberately has
no PyMuPDF import so its fallback behaviour can be unit tested independently.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

Box = tuple[float, float, float, float]

SEARCH_CLIP_PAD = 20.0
WORD_MATCH_PAD = 2.0
MARKER_HIDE_PAD = 0.6
FALLBACK_HIDE_PAD = 0.25


def signature_marker_candidates(*keys: str | None) -> list[str]:
    """Return searchable marker spellings for canonical and legacy keys."""
    aliases = {
        "ASSIGNED_AUDITOR": ("AUDITOR_MEMBER",),
        "APPOINTED_REVIEWER": ("CB_REVIEWER",),
        "CB_CERT_MANAGER": (
            "CB_REVIEWER",
            "CERT_MANAGER_REVIEW",
            "CERT_MANAGER_FR233",
        ),
        "ORG_REP": ("CLIENT",),
    }

    expanded: list[str] = []
    for key in keys:
        cleaned = (key or "").strip()
        if not cleaned or cleaned == "__none__":
            continue
        for candidate_key in (cleaned, *aliases.get(cleaned, ())):
            if candidate_key not in expanded:
                expanded.append(candidate_key)

    candidates: list[str] = []
    for key in expanded:
        for marker in (f"[SIG:{key}]", f"[SIG: {key}]", f"SIG:{key}"):
            if marker not in candidates:
                candidates.append(marker)
    return candidates


def marker_hide_boxes(
    page: Any,
    field_box: Box,
    candidates: Iterable[str],
) -> list[Box]:
    """Return tight boxes that can be painted white to hide one marker.

    Resolution order:
      1. Exact PDF text search, preserving separate rectangles for wrapped text.
      2. Per-line word boxes intersecting the extracted signature-field bounds.
      3. The stored field bounds themselves as a final visibility guarantee.

    The word-level fallback is intentionally constrained to the field bounds so
    normal cell content and table borders are not masked.
    """
    page_box = _box(page.rect)
    field_box = _clip_box(_box(field_box), page_box)
    if _is_empty(field_box):
        return []

    clip = _pad_box(field_box, SEARCH_CLIP_PAD, page_box)
    exact: list[Box] = []
    for marker in candidates:
        try:
            matches = page.search_for(marker, clip=clip)
        except Exception:
            continue
        for match in matches or []:
            box = _clip_box(_pad_box(_box(match), MARKER_HIDE_PAD, page_box), page_box)
            if not _is_empty(box) and box not in exact:
                exact.append(box)
    if exact:
        return exact

    word_boxes = _word_line_boxes(page, field_box, clip, page_box)
    if word_boxes:
        return word_boxes

    # Coordinates originate from the marker extraction pass, so this is safer
    # than leaving rendering handles visible when a PDF engine cannot re-find
    # the text. Keep the padding extremely tight to protect surrounding rules.
    return [_pad_box(field_box, FALLBACK_HIDE_PAD, page_box)]


def erase_marker_boxes(page: Any, boxes: Iterable[Box]) -> bool:
    """Remove marker text while preserving table rules and signature images.

    PyMuPDF redaction with ``fill=None`` removes only text content. The numeric
    options are the stable values used by the project's pinned PyMuPDF 1.24:
    images=0 preserves images, graphics=0 preserves line art, and text=0 removes
    text. If a renderer lacks that API, tightly painted white boxes provide a
    backwards-compatible fallback.
    """
    boxes = list(boxes)
    if not boxes:
        return False

    try:
        for box in boxes:
            page.add_redact_annot(box, fill=None, cross_out=False)
        page.apply_redactions(images=0, graphics=0, text=0)
        return True
    except Exception:
        return paint_marker_boxes(page, boxes)


def paint_marker_boxes(page: Any, boxes: Iterable[Box]) -> bool:
    """Paint marker glyphs white while retaining their extractable PDF text.

    Cached viewer PDFs use this path so coordinates can be recovered if the
    signature-field database cache is ever rebuilt. Final downloaded PDFs use
    :func:`erase_marker_boxes` to remove the rendering handles completely.
    """
    changed = False
    for box in boxes:
        try:
            page.draw_rect(
                box,
                color=(1.0, 1.0, 1.0),
                fill=(1.0, 1.0, 1.0),
                width=0,
            )
            changed = True
        except Exception:
            continue
    return changed


def _word_line_boxes(page: Any, field_box: Box, clip: Box, page_box: Box) -> list[Box]:
    try:
        words = page.get_text("words", clip=clip) or []
    except Exception:
        return []

    target = _pad_box(field_box, WORD_MATCH_PAD, page_box)
    grouped: dict[tuple[Any, ...], Box] = {}
    for index, word in enumerate(words):
        if len(word) < 5:
            continue
        box = _box(word[:4])
        text = str(word[4] or "")
        if not text or not _intersects(box, target):
            continue

        # PyMuPDF word tuples normally include block, line and word numbers.
        # Fall back to a y-coordinate bucket for simple/fake page providers.
        line_key: tuple[Any, ...]
        if len(word) >= 8:
            line_key = (word[5], word[6])
        else:
            line_key = (round(box[1], 1), index)
        grouped[line_key] = _union_box(grouped.get(line_key), box)

    boxes: list[Box] = []
    for box in grouped.values():
        clipped = _clip_box(_pad_box(box, MARKER_HIDE_PAD, page_box), page_box)
        if not _is_empty(clipped):
            boxes.append(clipped)
    return boxes


def _box(value: Any) -> Box:
    if all(hasattr(value, attr) for attr in ("x0", "y0", "x1", "y1")):
        return (
            float(value.x0),
            float(value.y0),
            float(value.x1),
            float(value.y1),
        )
    return tuple(float(item) for item in value[:4])  # type: ignore[return-value]


def _pad_box(box: Box, pad: float, page_box: Box) -> Box:
    return _clip_box(
        (box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad),
        page_box,
    )


def _clip_box(box: Box, bounds: Box) -> Box:
    return (
        max(bounds[0], box[0]),
        max(bounds[1], box[1]),
        min(bounds[2], box[2]),
        min(bounds[3], box[3]),
    )


def _intersects(left: Box, right: Box) -> bool:
    return not (
        left[2] <= right[0]
        or left[0] >= right[2]
        or left[3] <= right[1]
        or left[1] >= right[3]
    )


def _is_empty(box: Box) -> bool:
    return box[2] <= box[0] or box[3] <= box[1]


def _union_box(current: Box | None, other: Box) -> Box:
    if current is None:
        return other
    return (
        min(current[0], other[0]),
        min(current[1], other[1]),
        max(current[2], other[2]),
        max(current[3], other[3]),
    )
