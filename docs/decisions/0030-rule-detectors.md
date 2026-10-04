# Revenue-assurance checks are SQL, scored against the planted labels

## Decision

Fraud and revenue checks are SQL over the ledger. They do not read `ground_truth.json`. Each finding stores the detector id, the generator's anomaly type, a severity, and the evidence row. `usage_without_charge` is a real check (quantity above zero, rate and rated amount both zero). The generator does not plant that shape, so a correct run emits no row for it.

`billpilot assurance score` compares findings to the labelled anomalies: a hit is the same account and the same anomaly type. Controls are not labels. Precision is matched findings over all findings. Recall is matched labels over labelled anomalies. The detectors and the planted anomalies come from the same synthetic generator, so the rates show that the SQL matches its spec. They are not real-world accuracy and they are not a language-model score. CI asserts the 48-customer seed (precision 1.0, recall 1.0). The README quotes a separate run of the same command on the default 500-customer seed, including the false positives that run produced. The SQL was not edited to chase a perfect score on that seed.

Ops can open a ticket (`finding.case`) or propose a credit (`finding.propose_adjustment`) from a finding that has a positive pre-tax amount. The credit uses `credit_for_removing` and stays `pending_approval`. The proposer is the ops actor, so the existing rule blocks that same actor from approving it. A second case open does not write a second audit row.

## Alternatives

- Ask the model to judge fraud. That would spend tokens, would not be stable in CI, and would mix a model score into a ledger check.
- Treat the answer key as the detector. The checks would pass even if the bad rows were missing.
- Let ops apply the credit from the finding. Money changes stay on the approval queue.

## Why

The generator already plants one of each fault. Scoring the SQL against that file shows whether the checks see the fault, and the README can quote the run instead of a target.
