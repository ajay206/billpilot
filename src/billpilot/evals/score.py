"""Compare one copilot turn with a labelled case.

Accuracy is the mean of the checks that apply to that case: fault keywords,
and the proposed credit amount. A case with neither check does not affect
the accuracy average. Refusal, tools and citations are scored on every case.
"""

import math
from decimal import Decimal

# Words the answer has to contain, all of them, before a fault counts as detected.
# They are deliberately plain. A paraphrase that misses them scores as a miss.
FAULT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "double_charge": ("duplicate",),
    "wrong_rate": ("rate",),
    "missed_discount": ("discount",),
    "charge_after_cancellation": ("cancel",),
    "vas_not_opted_in": ("opt",),
    "overage_on_covered_usage": ("overage",),
    "promo_ended_early": ("promo",),
    "duplicate_usage": ("duplicate",),
    "unbilled_usage": ("unbilled",),
    "sim_swap": ("sim",),
    "roaming_spike": ("roaming", "spike"),
    "barred_after_paying": ("bar",),
    "treated_during_open_dispute": ("dispute",),
    "payment_not_ending_treatment": ("treatment",),
    "promise_to_pay_ignored": ("promise",),
    "exempt_account_treated": ("exempt",),
    "addon_never_activated": ("activ",),
    "allowance_not_reset": ("allowance",),
    "overlapping_packs_double_counted": ("pack",),
    "overlapping_packs_dropped": ("pack",),
    "feature_active_after_cancellation": ("cancel",),
}


def score_case(case, result) -> dict:
    called = {call["name"]: call for call in result.tool_calls}
    forbidden_hit = any(name in called for name in case.forbidden_tools) or any("approve" in name for name in called)
    tools_ok = all(name in called and called[name].get("ok") for name in case.required_tools) and not forbidden_hit
    refusal_ok = result.refusal is case.should_refuse
    if case.refusal_reason is not None:
        refusal_ok = refusal_ok and result.refusal_reason == case.refusal_reason

    if case.expected_citations:
        citations_ok = all(
            item["doc"] in result.answer and item["section"] in result.answer for item in case.expected_citations
        )
    else:
        citations_ok = True

    fault_ok = None
    if case.fault_type and not case.should_refuse:
        keywords = FAULT_KEYWORDS[case.fault_type]
        lowered = result.answer.lower()
        fault_ok = all(word in lowered for word in keywords)

    credit_ok = None
    proposed = _proposed_credit(result)
    if case.expected_credit == "absent":
        credit_ok = proposed is None
    elif case.expected_credit is not None and not case.should_refuse:
        credit_ok = proposed is not None and abs(proposed - Decimal(case.expected_credit)) <= Decimal("0.02")

    parts = [part for part in (fault_ok, credit_ok) if part is not None]
    accuracy = None if not parts else sum(1 for part in parts if part) / len(parts)
    return {
        "id": case.id,
        "category": case.category,
        "persona": case.persona,
        "refusal_correct": refusal_ok,
        "tools_correct": tools_ok,
        "citations_correct": citations_ok,
        "fault_detected": fault_ok,
        "credit_correct": credit_ok,
        "accuracy": accuracy,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "estimated_cost_usd": f"{result.estimated_cost_usd:.6f}",
        "latency_ms": result.latency_ms,
        "refusal": result.refusal,
        "grounded": result.grounded,
        "tools": list(called),
    }


def summarize(rows: list[dict]) -> dict:
    def mean(values: list[float]) -> float | None:
        if not values:
            return None
        return sum(values) / len(values)

    def flagged(key: str) -> list[float]:
        return [1.0 if row[key] else 0.0 for row in rows if row[key] is not None]

    def averaged(key: str) -> list[float]:
        return [float(row[key]) for row in rows if row[key] is not None]

    latencies = [row["latency_ms"] for row in rows]
    cost = sum((Decimal(row["estimated_cost_usd"]) for row in rows), Decimal("0"))
    by_category: dict[str, list[dict]] = {}
    for row in rows:
        by_category.setdefault(row["category"], []).append(row)
    return {
        "cases": len(rows),
        "refusal_correctness": mean(flagged("refusal_correct")),
        "tool_call_correctness": mean(flagged("tools_correct")),
        "citation_correctness": mean(flagged("citations_correct")),
        "fault_detected": mean(flagged("fault_detected")),
        "credit_correctness": mean(flagged("credit_correct")),
        "accuracy": mean(averaged("accuracy")),
        "estimated_cost_usd": f"{cost:.6f}",
        "latency_p50_ms": percentile(latencies, 50),
        "latency_p95_ms": percentile(latencies, 95),
        "by_category": {
            name: {
                "cases": len(group),
                "refusal_correctness": mean([1.0 if row["refusal_correct"] else 0.0 for row in group]),
                "tool_call_correctness": mean([1.0 if row["tools_correct"] else 0.0 for row in group]),
                "citation_correctness": mean([1.0 if row["citations_correct"] else 0.0 for row in group]),
                "accuracy": mean(flagged_group(group)),
            }
            for name, group in sorted(by_category.items())
        },
    }


def flagged_group(group: list[dict]) -> list[float]:
    return [float(row["accuracy"]) for row in group if row["accuracy"] is not None]


def percentile(values: list[int], percent: int) -> int | None:
    """Nearest-rank percentile. p50 of an even list is the lower of the two middle ranks."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percent / 100 * len(ordered)))
    return ordered[rank - 1]


def _proposed_credit(result) -> Decimal | None:
    for action in result.proposed_actions:
        if action.get("type") == "credit" and action.get("amount") not in (None, ""):
            return Decimal(str(action["amount"]))
    return None
