"""In-process consumer and report job. Both are off when the settings say so."""

import logging
import threading

from sqlalchemy import select

from billpilot.config import Settings
from billpilot.db import get_session_factory
from billpilot.models import OutboxEvent
from billpilot.ops.pipeline import OutboxPublisher, consume_broker, consume_outbox, sweep_stuck
from billpilot.ops.reports import generate_scheduled

logger = logging.getLogger("billpilot.ops.worker")


def start_workers(settings: Settings, transport=None) -> threading.Event:
    stop = threading.Event()
    if settings.event_consumer_enabled:
        threading.Thread(
            target=_consumer_loop,
            args=(stop, settings, transport),
            name="billpilot-consumer",
            daemon=True,
        ).start()
    if settings.report_schedule_seconds > 0:
        threading.Thread(
            target=_report_loop,
            args=(stop, settings),
            name="billpilot-reports",
            daemon=True,
        ).start()
    return stop


def _consumer_loop(stop: threading.Event, settings: Settings, transport) -> None:
    while not stop.is_set():
        try:
            with get_session_factory()() as session:
                if settings.event_backend == "redpanda" and transport is not None:
                    ids = session.scalars(select(OutboxEvent.id).where(OutboxEvent.status == "pending")).all()
                    if ids:
                        OutboxPublisher(settings, transport).relay(list(ids))
                    consume_broker(session, settings, transport)
                else:
                    consume_outbox(session, settings)
                sweep_stuck(session, settings)
                session.commit()
        except Exception:
            logger.exception("Failure consumer pass failed.")
        stop.wait(settings.event_poll_seconds)


def _report_loop(stop: threading.Event, settings: Settings) -> None:
    # Let the process open its port before the first aggregate.
    if stop.wait(15):
        return
    while not stop.is_set():
        try:
            with get_session_factory()() as session:
                generate_scheduled(session, "scheduler")
        except Exception:
            logger.exception("Report job failed.")
        if stop.wait(settings.report_schedule_seconds):
            return
