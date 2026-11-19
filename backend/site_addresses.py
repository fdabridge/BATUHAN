"""Address helpers shared by document-generation pipelines."""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Mapping
from typing import TypeVar


_Site = TypeVar("_Site")


def normalized_address(value: object) -> str:
    """Return a comparison key that ignores casing, accents, and punctuation."""
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return "".join(character for character in text if character.isalnum())


def _address_tokens(value: object) -> list[str]:
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return [
        "".join(character for character in token if character.isalnum())
        for token in text.split()
        if any(character.isalnum() for character in token)
    ]


def is_primary_address(candidate: object, primary_address: object) -> bool:
    """Return whether a site address describes the principal facility.

    Legacy records sometimes contain the same address twice with the city or
    country appended to only one copy.  Exact punctuation-insensitive matching
    alone therefore is not enough.  The conservative containment rule below
    accepts the extended form only when every token from the shorter address is
    present and the shorter value is specific enough to be an address.
    """
    candidate_key = normalized_address(candidate)
    primary_key = normalized_address(primary_address)
    if not candidate_key or not primary_key:
        return False
    if candidate_key == primary_key:
        return True

    candidate_tokens = _address_tokens(candidate)
    primary_tokens = _address_tokens(primary_address)
    shorter, longer = (
        (candidate_tokens, primary_tokens)
        if len(candidate_tokens) <= len(primary_tokens)
        else (primary_tokens, candidate_tokens)
    )
    if len(shorter) < 3:
        return False

    shorter_set = set(shorter)
    longer_set = set(longer)
    has_specific_marker = len(shorter) >= 4 or any(
        any(character.isdigit() for character in token) for token in shorter
    )
    return has_specific_marker and shorter_set.issubset(longer_set)


def additional_sites(sites: Iterable[_Site] | None, primary_address: object) -> list[_Site]:
    """Return only genuine additional sites while preserving input objects."""
    result: list[_Site] = []
    for site in sites or []:
        address = (
            site.get("address")
            if isinstance(site, Mapping)
            else getattr(site, "address", "")
        )
        if not is_primary_address(address, primary_address):
            result.append(site)
    return result
