"""Scorer math, with hand-written turns. No model call."""

from decimal import Decimal
from types import SimpleNamespace

from billpilot.agent.cost import estimate_cost, estimate_eval_run_usd
from billpilot.agent.guardrails import citations_in, format_citation
from billpilot.config import Settings
from billpilot.evals.cases import Case, build_cases, category_counts
from billpilot.evals.score import percentile, score_case, summarize
from billpilot.synthetic.config import small_config
from billpilot.synthetic.generate import build_world


def _result(**overrides):
    base = dict(
        answer="The bill has a duplicate charge. I proposed a credit of 10.00 INR.",
        refusal=False,
        refusal_reason=None,
        grounded=True,
        tool_calls=[{"name": "list_bills", "ok": True}, {"name": "propose_adjustment", "ok": True}],
        proposed_actions=[{"type": "credit", "amount": "10.00", "status": "pending_approval", "applied": False}],
        prompt_tokens=10,
        completion_tokens=5,
        estimated_cost_usd=Decimal("0"),
        latency_ms=12,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_score_detects_fault_credit_tools_and_a_forbidden_approve():
    case = Case(
        id="sample",
        category="disputes",
        persona="csr",
        message="investigate",
        fault_type="double_charge",
        expected_credit="10.00",
        required_tools=["list_bills", "propose_adjustment"],
        expected_citations=[{"doc": "refunds-and-credits.md", "section": "Duplicate charges"}],
    )
    good = _result(answer="duplicate charge. [refunds-and-credits.md § Duplicate charges]")
    scored = score_case(case, good)
    assert scored["fault_detected"] is True
    assert scored["credit_correct"] is True
    assert scored["tools_correct"] is True
    assert scored["citations_correct"] is True
    assert scored["accuracy"] == 1

    refused = _result(answer="no", tool_calls=[{"name": "approve_adjustment", "ok": False}], proposed_actions=[])
    bad = score_case(case, refused)
    assert bad["tools_correct"] is False
    assert bad["credit_correct"] is False


def test_absent_credit_and_refusal_reason():
    case = Case(
        id="roaming",
        category="disputes",
        persona="csr",
        message="spike",
        expected_credit="absent",
        should_refuse=False,
        required_tools=[],
    )
    assert score_case(case, _result(proposed_actions=[], tool_calls=[]))["credit_correct"] is True
    guard = Case(
        id="guard",
        category="guardrail",
        persona="customer",
        message="weather",
        should_refuse=True,
        refusal_reason="out_of_scope",
    )
    turned = _result(answer="no", refusal=True, refusal_reason="out_of_scope", tool_calls=[], proposed_actions=[])
    assert score_case(guard, turned)["refusal_correct"] is True


def test_summary_percentiles_and_cost_are_not_invented_accuracy():
    rows = [
        score_case(
            Case(id="a", category="policy", persona="csr", message="q", required_tools=["search_knowledge"]),
            _result(
                answer="ok", tool_calls=[{"name": "search_knowledge", "ok": True}], proposed_actions=[], latency_ms=10
            ),
        ),
        score_case(
            Case(id="b", category="policy", persona="csr", message="q", required_tools=["search_knowledge"]),
            _result(answer="ok", tool_calls=[], proposed_actions=[], latency_ms=30),
        ),
    ]
    summary = summarize(rows)
    assert summary["cases"] == 2
    assert summary["tool_call_correctness"] == 0.5
    assert summary["latency_p50_ms"] == percentile([10, 30], 50)
    assert summary["latency_p95_ms"] == 30
    assert "by_category" in summary


def test_citation_markers_round_trip():
    text = format_citation("billing-policy.md", "Late fee")
    assert citations_in(f"See {text} for the rule.") == [{"doc": "billing-policy.md", "section": "Late fee"}]


def test_case_catalog_stays_inside_the_target_band():
    cases = build_cases(build_world(small_config()).ground_truth)
    assert 50 <= len(cases) <= 100
    counts = category_counts(cases)
    assert counts["guardrail"] >= 10
    assert counts["policy"] >= 8
    assert counts["disputes"] >= 8
    assert counts["bill_explanation"] >= 5
    assert sum(counts.values()) == len(cases)


def test_price_table_prices_the_fake_model_at_zero_and_estimates_a_real_run():
    settings = Settings()
    assert estimate_cost("fake", 5000, 500, settings) == 0
    estimate = estimate_eval_run_usd(67, settings, model="gpt-4o-mini")
    # 67 cases * 3 calls * (1200 * 0.15 + 350 * 0.60) / 1_000_000
    assert estimate == Decimal("0.078390")
