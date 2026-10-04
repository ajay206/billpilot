"""Detector precision and recall against the planted anomalies. This is SQL, not a model score."""

from sqlalchemy.orm import Session

from billpilot.ops.detectors import detect
from billpilot.ops.score import score_findings
from billpilot.synthetic.config import small_config
from billpilot.synthetic.generate import build_world


def test_detectors_match_the_planted_anomalies(session: Session):
    ground_truth = build_world(small_config()).ground_truth
    findings = detect(session)
    scored = score_findings(findings, ground_truth)
    zero_charge = [row for row in findings if row["anomaly_type"] == "usage_without_charge"]
    assert zero_charge == []
    assert scored["false_positive_findings"] == 0, scored["false_positives"]
    assert scored["false_negative_anomalies"] == 0, scored["missed"]
    assert scored["precision"] == 1
    assert scored["recall"] == 1
    assert scored["labelled"] == len(ground_truth["anomalies"])
    print(
        f"measured precision={scored['precision']} recall={scored['recall']} "
        f"findings={scored['findings']} labelled={scored['labelled']}"
    )
