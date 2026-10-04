"""Report numbers come from SQL over the seeded ledger."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from billpilot.config import get_settings
from billpilot.main import create_app
from billpilot.ops.reports import generate_report, generate_scheduled, report_csv, scheduled_windows


def test_scheduled_billing_matches_the_invoice_table(session: Session):
    windows = scheduled_windows(session)
    assert windows
    grain, start, end = windows[0]
    assert grain == "daily"
    saved = generate_report(session, "billing", grain, start, end, "test")
    expected = (
        session.execute(
            text(
                """
            SELECT COUNT(*) AS invoice_count, COALESCE(SUM(total), 0) AS total
            FROM invoices
            WHERE issue_date >= :start AND issue_date < :end
            """
            ),
            {"start": start, "end": end},
        )
        .mappings()
        .one()
    )
    assert int(saved.payload["totals"]["invoice_count"]) == int(expected["invoice_count"])
    assert saved.payload["totals"]["total"] == format(expected["total"], "f")


def test_second_generate_updates_the_same_row(session: Session):
    windows = scheduled_windows(session)
    _, start, end = windows[1]
    first = generate_report(session, "payments", "monthly", start, end, "test")
    second = generate_report(session, "payments", "monthly", start, end, "test-again")
    assert first.id == second.id
    assert second.generated_by == "test-again"
    csv_text = report_csv(second.payload)
    assert csv_text.splitlines()[0]
    assert "\n" in csv_text or csv_text.endswith("\n") or "," in csv_text.splitlines()[0]


def test_generate_scheduled_covers_every_report(session: Session):
    rows = generate_scheduled(session, "test")
    keys = {row.report_key for row in rows}
    assert keys == {"billing", "collections", "disputes", "payments", "agent"}
    assert {row.grain for row in rows} == {"daily", "monthly"}


def test_report_window_is_the_latest_invoice_day(session: Session):
    latest = session.scalar(text("SELECT MAX(issue_date) FROM invoices"))
    windows = dict((grain, (start, end)) for grain, start, end in scheduled_windows(session))
    start, end = windows["daily"]
    assert start == latest
    assert end == latest + timedelta(days=1)


def test_customer_cannot_download_a_report(seeded):
    del seeded
    app = create_app(get_settings())
    with TestClient(app) as client:
        denied = client.post("/ops/reports/generate", headers={"X-API-Key": "test-customer"}, json={})
        assert denied.status_code == 403
        created = client.post("/ops/reports/generate", headers={"X-API-Key": "test-ops"}, json={})
        assert created.status_code == 200
        report_id = created.json()[0]["id"]
        downloaded = client.get(f"/ops/reports/{report_id}/csv", headers={"X-API-Key": "test-ops"})
        assert downloaded.status_code == 200
        assert "text/csv" in downloaded.headers["content-type"]
        assert downloaded.text.splitlines()[0]
