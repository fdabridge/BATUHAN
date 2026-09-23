"""OpenAI Responses API adapter used by Certiva's AI workflows.

The application historically called a message-style SDK directly from many
features.  This adapter keeps that small internal interface stable while the
actual provider is OpenAI's Responses API.  It deliberately uses stateless
requests (``store=False``) because audit inputs can contain confidential client
information.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any


logger = logging.getLogger(__name__)


@dataclass
class TextBlock:
    type: str = "text"
    text: str = ""


@dataclass
class ToolUseBlock:
    type: str = "tool_use"
    name: str = ""
    input: dict[str, Any] = field(default_factory=dict)


@dataclass
class AIMessage:
    content: list[TextBlock | ToolUseBlock]
    stop_reason: str = "end_turn"
    model: str = ""
    request_id: str = ""
    usage: Any = None


def _normalise_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)

    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
            continue
        if not isinstance(block, dict):
            parts.append(str(block))
            continue
        block_type = block.get("type")
        if block_type in {None, "text", "input_text"}:
            parts.append(str(block.get("text", "")))
        elif block_type == "document":
            source = block.get("source", {})
            parts.append(str(source.get("data", "")))
    return "\n".join(part for part in parts if part)


def _normalise_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "role": str(message.get("role", "user")),
            "content": _normalise_content(message.get("content", "")),
        }
        for message in messages
    ]


def _normalise_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    normalised: list[dict[str, Any]] = []
    for tool in tools or []:
        normalised.append(
            {
                "type": "function",
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {"type": "object"}),
                "strict": True,
            }
        )
    return normalised


def _normalise_tool_choice(tool_choice: dict[str, Any] | None) -> Any:
    if not tool_choice:
        return None
    if tool_choice.get("type") == "tool" and tool_choice.get("name"):
        return {"type": "function", "name": tool_choice["name"]}
    return tool_choice


def _item_value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


class _Messages:
    def __init__(self, owner: "OpenAIClient") -> None:
        self._owner = owner

    def create(
        self,
        *,
        model: str,
        max_tokens: int,
        messages: list[dict[str, Any]],
        system: str | None = None,
        temperature: float | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | None = None,
        **_: Any,
    ) -> AIMessage:
        client = self._owner._get_client()
        request: dict[str, Any] = {
            "model": model,
            "input": _normalise_messages(messages),
            "max_output_tokens": max_tokens,
            "store": False,
        }
        if system:
            request["instructions"] = system

        openai_tools = _normalise_tools(tools)
        if openai_tools:
            request["tools"] = openai_tools
            request["tool_choice"] = _normalise_tool_choice(tool_choice) or "auto"

        # Current reasoning models control determinism through reasoning effort.
        # Keep temperature only for model families that explicitly accept it.
        if temperature is not None and not model.startswith(("gpt-5", "gpt-6")):
            request["temperature"] = temperature
        if model.startswith(("gpt-5", "gpt-6")):
            request["reasoning"] = {"effort": self._owner.reasoning_effort}

        response = client.responses.create(**request)
        usage = getattr(response, "usage", None)
        logger.info(
            "OpenAI response completed | model=%s request_id=%s input_tokens=%s "
            "cached_input_tokens=%s output_tokens=%s",
            str(getattr(response, "model", model) or model),
            str(getattr(response, "_request_id", "") or ""),
            _item_value(usage, "input_tokens", None),
            _item_value(
                _item_value(usage, "input_tokens_details", None),
                "cached_tokens",
                None,
            ),
            _item_value(usage, "output_tokens", None),
        )
        content: list[TextBlock | ToolUseBlock] = []

        for item in getattr(response, "output", None) or []:
            if _item_value(item, "type") != "function_call":
                continue
            raw_arguments = _item_value(item, "arguments", "{}")
            try:
                arguments = (
                    raw_arguments
                    if isinstance(raw_arguments, dict)
                    else json.loads(raw_arguments or "{}")
                )
            except (TypeError, json.JSONDecodeError):
                arguments = {}
            content.append(
                ToolUseBlock(
                    name=str(_item_value(item, "name", "")),
                    input=arguments if isinstance(arguments, dict) else {},
                )
            )

        output_text = str(getattr(response, "output_text", "") or "")
        if output_text:
            content.append(TextBlock(text=output_text))

        incomplete_details = getattr(response, "incomplete_details", None)
        incomplete_reason = _item_value(incomplete_details, "reason", "")
        stop_reason = (
            "max_tokens"
            if incomplete_reason in {"max_output_tokens", "max_tokens"}
            else "end_turn"
        )
        return AIMessage(
            content=content,
            stop_reason=stop_reason,
            model=str(getattr(response, "model", model) or model),
            request_id=str(getattr(response, "_request_id", "") or ""),
            usage=usage,
        )


class OpenAIClient:
    """Small application-facing wrapper around the official OpenAI client."""

    def __init__(self, *, api_key: str, reasoning_effort: str = "medium") -> None:
        self.api_key = api_key
        self.reasoning_effort = reasoning_effort
        self._sdk_client: Any = None
        self.messages = _Messages(self)

    def _get_client(self) -> Any:
        if self._sdk_client is None:
            if not self.api_key or self.api_key.startswith("your-"):
                raise RuntimeError(
                    "OPENAI_API_KEY is not configured. Add a fresh project-scoped "
                    "key to the deployment secret store."
                )
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover - deployment dependency guard
                raise RuntimeError(
                    "The OpenAI SDK is not installed. Install backend requirements."
                ) from exc
            self._sdk_client = OpenAI(api_key=self.api_key)
        return self._sdk_client
