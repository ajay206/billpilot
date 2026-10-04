"""Persist one copilot turn and a matching audit_log row.

The transcript (prompt, tools, citations, proposals, tokens, cost) is on
agent_runs. audit_log keeps the short version every other write already uses,
and agent_runs.audit_log_id ties them together.
"""

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from billpilot.api.audit import append_audit
from billpilot.models import AgentRun


def save_run(session: Session, result) -> uuid.UUID:
    run_id = uuid.uuid4()
    account_id = _uuid(result.account_id)
    audit = append_audit(
        session,
        role=result.persona,
        actor_id=result.actor_id,
        request_id=result.request_id,
        action="agent.chat",
        resource_type="agent_run",
        resource_id=run_id,
        account_id=account_id,
        payload={
            "refusal": result.refusal,
            "refusalReason": result.refusal_reason,
            "grounded": result.grounded,
            "tools": [call["name"] for call in result.tool_calls],
            "citations": result.citations,
            "proposedActions": result.proposed_actions,
            "promptTokens": result.prompt_tokens,
            "completionTokens": result.completion_tokens,
            "estimatedCostUsd": f"{result.estimated_cost_usd:.6f}",
            "latencyMs": result.latency_ms,
            "decision": _decision(result),
            "model": result.model,
        },
    )
    session.flush()
    session.add(
        AgentRun(
            id=run_id,
            occurred_at=datetime.now(UTC),
            request_id=result.request_id,
            persona=result.persona,
            actor_id=result.actor_id,
            account_id=account_id,
            user_message=result.user_message,
            system_prompt=result.system_prompt,
            answer=result.answer,
            refusal=result.refusal,
            grounded=result.grounded,
            tool_calls=_jsonable(result.tool_calls),
            citations=_jsonable(result.citations),
            proposed_actions=_jsonable(result.proposed_actions),
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            estimated_cost_usd=result.estimated_cost_usd,
            latency_ms=result.latency_ms,
            model=result.model[:80],
            audit_log_id=audit.id,
        )
    )
    session.commit()
    return run_id


def _decision(result) -> str:
    """read, advise, propose, or refuse. The approver is recorded later, on the approve action."""
    if result.refusal:
        return "refuse"
    if any(action.get("type") == "credit" for action in result.proposed_actions):
        return "propose"
    if result.citations:
        return "advise"
    return "read"


def _uuid(value) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _jsonable(value):
    return json.loads(json.dumps(value, default=str))
