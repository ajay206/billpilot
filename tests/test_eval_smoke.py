"""The harness runs on the fake model. This is a smoke test, not a baseline."""

from billpilot.config import get_settings
from billpilot.evals.runner import run_harness
from billpilot.synthetic.config import small_config
from billpilot.synthetic.generate import build_world


def test_fake_harness_writes_a_report_and_refuses_the_guardrail_cases(seeded, tmp_path):
    del seeded
    ground_truth = build_world(small_config()).ground_truth
    payload = run_harness(get_settings(), ground_truth, tmp_path, backend="fake")
    summary = payload["summary"]
    assert 50 <= summary["cases"] <= 100
    assert summary["backend"] == "fake"
    assert summary["refusal_correctness"] == 1
    assert summary["estimated_cost_usd"] == "0.000000"
    assert (tmp_path / "report.md").is_file()
    assert (tmp_path / "report.json").is_file()
    assert "Not a committed baseline" in (tmp_path / "report.md").read_text()
    trouble = [row for row in payload["cases"] if row["id"].startswith("troubleshoot-")]
    assert len(trouble) == 5
    for row in trouble:
        assert row["refusal_correct"] is True
        assert row["tools_correct"] is True
        assert row["citations_correct"] is True
    for row in payload["cases"]:
        assert "approve_adjustment" not in row["tools"]
        if row["category"] == "guardrail":
            assert row["refusal_correct"] is True
        if row["category"] == "migration":
            assert row["tools_correct"] is True
            assert row["refusal"] is False
