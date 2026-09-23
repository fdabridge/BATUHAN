from types import SimpleNamespace

import pytest

from ai.openai_client import OpenAIClient, TextBlock, ToolUseBlock


class _Responses:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def _client(response):
    adapter = OpenAIClient(api_key="test-key", reasoning_effort="medium")
    responses = _Responses(response)
    adapter._sdk_client = SimpleNamespace(responses=responses)
    return adapter, responses


def test_text_request_uses_stateless_responses_api():
    adapter, responses = _client(
        SimpleNamespace(
            output=[],
            output_text="completed report",
            status="completed",
            incomplete_details=None,
            model="gpt-6-sol",
            usage=SimpleNamespace(input_tokens=12, output_tokens=3),
            _request_id="req_123",
        )
    )

    message = adapter.messages.create(
        model="gpt-6-sol",
        max_tokens=1000,
        system="Follow the certification rules.",
        temperature=0.2,
        messages=[{"role": "user", "content": "Generate the report."}],
    )

    assert responses.kwargs["store"] is False
    assert responses.kwargs["max_output_tokens"] == 1000
    assert responses.kwargs["instructions"] == "Follow the certification rules."
    assert responses.kwargs["reasoning"] == {"effort": "medium"}
    assert "temperature" not in responses.kwargs
    assert message.content == [TextBlock(text="completed report")]
    assert message.request_id == "req_123"


def test_forced_tool_is_translated_to_function_call_and_back():
    adapter, responses = _client(
        SimpleNamespace(
            output=[
                SimpleNamespace(
                    type="function_call",
                    name="submit_audit_schedule",
                    arguments='{"days": [{"day_number": 1}]}',
                )
            ],
            output_text="",
            status="completed",
            incomplete_details=None,
            model="gpt-6-sol",
            usage=None,
            _request_id="req_tool",
        )
    )

    message = adapter.messages.create(
        model="gpt-6-sol",
        max_tokens=16000,
        messages=[{"role": "user", "content": "Build a schedule."}],
        tools=[{
            "name": "submit_audit_schedule",
            "description": "Submit the schedule.",
            "input_schema": {
                "type": "object",
                "properties": {"days": {"type": "array"}},
                "required": ["days"],
                "additionalProperties": False,
            },
        }],
        tool_choice={"type": "tool", "name": "submit_audit_schedule"},
    )

    assert responses.kwargs["tools"][0]["type"] == "function"
    assert responses.kwargs["tools"][0]["strict"] is True
    assert responses.kwargs["tool_choice"] == {
        "type": "function",
        "name": "submit_audit_schedule",
    }
    assert message.content == [
        ToolUseBlock(
            name="submit_audit_schedule",
            input={"days": [{"day_number": 1}]},
        )
    ]


def test_output_limit_maps_to_existing_retry_contract():
    adapter, _ = _client(
        SimpleNamespace(
            output=[],
            output_text="",
            status="incomplete",
            incomplete_details=SimpleNamespace(reason="max_output_tokens"),
            model="gpt-6-sol",
            usage=None,
            _request_id="req_limit",
        )
    )

    message = adapter.messages.create(
        model="gpt-6-sol",
        max_tokens=10,
        messages=[{"role": "user", "content": "Generate."}],
    )

    assert message.stop_reason == "max_tokens"


def test_missing_key_fails_before_sdk_or_network_use():
    adapter = OpenAIClient(api_key="")

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY is not configured"):
        adapter.messages.create(
            model="gpt-6-sol",
            max_tokens=10,
            messages=[{"role": "user", "content": "Generate."}],
        )
