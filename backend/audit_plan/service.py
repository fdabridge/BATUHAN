"""Shared audit-plan generation helpers for HTTP and background jobs."""

from __future__ import annotations

from dataclasses import asdict

from .docx_filler import fill_schedule
from .schedule_generator import generate_schedule
from .template_reader import (
    AuditPlanContext,
    AuditorEntry,
    DayWindow,
    SiteEntry,
)


def context_to_dict(ctx: AuditPlanContext) -> dict:
    """Convert an audit-plan context into a Celery JSON-safe dictionary."""
    return asdict(ctx)


def context_from_dict(payload: dict) -> AuditPlanContext:
    """Restore nested audit-plan dataclasses from a Celery payload."""
    data = dict(payload)
    data["auditors"] = [AuditorEntry(**item) for item in data.get("auditors", [])]
    data["sites"] = [SiteEntry(**item) for item in data.get("sites", [])]
    data["day_windows"] = [DayWindow(**item) for item in data.get("day_windows", [])]
    return AuditPlanContext(**data)


def audit_plan_filename(ctx: AuditPlanContext) -> str:
    """Return a safe, stable filename for a generated FR.223 document."""
    safe_org = "".join(
        char if char.isalnum() or char in " _-" else "_"
        for char in ctx.org_name
    )[:40]
    safe_dates = "".join(
        char if char not in "\r\n\t" else " "
        for char in ctx.audit_dates
    )
    safe_dates = "".join(
        char if char.isalnum() or char in "._- " else "_"
        for char in safe_dates
    ).strip(" _")[:60]
    audit_type = ctx.audit_type.replace(" ", "")
    return f"AuditPlan_{safe_org}_{audit_type}_{safe_dates}.docx"


def generate_audit_plan_document(
    template_bytes: bytes,
    ctx: AuditPlanContext,
) -> tuple[bytes, str]:
    """Generate, validate, and assemble a complete audit-plan DOCX."""
    days = generate_schedule(ctx)
    document = fill_schedule(template_bytes, days, ctx)
    return document, audit_plan_filename(ctx)
