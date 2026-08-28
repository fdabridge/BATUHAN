"""Dependency-free normalization shared by Certiv.AI API and worker paths."""

from __future__ import annotations

from collections.abc import Iterable
import re

from schemas.models import normalize_iso_standard


def normalize_iso_standard_inputs(values: Iterable[str]) -> list[str]:
    selected: list[str] = []
    for raw in values:
        for part in str(raw or "").replace("+", ",").split(","):
            parsed = normalize_iso_standard(part)
            code = parsed.value if parsed else part.strip().upper()
            if code and code not in selected:
                selected.append(code)
    return selected


def review_stage_key(stage: str) -> str:
    normalized = stage.strip().lower().replace("-", " ")
    if "stage 1" in normalized:
        return "stage_1"
    if "stage 2" in normalized:
        return "stage_2"
    if "surveillance" in normalized:
        return "surveillance"
    if "recert" in normalized:
        return "recertification"
    return "stage_2"


def company_name_matches_target(candidate: str, target: str) -> bool:
    """Identify a blocked sample name that is actually the current auditee."""
    candidate_key = re.sub(r"[^a-z0-9]", "", (candidate or "").lower())
    target_key = re.sub(r"[^a-z0-9]", "", (target or "").lower())
    if min(len(candidate_key), len(target_key)) < 4:
        return False
    return candidate_key in target_key or target_key in candidate_key


def submitted_scope_text(scope_en: str | None, scope_tr: str | None) -> str:
    lines: list[str] = []
    if scope_en and scope_en.strip():
        lines.append(f"Certification scope (English): {scope_en.strip()}")
    if scope_tr and scope_tr.strip():
        lines.append(f"Belgelendirme kapsamı (Türkçe): {scope_tr.strip()}")
    return "\n".join(lines)
