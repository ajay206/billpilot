"""Kafka-compatible transport. Tests inject MemoryBroker. Compose uses Redpanda."""

import json
import logging
from collections import defaultdict
from dataclasses import dataclass

logger = logging.getLogger("billpilot.ops.bus")


@dataclass
class BusMessage:
    topic: str
    partition: int
    offset: int
    value: dict


class MemoryBroker:
    """In-process stand-in so the Redpanda path can be tested without a broker."""

    def __init__(self) -> None:
        self.messages: dict[str, list[dict]] = defaultdict(list)
        self.committed: dict[tuple[str, str], int] = defaultdict(int)

    def produce(self, topic: str, key: str, value: dict) -> None:
        del key
        self.messages[topic].append(value)

    def poll(self, topics: tuple[str, ...] | list[str], group: str, limit: int) -> list[BusMessage]:
        found: list[BusMessage] = []
        for topic in topics:
            start = self.committed[(group, topic)]
            batch = self.messages[topic][start : start + max(limit - len(found), 0)]
            for index, value in enumerate(batch):
                found.append(BusMessage(topic=topic, partition=0, offset=start + index, value=value))
            if len(found) >= limit:
                break
        return found

    def commit(self, group: str, topic: str, offset: int) -> None:
        self.committed[(group, topic)] = max(self.committed[(group, topic)], offset + 1)

    def lag(self, topics: tuple[str, ...] | list[str], group: str) -> list[dict]:
        rows = []
        for topic in topics:
            pending = len(self.messages[topic]) - self.committed[(group, topic)]
            rows.append({"topic": topic, "lag": max(pending, 0)})
        return rows


class RedpandaBroker:
    """kafka-python-ng client. Imported only when this backend is actually used."""

    def __init__(self, bootstrap: str) -> None:
        self.bootstrap = bootstrap
        self._producer = None
        self._consumer = None

    def _servers(self) -> list[str]:
        return [item.strip() for item in self.bootstrap.split(",") if item.strip()]

    def _producer_client(self):
        if self._producer is None:
            from kafka import KafkaProducer

            self._producer = KafkaProducer(
                bootstrap_servers=self._servers(),
                value_serializer=lambda value: json.dumps(value).encode(),
                key_serializer=lambda value: value.encode() if isinstance(value, str) else value,
                acks=1,
                retries=2,
                request_timeout_ms=8000,
                api_version_auto_timeout_ms=8000,
            )
        return self._producer

    def produce(self, topic: str, key: str, value: dict) -> None:
        future = self._producer_client().send(topic, key=key, value=value)
        future.get(timeout=10)

    def _consumer_client(self, topics: tuple[str, ...] | list[str], group: str):
        if self._consumer is not None:
            return self._consumer
        from kafka import KafkaConsumer

        self._consumer = KafkaConsumer(
            *topics,
            bootstrap_servers=self._servers(),
            group_id=group,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            value_deserializer=lambda raw: json.loads(raw.decode()),
            # request_timeout_ms has to exceed session_timeout_ms. The library default session is 10s.
            session_timeout_ms=10000,
            request_timeout_ms=30000,
            api_version_auto_timeout_ms=10000,
        )
        return self._consumer

    def poll(self, topics: tuple[str, ...] | list[str], group: str, limit: int) -> list[BusMessage]:
        consumer = self._consumer_client(topics, group)
        batch = consumer.poll(timeout_ms=1000, max_records=limit)
        found: list[BusMessage] = []
        for records in batch.values():
            for record in records:
                found.append(
                    BusMessage(
                        topic=record.topic,
                        partition=record.partition,
                        offset=record.offset,
                        value=record.value,
                    )
                )
        return found

    def commit(self, group: str, topic: str, offset: int) -> None:
        del group
        consumer = self._consumer
        if consumer is None:
            return
        try:
            from kafka import OffsetAndMetadata, TopicPartition

            consumer.commit({TopicPartition(topic, 0): OffsetAndMetadata(offset + 1, "")})
        except TypeError:
            from kafka import TopicPartition

            consumer.commit({TopicPartition(topic, 0): offset + 1})
        except Exception:
            logger.exception("Redpanda commit failed for %s at %s", topic, offset)

    def lag(self, topics: tuple[str, ...] | list[str], group: str) -> list[dict]:
        from kafka import KafkaConsumer, TopicPartition

        consumer = KafkaConsumer(
            bootstrap_servers=self._servers(),
            group_id=group,
            enable_auto_commit=False,
            session_timeout_ms=10000,
            request_timeout_ms=30000,
            api_version_auto_timeout_ms=10000,
        )
        try:
            rows = []
            for topic in topics:
                partitions = consumer.partitions_for_topic(topic) or set()
                parts = [TopicPartition(topic, partition) for partition in partitions]
                if not parts:
                    rows.append({"topic": topic, "lag": 0})
                    continue
                ends = consumer.end_offsets(parts)
                total = 0
                for part in parts:
                    committed = consumer.committed(part)
                    position = 0 if committed is None else committed
                    total += max(int(ends.get(part, 0)) - int(position), 0)
                rows.append({"topic": topic, "lag": total})
            return rows
        finally:
            consumer.close()
