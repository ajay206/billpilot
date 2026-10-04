# Failure store, stuck runs, and idempotent replay

## Decision

The consumer writes incidents for a failed bill run, a failed payment, a failed autopay, a provisioning mismatch, an entitlement mismatch, and a dead-lettered event. A bill run that stays `started` longer than `STUCK_BILL_RUN_SECONDS` (900) is marked `stuck` and gets an incident whose `source_event_id` is the bill-run id. Other incidents use the outbox event id. That column is unique, so applying the same event twice does not open a second incident.

A payload with `eventType=system.error.poison` and no `replayOf` raises until `retry_count` reaches `EVENT_MAX_RETRIES` (3). The retry loop is inside one consume pass. The row then lands on `dead_letter_events` with an incident of type `dead_letter`. Replay copies the payload, sets `replayOf`, and uses idempotency key `replay:{dead letter id}`. A second replay returns that same outbox row and does not write a second audit row. The replayed poison does not raise, because `replayOf` is set. Replay is an ops action.

`billpilot faults simulate` and `POST /ops/faults/simulate` emit the synthetic scenarios, then drain the queue. Both require the ops role on the HTTP path.

Consumer lag is the count of `pending` rows in postgres mode and `queued` rows in redpanda mode, plus the broker lag when a transport is attached.

## Alternatives

- Rely on Kafka redelivery for retries. The postgres mode has no broker redelivery, and a poison event would spin forever.
- A separate incident per retry. The dashboard would fill with copies of one failure.
- Let the CSR replay a dead letter. Replay changes the queue. That stays an ops action.

## Why

A demo has to show failed runs, stuck runs, and a dead-letter queue without a second click creating a second incident or a second audit row. The fault simulator is how that store gets populated on an otherwise healthy seed.
