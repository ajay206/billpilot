"""A synthetic legacy extract, including rows a real file would reject.

The dirty rows are deliberate: a bad MSISDN, a repeated customer, a repeated
MSISDN, a plan code with no mapping, a negative balance, an orphan service,
and an orphan balance. Clean rows use the codes in plan_map.json.
"""

import csv
import io
import json
from decimal import Decimal

FIELDS = (
    "record_type",
    "legacy_customer_id",
    "legacy_service_id",
    "given_name",
    "family_name",
    "email",
    "phone",
    "city",
    "state",
    "msisdn",
    "legacy_plan",
    "balance",
    "vas_opt_in",
)

MAX_BODY_CHARS = 1_000_000
MAX_RECORDS = 500


def _row(**values: str) -> dict[str, str]:
    record = {key: "" for key in FIELDS}
    record.update(values)
    return record


def _customer(legacy_id: str, given: str, family: str, email: str, phone: str, city: str, state: str) -> dict:
    return _row(
        record_type="customer",
        legacy_customer_id=legacy_id,
        given_name=given,
        family_name=family,
        email=email,
        phone=phone,
        city=city,
        state=state,
    )


def _service(legacy_id: str, service_id: str, msisdn: str, plan: str, vas: str = "") -> dict:
    return _row(
        record_type="service",
        legacy_customer_id=legacy_id,
        legacy_service_id=service_id,
        msisdn=msisdn,
        legacy_plan=plan,
        vas_opt_in=vas,
    )


def _balance(legacy_id: str, amount: str) -> dict:
    return _row(record_type="balance", legacy_customer_id=legacy_id, balance=amount)


def sample_records() -> list[dict[str, str]]:
    """Four clean subscribers, then the dirty rows named in the phase notes."""
    return [
        _customer("LC-1001", "Asha", "Rao", "asha.rao.mig@example.com", "+919810001001", "Pune", "Maharashtra"),
        _customer("LC-1002", "Kabir", "Shah", "kabir.shah.mig@example.com", "+919810001002", "Mumbai", "Maharashtra"),
        _customer("LC-1003", "Meera", "Nair", "meera.nair.mig@example.com", "+919810001003", "Kochi", "Kerala"),
        _customer("LC-1004", "Dev", "Patel", "dev.patel.mig@example.com", "+919810001004", "Ahmedabad", "Gujarat"),
        _customer("LC-1005", "Ritu", "Sen", "ritu.sen.mig@example.com", "+919810001005", "Kolkata", "West Bengal"),
        _customer("LC-1006", "Omar", "Ali", "omar.ali.mig@example.com", "+919810001006", "Delhi", "Delhi"),
        _customer("LC-1007", "Nila", "Das", "nila.das.mig@example.com", "+919810001007", "Jaipur", "Rajasthan"),
        _customer("LC-1008", "Veer", "Iyer", "veer.iyer.mig@example.com", "+919810001008", "Chennai", "Tamil Nadu"),
        _customer(
            "LC-1001",
            "Duplicate",
            "Rao",
            "duplicate.rao.mig@example.com",
            "+919810001099",
            "Pune",
            "Maharashtra",
        ),
        _service("LC-1001", "LS-1001", "9810001001", "LEG-SMART"),
        _service("LC-1002", "LS-1002", "9810001002", "LEG-PLUS", "CALLER-TUNE"),
        _service("LC-1003", "LS-1003", "9810001003", "LEG-MAX"),
        _service("LC-1004", "LS-1004", "9810001004", "LEG-ULTRA"),
        _service("LC-1005", "LS-1005", "12AB", "LEG-SMART"),
        _service("LC-1006", "LS-1006", "9810001001", "LEG-MAX"),
        _service("LC-1007", "LS-1007", "9810001007", "LEG-GONE"),
        _service("LC-1008", "LS-1008", "9810001008", "LEG-SMART"),
        _service("LC-MISSING", "LS-9999", "9810001009", "LEG-PLUS"),
        _balance("LC-1001", "120.00"),
        _balance("LC-1002", "0.00"),
        _balance("LC-1003", "450.50"),
        _balance("LC-1004", "80.00"),
        _balance("LC-1005", "10.00"),
        _balance("LC-1007", "30.00"),
        _balance("LC-1008", "-25.50"),
        _balance("LC-4040", "40.00"),
    ]


def render_csv(records: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    for record in records:
        writer.writerow({key: record.get(key, "") for key in FIELDS})
    return buffer.getvalue()


def render_json(records: list[dict]) -> str:
    rows = [{key: record.get(key, "") for key in FIELDS} for record in records]
    return json.dumps({"records": rows}, indent=2) + "\n"


def parse_records(body: str, source_format: str) -> list[dict[str, str]]:
    if len(body) > MAX_BODY_CHARS:
        raise ValueError(f"The file is larger than {MAX_BODY_CHARS} characters.")
    if source_format == "csv":
        rows = _parse_csv(body)
    elif source_format == "json":
        rows = _parse_json(body)
    else:
        raise ValueError("Format must be csv or json.")
    if not rows:
        raise ValueError("The file has no records.")
    if len(rows) > MAX_RECORDS:
        raise ValueError(f"A batch can hold {MAX_RECORDS} records. Split the file.")
    return rows


def _blank(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize(raw: dict, ordinal: int) -> dict[str, str]:
    row = {key: _blank(raw.get(key)) for key in FIELDS}
    row["record_type"] = row["record_type"].lower()
    row["ordinal"] = str(ordinal)
    return row


def _parse_csv(body: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(body))
    if reader.fieldnames is None:
        raise ValueError("The CSV needs a header row.")
    missing = [name for name in ("record_type", "legacy_customer_id") if name not in reader.fieldnames]
    if missing:
        raise ValueError("The CSV is missing columns: " + ", ".join(missing) + ".")
    rows = []
    for ordinal, raw in enumerate(reader):
        if raw is None or not any(_blank(value) for value in raw.values()):
            continue
        rows.append(_normalize(raw, ordinal))
    return rows


def _parse_json(body: str) -> list[dict[str, str]]:
    try:
        document = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError("The JSON file could not be read.") from exc
    if isinstance(document, dict):
        document = document.get("records")
    if not isinstance(document, list):
        raise ValueError("JSON must be a list of records, or an object with a records list.")
    rows = []
    for ordinal, raw in enumerate(document):
        if not isinstance(raw, dict):
            raise ValueError(f"Record {ordinal + 1} is not an object.")
        rows.append(_normalize(raw, ordinal))
    return rows


def parse_balance(value: str) -> Decimal | None:
    """Return a decimal, or None when the cell is empty. Raise when it is not a number."""
    text = value.strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except Exception as exc:
        raise ValueError(text) from exc
