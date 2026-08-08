"""Authoritative standard-specific qualification and scope matching helpers."""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any


_STANDARD_ALIASES = {
    "qms": "9001",
    "ems": "14001",
    "ohsms": "45001",
    "fsms": "22000",
    "isms": "27001",
    "enms": "50001",
    "abms": "37001",
    "cms": "37301",
    "mdqms": "13485",
    "mdms": "13485",
}
_STANDARD_NUMBERS = (
    "9001",
    "14001",
    "45001",
    "22000",
    "27001",
    "50001",
    "37001",
    "37301",
    "13485",
)
_EA_STANDARD_KEYS = {"9001", "14001", "45001"}
_CATEGORY_SCOPE_TYPES = {"food", "medical", "isms", "sector", "energy"}
_SCOPE_TYPE_ALIASES = {
    "ea": "ea",
    "iaf": "ea",
    "food": "food",
    "foodchain": "food",
    "foodchaincategory": "food",
    "foodchaincategories": "food",
    "medical": "medical",
    "medicalta": "medical",
    "medicaltas": "medical",
    "medicaltechnicalarea": "medical",
    "medicaltechnicalareas": "medical",
    "mdqms": "medical",
    "isms": "isms",
    "ismstechnicalarea": "isms",
    "ismstechnicalareas": "isms",
    "sector": "sector",
    "sectortype": "sector",
    "energy": "energy",
    "energycomplexity": "energy",
}
_ENERGY_COMPLEXITY_RANK = {
    "low": 1,
    "medium": 2,
    "high": 3,
}


def _value(item: object, field: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(field, default)
    return getattr(item, field, default)


def _items(value: object) -> list[object]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    if isinstance(value, str):
        split = [
            item.strip()
            for item in re.split(r"[,;/|\n]+", value)
            if item.strip()
        ]
        return split or [value]
    return [value]


def normalize_standard(value: object) -> str:
    """Return one stable key for ISO names, editions, and CB abbreviations."""
    raw = str(value or "").strip().lower()
    compact = re.sub(r"[^a-z0-9]", "", raw)
    if compact.startswith("fssc"):
        return "fssc22000"
    if compact in _STANDARD_ALIASES:
        return _STANDARD_ALIASES[compact]
    for number in _STANDARD_NUMBERS:
        if re.search(rf"(?<!\d){re.escape(number)}(?!\d)", raw):
            return number
    return _STANDARD_ALIASES.get(compact, compact)


def normalize_accreditation_body(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").strip().upper())


def normalize_scope_type(value: object) -> str:
    """Normalize current and legacy required-scope type names."""
    raw = str(value or "ea").strip().lower()
    compact = re.sub(r"[^a-z0-9]", "", raw)
    return _SCOPE_TYPE_ALIASES.get(compact, raw)


def normalize_scope_code(value: object, scope_type: str = "ea") -> str:
    """Normalize EA numbers and non-EA category codes without conflating them."""
    scope_type = normalize_scope_type(scope_type)
    if (
        scope_type == "ea"
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
        and float(value).is_integer()
    ):
        return f"EA:{int(value)}"
    raw = str(value or "").strip().upper()
    if scope_type == "ea":
        match = re.fullmatch(r"(?:EA|IAF)?\s*0*(\d+)", raw)
        if match:
            return f"EA:{int(match.group(1))}"
    if scope_type == "medical":
        # IAF MD 9 technical areas occur in both A1.1 and legacy A.1.1
        # notation. Punctuation is presentational and must not change scope.
        compact = re.sub(r"[^A-Z0-9]", "", raw)
        return f"MEDICAL:{compact}" if compact else ""
    return re.sub(r"\s+", "", raw)


def energy_complexity_covers(
    qualification_complexity: object,
    required_complexity: object,
) -> bool:
    """Return whether an EnMS competence level covers an audit complexity.

    Higher-complexity ISO 50001 competence covers lower-complexity audits.
    Missing or unknown values deliberately do not claim scope coverage.
    """
    qualification = str(qualification_complexity or "").strip().lower()
    required = str(required_complexity or "").strip().lower()
    qualification = qualification.removesuffix(" complexity").strip()
    required = required.removesuffix(" complexity").strip()
    qualification_rank = _ENERGY_COMPLEXITY_RANK.get(qualification)
    required_rank = _ENERGY_COMPLEXITY_RANK.get(required)
    return bool(
        qualification_rank
        and required_rank
        and qualification_rank >= required_rank
    )


def _is_qualified(qualification: object) -> bool:
    return _value(qualification, "is_qualified", True) is not False


def _accreditation_matches(
    qualification: object,
    requested_body: str | None,
    legacy_bodies: Iterable[object] | None,
) -> bool:
    requested = normalize_accreditation_body(requested_body)
    if not requested:
        return True
    qualification_body = normalize_accreditation_body(
        _value(qualification, "accreditation_body")
    )
    if qualification_body:
        return qualification_body == requested
    legacy = {
        normalize_accreditation_body(body)
        for body in _items(legacy_bodies)
        if normalize_accreditation_body(body)
    }
    return requested in legacy


def matching_qualifications(
    qualifications: Iterable[object] | None,
    standard: object,
    accreditation_body: str | None = None,
    legacy_accreditation_bodies: Iterable[object] | None = None,
) -> list[object]:
    """Return every active qualification for the exact standard and body."""
    target = normalize_standard(standard)
    if not target:
        return []
    return [
        qualification
        for qualification in (qualifications or [])
        if _is_qualified(qualification)
        and normalize_standard(_value(qualification, "standard_code")) == target
        and _accreditation_matches(
            qualification,
            accreditation_body,
            legacy_accreditation_bodies,
        )
    ]


def has_qualification_for_scope_type(
    qualifications: Iterable[object] | None,
    required_scope: Mapping[str, Mapping[str, object]] | None,
    scope_type: str,
    *,
    accreditation_body: str | None = None,
    legacy_accreditation_bodies: Iterable[object] | None = None,
) -> bool:
    """Return whether any required standard of one scope type is qualified."""
    target_type = normalize_scope_type(scope_type)
    return any(
        normalize_scope_type(entry.get("type", "")) == target_type
        and bool(
            matching_qualifications(
                qualifications,
                standard,
                accreditation_body,
                legacy_accreditation_bodies,
            )
        )
        for standard, entry in (required_scope or {}).items()
    )


def _split_categories(value: object) -> list[str]:
    return [str(item).strip() for item in _items(value) if str(item).strip()]


def _legacy_ea_codes_for_standard(
    qualifications: Iterable[object] | None,
    standard: object,
    accreditation_body: str | None,
    legacy_ea_codes: Iterable[object] | None,
    legacy_accreditation_bodies: Iterable[object] | None,
) -> list[object]:
    """Use global EA codes only when their standard ownership is unambiguous.

    A legacy global list is accepted only when there is an active matching
    per-standard qualification and that is the sole EA-code standard represented
    for the requested accreditation body. This preserves safe legacy records
    without letting one standard's EA code qualify another standard.
    """
    codes = _items(legacy_ea_codes)
    target = normalize_standard(standard)
    if not codes or target not in _EA_STANDARD_KEYS:
        return []

    active_ea_standards = {
        normalize_standard(_value(qualification, "standard_code"))
        for qualification in (qualifications or [])
        if _is_qualified(qualification)
        and normalize_standard(_value(qualification, "standard_code"))
        in _EA_STANDARD_KEYS
        and _accreditation_matches(
            qualification,
            accreditation_body,
            legacy_accreditation_bodies,
        )
    }
    return codes if active_ea_standards == {target} else []


def qualification_codes_for_standard(
    qualifications: Iterable[object] | None,
    standard: object,
    scope_type: str,
    accreditation_body: str | None = None,
    legacy_ea_codes: Iterable[object] | None = None,
    legacy_accreditation_bodies: Iterable[object] | None = None,
) -> tuple[list[object], bool]:
    """Return (codes, has_matching_qualification) for one exact standard."""
    scope_type = normalize_scope_type(scope_type)
    matching = matching_qualifications(
        qualifications,
        standard,
        accreditation_body,
        legacy_accreditation_bodies,
    )
    if not matching:
        return [], False

    codes: list[object] = []
    if scope_type in _CATEGORY_SCOPE_TYPES:
        for qualification in matching:
            codes.extend(_split_categories(_value(qualification, "scope_category")))
    elif scope_type == "ea":
        for qualification in matching:
            codes.extend(_items(_value(qualification, "ea_codes", None)))
        if not codes:
            codes = _legacy_ea_codes_for_standard(
                qualifications,
                standard,
                accreditation_body,
                legacy_ea_codes,
                legacy_accreditation_bodies,
            )

    return codes, True


def compute_covered_scope(
    qualifications: Iterable[object] | None,
    required_scope: Mapping[str, Mapping[str, object]] | None,
    *,
    accreditation_body: str | None = None,
    legacy_ea_codes: Iterable[object] | None = None,
    legacy_accreditation_bodies: Iterable[object] | None = None,
) -> dict[str, list[object]]:
    """Return required codes covered by qualifications for each exact standard."""
    covered: dict[str, list[object]] = {}
    for standard, entry in (required_scope or {}).items():
        scope_type = normalize_scope_type(entry.get("type", "ea"))
        required_codes = _items(entry.get("codes", []))
        qualification_codes, has_qualification = qualification_codes_for_standard(
            qualifications,
            standard,
            scope_type,
            accreditation_body,
            legacy_ea_codes,
            legacy_accreditation_bodies,
        )
        if not has_qualification:
            continue
        if not required_codes:
            covered[standard] = ["UNSCOPED"]
            continue
        if not qualification_codes:
            continue

        if scope_type == "energy":
            matched = [
                code
                for code in required_codes
                if any(
                    energy_complexity_covers(qualification_code, code)
                    for qualification_code in qualification_codes
                )
            ]
        else:
            qualification_keys = {
                normalize_scope_code(code, scope_type)
                for code in qualification_codes
                if normalize_scope_code(code, scope_type)
            }
            matched = [
                code
                for code in required_codes
                if normalize_scope_code(code, scope_type) in qualification_keys
            ]
        if matched:
            covered[standard] = matched
    return covered
