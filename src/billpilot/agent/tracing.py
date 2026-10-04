"""Optional Langfuse export.

Off unless LANGFUSE_ENABLED is true. A missing package or a network error is
logged and swallowed: the copilot answer must not depend on the tracer.
"""

import logging

logger = logging.getLogger("billpilot.agent.trace")


def trace_run(settings, result) -> None:
    if not settings.langfuse_enabled:
        return
    try:
        from langfuse import Langfuse
    except ImportError:
        logger.warning("LANGFUSE_ENABLED is set but the langfuse package is not installed.")
        return
    try:
        client = Langfuse(
            public_key=settings.langfuse_public_key or None,
            secret_key=settings.langfuse_secret_key or None,
            host=settings.langfuse_host or None,
        )
        trace = client.trace(
            name="billpilot.agent",
            user_id=result.actor_id,
            input=result.user_message,
            output=result.answer,
            metadata={
                "persona": result.persona,
                "run_id": result.run_id,
                "refusal": result.refusal,
                "model": result.model,
            },
        )
        trace.update(tags=["billpilot", result.persona])
        client.flush()
    except Exception:
        logger.exception("Langfuse trace was not recorded.")
