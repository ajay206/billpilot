"""Run the eval harness.

    python -m billpilot.evals --backend fake --output reports/eval
    python -m billpilot.evals --estimate-only

`--backend api` calls the hosted model in LLM_BASE_URL. The cost line printed
first is an estimate from the price table, not a measurement of that run.
"""

import argparse
import json
import sys
from pathlib import Path

from billpilot.agent.cost import estimate_eval_run_usd
from billpilot.config import get_settings
from billpilot.evals.cases import build_cases, category_counts
from billpilot.evals.runner import run_harness
from billpilot.synthetic.config import GeneratorConfig
from billpilot.synthetic.generate import build_world


def load_ground_truth(path: Path):
    if path.is_file():
        return json.loads(path.read_text())
    settings = get_settings()
    config = GeneratorConfig(seed=settings.seed, customer_count=settings.customer_count, months=settings.months)
    return build_world(config).ground_truth


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m billpilot.evals")
    parser.add_argument("--backend", choices=("fake", "api"), default="fake")
    parser.add_argument("--ground-truth", default="data/ground_truth.json")
    parser.add_argument("--output", default="reports/eval")
    parser.add_argument(
        "--estimate-only",
        action="store_true",
        help="Print the labelled cost estimate and the case counts, then exit.",
    )
    args = parser.parse_args(argv)
    settings = get_settings()
    ground_truth = load_ground_truth(Path(args.ground_truth))
    cases = build_cases(ground_truth)
    priced_as = settings.llm_model if args.backend == "api" else settings.llm_model
    estimate = estimate_eval_run_usd(len(cases), settings, model=priced_as)
    print(
        f"Cost estimate for {len(cases)} cases at {priced_as} prices: {estimate} USD. "
        "This is an estimate, not a measured spend. "
        "It assumes 3 calls per case, 1200 prompt tokens and 350 completion tokens per call. "
        "Embeddings stay on the local hash embedder and are not charged."
    )
    print(
        "Cases by category: " + ", ".join(f"{name}={count}" for name, count in sorted(category_counts(cases).items()))
    )
    if args.estimate_only:
        return
    if args.backend == "api" and not settings.llm_api_key:
        raise SystemExit("LLM_BACKEND=api needs LLM_API_KEY. CI should use --backend fake.")
    payload = run_harness(settings, ground_truth, Path(args.output), backend=args.backend)
    summary = payload["summary"]
    print(
        f"Wrote {args.output}/report.md . "
        f"refusal={summary['refusal_correctness']} tools={summary['tool_call_correctness']} "
        f"citations={summary['citation_correctness']} accuracy={summary['accuracy']} "
        f"measured_cost_usd={summary['estimated_cost_usd']}"
    )


if __name__ == "__main__":
    sys.exit(main())
