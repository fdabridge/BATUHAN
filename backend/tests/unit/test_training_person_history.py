from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from auth.db_models import Base as AuthBase, PlatformUser
from trainings.models import (
    Base as TrainingBase,
    TrainingAssignment,
    TrainingCourse,
    TrainingExamAttempt,
)
from trainings.router import (
    _person_exam_history_rows,
    training_people,
    user_exam_history,
)


@pytest.fixture
def person_history_sessions():
    training_engine = create_engine("sqlite:///:memory:")
    auth_engine = create_engine("sqlite:///:memory:")
    TrainingBase.metadata.create_all(training_engine)
    AuthBase.metadata.create_all(auth_engine)
    training_db = sessionmaker(bind=training_engine)()
    auth_db = sessionmaker(bind=auth_engine)()
    try:
        yield training_db, auth_db
    finally:
        training_db.close()
        auth_db.close()


def _assignment(**overrides):
    values = {
        "id": "assignment-1",
        "course_id": "course-1",
        "exam_completed": True,
        "exam_completed_at": datetime(2026, 8, 1, 10, 30),
        "exam_score": 80.0,
        "exam_passed": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _attempt(**overrides):
    values = {
        "id": "attempt-1",
        "assignment_id": "assignment-1",
        "course_id": "course-1",
        "attempt_number": 1,
        "exam_completed_at": datetime(2026, 8, 1, 10, 30),
        "exam_score": 80.0,
        "exam_passed": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_archived_current_attempt_is_not_duplicated_by_assignment():
    rows = _person_exam_history_rows(
        [_assignment()],
        [_attempt()],
        {"course-1": SimpleNamespace(title="Internal Auditor Training")},
    )

    assert len(rows) == 1
    assert rows[0]["course_title"] == "Internal Auditor Training"
    assert rows[0]["exam_taken_at"] == "2026-08-01T10:30:00Z"
    assert rows[0]["exam_score"] == 80.0


def test_legacy_completed_assignment_remains_visible_without_attempt_row():
    rows = _person_exam_history_rows(
        [_assignment(exam_score=65.0, exam_passed=False)],
        [],
        {"course-1": SimpleNamespace(title="QMS Refresher")},
    )

    assert rows == [{
        "attempt_id": None,
        "assignment_id": "assignment-1",
        "course_id": "course-1",
        "course_title": "QMS Refresher",
        "attempt_number": 1,
        "exam_taken_at": "2026-08-01T10:30:00Z",
        "exam_score": 65.0,
        "exam_passed": False,
        "source": "legacy_assignment",
    }]


def test_failed_retake_history_keeps_both_attempts_newest_first():
    rows = _person_exam_history_rows(
        [],
        [
            _attempt(exam_score=45.0, exam_passed=False),
            _attempt(
                id="attempt-2",
                attempt_number=2,
                exam_completed_at=datetime(2026, 8, 5, 14, 0),
                exam_score=90.0,
                exam_passed=True,
            ),
        ],
        {"course-1": SimpleNamespace(title="QMS Refresher")},
    )

    assert [row["attempt_number"] for row in rows] == [2, 1]
    assert [row["exam_passed"] for row in rows] == [True, False]


def test_person_endpoints_return_identity_totals_dates_and_scores(
    person_history_sessions,
):
    training_db, auth_db = person_history_sessions
    user = PlatformUser(
        id="person-1",
        email="auditor@example.com",
        password_hash="not-used",
        full_name="Alex Auditor",
        role="auditor",
        is_active=True,
    )
    course = TrainingCourse(
        id="course-1",
        title="Internal Auditor Training",
        created_by="officer-1",
    )
    assignment = TrainingAssignment(
        id="assignment-1",
        course_id=course.id,
        user_id=user.id,
        assigned_by="officer-1",
        exam_completed=False,
    )
    attempts = [
        TrainingExamAttempt(
            id="attempt-1",
            assignment_id=assignment.id,
            course_id=course.id,
            user_id=user.id,
            attempt_number=1,
            exam_score=50.0,
            exam_passed=False,
            exam_completed_at=datetime(2026, 8, 1, 9, 0),
        ),
        TrainingExamAttempt(
            id="attempt-2",
            assignment_id=assignment.id,
            course_id=course.id,
            user_id=user.id,
            attempt_number=2,
            exam_score=90.0,
            exam_passed=True,
            exam_completed_at=datetime(2026, 8, 5, 14, 30),
        ),
    ]
    auth_db.add(user)
    training_db.add_all([course, assignment, *attempts])
    auth_db.commit()
    training_db.commit()
    officer = SimpleNamespace(id="officer-1", role="training_officer")

    people = training_people(officer, training_db, auth_db)
    history = user_exam_history(user.id, officer, training_db, auth_db)

    assert people == [{
        "user_id": user.id,
        "full_name": "Alex Auditor",
        "email": "auditor@example.com",
        "role": "auditor",
        "assignment_count": 1,
        "exam_count": 2,
        "passed_count": 1,
        "failed_count": 1,
        "last_exam_at": "2026-08-05T14:30:00Z",
    }]
    assert history["summary"] == {
        "exam_count": 2,
        "passed_count": 1,
        "failed_count": 1,
        "average_score": 70.0,
    }
    assert [exam["exam_score"] for exam in history["exams"]] == [90.0, 50.0]
    assert history["exams"][0]["course_title"] == "Internal Auditor Training"
