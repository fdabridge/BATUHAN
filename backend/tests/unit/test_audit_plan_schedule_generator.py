"""Regression coverage for structured AI audit-plan generation."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from audit_plan.schedule_generator import (
    _SCHEDULE_TOOL_NAME,
    _extract_schedule_payload,
    generate_schedule,
)
from audit_plan.template_reader import AuditPlanContext, DayWindow


def _payload() -> dict:
    return {
        "days": [{
            "day_number": 1,
            "date": "17.08.2026",
            "site": "Main site",
            "slots": [{
                "time": "09:00 - 09:30",
                "is_break": False,
                "standard": "",
                "clauses": "",
                "activity": "Opening Meeting",
                "auditors": "Lead Auditor (LA)",
            }],
        }],
    }


def _context() -> AuditPlanContext:
    return AuditPlanContext(
        date="17.08.2026",
        project_number="1725",
        org_name="Example Foods",
        address="Main site",
        telephone="",
        email="",
        org_representative="",
        standards_raw="ISO 9001:2015",
        standards=["ISO 9001:2015"],
        ea_code="3",
        category="",
        scope="Food production",
        not_applicable="",
        audit_type_raw="Stage 2",
        audit_type="Stage 2",
        audit_dates="17.08.2026",
        num_employees="14",
        audit_time="1 day",
        shift_number="1",
        language="English",
        audit_criteria="",
        audit_objectives="",
        day_windows=[DayWindow(
            date="17.08.2026",
            start_time="09.00",
            end_time="17.00",
            site="Main site",
        )],
    )


def _response(content, stop_reason="tool_use"):
    return SimpleNamespace(content=content, stop_reason=stop_reason)


def _tool_block(payload=None):
    return SimpleNamespace(
        type="tool_use",
        name=_SCHEDULE_TOOL_NAME,
        input=_payload() if payload is None else payload,
    )


def test_extracts_forced_tool_payload_without_text_json():
    assert _extract_schedule_payload(_response([_tool_block()])) == _payload()


def test_text_json_remains_a_compatibility_fallback_across_content_blocks():
    response = _response([
        SimpleNamespace(type="thinking", thinking="internal"),
        SimpleNamespace(type="text", text='```json\n{"days": []}\n```'),
    ])
    assert _extract_schedule_payload(response) == {"days": []}


def test_generate_schedule_retries_empty_response_then_uses_tool_payload():
    messages = MagicMock()
    messages.create.side_effect = [
        _response([], stop_reason="max_tokens"),
        _response([_tool_block()]),
    ]
    client = SimpleNamespace(messages=messages)

    with (
        patch("audit_plan.schedule_generator.get_settings", return_value=SimpleNamespace(
            anthropic_api_key="test", claude_model="test-model",
        )),
        patch("audit_plan.schedule_generator.anthropic.Anthropic", return_value=client),
    ):
        days = generate_schedule(_context())

    assert messages.create.call_count == 2
    assert days[0].slots[0].time == "09.00 – 09.30"
    request = messages.create.call_args.kwargs
    assert request["max_tokens"] == 16000
    assert request["tool_choice"] == {"type": "tool", "name": _SCHEDULE_TOOL_NAME}
    assert request["tools"][0]["input_schema"]["required"] == ["days"]


def test_generate_schedule_reports_output_limit_instead_of_json_decoder_error():
    messages = MagicMock()
    messages.create.return_value = _response([], stop_reason="max_tokens")
    client = SimpleNamespace(messages=messages)

    with (
        patch("audit_plan.schedule_generator.get_settings", return_value=SimpleNamespace(
            anthropic_api_key="test", claude_model="test-model",
        )),
        patch("audit_plan.schedule_generator.anthropic.Anthropic", return_value=client),
        pytest.raises(ValueError, match="output limit") as exc_info,
    ):
        generate_schedule(_context())

    assert "line 1 column 1" not in str(exc_info.value)
