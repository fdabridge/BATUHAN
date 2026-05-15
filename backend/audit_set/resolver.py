"""
BATUHAN — Audit Set: blank-template resolver.

Given an `AuditSet`, decide which IFC blank DOCX files must be filled and how
they group into output folders (Stage_1 / Stage_2 / Surveillance).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from audit_set.field_maps import (
    FR211_MAP, FR217_MAP, FR218_MAP, FR222_MAP, FR223_MAP,
    FR224_MAP, FR225_MAP, FR230_MAP, FR231_MAP, FR232_MAP, FR234_MAP,
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
    "base":  "9-14-45",
    "mdqms": "13485",
    "isms":  "27001",
}

STAGE_SUBFOLDER = {
    "stage_1":      "İlk Belgelendirme/Aşama 1",
    "stage_2":      "İlk Belgelendirme/Aşama 2",
    "surveillance": "Gözetim",
}

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


def _add(specs, seen, fr_number, group, stage_sub, field_map, stage_context, *, allow_dup=False):
    """Append a DocumentSpec if the fr_number isn't already in `seen` (or always when allow_dup)."""
    if not allow_dup and fr_number in seen:
        return
    folder = BLANK_SET_PATH / GROUP_FOLDER[group] / stage_sub
    template = _find_template(folder, fr_number)
    if template is None:
        return
    specs.append(DocumentSpec(
        fr_number=fr_number,
        template_path=template,
        field_map=field_map,
        stage_context=stage_context,
        output_filename=_clean_filename(template.name),
    ))
    seen.add(fr_number)


# --------------------------------------------------------------------------- #
# Per-stage builders
# --------------------------------------------------------------------------- #
def _build_stage_1(needs_base, needs_mdqms, needs_isms) -> list[DocumentSpec]:
    specs: list[DocumentSpec] = []
    seen: set[str] = set()
    sub = STAGE_SUBFOLDER["stage_1"]

    primary = "base" if needs_base else ("mdqms" if needs_mdqms else ("isms" if needs_isms else None))
    if primary:
        _add(specs, seen, "FR.217", primary, sub, FR217_MAP, "all")
        _add(specs, seen, "FR.218", primary, sub, FR218_MAP, "all")
        _add(specs, seen, "FR.220", primary, sub, {},        "all")
        _add(specs, seen, "FR.222", primary, sub, FR222_MAP, "all")

    for fr, fmap in [("FR.223", FR223_MAP), ("FR.224", FR224_MAP),
                     ("FR.225", FR225_MAP), ("FR.230", FR230_MAP)]:
        if needs_base:  _add(specs, seen, fr, "base",  sub, fmap, "stage_1")
        if needs_mdqms: _add(specs, seen, fr, "mdqms", sub, fmap, "stage_1")
        if needs_isms:  _add(specs, seen, fr, "isms",  sub, fmap, "stage_1")

    if needs_base:
        _add(specs, seen, "FR.231", "base", sub, FR231_MAP, "stage_1")
    if needs_mdqms:
        _add(specs, seen, "FR.231-1", "mdqms", sub, FR231_MAP, "stage_1")

    if needs_base:  _add(specs, seen, "FR.211", "base",  sub, FR211_MAP, "stage_1")
    if needs_mdqms: _add(specs, seen, "FR.211", "mdqms", sub, FR211_MAP, "stage_1")
    if needs_isms:  _add(specs, seen, "FR.211", "isms",  sub, FR211_MAP, "stage_1")
    return specs



def _build_stage_2(needs_base, needs_mdqms, needs_isms) -> list[DocumentSpec]:
    specs: list[DocumentSpec] = []
    seen: set[str] = set()
    sub = STAGE_SUBFOLDER["stage_2"]

    for fr, fmap in [("FR.223", FR223_MAP), ("FR.224", FR224_MAP),
                     ("FR.225", FR225_MAP), ("FR.230", FR230_MAP)]:
        if needs_base:  _add(specs, seen, fr, "base",  sub, fmap, "stage_2")
        if needs_mdqms: _add(specs, seen, fr, "mdqms", sub, fmap, "stage_2")
        if needs_isms:  _add(specs, seen, fr, "isms",  sub, fmap, "stage_2")

    if needs_base:
        _add(specs, seen, "FR.232", "base", sub, FR232_MAP, "stage_2")
    if needs_mdqms:
        _add(specs, seen, "FR.232-1", "mdqms", sub, FR232_MAP, "stage_2")
    if needs_isms:
        _add(specs, seen, "FR.229", "isms", sub, FR232_MAP, "stage_2")

    if needs_base:  _add(specs, seen, "FR.211", "base",  sub, FR211_MAP, "stage_2")
    if needs_mdqms: _add(specs, seen, "FR.211", "mdqms", sub, FR211_MAP, "stage_2")
    if needs_isms:  _add(specs, seen, "FR.211", "isms",  sub, FR211_MAP, "stage_2")
    return specs


def _build_surveillance(needs_base, needs_mdqms, needs_isms) -> list[DocumentSpec]:
    specs: list[DocumentSpec] = []
    seen: set[str] = set()
    sub = STAGE_SUBFOLDER["surveillance"]

    for fr, fmap in [
        ("FR.223", FR223_MAP), ("FR.224", FR224_MAP), ("FR.225", FR225_MAP),
        ("FR.230", FR230_MAP), ("FR.232", FR232_MAP), ("FR.234", FR234_MAP),
        ("FR.211", FR211_MAP),
    ]:
        if needs_base:  _add(specs, seen, fr, "base",  sub, fmap, "surveillance")
        if needs_mdqms: _add(specs, seen, fr, "mdqms", sub, fmap, "surveillance")
        if needs_isms:  _add(specs, seen, fr, "isms",  sub, fmap, "surveillance")
    return specs


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def resolve_document_set(audit_set) -> dict[str, list[DocumentSpec]]:
    """
    Returns a dict keyed by output folder name:
      "Stage_1"      → list[DocumentSpec]
      "Stage_2"      → list[DocumentSpec]
      "Surveillance" → list[DocumentSpec]
    Initial / recertification produce Stage_1 + Stage_2.
    Surveillance produces only Surveillance.
    """
    standards = audit_set.standards or []
    needs_base  = any(s in BASE_STANDARDS for s in standards)
    needs_mdqms = "MDQMS" in standards
    needs_isms  = "ISMS"  in standards

    audit_type = (audit_set.audit_type or "").lower()
    result: dict[str, list[DocumentSpec]] = {}

    if audit_type == "surveillance":
        result["Surveillance"] = _build_surveillance(needs_base, needs_mdqms, needs_isms)
    else:  # initial or recertification
        result["Stage_1"] = _build_stage_1(needs_base, needs_mdqms, needs_isms)
        result["Stage_2"] = _build_stage_2(needs_base, needs_mdqms, needs_isms)

    return result
