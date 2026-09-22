from __future__ import annotations

import pytest

from audit_set.workflow_policy import status_at_least


@pytest.mark.parametrize(
    "status",
    [
        "fr218_complete",
        "audit_scheduled",
        "audit_in_progress",
        "under_review",
        "committee_review",
        "certified",
    ],
)
def test_fr222_gate_accepts_recertification_states_after_fr218(status):
    assert status_at_least(status, "fr218_complete") is True


@pytest.mark.parametrize(
    "status",
    ["pending_review", "in_planning", "quotation_sent", "agreement_signed", "fr218_in_progress"],
)
def test_fr222_gate_still_rejects_states_before_fr218_completion(status):
    assert status_at_least(status, "fr218_complete") is False


@pytest.mark.parametrize("status", ["quotation_sent", "agreement_signed", "certified"])
def test_fr218_first_order_accepts_commercial_and_completed_states(status):
    assert status_at_least(status, "fr218_complete", version=2) is True
