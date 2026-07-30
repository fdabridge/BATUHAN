from datetime import datetime
from types import SimpleNamespace

import pytest

from trainings.reassignment import (
    can_reassign_failed_exam,
    reset_assignment_for_retake,
)


def _assignment(**overrides):
    values = {
        "assigned_by": "original-officer",
        "assigned_at": datetime(2026, 7, 1),
        "training_completed": True,
        "training_completed_at": datetime(2026, 7, 2),
        "training_last_page_seen": 12,
        "exam_completed": True,
        "exam_score": 40.0,
        "exam_passed": False,
        "exam_completed_at": datetime(2026, 7, 3),
        "exam_answers": '[{"question_number": 1, "selected_option_index": 0}]',
        "exam_started_at": datetime(2026, 7, 3, 9),
        "exam_due_at": datetime(2026, 7, 3, 9, 30),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_only_latest_failed_completed_exam_can_be_reassigned():
    assert can_reassign_failed_exam(_assignment()) is True
    assert can_reassign_failed_exam(_assignment(exam_passed=True)) is False
    assert can_reassign_failed_exam(
        _assignment(exam_completed=False, exam_passed=None),
    ) is False


def test_reassignment_resets_training_exam_answers_and_timer():
    assignment = _assignment()
    reassigned_at = datetime(2026, 7, 30, 10, 0)

    reset_assignment_for_retake(
        assignment,
        assigned_by="training-officer",
        assigned_at=reassigned_at,
    )

    assert assignment.assigned_by == "training-officer"
    assert assignment.assigned_at == reassigned_at
    assert assignment.training_completed is False
    assert assignment.training_completed_at is None
    assert assignment.training_last_page_seen == 0
    assert assignment.exam_completed is False
    assert assignment.exam_score is None
    assert assignment.exam_passed is None
    assert assignment.exam_completed_at is None
    assert assignment.exam_answers is None
    assert assignment.exam_started_at is None
    assert assignment.exam_due_at is None


@pytest.mark.parametrize(
    "assignment",
    [
        _assignment(exam_passed=True),
        _assignment(exam_completed=False, exam_passed=None),
    ],
)
def test_reset_rejects_passed_and_incomplete_assignments(assignment):
    with pytest.raises(ValueError, match="failed completed exam"):
        reset_assignment_for_retake(
            assignment,
            assigned_by="training-officer",
            assigned_at=datetime(2026, 7, 30),
        )
