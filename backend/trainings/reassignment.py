"""Safe state rules for retrying a failed training assignment."""
from __future__ import annotations

from datetime import datetime
from typing import Any


def can_reassign_failed_exam(assignment: Any) -> bool:
    """Only a completed latest attempt with an explicit failure is retryable."""
    return bool(
        getattr(assignment, "exam_completed", False)
        and getattr(assignment, "exam_passed", None) is False
    )


def reset_assignment_for_retake(
    assignment: Any,
    *,
    assigned_by: str,
    assigned_at: datetime,
) -> None:
    """Reset course progress and current exam state for a clean retry."""
    if not can_reassign_failed_exam(assignment):
        raise ValueError("Only a failed completed exam can be reassigned")

    assignment.assigned_by = assigned_by
    assignment.assigned_at = assigned_at
    assignment.training_completed = False
    assignment.training_completed_at = None
    assignment.training_last_page_seen = 0
    assignment.exam_completed = False
    assignment.exam_score = None
    assignment.exam_passed = None
    assignment.exam_completed_at = None
    assignment.exam_answers = None
    assignment.exam_started_at = None
    assignment.exam_due_at = None
