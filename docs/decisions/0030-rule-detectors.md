# Revenue-assurance checks are SQL, scored against the planted labels

## Decision

Fraud and revenue checks are SQL over the ledger. They do not read `ground_truth.json`. Each finding stores the detector id, the generator's anomaly type, a severity, and the evidence row. `usage_without_charge` is a real check (quantity above zero, rate and rated amount both zero). The generator does not plant that shape, so a correct run emits no row for it.

`billpilot assurance score` compares findings to the labelled anomalies: a hit is the same account and the same anomaly type. Controls are not labels. Precision is matched findings over all findings. Recall is matched labels over labelled anomalies. Those numbers in the README are that measurement on the synthetic seed. They are not a language-model score.

Ops can open a ticket (`finding.case`) or propose a credit (`finding.propose_adjustment`) from a finding that has a positive pre-tax amount. The credit uses `credit_for_removing` and stays `pending_approval`. The proposer is the ops actor, so the existing rule blocks that same actor from approving it. A second case open does not write a second audit row.

## Alternatives

- Ask the model to judge fraud. That would spend tokens, would not be stable in CI, and would mix a model score into a ledger check.
- Treat the answer key as the detector. The checks would pass even if the bad rows were missing.
- Let ops apply the credit from the finding. Money changes stay on the approval queue.

## Why

The generator already plants one of each fault. Scoring the SQL against that file shows whether the checks see the fault, and the README can quote the run instead of a target.
