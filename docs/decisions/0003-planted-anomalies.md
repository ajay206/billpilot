# Planted anomalies with a ground-truth file

## Decision

The generator builds a consistent ledger, then plants a known list of faults. Each fault is a row in `data/ground_truth.json`: type, the ids involved, what a reviewer should find, and the correction. Where the fix is a credit, the file includes the INR amount. Healthy control accounts are labelled too, so "the ladder worked" is as checkable as "the ladder failed".

## Alternatives

- Generate only clean data and let a model invent findings. There is then no way to mark an answer right or wrong.
- Scatter faults without recording them, and detect them with rules later. That makes the demo look magical and makes the tests circular: the detector and the planter can share a bug.

## Why

A later evaluation set needs a key. The tests load the key and recompute each fault from the tables (two rental lines, a rate ten times the catalogue, a bar after a posted payment, an allowance that was not reset). A planter that only writes the label fails those tests. Counts are a dict so a demo can plant one of each type or the default 92.
