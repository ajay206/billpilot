"""Generate a world and, when a session is passed, store it."""

import json
from pathlib import Path

from sqlalchemy.orm import Session

from billpilot.billing import AS_OF
from billpilot.synthetic.build import build_world, world_signature
from billpilot.synthetic.config import GeneratorConfig
from billpilot.synthetic.persist import replace_all
from billpilot.synthetic.records import World

__all__ = ["AS_OF", "build_world", "generate", "world_signature"]


def generate(
    config: GeneratorConfig,
    session: Session | None = None,
    output_path: Path | None = None,
) -> tuple[World, dict]:
    world = build_world(config)
    if session is not None:
        replace_all(session, world)
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(world.ground_truth, indent=2, sort_keys=True) + "\n")
    return world, world.ground_truth
