"""Deterministic ids. The same seed and key always produce the same UUID."""

import uuid

_ROOT = uuid.UUID("6f0c2c3e-1b4a-4f0a-9c1e-0a5b7d8e9f10")


class IdFactory:
    def __init__(self, seed: int) -> None:
        self._namespace = uuid.uuid5(_ROOT, f"billpilot:{seed}")

    def uuid(self, *parts: object) -> uuid.UUID:
        key = "|".join(str(part) for part in parts)
        return uuid.uuid5(self._namespace, key)
