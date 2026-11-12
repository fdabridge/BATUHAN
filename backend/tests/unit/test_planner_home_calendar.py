"""Regression coverage for the read-only planner homepage calendar."""

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from audit_set.db_models import AuditSet, AuditSetStage, Base as AuditBase
from audit_set.planner_calendar import list_planner_calendar_bookings
from auditors.models import Auditor, Base as AuditorBase


@pytest.fixture
def calendar_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    AuditBase.metadata.create_all(engine)
    AuditorBase.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def test_calendar_includes_cross_month_stages_and_resolves_legacy_names(calendar_db):
    auditor = Auditor(id="lead-1", name="Aylin Auditor", email="aylin@example.com")
    audit_set = AuditSet(
        id="set-1",
        plan_number=1725,
        company_name="Example Foods",
        standards=["QMS", "FSMS"],
        audit_type="initial",
        status="active",
    )
    stage = AuditSetStage(
        id="stage-1",
        audit_set_id=audit_set.id,
        stage_type="stage_2",
        stage_order=2,
        audit_date_start=date(2027, 1, 31),
        audit_date_end=date(2027, 2, 2),
        lead_auditor_id=auditor.id,
        auditors=[{"id": "auditor-2", "name": "Food Auditor", "standard": "FSMS"}],
        status="complete",
    )
    calendar_db.add_all([auditor, audit_set, stage])
    calendar_db.commit()

    bookings = list_planner_calendar_bookings(
        calendar_db,
        date(2027, 2, 1),
        date(2027, 2, 28),
    )

    assert [booking.id for booking in bookings] == [stage.id]
    assert bookings[0].start == date(2027, 1, 31)
    assert bookings[0].end == date(2027, 2, 2)
    assert bookings[0].standards == ["QMS", "FSMS"]
    assert [person.model_dump() for person in bookings[0].people] == [
        {"name": "Aylin Auditor", "role": "Lead Auditor", "standard": None},
        {"name": "Food Auditor", "role": "Auditor", "standard": "FSMS"},
    ]


def test_calendar_excludes_archived_cancelled_and_invalid_ranges(calendar_db):
    active = AuditSet(
        id="active",
        plan_number=1,
        company_name="Active Co",
        standards=["QMS"],
        audit_type="surveillance_1",
        status="active",
    )
    archived = AuditSet(
        id="archived",
        plan_number=2,
        company_name="Archived Co",
        standards=["QMS"],
        audit_type="initial",
        status="archived",
    )
    calendar_db.add_all([
        active,
        archived,
        AuditSetStage(
            id="visible",
            audit_set_id=active.id,
            stage_type="surveillance",
            stage_order=1,
            audit_date_start=date(2027, 2, 5),
            status="pending",
        ),
        AuditSetStage(
            id="cancelled",
            audit_set_id=active.id,
            stage_type="surveillance",
            stage_order=2,
            audit_date_start=date(2027, 2, 6),
            status="cancelled",
        ),
        AuditSetStage(
            id="invalid",
            audit_set_id=active.id,
            stage_type="surveillance",
            stage_order=3,
            audit_date_start=date(2027, 2, 8),
            audit_date_end=date(2027, 2, 7),
            status="pending",
        ),
        AuditSetStage(
            id="archived-stage",
            audit_set_id=archived.id,
            stage_type="stage_1",
            stage_order=1,
            audit_date_start=date(2027, 2, 9),
            status="pending",
        ),
    ])
    calendar_db.commit()

    bookings = list_planner_calendar_bookings(
        calendar_db,
        date(2027, 2, 1),
        date(2027, 2, 28),
    )

    assert [booking.id for booking in bookings] == ["visible"]
    assert bookings[0].people == []
