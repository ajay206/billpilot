"""Precision and recall of detector findings against planted anomalies.

A finding matches when its account and anomaly type are a labelled anomaly.
Controls are not anomalies. A finding on a control, or a type that was not
planted, is a false positive. This is a measurement of the SQL checks, not of
a language model. The detectors and the planted anomalies come from the same
synthetic generator, so the rates show that the SQL matches its spec.
"""

from billpilot.ops.detectors import DETECTORS


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def score_findings(findings: list[dict], ground_truth: dict) -> dict:
    labelled = {(str(row["account_id"]), row["type"]) for row in ground_truth["anomalies"]}
    matched_labels: set[tuple[str, str]] = set()
    matched_findings = 0
    false_findings: list[dict] = []
    for finding in findings:
        key = (str(finding["account_id"]), finding["anomaly_type"])
        if key in labelled:
            matched_findings += 1
            matched_labels.add(key)
        else:
            false_findings.append({"accountId": key[0], "anomalyType": key[1], "detector": finding.get("detector")})
    true_positive = len(matched_labels)
    false_positive = len(findings) - matched_findings
    false_negative = len(labelled) - true_positive
    precision = _rate(matched_findings, len(findings))
    recall = _rate(true_positive, len(labelled))
    missed = sorted(labelled - matched_labels)
    by_detector = []
    for spec in DETECTORS:
        kind = spec["anomaly_type"]
        kind_labels = {key for key in labelled if key[1] == kind}
        kind_findings = [row for row in findings if row["anomaly_type"] == kind]
        kind_matched_labels: set[tuple[str, str]] = set()
        kind_true = 0
        for finding in kind_findings:
            key = (str(finding["account_id"]), finding["anomaly_type"])
            if key in kind_labels:
                kind_true += 1
                kind_matched_labels.add(key)
        by_detector.append(
            {
                "detector": spec["detector"],
                "anomaly_type": kind,
                "labelled": len(kind_labels),
                "findings": len(kind_findings),
                "true_positives": len(kind_matched_labels),
                "false_positives": len(kind_findings) - kind_true,
                "false_negatives": len(kind_labels) - len(kind_matched_labels),
                "precision": _rate(kind_true, len(kind_findings)),
                "recall": _rate(len(kind_matched_labels), len(kind_labels)),
            }
        )
    return {
        "labelled": len(labelled),
        "findings": len(findings),
        "true_positive_anomalies": true_positive,
        "false_positive_findings": false_positive,
        "false_negative_anomalies": false_negative,
        "precision": precision if precision is not None else 0.0,
        "recall": recall if recall is not None else 0.0,
        "missed": [{"accountId": account, "anomalyType": kind} for account, kind in missed],
        "false_positives": false_findings,
        "detectors": by_detector,
    }
