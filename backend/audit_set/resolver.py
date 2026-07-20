"""
BATUHAN — Audit Set: blank-template resolver.

Given an `AuditSet`, decide which IFC blank DOCX files must be filled and how
they group into output folders (Stage_1 / Stage_2 / Surveillance / Recertification).
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

from audit_set.field_maps import (
    FR211_MAP, FR218_MAP, FR222_MAP, FR223_MAP,
    FR224_MAP, FR225_MAP, FR230_MAP, FR231_MAP, FR232_MAP, FR233_MAP, FR234_MAP,
    FR250_MAP,
)


from config.settings import get_settings
BLANK_SET_PATH = Path(get_settings().blank_set_path)

# Standard group → folder name (under BLANK_SET_PATH)
STANDARD_FOLDER = {
    "QMS":   "9-14-45",
    "EMS":   "9-14-45",
    "OHSMS": "9-14-45",
    "FSMS":  "9-14-45",
    "ABMS":  "9-14-45",
    "ENMS":  "9-14-45",
    "MDQMS": "13485",
    "ISMS":  "27001",
}

GROUP_FOLDER = {
    "base":  "9-14-45-22-5001",
    "mdqms": "13485",
    "isms":  "27001",
}

STAGE_SUBFOLDER = {
    "stage_1":      "İlk Belgelendirme/Aşama 1",
    "stage_2":      "İlk Belgelendirme/Aşama 2",
    "surveillance": "Gözetim",
}

# English equivalents (used when accreditation_body == "UAF")
STAGE_SUBFOLDER_EN = {
    "stage_1":      "Initial Certification/Stage 1",
    "stage_2":      "Initial Certification/Stage 2",
    "surveillance": "Surveillance",
}
STAGE_SUBFOLDER_RECERT_EN = "Recertification"
STAGE_SUBFOLDER_RECERT_TR = "Yeniden Belgelendirme"


def _get_stage_subfolder(audit_type: str, stage_key: str, accreditation_body: str) -> str:
    """Return the correct sub-folder name for language routing.

    Args:
        audit_type: 'initial' | 'recertification' | 'surveillance' | 'surveillance_1' | ...
        stage_key:  'stage_1' | 'stage_2' | 'surveillance' | 'recertification'
        accreditation_body: 'UAF' | 'TÜRKAK' | 'TURKAK' | ...
    """
    is_uaf = (accreditation_body or "").upper() == "UAF"

    if (audit_type or "").lower() == "recertification" and stage_key in {"recertification", "surveillance", "stage_2"}:
        return STAGE_SUBFOLDER_RECERT_EN if is_uaf else STAGE_SUBFOLDER_RECERT_TR

    if stage_key == "surveillance":
        return STAGE_SUBFOLDER_EN["surveillance"] if is_uaf else STAGE_SUBFOLDER["surveillance"]

    return STAGE_SUBFOLDER_EN[stage_key] if is_uaf else STAGE_SUBFOLDER[stage_key]

BASE_STANDARDS = {"QMS", "EMS", "OHSMS", "FSMS", "ABMS", "ENMS"}


@dataclass
class DocumentSpec:
    fr_number: str          # e.g. "FR.223", "FR.231-1"
    template_path: Path
    field_map: dict
    stage_context: str      # "stage_1" | "stage_2" | "surveillance" | "all"
    output_filename: str    # clean name for the ZIP entry


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _clean_filename(name: str) -> str:
    """Strip the revision suffix (`_R6&09.10.2025` or `R1&10.06.2024 - Kopya`)."""
    cleaned = re.sub(r"\s*_?R\d+[^.]*\.docx$", ".docx", name, flags=re.IGNORECASE)
    return cleaned.strip()


def _norm_name(s: str) -> str:
    """Normalise a folder name for tolerant matching: NFC, stripped, casefolded."""
    return unicodedata.normalize("NFC", s or "").strip().casefold()


def _resolve_dir(base: Path, sub: str) -> Path:
    """Resolve a (possibly multi-segment) sub-path under `base`, tolerating
    trailing/leading whitespace, case and unicode-normalisation drift in the
    on-disk folder names (e.g. 'Initial Certification ' with a trailing space).

    Falls back to the literal path if no match is found, so the caller's
    missing-template handling still fires.
    """
    current = base
    for part in Path(sub).parts:
        if not current.is_dir():
            return current / part
        target = _norm_name(part)
        match = next(
            (c for c in current.iterdir() if c.is_dir() and _norm_name(c.name) == target),
            None,
        )
        current = match if match is not None else current / part
    return current


def _find_template(folder: Path, fr_number: str) -> Path | None:
    """Locate a template file by FR-number prefix inside a stage folder."""
    if not folder.exists():
        return None
    candidates = list(folder.glob(f"{fr_number}*.docx"))
    if "-" not in fr_number:
        # Exclude sub-variants such as FR.231-1 when looking up FR.231.
        candidates = [
            p for p in candidates
            if not (len(p.name) > len(fr_number) and p.name[len(fr_number)] == "-")
        ]
    return candidates[0] if candidates else None


def _add(specs, seen, fr_number, group, stage_sub, field_map, stage_context, missing: list[str], *, allow_dup=False):
    """Append a DocumentSpec if the fr_number isn't already in `seen` (or always when allow_dup).

    When the template file cannot be found on disk, the fr_number is appended to
    `missing` so callers can surface the gap to the user.
    """
    if not allow_dup and fr_number in seen:
        return
    folder = _resolve_dir(BLANK_SET_PATH / GROUP_FOLDER[group], stage_sub)
    template = _find_template(folder, fr_number)
    if template is None:
        missing.append(f"{group}/{stage_sub}/{fr_number}")
        logger.warning("[Resolver] Template not found: %s/%s/%s", group, stage_sub, fr_number)
        return
    specs.append(DocumentSpec(
        fr_number=fr_number,
        template_path=template,
        field_map=field_map,
        stage_context=stage_context,
        output_filename=_clean_filename(template.name),
    ))
    seen.add(fr_number)


def _transfer_spec(missing: list[str]) -> DocumentSpec | None:
    """Return FR.250 for transfer applications, independent of audit type."""
    folder = _resolve_dir(BLANK_SET_PATH / GROUP_FOLDER["base"], "Transfer")
    template = _find_template(folder, "FR.250")
    if template is None:
        missing.append(f"{GROUP_FOLDER['base']}/Transfer/FR.250")
        logger.warning("[Resolver] Transfer template not found: %s/Transfer/FR.250", GROUP_FOLDER["base"])
        return None
    return DocumentSpec(
        fr_number="FR.250",
        template_path=template,
        field_map=FR250_MAP,
        stage_context="all",
        output_filename=_clean_filename(template.name),
    )


# --------------------------------------------------------------------------- #
# Per-stage builders
# --------------------------------------------------------------------------- #
def _build_stage_1(needs_base, needs_mdqms, needs_isms, sub: str, missing: list[str]) -> list[DocumentSpec]:
    specs: list[DocumentSpec] = []
    seen: set[str] = set()

    primary = "base" if needs_base else ("mdqms" if needs_mdqms else ("isms" if needs_isms else None))
    if primary:
        _add(specs, seen, "FR.218", primary, sub, FR218_MAP, "all", missing)
        _add(specs, seen, "FR.220", primary, sub, {},        "all", missing)
        _add(specs, seen, "FR.221", primary, sub, {},        "all", missing)
        _add(specs, seen, "FR.222", primary, sub, FR222_MAP, "all", missing)

    for fr, fmap in [("FR.223", FR223_MAP), ("FR.224", FR224_MAP),
                     ("FR.225", FR225_MAP), ("FR.230", FR230_MAP)]:
        if needs_base:  _add(specs, seen, fr, "base",  sub, fmap, "stage_1", missing)
        if needs_mdqms: _add(specs, seen, fr, "mdqms", sub, fmap, "stage_1", missing)
        if needs_isms:  _add(specs, seen, fr, "isms",  sub, fmap, "stage_1", missing)

    if needs_base:
        _add(specs, seen, "FR.231",   "base",  sub, FR231_MAP, "stage_1", missing)
    if needs_mdqms:
        _add(specs, seen, "FR.231-1", "mdqms", sub, FR231_MAP, "stage_1", missing)
    if needs_isms:
        _add(specs, seen, "FR.231",   "isms",  sub, FR231_MAP, "stage_1", missing)

    if needs_base:  _add(specs, seen, "FR.211", "base",  sub, FR211_MAP, "stage_1", missing)
    if needs_mdqms: _add(specs, seen, "FR.211", "mdqms", sub, FR211_MAP, "stage_1", missing)
    if needs_isms:  _add(specs, seen, "FR.211", "isms",  sub, FR211_MAP, "stage_1", missing)
    return specs



def _build_stage_2(needs_base, needs_mdqms, needs_isms, sub: str, missing: list[str]) -> list[DocumentSpec]:
    specs: list[DocumentSpec] = []
    seen: set[str] = set()

    for fr, fmap in [("FR.223", FR223_MAP), ("FR.224", FR224_MAP),
                     ("FR.225", FR225_MAP), ("FR.230", FR230_MAP)]:
        if needs_base:  _add(specs, seen, fr, "base",  sub, fmap, "stage_2", missing)
        if needs_mdqms: _add(specs, seen, fr, "mdqms", sub, fmap, "stage_2", missing)
        if needs_isms:  _add(specs, seen, fr, "isms",  sub, fmap, "stage_2", missing)

    if needs_base:
        _add(specs, seen, "FR.232",   "base",  sub, FR232_MAP, "stage_2", missing)
    if needs_mdqms:
        _add(specs, seen, "FR.232-1", "mdqms", sub, FR232_MAP, "stage_2", missing)
    if needs_isms:
        _add(specs, seen, "FR.229",   "isms",  sub, FR232_MAP, "stage_2", missing)

    if needs_base:  _add(specs, seen, "FR.211", "base",  sub, FR211_MAP, "stage_2", missing)
    if needs_mdqms: _add(specs, seen, "FR.211", "mdqms", sub, FR211_MAP, "stage_2", missing)
    if needs_isms:  _add(specs, seen, "FR.211", "isms",  sub, FR211_MAP, "stage_2", missing)

    # FR.233 — Review & Decision Form (certification committee; included once per audit)
    primary = "base" if needs_base else ("mdqms" if needs_mdqms else ("isms" if needs_isms else None))
    if primary:
        _add(specs, seen, "FR.233", primary, sub, FR233_MAP, "stage_2", missing)

    return specs


def _build_surveillance(
    needs_base,
    needs_mdqms,
    needs_isms,
    sub: str,
    missing: list[str],
    stage_context: str = "surveillance",
) -> list[DocumentSpec]:
    specs: list[DocumentSpec] = []
    seen: set[str] = set()

    # Common plan / meeting / NC forms — same template for all standard groups.
    for fr, fmap in [
        ("FR.223", FR223_MAP), ("FR.224", FR224_MAP), ("FR.225", FR225_MAP),
        ("FR.230", FR230_MAP),
    ]:
        if needs_base:  _add(specs, seen, fr, "base",  sub, fmap, stage_context, missing)
        if needs_mdqms: _add(specs, seen, fr, "mdqms", sub, fmap, stage_context, missing)
        if needs_isms:  _add(specs, seen, fr, "isms",  sub, fmap, stage_context, missing)

    # Audit report — standard-specific form (mirrors _build_stage_2).
    if needs_base:
        _add(specs, seen, "FR.232",   "base",  sub, FR232_MAP, stage_context, missing)
    if needs_mdqms:
        _add(specs, seen, "FR.232-1", "mdqms", sub, FR232_MAP, stage_context, missing)
    if needs_isms:
        _add(specs, seen, "FR.229",   "isms",  sub, FR232_MAP, stage_context, missing)

    # Auditor assessment — one per standard group.
    if needs_base:  _add(specs, seen, "FR.211", "base",  sub, FR211_MAP, stage_context, missing)
    if needs_mdqms: _add(specs, seen, "FR.211", "mdqms", sub, FR211_MAP, stage_context, missing)
    if needs_isms:  _add(specs, seen, "FR.211", "isms",  sub, FR211_MAP, stage_context, missing)

    # Single-instance forms (primary group only).
    primary = "base" if needs_base else ("mdqms" if needs_mdqms else ("isms" if needs_isms else None))
    if primary:
        _add(specs, seen, "FR.234", primary, sub, FR234_MAP, stage_context, missing)
        _add(specs, seen, "FR.233", primary, sub, FR233_MAP, stage_context, missing)

    return specs


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def resolve_document_set(audit_set) -> tuple[dict[str, list[DocumentSpec]], list[str]]:
    """
    Returns ``(document_set, missing)`` where:

    * ``document_set`` is keyed by output folder name:
        - "Stage_1"      → list[DocumentSpec]
        - "Stage_2"      → list[DocumentSpec]
        - "Surveillance" → list[DocumentSpec]
        - "Recertification" → list[DocumentSpec]
    * ``missing`` is a list of template paths that could not be found on disk.

    Initial produces Stage_1 + Stage_2.
    Surveillance (any variant) produces only Surveillance.
    Recertification produces only Recertification.
    """
    standards = audit_set.standards or []
    needs_base  = any(s in BASE_STANDARDS for s in standards)
    needs_mdqms = "MDQMS" in standards
    needs_isms  = "ISMS"  in standards

    audit_type = (audit_set.audit_type or "").lower()
    accreditation_body = getattr(audit_set, "accreditation_body", "") or ""
    document_set: dict[str, list[DocumentSpec]] = {}
    missing: list[str] = []

    if audit_type.startswith("surveillance"):
        sub = _get_stage_subfolder(audit_type, "surveillance", accreditation_body)
        document_set["Surveillance"] = _build_surveillance(needs_base, needs_mdqms, needs_isms, sub, missing)
    elif audit_type == "recertification":
        sub = _get_stage_subfolder(audit_type, "recertification", accreditation_body)
        document_set["Recertification"] = _build_surveillance(
            needs_base, needs_mdqms, needs_isms, sub, missing, stage_context="recertification",
        )
    else:
        sub1 = _get_stage_subfolder(audit_type, "stage_1", accreditation_body)
        sub2 = _get_stage_subfolder(audit_type, "stage_2", accreditation_body)
        document_set["Stage_1"] = _build_stage_1(needs_base, needs_mdqms, needs_isms, sub1, missing)
        document_set["Stage_2"] = _build_stage_2(needs_base, needs_mdqms, needs_isms, sub2, missing)

    if getattr(audit_set, "is_transfer", False):
        spec = _transfer_spec(missing)
        if spec:
            if audit_type == "recertification":
                first_folder = "Recertification"
            elif audit_type.startswith("surveillance"):
                first_folder = "Surveillance"
            else:
                first_folder = "Stage_1"
            document_set.setdefault(first_folder, [])
            document_set[first_folder].insert(0, spec)

    return document_set, missing
