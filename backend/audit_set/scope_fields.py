"""Resolve document-facing fields from the authoritative required scope."""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


_EA_SCOPE_TYPES = {"ea", "ea_code", "ea_codes", "iaf"}


def _normalise_ea_code(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    match = re.fullmatch(r"(?:EA|IAF)?\s*(\d+)", raw, flags=re.IGNORECASE)
    if match:
        return f"EA {int(match.group(1))}"
    return raw


def ea_code_from_required_scope(required_scope: Any) -> str | None:
    """Return current EA codes, ``""`` when explicitly empty, or ``None``.

    ``None`` means the scope has no EA-classified entry, so legacy records may
    still fall back to their top-level ``ea_code``. An empty string means an EA
    entry exists but its codes were deliberately cleared.
    """
    if not isinstance(required_scope, Mapping):
        return None

    saw_ea_scope = False
    codes: list[str] = []
    for entry in required_scope.values():
        if not isinstance(entry, Mapping):
            continue
        if str(entry.get("type") or "").strip().lower() not in _EA_SCOPE_TYPES:
            continue
        saw_ea_scope = True
        raw_codes = entry.get("codes") or []
        if isinstance(raw_codes, str):
            raw_codes = re.split(r"[,;/|\n]+", raw_codes)
        for raw_code in raw_codes:
            code = _normalise_ea_code(raw_code)
            if code and code not in codes:
                codes.append(code)

    if not saw_ea_scope:
        return None
    return ", ".join(codes)


def effective_ea_code(required_scope: Any, legacy_ea_code: Any) -> str:
    """Prefer the revised required-scope code over the legacy top-level field."""
    scoped_code = ea_code_from_required_scope(required_scope)
    if scoped_code is not None:
        return scoped_code
    return str(legacy_ea_code or "").strip()
