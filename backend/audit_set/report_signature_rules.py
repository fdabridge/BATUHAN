"""Signature rules for uploaded audit reports."""
from __future__ import annotations

from typing import Any


_STAGE1_EXTRA_REVIEW_STANDARDS = ("FSMS", "ISMS", "22000", "27001")


def audit_set_has_stage1_extra_review(audit_set: Any) -> bool:
    """FR.231's extra reviewer row is only required for FSMS/ISMS audits."""
    standards = getattr(audit_set, "standards", None) or []
    if isinstance(standards, str):
        standards = [standards]
    normalized = {str(std).upper() for std in standards}
    return any(
        marker in std
        for std in normalized
        for marker in _STAGE1_EXTRA_REVIEW_STANDARDS
    )


def audit_report_requires_appointed_reviewer(
    report: Any,
    audit_set: Any,
) -> bool:
    """Return whether APPOINTED_REVIEWER is a real required slot for a report."""
    report_form = (getattr(report, "report_form", "") or "").upper()
    if report_form == "FR.232":
        return True
    if report_form in {"FR.231", "FR.231-1"}:
        return False
    return False


def audit_report_requires_certification_manager(
    report: Any,
    audit_set: Any,
) -> bool:
    """Return whether CB_CERT_MANAGER/CB_REVIEWER is a real required slot."""
    report_form = (getattr(report, "report_form", "") or "").upper()
    if report_form in {"FR.231", "FR.231-1"}:
        return True
    if audit_report_requires_appointed_reviewer(report, audit_set):
        return False
    return True


def audit_report_has_all_required_approvals(report: Any, audit_set: Any) -> bool:
    """Return True when all required audit-report signature roles are complete."""
    if not getattr(report, "la_signed_at", None):
        return False
    if audit_report_requires_appointed_reviewer(report, audit_set):
        return bool(getattr(report, "appointed_reviewer_signed_at", None))
    if not audit_report_requires_certification_manager(report, audit_set):
        return True
    if not getattr(report, "reviewer_signed_at", None):
        return False
    return True
