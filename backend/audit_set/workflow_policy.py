"""Versioned certification-workflow policy.

Version 1 is the historical workflow and must remain the default for every
record created before the FR.218-first procedure was introduced. Version 2 is
assigned explicitly to new portal applications and places FR.218 before the
quotation and agreement stages.
"""
from __future__ import annotations

from typing import Optional


LEGACY_WORKFLOW_VERSION = 1
FR218_BEFORE_COMMERCIAL_VERSION = 2

LEGACY_STATUS_ORDER = [
    "pending_review",
    "in_planning",
    "notification_sent",
    "quotation_sent",
    "agreement_signed",
    "fr218_in_progress",
    "fr218_complete",
    "audit_scheduled",
    "audit_in_progress",
    "stage1_scheduled",
    "stage1_in_progress",
    "stage1_complete",
    "stage2_scheduled",
    "stage2_in_progress",
    "stage2_complete",
    "under_review",
    "committee_review",
    "certified",
]

FR218_FIRST_STATUS_ORDER = [
    "pending_review",
    "in_planning",
    "notification_sent",
    "fr218_in_progress",
    "fr218_complete",
    "quotation_sent",
    "agreement_signed",
    "audit_scheduled",
    "audit_in_progress",
    "stage1_scheduled",
    "stage1_in_progress",
    "stage1_complete",
    "stage2_scheduled",
    "stage2_in_progress",
    "stage2_complete",
    "under_review",
    "committee_review",
    "certified",
]

# These pairs express the only ordering differences between the historical and
# FR.218-first workflows. All later transitions retain their existing rules.
LEGACY_ONLY_TRANSITIONS = {
    ("in_planning", "quotation_sent"),
    ("agreement_signed", "fr218_in_progress"),
    ("fr218_complete", "audit_scheduled"),
    ("fr218_complete", "stage1_scheduled"),
    ("fr218_complete", "stage1_in_progress"),
}

FR218_FIRST_ONLY_TRANSITIONS = {
    ("in_planning", "fr218_in_progress"),
    ("fr218_complete", "quotation_sent"),
    ("agreement_signed", "stage1_in_progress"),
}


def workflow_version(audit_set) -> int:
    """Return a safe integer version; absent/NULL values are always legacy."""
    value = getattr(audit_set, "workflow_version", None)
    try:
        return int(value or LEGACY_WORKFLOW_VERSION)
    except (TypeError, ValueError):
        return LEGACY_WORKFLOW_VERSION


def uses_fr218_before_commercial(audit_set) -> bool:
    """True only for version-2 non-surveillance portal applications."""
    audit_type = str(getattr(audit_set, "audit_type", "") or "").lower()
    return (
        workflow_version(audit_set) >= FR218_BEFORE_COMMERCIAL_VERSION
        and not audit_type.startswith("surveillance")
    )


def transition_matches_version(audit_set, from_status: Optional[str], to_status: str) -> bool:
    """Reject only the old/new branch transitions that belong to another version."""
    pair = (from_status, to_status)
    if uses_fr218_before_commercial(audit_set):
        return pair not in LEGACY_ONLY_TRANSITIONS
    return pair not in FR218_FIRST_ONLY_TRANSITIONS


def quotation_source_status(audit_set) -> str:
    """Status from which a fully signed quotation advances."""
    return "fr218_complete" if uses_fr218_before_commercial(audit_set) else "in_planning"


def status_at_least(
    current: Optional[str],
    threshold: str,
    version: int = LEGACY_WORKFLOW_VERSION,
) -> bool:
    """Compare statuses using the order belonging to the record's workflow."""
    order = (
        FR218_FIRST_STATUS_ORDER
        if version >= FR218_BEFORE_COMMERCIAL_VERSION
        else LEGACY_STATUS_ORDER
    )
    try:
        return order.index(current or "") >= order.index(threshold)
    except ValueError:
        return False


def commercial_documents_unlocked(audit_set) -> bool:
    """Whether FR.220/FR.221 may be generated or released for this record."""
    if not uses_fr218_before_commercial(audit_set):
        return True
    return status_at_least(
        getattr(audit_set, "workflow_status", None),
        "fr218_complete",
        workflow_version(audit_set),
    )
