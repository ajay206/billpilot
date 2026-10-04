"""Legacy plan codes map to current tariff codes through a JSON file, not a branch.

The rationale string is the suggestion a reviewer signs off. A code that is
not in the file is not guessed.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_PATH = Path(__file__).with_name("plan_map.json")


@dataclass(frozen=True)
class PlanRule:
    legacy_code: str
    legacy_name: str
    target_code: str
    rationale: str


@dataclass(frozen=True)
class PlanMap:
    version: str
    rules: dict[str, PlanRule]

    def suggest(self, legacy_code: str) -> PlanRule | None:
        return self.rules.get(legacy_code.strip().upper())


@lru_cache(maxsize=1)
def load_plan_map() -> PlanMap:
    document = json.loads(_PATH.read_text())
    rules: dict[str, PlanRule] = {}
    for row in document["rules"]:
        rule = PlanRule(
            legacy_code=row["legacyCode"].strip().upper(),
            legacy_name=row["legacyName"].strip(),
            target_code=row["targetCode"].strip(),
            rationale=row["rationale"].strip(),
        )
        rules[rule.legacy_code] = rule
    return PlanMap(version=str(document["version"]), rules=rules)
