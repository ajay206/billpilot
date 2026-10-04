"""POST /agent/chat. The session or API key is the persona. The body cannot upgrade it.

Ops can also list recent turns. Any persona can read a cited policy section.
"""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from billpilot.agent.loop import run_agent
from billpilot.agent.model import build_model
from billpilot.agent.store import decision_tier
from billpilot.agent.tools import BssClient, ThreadedASGITransport
from billpilot.api.access import require_account
from billpilot.api.security import Principal, get_principal, require_roles
from billpilot.db import get_session
from billpilot.models import AgentRun, KnowledgeChunk

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
    traceId: str | None = None


@router.post("/agent/chat", response_model=AgentChatResponse, tags=["Agent"])
def agent_chat(
    body: AgentChatRequest,
    request: Request,
    session: Session = Depends(get_session),
    principal: Principal = Depends(get_principal),
):
    """One grounded turn. Tools call this same API as the same principal.

    The call stays in-process (ASGI) so a single worker does not deadlock by
    opening a TCP connection to itself. The CLI, a different process, uses
    BSS_BASE_URL and an API key instead.
    """
    if body.accountId is not None:
        require_account(session, principal, body.accountId)
    settings = request.app.state.settings
    model = getattr(request.app.state, "chat_model", None) or build_model(settings)
    api_key = request.headers.get("x-api-key") or ""
    extra: dict[str, str] = {}
    if not api_key:
        cookie = request.headers.get("cookie")
        if cookie:
            extra["Cookie"] = cookie
        csrf = request.headers.get("x-csrf-token")
        if csrf:
            extra["X-CSRF-Token"] = csrf
    transport = ThreadedASGITransport(request.app)
    bss = BssClient("http://billpilot.internal", api_key, transport=transport, extra_headers=extra)
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
        toolCalls=[_tool_view(call) for call in result.tool_calls],
        promptTokens=result.prompt_tokens,
        completionTokens=result.completion_tokens,
        estimatedCostUsd=f"{result.estimated_cost_usd:.6f}",
        latencyMs=result.latency_ms,
        model=result.model,
        traceId=result.trace_id,
    )


class AgentRunView(BaseModel):
    id: str
    occurredAt: str
    requestId: str
    persona: str
    actorId: str
    accountId: str | None = None
    userMessage: str
    answer: str
    refusal: bool
    grounded: bool
    decision: str
    promptTokens: int
    completionTokens: int
    estimatedCostUsd: str
    latencyMs: int
    model: str
    traceId: str | None = None
    toolCalls: list[dict]
    citations: list
    proposedActions: list


class KnowledgeSection(BaseModel):
    doc: str
    title: str
    section: str
    source: str
    body: str


def _tool_view(call: dict) -> dict:
    return {
        "name": call["name"],
        "arguments": call.get("arguments") or {},
        "ok": call["ok"],
        "status": call["status"],
        "preview": _preview(call.get("result")),
    }


def _preview(value, limit: int = 500) -> str:
    if value is None:
        return ""
    try:
        text = json.dumps(value, default=str)
    except TypeError:
        text = str(value)
    if len(text) > limit:
        return text[:limit] + "…"
    return text


def _count(session: Session, stmt) -> int:
    return session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0


@router.get("/ops/agentRuns", response_model=list[AgentRunView], tags=["Agent"])
def list_agent_runs(
    response: Response,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_roles("ops")),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    """Recent copilot turns: cost, latency, tokens, decision tier, and the Langfuse trace id."""
    del principal
    stmt = select(AgentRun)
    total = _count(session, stmt)
    rows = session.scalars(stmt.order_by(AgentRun.occurred_at.desc(), AgentRun.id).offset(offset).limit(limit)).all()
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Result-Count"] = str(len(rows))
    return [_run_view(row) for row in rows]


@router.get("/knowledge/section", response_model=KnowledgeSection, tags=["Agent"])
def knowledge_section(
    doc: str = Query(min_length=1, max_length=80),
    section: str = Query(min_length=1, max_length=200),
    session: Session = Depends(get_session),
    principal: Principal = Depends(get_principal),
):
    """The policy section a citation points at. The UI opens this from a chip."""
    del principal
    row = session.scalar(select(KnowledgeChunk).where(KnowledgeChunk.doc_id == doc, KnowledgeChunk.section == section))
    if row is None:
        raise HTTPException(status_code=404, detail="Policy section not found.")
    return KnowledgeSection(doc=row.doc_id, title=row.title, section=row.section, source=row.source_path, body=row.body)


def _run_view(row: AgentRun) -> AgentRunView:
    citations = list(row.citations or [])
    proposed = list(row.proposed_actions or [])
    return AgentRunView(
        id=str(row.id),
        occurredAt=row.occurred_at.isoformat(),
        requestId=row.request_id,
        persona=row.persona,
        actorId=row.actor_id,
        accountId=None if row.account_id is None else str(row.account_id),
        userMessage=row.user_message,
        answer=row.answer,
        refusal=row.refusal,
        grounded=row.grounded,
        decision=decision_tier(refusal=row.refusal, proposed_actions=proposed, citations=citations),
        promptTokens=row.prompt_tokens,
        completionTokens=row.completion_tokens,
        estimatedCostUsd=f"{row.estimated_cost_usd:.6f}",
        latencyMs=row.latency_ms,
        model=row.model,
        traceId=row.trace_id,
        toolCalls=[
            {
                "name": call.get("name"),
                "arguments": call.get("arguments") or {},
                "ok": call.get("ok"),
                "status": call.get("status"),
            }
            for call in (row.tool_calls or [])
            if isinstance(call, dict)
        ],
        citations=citations,
        proposedActions=proposed,
    )
