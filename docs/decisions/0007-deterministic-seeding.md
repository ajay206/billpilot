# Deterministic seeding

## Decision

The generator takes a seed and a fixed clock (1 October 2026). Identifiers are UUID version 5 from that seed, so the same inputs produce the same customers, bills, and ground-truth ids. Names come from Faker's `en_IN` locale with the same seed. Cities are a fixed list of Indian city and state pairs, not a random city glued to a random state.

## Alternatives

- `uuid4` and `datetime.now()` inside the generator. Every run is a new dataset, and a failing test cannot be replayed.
- Random city and state from Faker independently. You get Mumbai in Kerala. The fixed pairs stay coherent.

## Why

A portfolio demo and a test suite both need "run it twice, get the same answer". The ground-truth file is then a pure function of the seed, the customer count, the months, and the anomaly counts. Live API writes (a dispute created during a demo) use UUID version 4 and the wall clock, because those are new facts, not part of the seed.
