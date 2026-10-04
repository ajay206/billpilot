# Two event backends, one consumer

## Decision

Billing events are written to an `outbox_events` row in the caller's transaction. `EVENT_BACKEND=postgres` is the default: the failure consumer reads `pending` rows. `EVENT_BACKEND=redpanda` is what Docker Compose runs. After commit, a relay produces the same envelope to a single-node Redpanda and marks the row `queued`. The Kafka consumer applies it and marks it `published`. `apply_event` is the same function either way.

Render's free web service has no Kafka. `render.yaml` sets `EVENT_BACKEND=postgres`. Compose sets `redpanda` and `REDPANDA_BOOTSTRAP=redpanda:9092`. The broker is one node with `--smp 1`, `--memory 256M`, `--reserve-memory 0M`, and `--overprovisioned`. `/health` does not wait for the broker.

Topics are `usage.rated`, `bill.run`, `payment.events`, `treatment.actions`, `entitlement.changes`, `system.errors`, and `provisioning.events`. The last one is not on the architecture-deck list. Provisioning mismatches are a different failure from entitlement changes, so they do not share a topic.

## Alternatives

- Kafka only, including on Render. The free instance cannot run a broker, and Neon is not a message bus.
- Skip the outbox when Redpanda is up. A crash between commit and produce would drop the event, and the tests would need a broker.
- A second cloud service for Redpanda. That is a paid dependency the free deploy is not allowed to take.

## Why

The hosted demo has to keep working on Render and Neon inside 512 MB. Local compose still has to show a real Kafka-compatible broker. One apply path means a failure recorded in either mode is the same incident.
