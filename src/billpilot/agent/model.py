"""Chat models: an OpenAI-compatible HTTP client, and scripted stand-ins.

The scripted models are for tests and CI. They do not open a socket.
"""

import json
from dataclasses import dataclass, field

import httpx

from billpilot.agent.tools import ToolSpec, openai_tools
from billpilot.config import Settings


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Message:
    role: str
    content: str = ""
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None


@dataclass
class Completion:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""


class ScriptedChatModel:
    """Returns a fixed sequence of completions. Tests use this to force a path."""

    name = "scripted"

    def __init__(self, steps: list[Completion]) -> None:
        self.steps = list(steps)
        self.seen: list[list[Message]] = []

    def complete(self, messages: list[Message], tools: list[ToolSpec], max_tokens: int | None = None) -> Completion:
        del tools, max_tokens
        self.seen.append(list(messages))
        if not self.steps:
            return Completion(content="No scripted step left.", model=self.name, prompt_tokens=1, completion_tokens=1)
        return self.steps.pop(0)


class OpenAICompatibleModel:
    """POST {LLM_BASE_URL}/chat/completions. Any host that speaks this API works."""

    def __init__(self, settings: Settings) -> None:
        if not settings.llm_api_key:
            raise RuntimeError("LLM_BACKEND=api requires LLM_API_KEY.")
        self._settings = settings
        self.name = settings.llm_model

    def complete(self, messages: list[Message], tools: list[ToolSpec], max_tokens: int | None = None) -> Completion:
        payload: dict = {
            "model": self._settings.llm_model,
            "temperature": 0,
            "messages": [_encode(message) for message in messages],
        }
        if tools:
            payload["tools"] = openai_tools(tools)
            payload["tool_choice"] = "auto"
        if max_tokens:
            payload["max_tokens"] = max_tokens
        url = self._settings.llm_base_url.rstrip("/") + "/chat/completions"
        response = httpx.post(
            url,
            headers={"Authorization": f"Bearer {self._settings.llm_api_key}"},
            json=payload,
            timeout=self._settings.llm_timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        message = data["choices"][0]["message"]
        calls: list[ToolCall] = []
        for call in message.get("tool_calls") or []:
            raw = (call.get("function") or {}).get("arguments") or "{}"
            try:
                arguments = json.loads(raw)
            except json.JSONDecodeError:
                arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}
            calls.append(
                ToolCall(
                    id=str(call.get("id") or f"call-{len(calls) + 1}"),
                    name=str((call.get("function") or {}).get("name") or ""),
                    arguments=arguments,
                )
            )
        usage = data.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or _estimate("".join(item.content for item in messages)))
        completion_text = message.get("content") or ""
        completion_tokens = int(usage.get("completion_tokens") or _estimate(completion_text or json.dumps(calls)))
        return Completion(
            content=completion_text or "",
            tool_calls=calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            model=str(data.get("model") or self._settings.llm_model),
        )


def build_model(settings: Settings):
    if settings.llm_backend == "fake":
        from billpilot.agent.fake import FakeChatModel

        return FakeChatModel()
    if settings.llm_backend == "api":
        return OpenAICompatibleModel(settings)
    raise RuntimeError(f"Unknown LLM_BACKEND {settings.llm_backend!r}. Use fake or api.")


def _encode(message: Message) -> dict:
    if message.role == "assistant" and message.tool_calls:
        return {
            "role": "assistant",
            "content": message.content or None,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                }
                for call in message.tool_calls
            ],
        }
    if message.role == "tool":
        return {"role": "tool", "tool_call_id": message.tool_call_id, "content": message.content}
    return {"role": message.role, "content": message.content}


def _estimate(text: str) -> int:
    return max(1, len(text) // 4)
