"""POST /agent/chat. The caller's API key is the persona. The body cannot upgrade it."""

import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from billpilot.agent.loop import run_agent
from billpilot.agent.model import build_model
from billpilot.agent.tools import BssClient, ThreadedASGITransport
from billpilot.api.security import Principal, get_principal
from billpilot.db import get_session

router = APIRouter()


class AgentChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    accountId: uuid.UUID | None = None


class AgentChatResponse(BaseModel):
    runId: str
    answer: str
    refusal: bool
    refusalReason: str | None = None
    grounded: bool
    citations: list[dict]
    proposedActions: list[dict]
    toolCalls: list[dict]
    promptTokens: int
    completionTokens: int
    estimatedCostUsd: str
    latencyMs: int
    model: str


@router.post("/agent/chat", response_model=AgentChatResponse, tags=["Agent"])
def agent_chat(
    body: AgentChatRequest,
    request: Request,
    session: Session = Depends(get_session),
    principal: Principal = Depends(get_principal),
):
    """One grounded turn. Tools call this same API with the caller's key.

    The call stays in-process (ASGI) so a single worker does not deadlock by
    opening a TCP connection to itself. The CLI, a different process, uses
    BSS_BASE_URL instead.
    """
    settings = request.app.state.settings
    model = getattr(request.app.state, "chat_model", None) or build_model(settings)
    api_key = request.headers.get("x-api-key") or ""
    transport = ThreadedASGITransport(request.app)
    bss = BssClient("http://billpilot.internal", api_key, transport=transport)
    try:
        result = run_agent(
            message=body.message,
            persona=principal.role,
            actor_id=principal.actor_id,
            bss=bss,
            model=model,
            session=session,
            request_id=request.state.request_id,
            settings=settings,
            account_id=None if body.accountId is None else str(body.accountId),
            customer_number=principal.customer_number,
        )
    finally:
        bss.close()
    return AgentChatResponse(
        runId=result.run_id,
        answer=result.answer,
        refusal=result.refusal,
        refusalReason=result.refusal_reason,
        grounded=result.grounded,
        citations=result.citations,
        proposedActions=result.proposed_actions,
        toolCalls=[{"name": call["name"], "ok": call["ok"], "status": call["status"]} for call in result.tool_calls],
        promptTokens=result.prompt_tokens,
        completionTokens=result.completion_tokens,
        estimatedCostUsd=f"{result.estimated_cost_usd:.6f}",
        latencyMs=result.latency_ms,
        model=result.model,
    )
