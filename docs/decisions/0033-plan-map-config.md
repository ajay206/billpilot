# Legacy plans map through config, and a person signs off

## Decision

Legacy plan codes map to current tariff codes in `src/billpilot/migration/plan_map.json`. Each rule carries a rationale string. An unknown code is rejected. The dry-run report shows the suggestions. Commit is refused until ops sends `approveMapping: true` after that dry run. The copilot can read the suggestions. It cannot approve them.

## Alternatives

- Ask the chat model to pick a target tariff. A wrong guess would move the wrong monthly fee onto a migrated balance.
- Hard-code the map in Python. A tariff change would need a deploy instead of a config edit.

## Why

The deck asks for an AI suggestion and a human sign-off, and for nothing to be written before both. A stored rationale is the suggestion. A free model guess is the wrong place to choose a price. The sign-off is the human step, and it is an ops action, not a tool the copilot can call.
