"""Per-step Langfuse traces for one copilot turn.

Tracing is on only when LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, and
LANGFUSE_HOST are all set. Otherwise every call is a no-op. A missing
package, a rejected client, or a host that is down is logged and swallowed.
The answer does not depend on the tracer.
"""

import logging
from typing import Any

from billpilot.config import Settings

logger = logging.getLogger("billpilot.agent.trace")

_client = None
_client_key: tuple[str, str, str] | None = None


def tracing_configured(settings: Settings) -> bool:
    return bool(
        settings.langfuse_public_key.strip() and settings.langfuse_secret_key.strip() and settings.langfuse_host.strip()
    )


def reset_client_cache() -> None:
    """Drop the cached SDK client. Tests use this so a fake is not reused."""
    global _client, _client_key
    _client = None
    _client_key = None


def get_langfuse_client(settings: Settings):
    """One process-wide client, or None when tracing is off or the SDK fails."""
    global _client, _client_key
    if not tracing_configured(settings):
        return None
    key = (settings.langfuse_public_key, settings.langfuse_secret_key, settings.langfuse_host)
    if _client is not None and _client_key == key:
        return _client
    try:
        from langfuse import Langfuse

        _client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
            timeout=3,
        )
        _client_key = key
        return _client
    except Exception:
        logger.exception("Langfuse client was not created.")
        _client = None
        _client_key = None
        return None


class NullTurnTrace:
    """Used when the keys are absent, or when the client could not be opened."""

    trace_id: str | None = None

    def span(self, name: str, **kwargs: Any) -> None:
        del name, kwargs

    def generation(self, name: str, **kwargs: Any) -> None:
        del name, kwargs

    def finish(self, **kwargs: Any) -> None:
        del kwargs


class LangfuseTurnTrace:
    """One trace. Child observations are spans, a retriever, and generations.

    `client` is the Langfuse SDK client, or a test double with the same
    methods: create_trace_id, start_observation, flush. Children are created
    on the root observation so they stay on this trace.
    """

    def __init__(self, client, *, persona: str, actor_id: str, request_id: str, message: str) -> None:
        self.trace_id: str | None = None
        self._client = client
        self._root = None
        self._closed = False
        self._disabled = False
        try:
            self.trace_id = client.create_trace_id(seed=request_id)
            self._root = client.start_observation(
                name="billpilot.chat",
                as_type="span",
                trace_context={"trace_id": self.trace_id},
                input={"message": message},
                metadata={"persona": persona, "actor_id": actor_id, "request_id": request_id},
            )
        except Exception:
            logger.exception("Langfuse trace was not opened.")
            self.trace_id = None
            self._root = None
            self._disabled = True

    def span(self, name: str, *, as_type: str = "span", input=None, output=None, metadata=None) -> None:
        self._child(name, as_type=as_type, input=input, output=output, metadata=metadata)

    def generation(
        self,
        name: str,
        *,
        model: str,
        input=None,
        output=None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cost=None,
    ) -> None:
        cost_details = None
        if cost is not None:
            cost_details = {"total": float(cost)}
        self._child(
            name,
            as_type="generation",
            input=input,
            output=output,
            metadata={"estimated_cost_usd": None if cost is None else f"{cost}"},
            model=model,
            usage_details={"input_tokens": int(prompt_tokens), "output_tokens": int(completion_tokens)},
            cost_details=cost_details,
        )

    def finish(self, *, output: str, decision: str, metadata=None) -> None:
        if self._closed:
            return
        self._closed = True
        if self._root is None:
            return
        try:
            extra = dict(metadata or {})
            extra["decision"] = decision
            self._root.update(output={"decision": decision, "answer": output[:1500]}, metadata=extra)
            self._root.end()
            self._client.flush()
        except Exception:
            logger.exception("Langfuse trace was not finished.")

    def _child(self, name: str, **kwargs: Any) -> None:
        if self._disabled or self._root is None:
            return
        try:
            child = self._root.start_observation(name=name, **kwargs)
            child.end()
        except Exception:
            logger.exception("Langfuse span %s was not recorded.", name)
            self._disabled = True


def build_turn_trace(settings: Settings, *, persona: str, actor_id: str, request_id: str, message: str):
    client = get_langfuse_client(settings)
    if client is None:
        return NullTurnTrace()
    return LangfuseTurnTrace(
        client,
        persona=persona,
        actor_id=actor_id,
        request_id=request_id,
        message=message,
    )
