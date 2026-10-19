"""Canonical audit-type semantics shared by the audit-set workflow.

Scope-extension audits are recorded distinctly for traceability, while their
operational workflow intentionally follows Surveillance 1.
"""
from __future__ import annotations


SCOPE_EXTENSION = "scope_extension"
SURVEILLANCE_1_SCOPE_EXTENSION = "surveillance_1_scope_extension"

SURVEILLANCE_LIKE_AUDIT_TYPES = frozenset({
    "surveillance",
    "surveillance_1",
    "surveillance_2",
    SCOPE_EXTENSION,
    SURVEILLANCE_1_SCOPE_EXTENSION,
})


def normalize_audit_type(value: object) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def is_surveillance_like_audit_type(value: object) -> bool:
    """Return whether ``value`` must use the one-stage surveillance workflow."""
    normalized = normalize_audit_type(value)
    return normalized.startswith("surveillance") or normalized == SCOPE_EXTENSION


def audit_type_display(value: object) -> str:
    normalized = normalize_audit_type(value)
    labels = {
        "initial": "Initial Certification",
        "surveillance": "Surveillance",
        "surveillance_1": "Surveillance 1",
        "surveillance_2": "Surveillance 2",
        SCOPE_EXTENSION: "Scope Extension",
        SURVEILLANCE_1_SCOPE_EXTENSION: "Surveillance 1 + Scope Extension",
        "recertification": "Recertification",
        "special": "Special Audit",
    }
    return labels.get(normalized, str(value or "").replace("_", " ").title())
