"""Regression coverage for structured AI audit-plan generation."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from audit_plan.schedule_generator import (
    _SCHEDULE_TOOL_NAME,
    _extract_schedule_payload,
    _integrated_mode,
    _repair_days_from_windows,
    _validate_schedule,
    DaySchedule,
    Slot,
    generate_schedule,
)
from audit_plan.clause_map import CLAUSE_MAP, normalize_standard
from audit_plan.template_reader import AuditPlanContext, DayWindow, _normalise_standards


def _payload() -> dict:
    return {
        "days": [{
            "day_number": 1,
            "date": "17.08.2026",
            "site": "Main site",
            "slots": [
                {
                    "time": "09:00 - 09:30",
                    "is_break": False,
                    "standard": "",
                    "clauses": "",
                    "activity": "Opening Meeting",
                    "auditors": "Lead Auditor (LA)",
                },
                {
                    "time": "09:30 - 13:00",
                    "is_break": False,
                    "standard": "ISO 9001:2015",
                    "clauses": CLAUSE_MAP["ISO 9001:2015"]["Stage 2"],
                    "activity": "QMS audit",
                    "auditors": "Lead Auditor (LA)",
                },
                {
                    "time": "13:00 - 14:00",
                    "is_break": True,
                    "standard": "",
                    "clauses": "",
                    "activity": "Lunch Break",
                    "auditors": "",
                },
                {
                    "time": "14:00 - 16:30",
                    "is_break": False,
                    "standard": "ISO 9001:2015",
                    "clauses": "5.1-5.2",
                    "activity": "QMS audit",
                    "auditors": "Lead Auditor (LA)",
                },
                {
                    "time": "16:30 - 17:00",
                    "is_break": False,
                    "standard": "",
                    "clauses": "",
                    "activity": "Closing Meeting",
                    "auditors": "Lead Auditor (LA)",
                },
            ],
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


def test_generate_schedule_retries_a_structurally_valid_but_incomplete_plan():
    incomplete = _payload()
    incomplete["days"][0]["slots"][1]["clauses"] = "4.1"
    messages = MagicMock()
    messages.create.side_effect = [
        _response([_tool_block(incomplete)]),
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
    assert len(days) == 1


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


def test_generate_schedule_retries_temporary_claude_api_failure():
    class APIConnectionError(Exception):
        pass

    messages = MagicMock()
    messages.create.side_effect = [
        APIConnectionError("connection reset"),
        _response([_tool_block()]),
    ]
    client = SimpleNamespace(messages=messages)

    with (
        patch("audit_plan.schedule_generator.get_settings", return_value=SimpleNamespace(
            anthropic_api_key="test", claude_model="test-model",
        )),
        patch("audit_plan.schedule_generator.anthropic.Anthropic", return_value=client),
        patch("audit_plan.schedule_generator.time.sleep") as sleep,
    ):
        days = generate_schedule(_context())

    assert len(days) == 1
    assert messages.create.call_count == 2
    sleep.assert_called_once_with(0.5)


def test_generate_schedule_explains_repeated_temporary_api_failure():
    class RateLimitError(Exception):
        status_code = 429

    messages = MagicMock()
    messages.create.side_effect = RateLimitError("overloaded")
    client = SimpleNamespace(messages=messages)

    with (
        patch("audit_plan.schedule_generator.get_settings", return_value=SimpleNamespace(
            anthropic_api_key="test", claude_model="test-model",
        )),
        patch("audit_plan.schedule_generator.anthropic.Anthropic", return_value=client),
        patch("audit_plan.schedule_generator.time.sleep"),
        pytest.raises(ValueError, match="temporarily unavailable"),
    ):
        generate_schedule(_context())

    assert messages.create.call_count == 2


@pytest.mark.parametrize("raw, expected", [
    ("FSMS", "ISO 22000:2018"),
    ("ISO 22000", "ISO 22000:2018"),
    ("QMS", "ISO 9001:2015"),
])
def test_management_system_aliases_normalize_for_integrated_plans(raw, expected):
    assert normalize_standard(raw) == expected


def test_qms_fsms_plus_separated_template_text_preserves_both_standards():
    assert _normalise_standards("QMS + FSMS") == [
        "ISO 9001:2015",
        "ISO 22000:2018",
    ]


def test_stage1_qms_fsms_integrated_prompt_contains_both_clause_sets():
    ctx = _context()
    ctx.standards_raw = "QMS + FSMS"
    ctx.standards = ["ISO 9001:2015", "ISO 22000:2018"]
    ctx.audit_type_raw = "Stage 1"
    ctx.audit_type = "Stage 1"
    ctx.category = "CI"

    messages = MagicMock()
    integrated_payload = _payload()
    for slot in integrated_payload["days"][0]["slots"]:
        if slot["standard"]:
            slot["standard"] = "ISO 9001:2015\nISO 22000:2018"
    integrated_payload["days"][0]["slots"][1]["clauses"] += (
        " / " + CLAUSE_MAP["ISO 22000:2018"]["Stage 1"]
    )
    messages.create.return_value = _response([_tool_block(integrated_payload)])
    client = SimpleNamespace(messages=messages)

    with (
        patch("audit_plan.schedule_generator.get_settings", return_value=SimpleNamespace(
            anthropic_api_key="test", claude_model="test-model",
        )),
        patch("audit_plan.schedule_generator.anthropic.Anthropic", return_value=client),
    ):
        generate_schedule(ctx)

    prompt = messages.create.call_args.kwargs["messages"][0]["content"]
    for standard in ctx.standards:
        assert f"{standard} (Stage 1): {CLAUSE_MAP[standard]['Stage 1']}" in prompt
    assert "INTEGRATED MODE: SIMULTANEOUS" in prompt
    assert "CATEGORY / TECHNICAL AREA: CI" in prompt


@pytest.mark.parametrize("standards, days, expected", [
    (["ISO 22000:2018"], 5, "SINGLE"),
    (["ISO 9001:2015", "ISO 22000:2018"], 4, "SIMULTANEOUS"),
    (["ISO 9001:2015", "ISO 22000:2018"], 5, "BLOCK"),
    (["ISO 9001:2015", "ISO 14001:2015", "ISO 22000:2018"], 6, "SIMULTANEOUS"),
    (["ISO 9001:2015", "ISO 14001:2015", "ISO 22000:2018"], 7, "BLOCK"),
])
def test_integrated_day_mapping_mode_matrix(standards, days, expected):
    assert _integrated_mode(standards, days) == expected


def test_authoritative_windows_replace_model_date_and_site():
    ctx = _context()
    days = [DaySchedule(1, "wrong", "wrong", [
        Slot("09.00 – 09.30", False, "", "", "Opening Meeting", "LA"),
    ])]
    repaired = _repair_days_from_windows(days, ctx.day_windows, ctx.address)
    assert repaired[0].date == "17.08.2026"
    assert repaired[0].site == "Main site"


def test_authoritative_windows_reject_wrong_day_count():
    ctx = _context()
    with pytest.raises(ValueError, match="authoritative day window"):
        _repair_days_from_windows([], ctx.day_windows, ctx.address)


def test_integrated_schedule_rejects_an_omitted_standard():
    ctx = _context()
    ctx.standards = ["ISO 9001:2015", "ISO 22000:2018"]
    days_raw = _payload()["days"]
    days = [DaySchedule(
        day_number=1,
        date="17.08.2026",
        site="Main site",
        slots=[Slot(**slot) for slot in days_raw[0]["slots"]],
    )]
    with pytest.raises(ValueError, match="omitted standard.*ISO 22000"):
        _validate_schedule(days, ctx)


def test_schedule_rejects_wrong_lunch_window_and_not_applicable_clause():
    ctx = _context()
    days_raw = _payload()["days"]
    days_raw[0]["slots"][2]["time"] = "12:30 - 13:30"
    days = [DaySchedule(1, "17.08.2026", "Main site", [
        Slot(**slot) for slot in days_raw[0]["slots"]
    ])]
    with pytest.raises(ValueError, match="lunch window"):
        _validate_schedule(days, ctx)

    days_raw = _payload()["days"]
    days_raw[0]["slots"][1]["clauses"] = "8.3-8.4"
    ctx.not_applicable = "Clause 8.3 is not applicable"
    days = [DaySchedule(1, "17.08.2026", "Main site", [
        Slot(**slot) for slot in days_raw[0]["slots"]
    ])]
    with pytest.raises(ValueError, match="not-applicable.*8.3"):
        _validate_schedule(days, ctx)


def test_schedule_rejects_omitted_required_clauses():
    ctx = _context()
    days_raw = _payload()["days"]
    days_raw[0]["slots"][1]["clauses"] = "4.1-4.2"
    days = [DaySchedule(1, "17.08.2026", "Main site", [
        Slot(**slot) for slot in days_raw[0]["slots"]
    ])]
    with pytest.raises(ValueError, match="omitted required clause"):
        _validate_schedule(days, ctx)
