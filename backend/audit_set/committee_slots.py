"""Canonical FR.233 committee slot resolution.

The certification committee is selected during audit planning and stored as an
auditor snapshot on ``AuditSet.committee_members``. FR.233 must therefore use
auditor IDs from that snapshot, just like stage documents use auditor IDs from
the stage assignment.
"""
from __future__ import annotations

from typing import Any


STATIC_COMMITTEE_SIG_KEYS = (
    "COMMITTEE_CHAIR",
    "COMMITTEE_MEMBER_1",
    "COMMITTEE_MEMBER_2",
)

_CHAIR_ROLES = {"chairperson", "decision_maker"}


def planned_committee_members(audit_set: Any) -> list[dict]:
    """Return the planned committee in stable FR.233 row order."""
    raw = getattr(audit_set, "committee_members", None) or []
    members = [dict(member) for member in raw if isinstance(member, dict)]
    if not members:
        return []

    chair = next(
        (member for member in members if member.get("role") in _CHAIR_ROLES),
        members[0],
    )
    ordered = [chair, *(member for member in members if member is not chair)]
    return ordered[: len(STATIC_COMMITTEE_SIG_KEYS)]


def planned_committee_slots(audit_set: Any) -> dict[str, dict]:
    """Map each populated static FR.233 signature key to its planned auditor."""
    return dict(zip(STATIC_COMMITTEE_SIG_KEYS, planned_committee_members(audit_set)))


def planned_committee_chair(audit_set: Any) -> dict | None:
    """Return the auditor assigned to the chairperson row during planning."""
    members = planned_committee_members(audit_set)
    return members[0] if members else None


def committee_member_name(member: dict | None) -> str | None:
    if not member:
        return None
    return member.get("name") or member.get("full_name") or None


def committee_member_auditor_id(member: dict | None) -> str | None:
    if not member:
        return None
    member_id = member.get("id")
    return str(member_id) if member_id else None


def expected_committee_sig_keys(
    audit_set: Any,
    document_sig_keys: set[str] | None = None,
) -> set[str]:
    """Return the signature keys expected for this document and committee.

    New FR.233 files use three positional static keys. Older generated files
    used ``COMMITTEE_MEMBER_<auditor_id>``. When document keys are available,
    prefer whichever form the document actually contains.
    """
    available = document_sig_keys or set()
    expected: set[str] = set()
    for static_key, member in planned_committee_slots(audit_set).items():
        auditor_id = committee_member_auditor_id(member)
        dynamic_key = f"COMMITTEE_MEMBER_{auditor_id}" if auditor_id else None
        if dynamic_key and dynamic_key in available:
            expected.add(dynamic_key)
        else:
            expected.add(static_key)
    return expected
