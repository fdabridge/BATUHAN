"""Address helpers shared by document-generation pipelines."""

from __future__ import annotations

import unicodedata


def normalized_address(value: object) -> str:
    """Return a comparison key that ignores casing, accents, and punctuation."""
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return "".join(character for character in text if character.isalnum())


def is_primary_address(candidate: object, primary_address: object) -> bool:
    """Return True only when two non-empty addresses describe the same text."""
    candidate_key = normalized_address(candidate)
    primary_key = normalized_address(primary_address)
    return bool(candidate_key and primary_key and candidate_key == primary_key)
