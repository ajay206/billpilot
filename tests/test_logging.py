import json
import logging

from billpilot.logging import JsonFormatter, request_id_var


def test_formatter_emits_one_json_object_with_the_request_id():
    token = request_id_var.set("req-123")
    try:
        record = logging.LogRecord(
            name="billpilot.access",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="request",
            args=(),
            exc_info=None,
        )
        record.request_id = "req-123"
        record.method = "GET"
        record.path = "/health"
        record.status = 200
        record.duration_ms = 1.5
        payload = json.loads(JsonFormatter().format(record))
    finally:
        request_id_var.reset(token)
    assert payload["message"] == "request"
    assert payload["request_id"] == "req-123"
    assert payload["method"] == "GET"
    assert payload["status"] == 200
    assert "timestamp" in payload
