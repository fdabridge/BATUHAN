from __future__ import annotations

import ast
from pathlib import Path
from typing import Optional

import pytest


ROUTER_PATH = Path(__file__).resolve().parents[2] / "audit_set" / "documents_router.py"


def _load_status_at_least():
    """Load the real lightweight status helper without importing PDF dependencies."""
    module = ast.parse(ROUTER_PATH.read_text())
    selected = [
        node
        for node in module.body
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "STATUS_ORDER" for target in node.targets)
        )
        or (isinstance(node, ast.FunctionDef) and node.name == "_status_at_least")
    ]
    namespace = {"Optional": Optional}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(ROUTER_PATH), "exec"), namespace)
    return namespace["_status_at_least"]


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
    status_at_least = _load_status_at_least()

    assert status_at_least(status, "fr218_complete") is True


@pytest.mark.parametrize(
    "status",
    ["pending_review", "in_planning", "quotation_sent", "agreement_signed", "fr218_in_progress"],
)
def test_fr222_gate_still_rejects_states_before_fr218_completion(status):
    status_at_least = _load_status_at_least()

    assert status_at_least(status, "fr218_complete") is False
