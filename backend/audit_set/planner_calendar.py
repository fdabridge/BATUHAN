"""Read-only planner calendar projection for saved audit stages."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from audit_set.db_models import AuditSet, AuditSetStage
from auditors.models import Auditor


TEAM_ROLES = {
    "auditors": "Auditor",
    "technical_experts": "Technical Expert",
    "observers": "Observer",
    "trainees": "Trainee Auditor",
    "ik_experts": "Industry Expert",
    "evaluators": "Evaluator",
}


class PlannerCalendarPerson(BaseModel):
    name: str
    role: str
    standard: str | None = None


class PlannerCalendarBooking(BaseModel):
    id: str
    case_id: str
    plan_number: int
    company_name: str
    standards: list[str]
    audit_type: str | None
    stage_type: str
    start: date
    end: date | None
    people: list[PlannerCalendarPerson]


def _team_rows(stage: AuditSetStage):
    yield stage.lead_auditor_id, stage.lead_auditor_name, "Lead Auditor", None
    for field, role in TEAM_ROLES.items():
        for member in getattr(stage, field) or []:
            if isinstance(member, dict):
                yield member.get("id"), member.get("name"), role, member.get("standard")


def list_planner_calendar_bookings(
    db: Session,
    first_day: date,
    last_day: date,
) -> list[PlannerCalendarBooking]:
    """Return non-cancelled audit stages that overlap the requested month."""

    display_end = func.coalesce(AuditSetStage.audit_date_end, AuditSetStage.audit_date_start)
    rows = (
        db.query(
            AuditSetStage,
            AuditSet.plan_number,
            AuditSet.company_name,
            AuditSet.standards,
            AuditSet.audit_type,
        )
        .join(AuditSet, AuditSet.id == AuditSetStage.audit_set_id)
        .filter(
            AuditSet.status != "archived",
            AuditSetStage.status != "cancelled",
            AuditSetStage.audit_date_start <= last_day,
            display_end >= first_day,
            display_end >= AuditSetStage.audit_date_start,
        )
        .order_by(AuditSetStage.audit_date_start, AuditSet.company_name, AuditSetStage.id)
        .all()
    )

    teams = {stage.id: list(_team_rows(stage)) for stage, *_ in rows}
    missing_names = {
        person_id
        for team in teams.values()
        for person_id, name, _, _ in team
        if person_id and not (name or "").strip()
    }
    names = (
        dict(db.query(Auditor.id, Auditor.name).filter(Auditor.id.in_(missing_names)).all())
        if missing_names
        else {}
    )

    bookings: list[PlannerCalendarBooking] = []
    for stage, plan_number, company_name, standards, audit_type in rows:
        people: list[PlannerCalendarPerson] = []
        seen = set()
        for person_id, saved_name, role, assigned_standard in teams[stage.id]:
            name = (saved_name or "").strip() or (names.get(person_id) or "").strip()
            key = person_id or (name, role)
            if not name or key in seen:
                continue
            seen.add(key)
            people.append(
                PlannerCalendarPerson(
                    name=name,
                    role=role,
                    standard=assigned_standard,
                )
            )

        bookings.append(
            PlannerCalendarBooking(
                id=stage.id,
                case_id=stage.audit_set_id,
                plan_number=plan_number,
                company_name=company_name or f"Plan #{plan_number}",
                standards=standards or [],
                audit_type=audit_type,
                stage_type=stage.stage_type,
                start=stage.audit_date_start,
                end=stage.audit_date_end,
                people=people,
            )
        )

    return bookings
