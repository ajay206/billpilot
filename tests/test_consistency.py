"""Apart from the planted faults, the ledger still adds up."""

from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from billpilot.billing import ZERO, gst, money
from billpilot.synthetic.catalog import CITIES


def _rows(session: Session, sql: str):
    return session.execute(text(sql)).mappings().all()


def test_invoice_headers_match_their_lines_and_payments(session: Session):
    invoices = _rows(session, "SELECT * FROM invoices")
    lines = _rows(session, "SELECT invoice_id, charge_type, amount FROM invoice_lines")
    payments = _rows(session, "SELECT invoice_id, amount, status FROM payments")
    by_invoice: dict[str, list] = {}
    for line in lines:
        by_invoice.setdefault(str(line["invoice_id"]), []).append(line)
    posted: dict[str, Decimal] = {}
    for payment in payments:
        if payment["status"] != "posted":
            continue
        key = str(payment["invoice_id"])
        posted[key] = posted.get(key, ZERO) + Decimal(payment["amount"])

    assert invoices
    for invoice in invoices:
        key = str(invoice["id"])
        assert invoice["currency"] == "INR"
        subtotal = Decimal(invoice["subtotal"])
        tax = Decimal(invoice["tax"])
        total = Decimal(invoice["total"])
        due = Decimal(invoice["amount_due"])
        assert money(subtotal + tax) == total
        assert ZERO <= due <= total
        line_sum = sum((Decimal(line["amount"]) for line in by_invoice.get(key, [])), ZERO)
        assert money(line_sum) == total
        assert due == money(max(ZERO, total - posted.get(key, ZERO)))
        kinds = {line["charge_type"] for line in by_invoice.get(key, [])}
        if "adjustment" not in kinds:
            assert tax == gst(subtotal)


def test_customers_use_indian_cities_and_phone_numbers(session: Session):
    rows = _rows(session, "SELECT city, state, phone, email FROM customers")
    allowed = set(CITIES)
    assert len(rows) == 48
    for row in rows:
        assert (row["city"], row["state"]) in allowed
        assert row["phone"].startswith("+91")
        assert row["email"].endswith("@example.com")


def test_usage_line_amount_is_quantity_times_price(session: Session):
    rows = _rows(
        session,
        """
        SELECT quantity, unit_price, amount
        FROM invoice_lines
        WHERE charge_type IN ('usage', 'roaming', 'recurring', 'vas', 'addon')
        """,
    )
    for row in rows:
        expected = money(Decimal(row["quantity"]) * Decimal(row["unit_price"]))
        assert Decimal(row["amount"]) == expected
