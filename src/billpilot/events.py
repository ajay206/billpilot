"""The event seam. Phase 1 records nothing; a later phase can publish to Kafka here.

Topics match the architecture deck: usage.rated, bill.run, payment.events,
treatment.actions, entitlement.changes, system.errors.
"""

from typing import Protocol


class EventPublisher(Protocol):
    def publish(self, topic: str, payload: dict, *, session=None) -> str | None: ...


class NullPublisher:
    """Drops events. Tests that do not care about the pipeline still use this."""

    def publish(self, topic: str, payload: dict, *, session=None) -> None:
        del topic, payload, session
        return None


class ListPublisher:
    """Test double that keeps events in memory."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def publish(self, topic: str, payload: dict, *, session=None) -> str | None:
        del session
        self.events.append((topic, payload))
        return None
