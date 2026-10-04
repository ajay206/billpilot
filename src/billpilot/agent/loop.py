"""One copilot turn: guardrails, tools, then a grounded answer.

The model chooses tools. This module decides what those tools are allowed to
do, when to stop, and what may be shown to the caller.
"""

import time
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy.orm import Session

from billpilot.agent import knowledge
from billpilot.agent.cost import estimate_cost
from billpilot.agent.embeddings import build_embedder
from billpilot.agent.guardrails import (
    allowed_identifiers,
    proposal_error,
    redact_pii,
    redact_secrets,
    refusal_message,
    screen_input,
    screen_output,
)
from billpilot.agent.model import Message
from billpilot.agent.prompts import system_prompt
from billpilot.agent.store import decision_tier, save_run
from billpilot.agent.tools import ACCOUNTS, BssClient, ToolExecutor, tools_for
from billpilot.agent.tracing import build_turn_trace
from billpilot.config import Settings


@dataclass
class AgentResult:
    run_id: str
    request_id: str
    answer: str
    refusal: bool
    refusal_reason: str | None
    grounded: bool
    citations: list[dict]
    proposed_actions: list[dict]
    tool_calls: list[dict]
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: Decimal
    latency_ms: int
    model: str
    persona: str
    actor_id: str
    user_message: str
    system_prompt: str
    account_id: str | None
    trace_id: str | None = None
    retrieved: list[dict] = field(default_factory=list)


def run_agent(
    *,
    message: str,
    persona: str,
    actor_id: str,
    bss: BssClient,
    model,
    session: Session,
    request_id: str,
    settings: Settings,
    account_id: str | None = None,
    customer_number: str | None = None,
    flow: str = "chat",
) -> AgentResult:
    started = time.perf_counter()
    prompt = system_prompt(persona, account_id, customer_number)
    secrets = [
        settings.api_key_customer,
        settings.api_key_csr,
        settings.api_key_ops,
        settings.llm_api_key,
        settings.session_secret,
    ]
    tracer = build_turn_trace(
        settings,
        persona=persona,
        actor_id=actor_id,
        request_id=request_id,
        message=redact_secrets(message, secrets),
        name=f"billpilot.{flow}",
    )
    if flow == "troubleshoot":
        tracer.span("troubleshoot.start", input={"accountId": account_id, "persona": persona})

    reason = screen_input(message, persona, customer_number)
    tracer.span(
        "guardrails.input",
        as_type="guardrail",
        input={"persona": persona},
        output={"reason": reason or "pass"},
    )
    if reason:
        return _finish(
            message=message,
            persona=persona,
            actor_id=actor_id,
            session=session,
            request_id=request_id,
            settings=settings,
            started=started,
            prompt=prompt,
            account_id=account_id,
            answer=refusal_message(reason),
            refusal=True,
            refusal_reason=reason,
            grounded=True,
            model=getattr(model, "name", settings.llm_model),
            secrets=secrets,
            tracer=tracer,
        )

    pinned = account_id
    allowed: set[str] | None = None
    if persona == "customer":
        status, body = bss.request("GET", ACCOUNTS, params={"limit": 5})
        rows = body if isinstance(body, list) else []
        allowed = {str(row.get("id")) for row in rows if isinstance(row, dict) and row.get("id")}
        if status == 429:
            return _finish(
                message=message,
                persona=persona,
                actor_id=actor_id,
                session=session,
                request_id=request_id,
                settings=settings,
                started=started,
                prompt=prompt,
                account_id=account_id,
                answer="The billing API rate limit was hit before I could read the account.",
                refusal=True,
                refusal_reason="rate_limited",
                grounded=True,
                model=getattr(model, "name", settings.llm_model),
                secrets=secrets,
                tracer=tracer,
            )
        if account_id and account_id not in allowed:
            return _finish(
                message=message,
                persona=persona,
                actor_id=actor_id,
                session=session,
                request_id=request_id,
                settings=settings,
                started=started,
                prompt=prompt,
                account_id=account_id,
                answer=refusal_message("cross_account"),
                refusal=True,
                refusal_reason="cross_account",
                grounded=True,
                model=getattr(model, "name", settings.llm_model),
                secrets=secrets,
                tracer=tracer,
            )
        if not allowed:
            return _finish(
                message=message,
                persona=persona,
                actor_id=actor_id,
                session=session,
                request_id=request_id,
                settings=settings,
                started=started,
                prompt=prompt,
                account_id=None,
                answer=refusal_message("no_account"),
                refusal=True,
                refusal_reason="no_account",
                grounded=True,
                model=getattr(model, "name", settings.llm_model),
                secrets=secrets,
                tracer=tracer,
            )
        pinned = account_id or next(iter(allowed))
        prompt = system_prompt(persona, pinned, customer_number)

    embedder = build_embedder(settings)
    executor = ToolExecutor(
        persona=persona,
        bss=bss,
        search=lambda query: knowledge.search(session, embedder, query),
        pinned_account_id=pinned if persona == "customer" else None,
        allowed_account_ids=allowed,
        result_chars=settings.agent_tool_result_chars,
        secrets=secrets,
    )
    specs = tools_for(persona)
    messages = [Message(role="system", content=prompt), Message(role="user", content=message)]
    traces = []
    proposed: list[dict] = []
    retrieved: list[dict] = []
    evidence: list[str] = []
    prompt_tokens = 0
    completion_tokens = 0
    model_name = getattr(model, "name", settings.llm_model)
    answer = ""
    refusal = False
    refusal_reason = None

    while True:
        if prompt_tokens + completion_tokens >= settings.agent_max_tokens:
            answer = refusal_message("token_budget")
            refusal = True
            refusal_reason = "token_budget"
            break
        completion = model.complete(messages, specs, max_tokens=800)
        model_name = completion.model or model_name
        prompt_tokens += completion.prompt_tokens
        completion_tokens += completion.completion_tokens
        call_cost = estimate_cost(model_name, completion.prompt_tokens, completion.completion_tokens, settings)
        tracer.generation(
            "model.call",
            model=model_name,
            input={"messages": len(messages), "tools": len(specs)},
            output={
                "tool_calls": [call.name for call in completion.tool_calls],
                "text": (completion.content or "")[:400],
            },
            prompt_tokens=completion.prompt_tokens,
            completion_tokens=completion.completion_tokens,
            cost=call_cost,
        )
        if not completion.tool_calls:
            answer = completion.content or "I don't have a grounded answer for that."
            break
        if len(traces) >= settings.agent_max_tool_calls:
            answer = refusal_message("tool_budget")
            refusal = True
            refusal_reason = "tool_budget"
            break
        messages.append(Message(role="assistant", content=completion.content, tool_calls=completion.tool_calls))
        for call in completion.tool_calls:
            if len(traces) >= settings.agent_max_tool_calls:
                answer = refusal_message("tool_budget")
                refusal = True
                refusal_reason = "tool_budget"
                break
            trace = executor.execute(call.name, call.arguments)
            traces.append(trace)
            evidence.append(trace.model_text)
            retrieved.extend(trace.citations)
            tracer.span(
                f"tool.{trace.name}",
                as_type="tool",
                input=trace.arguments,
                output={"ok": trace.ok, "status": trace.status},
            )
            if trace.name == "search_knowledge":
                tracer.span(
                    "retrieval",
                    as_type="retriever",
                    input=trace.arguments,
                    output={
                        "doc_ids": sorted({item.get("doc") for item in trace.citations if item.get("doc")}),
                        "sections": [
                            {"doc": item.get("doc"), "section": item.get("section")} for item in trace.citations
                        ],
                    },
                )
            if trace.proposed:
                proposed.append(trace.proposed)
            messages.append(Message(role="tool", content=trace.model_text, tool_call_id=call.id))
        if refusal:
            break

    grounded = True
    citations: list[dict] = []
    if not refusal:
        answer, grounded, citations = screen_output(answer, evidence, retrieved, message)
        tracer.span(
            "output.checks",
            as_type="guardrail",
            output={
                "grounded": grounded,
                "citations": citations,
                "proposal_error": proposal_error(proposed),
            },
        )
        if proposal_error(proposed):
            answer = (
                "A credit proposal has to stay pending, with an amount taken from the bill, "
                "until a different person approves it. I will not treat this one as applied."
            )
            grounded = False
            refusal = True
            refusal_reason = "needs_a_person"
    answer = redact_secrets(answer, secrets)
    customers, emails, phones = allowed_identifiers(evidence, persona, customer_number)
    answer, _redacted = redact_pii(answer, customers, emails, phones)

    return _finish(
        message=message,
        persona=persona,
        actor_id=actor_id,
        session=session,
        request_id=request_id,
        settings=settings,
        started=started,
        prompt=prompt,
        account_id=pinned,
        answer=answer,
        refusal=refusal,
        refusal_reason=refusal_reason,
        grounded=grounded,
        model=model_name,
        secrets=secrets,
        citations=citations,
        proposed=proposed,
        traces=traces,
        retrieved=retrieved,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        tracer=tracer,
    )


def _finish(
    *,
    message,
    persona,
    actor_id,
    session,
    request_id,
    settings,
    started,
    prompt,
    account_id,
    answer,
    refusal,
    refusal_reason,
    grounded,
    model,
    secrets,
    citations=None,
    proposed=None,
    traces=None,
    retrieved=None,
    prompt_tokens=0,
    completion_tokens=0,
    tracer=None,
) -> AgentResult:
    del secrets
    latency_ms = int((time.perf_counter() - started) * 1000)
    cost = estimate_cost(model, prompt_tokens, completion_tokens, settings)
    tool_calls = [
        {
            "name": trace.name,
            "arguments": trace.arguments,
            "ok": trace.ok,
            "status": trace.status,
            "result": trace.result,
        }
        for trace in (traces or [])
    ]
    result = AgentResult(
        run_id="",
        request_id=request_id,
        answer=answer,
        refusal=refusal,
        refusal_reason=refusal_reason,
        grounded=grounded,
        citations=list(citations or []),
        proposed_actions=list(proposed or []),
        tool_calls=tool_calls,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        estimated_cost_usd=cost,
        latency_ms=latency_ms,
        model=model,
        persona=persona,
        actor_id=actor_id,
        user_message=message,
        system_prompt=prompt,
        account_id=account_id,
        trace_id=None if tracer is None else tracer.trace_id,
        retrieved=list(retrieved or []),
    )
    tier = decision_tier(
        refusal=result.refusal,
        proposed_actions=result.proposed_actions,
        citations=result.citations,
    )
    if tracer is not None:
        tracer.span("decision", output={"decision": tier, "refusal_reason": refusal_reason})
    try:
        result.run_id = str(save_run(session, result))
    finally:
        if tracer is not None:
            tracer.finish(output=answer, decision=tier, metadata={"run_id": result.run_id})
    return result
