"""Replay labelled cases through the copilot and write a JSON and markdown report.

The default backend is the fake model. Pass --backend api only when
LLM_API_KEY is set. The report is an output. It is not a committed baseline.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from billpilot.agent.embeddings import build_embedder
from billpilot.agent.knowledge import ensure_index
from billpilot.agent.loop import run_agent
from billpilot.agent.model import build_model
from billpilot.agent.tools import BssClient, ThreadedASGITransport
from billpilot.api.security import principal_for_key
from billpilot.config import Settings
from billpilot.evals.cases import build_cases
from billpilot.evals.score import score_case, summarize
from billpilot.main import create_app


def run_harness(settings: Settings, ground_truth: dict, output_dir: Path, backend: str = "fake") -> dict:
    settings = settings.model_copy(
        update={
            "llm_backend": backend,
            "langfuse_public_key": "",
            "langfuse_secret_key": "",
            "langfuse_host": "",
        }
    )
    app = create_app(settings)
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    with Session(engine) as session:
        ensure_index(session, build_embedder(settings))
    cases = build_cases(ground_truth)
    rows = []
    for case in cases:
        bound = _settings_for_case(settings, engine, case)
        app.state.settings = bound
        key = _key(bound, case.persona)
        principal = principal_for_key(bound, key)
        transport = ThreadedASGITransport(app)
        bss = BssClient("http://billpilot.internal", key, transport=transport)
        try:
            with Session(engine) as session:
                result = run_agent(
                    message=case.message,
                    persona=principal.role,
                    actor_id=principal.actor_id,
                    bss=bss,
                    model=build_model(bound),
                    session=session,
                    request_id=f"eval-{case.id}",
                    settings=bound,
                    account_id=case.account_id,
                    customer_number=principal.customer_number,
                )
        finally:
            bss.close()
        rows.append(score_case(case, result))
    summary = summarize(rows)
    summary["backend"] = backend
    summary["model"] = settings.llm_model if backend == "api" else "fake"
    summary["generated_at"] = datetime.now(UTC).isoformat()
    summary["note"] = (
        "Harness output. Not a committed baseline. Accuracy on the fake backend "
        "only shows that the scripted playbook and the scorers ran."
    )
    payload = {"summary": summary, "cases": rows}
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report.json").write_text(json.dumps(payload, indent=2) + "\n")
    (output_dir / "report.md").write_text(_markdown(summary, rows))
    engine.dispose()
    return payload


def _settings_for_case(settings: Settings, engine, case) -> Settings:
    if case.persona != "csr" or not case.account_id:
        return settings
    with engine.connect() as connection:
        assignee = connection.execute(
            text("SELECT assigned_csr FROM accounts WHERE id = :id"),
            {"id": case.account_id},
        ).scalar_one()
    return settings.model_copy(update={"csr_code": assignee})


def _key(settings: Settings, persona: str) -> str:
    return {
        "customer": settings.api_key_customer,
        "csr": settings.api_key_csr,
        "ops": settings.api_key_ops,
    }[persona]


def _markdown(summary: dict, rows: list[dict]) -> str:
    def cell(value) -> str:
        if value is None:
            return "—"
        if isinstance(value, float):
            return f"{value:.3f}"
        return str(value)

    lines = [
        "# BillPilot eval report",
        "",
        "This file is harness output. Do not commit it as a baseline.",
        "",
        f"- Backend: `{summary['backend']}`",
        f"- Model: `{summary['model']}`",
        f"- Generated: {summary['generated_at']}",
        f"- Cases: {summary['cases']}",
        "",
        summary["note"],
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Refusal correctness | {cell(summary['refusal_correctness'])} |",
        f"| Tool-call correctness | {cell(summary['tool_call_correctness'])} |",
        f"| Citation correctness | {cell(summary['citation_correctness'])} |",
        f"| Fault detected | {cell(summary['fault_detected'])} |",
        f"| Credit correctness | {cell(summary['credit_correctness'])} |",
        f"| Accuracy | {cell(summary['accuracy'])} |",
        f"| Estimated cost USD | {summary['estimated_cost_usd']} |",
        f"| Latency p50 ms | {cell(summary['latency_p50_ms'])} |",
        f"| Latency p95 ms | {cell(summary['latency_p95_ms'])} |",
        "",
        "## By category",
        "",
        "| Category | Cases | Refusal | Tools | Citations | Accuracy |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for name, group in summary["by_category"].items():
        lines.append(
            "| {name} | {cases} | {refusal} | {tools} | {citations} | {accuracy} |".format(
                name=name,
                cases=group["cases"],
                refusal=cell(group["refusal_correctness"]),
                tools=cell(group["tool_call_correctness"]),
                citations=cell(group["citation_correctness"]),
                accuracy=cell(group["accuracy"]),
            )
        )
    missed = [row["id"] for row in rows if not row["tools_correct"] or not row["refusal_correct"]]
    if missed:
        lines.extend(["", "## Cases that missed tools or refusal", ""])
        lines.extend(f"- {name}" for name in missed)
    lines.append("")
    return "\n".join(lines)
