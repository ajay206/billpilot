"""Deterministic stand-in for the chat model.

It follows a fixed playbook per question shape: call the tools a careful
analyst would call, then answer from the JSON those tools returned. It does
not know the planted answer key. CI uses it so a run needs no key and no spend.
"""

import json
from decimal import Decimal

from billpilot.agent.model import Completion, Message, ToolCall, _estimate
from billpilot.agent.tools import ToolSpec

_PLANS = {
    "explain": ["list_bills", "list_bill_lines", "list_products", "get_offering", "search_knowledge"],
    "dispute": [
        "list_bills",
        "list_bill_lines",
        "list_payments",
        "search_knowledge",
        "create_dispute",
        "propose_adjustment",
        "create_ticket",
    ],
    "policy": ["search_knowledge"],
    "treatment": ["get_treatment", "list_disputes", "list_payments", "search_knowledge"],
    "entitlement": ["list_balances", "list_products", "search_knowledge"],
    "payment": ["list_payments", "list_payment_attempts", "search_knowledge"],
}

_QUERIES = {
    "explain": "how a bill is calculated compare with the previous month and the tariff",
    "dispute": "duplicate charges who proposes and who approves a credit",
    "treatment": "collections ladder treatment status open dispute barred after the bill was paid",
    "entitlement": "allowances reset on the bill cycle packs covered usage",
    "payment": "posted versus received failed autopay late fee",
}


class FakeChatModel:
    name = "fake"

    def __init__(self) -> None:
        self._sequence = 0

    def complete(self, messages: list[Message], tools: list[ToolSpec], max_tokens: int | None = None) -> Completion:
        del max_tokens
        available = {tool.name for tool in tools}
        user = _user_text(messages)
        intent = classify(user)
        payloads = _payloads(messages)
        action = _next(intent, user, available, messages, payloads)
        if action is None:
            content = _answer(intent, user, payloads)
            return Completion(
                content=content,
                model=self.name,
                prompt_tokens=_estimate("".join(message.content for message in messages)),
                completion_tokens=_estimate(content),
            )
        name, arguments = action
        self._sequence += 1
        call = ToolCall(id=f"call-{self._sequence}", name=name, arguments=arguments)
        return Completion(
            content="",
            tool_calls=[call],
            model=self.name,
            prompt_tokens=_estimate("".join(message.content for message in messages)),
            completion_tokens=_estimate(name),
        )


def classify(text: str) -> str:
    lowered = text.lower()
    if "runbook" in lowered or "numbered steps" in lowered or lowered.startswith("policy question"):
        return "policy"
    if any(word in lowered for word in ("treatment status", "barred", "collections", "dunning", "soft bar")):
        return "treatment"
    if any(word in lowered for word in ("entitlement", "allowance", "data left", "value-added", "opted in", "add-on")):
        return "entitlement"
    if any(word in lowered for word in ("autopay", "check payments", "late fee", "payment status")):
        return "payment"
    if any(
        word in lowered for word in ("dispute", "propose a credit", "charged twice", "double charge", "investigate")
    ):
        return "dispute"
    if any(word in lowered for word in ("bill", "invoice", "tariff", "line by line", "why is")):
        return "explain"
    return "policy"


def _next(intent, user, available, messages, payloads):
    called = {name for name, _payload in payloads}
    account = _account_id(messages)
    lines = _as_list(_latest(payloads, "list_bill_lines"))
    bills = _as_list(_latest(payloads, "list_bills"))
    for name in _PLANS[intent]:
        if name not in available or name in called:
            continue
        if name == "propose_adjustment" and _duplicate(lines) is None:
            continue
        if name == "list_bill_lines" and not bills:
            continue
        if name == "get_offering" and not _offering_id(payloads):
            continue
        return name, _arguments(name, intent, user, account, payloads)
    return None


def _arguments(name: str, intent: str, user: str, account: str | None, payloads) -> dict:
    account_args = {"account_id": account} if account else {}
    bills = _as_list(_latest(payloads, "list_bills"))
    bill_id = bills[0]["id"] if bills else None
    if name == "list_bills":
        return {**account_args, "limit": 2}
    if name == "list_bill_lines":
        return {**account_args, "bill_id": bill_id}
    if name == "list_products":
        product_type = "subscription"
        if intent == "entitlement":
            product_type = (
                "vas"
                if any(word in user.lower() for word in ("vas", "opted", "value-added", "add-on"))
                else "entitlement"
            )
        return {**account_args, "product_type": product_type}
    if name == "get_offering":
        return {"offering_id": _offering_id(payloads)}
    if name == "search_knowledge":
        return {"query": user if intent == "policy" else _QUERIES[intent]}
    if name == "create_dispute":
        args = {**account_args, "category": "billing", "description": user[:1800]}
        if bill_id:
            args["bill_id"] = bill_id
        return args
    if name == "create_ticket":
        return {**account_args, "name": "Billing dispute", "description": user[:1800]}
    if name == "propose_adjustment":
        duplicate = _duplicate(_as_list(_latest(payloads, "list_bill_lines")))
        return {
            **account_args,
            "bill_id": (duplicate or {}).get("billId") or bill_id,
            "amount": duplicate["amount"],
            "reason": "Duplicate charge. Credit one of the matching lines. Pending review, not applied.",
        }
    return account_args


def _answer(intent: str, user: str, payloads) -> str:
    if intent == "policy":
        return _policy_answer(payloads)
    if intent == "explain":
        return _explain_answer(payloads)
    if intent == "dispute":
        return _dispute_answer(payloads)
    if intent == "treatment":
        return _treatment_answer(payloads)
    if intent == "entitlement":
        return _entitlement_answer(payloads)
    if intent == "payment":
        return _payment_answer(payloads)
    return _policy_answer(payloads)


def _policy_answer(payloads) -> str:
    results = (_latest(payloads, "search_knowledge") or {}).get("results") or []
    if not results:
        return "I could not find a policy section for that."
    top = results[0]
    sentence = top["excerpt"].strip().split("\n", 1)[0].strip()
    return f"{sentence} {top['citation']}"


def _explain_answer(payloads) -> str:
    bills = _as_list(_latest(payloads, "list_bills"))
    lines = _as_list(_latest(payloads, "list_bill_lines"))
    products = _as_list(_latest(payloads, "list_products"))
    offering = _latest(payloads, "get_offering") or {}
    parts: list[str] = []
    if not bills:
        parts.append("I could not find a bill in scope.")
    else:
        latest = bills[0]
        parts.append(
            f"Bill {latest.get('billNo')} dated {latest.get('billDate')} totals {latest.get('taxIncludedAmount')} INR."
        )
        if len(bills) > 1:
            previous = bills[1]
            parts.append(f"The previous bill {previous.get('billNo')} totals {previous.get('taxIncludedAmount')} INR.")
            if _decimal(latest.get("taxIncludedAmount")) > _decimal(previous.get("taxIncludedAmount")):
                parts.append("This bill is higher.")
            else:
                parts.append("This bill is not higher.")
    if lines:
        parts.append("Lines:")
        for line in lines[:15]:
            parts.append(f"- {line.get('name')}: {line.get('amount')} INR ({line.get('type')}).")
    duplicate = _duplicate(lines)
    if duplicate:
        parts.append(f"The bill has a duplicate charge on {duplicate.get('name')} at {duplicate.get('amount')} INR.")
    if products:
        parts.append(f"The subscription plan is {products[0].get('name')}.")
    fee = _monthly_fee(offering)
    if fee and offering.get("name"):
        parts.append(f"The tariff {offering.get('name')} has a monthly fee of {fee} INR.")
    citation = _citation(payloads)
    if citation:
        parts.append(citation)
    return " ".join(parts)


def _dispute_answer(payloads) -> str:
    parts: list[str] = []
    bills = _as_list(_latest(payloads, "list_bills"))
    lines = _as_list(_latest(payloads, "list_bill_lines"))
    if bills:
        parts.append(f"Latest bill {bills[0].get('billNo')} totals {bills[0].get('taxIncludedAmount')} INR.")
    duplicate = _duplicate(lines)
    if duplicate:
        name = duplicate.get("name")
        amount = duplicate.get("amount")
        parts.append(f"The bill has a duplicate charge: two lines named {name} at {amount} INR.")
    dispute = _as_list(_latest(payloads, "create_dispute"))
    if dispute:
        parts.append(f"I opened a dispute with status {dispute[0].get('status')}.")
    credit = _as_list(_latest(payloads, "propose_adjustment"))
    if credit:
        parts.append(
            f"I proposed a credit of {credit[0].get('amount')} INR. "
            f"Status is {credit[0].get('status')}. It is pending review."
        )
    elif dispute:
        parts.append("Any credit has to be proposed by a CSR and approved by ops. I did not apply one.")
    citation = _citation(payloads)
    if citation:
        parts.append(citation)
    return " ".join(parts) or "I could not assemble the dispute evidence."


def _treatment_answer(payloads) -> str:
    body = _latest(payloads, "get_treatment") or {}
    if isinstance(body, list):
        body = body[0] if body else {}
    treatment = body.get("treatment") if isinstance(body, dict) else None
    parts: list[str] = []
    if treatment:
        parts.append(f"Treatment stage is {treatment.get('stage')} and status is {treatment.get('status')}.")
        if treatment.get("holdReason"):
            parts.append(f"Hold reason is {treatment.get('holdReason')}.")
    else:
        parts.append("There is no active treatment on this account.")
    exemption = body.get("exemption") if isinstance(body, dict) else None
    if exemption:
        parts.append(f"An exemption is on the account: {exemption.get('reason')}.")
    citation = _citation(payloads)
    if citation:
        parts.append(citation)
    return " ".join(parts)


def _entitlement_answer(payloads) -> str:
    balances = _as_list(_latest(payloads, "list_balances"))
    products = _as_list(_latest(payloads, "list_products"))
    parts: list[str] = []
    if balances:
        for row in balances[:6]:
            parts.append(f"{row.get('name')} remaining {row.get('remaining')} {row.get('units')}.")
    else:
        parts.append("I did not find an allowance balance.")
    for product in products[:4]:
        parts.append(f"Product {product.get('name')} is {product.get('status')} ({product.get('productType')}).")
    citation = _citation(payloads)
    if citation:
        parts.append(citation)
    return " ".join(parts)


def _payment_answer(payloads) -> str:
    payments = _as_list(_latest(payloads, "list_payments"))
    attempts = _as_list(_latest(payloads, "list_payment_attempts"))
    parts: list[str] = []
    if payments:
        for row in payments[:5]:
            parts.append(f"Payment {row.get('status')} of {row.get('amount')} INR on {row.get('paymentDate')}.")
    else:
        parts.append("I did not find a payment.")
    for row in attempts[:4]:
        parts.append(f"Attempt {row.get('status')} of {row.get('amount')} INR.")
    citation = _citation(payloads)
    if citation:
        parts.append(citation)
    return " ".join(parts)


def _citation(payloads) -> str | None:
    results = (_latest(payloads, "search_knowledge") or {}).get("results") or []
    if not results:
        return None
    return results[0].get("citation")


def _monthly_fee(offering: dict) -> str | None:
    for price in offering.get("prices") or []:
        if price.get("priceType") == "recurring":
            return price.get("value")
    return None


def _duplicate(lines: list[dict]) -> dict | None:
    seen: dict[tuple, dict] = {}
    for line in lines:
        if not isinstance(line, dict):
            continue
        if line.get("type") in {"tax", "discount"}:
            continue
        key = (line.get("name"), line.get("amount"))
        if not key[0] or not key[1]:
            continue
        if key in seen:
            return line
        seen[key] = line
    return None


def _user_text(messages: list[Message]) -> str:
    for message in reversed(messages):
        if message.role == "user":
            return message.content
    return ""


def _account_id(messages: list[Message]) -> str | None:
    for message in messages:
        if message.role != "system":
            continue
        for line in message.content.splitlines():
            if line.startswith("account_id:"):
                value = line.split(":", 1)[1].strip()
                if value and value != "unknown":
                    return value
    return None


def _payloads(messages: list[Message]) -> list[tuple[str, object]]:
    found: list[tuple[str, object]] = []
    pending: list[ToolCall] = []
    for message in messages:
        if message.role == "assistant" and message.tool_calls:
            pending.extend(message.tool_calls)
        elif message.role == "tool" and pending:
            call = pending.pop(0)
            found.append((call.name, _parse_json(message.content)))
    return found


def _parse_json(text: str):
    starts = [index for index in (text.find("{"), text.find("[")) if index >= 0]
    if not starts:
        return None
    blob = text[min(starts) :]
    if blob.endswith("...[truncated]"):
        return None
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        return None


def _latest(payloads, name: str):
    found = [payload for tool, payload in payloads if tool == name]
    return found[-1] if found else None


def _as_list(payload) -> list:
    if isinstance(payload, list):
        return payload
    return []


def _offering_id(payloads) -> str | None:
    products = _as_list(_latest(payloads, "list_products"))
    for product in products:
        if product.get("offeringId"):
            return product["offeringId"]
    return None


def _decimal(value) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")
