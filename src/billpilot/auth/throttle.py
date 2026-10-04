"""Failed sign-in limiter. Separate from the per-actor API limiter."""

import time
from collections import defaultdict, deque
from collections.abc import Callable


class FailureLimiter:
    """Count failures inside a window. A success clears that key."""

    def __init__(
        self,
        limit: int,
        window_seconds: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit = limit
        self.window = window_seconds
        self.clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def blocked(self, key: str) -> bool:
        self._prune(key)
        return len(self._hits[key]) >= self.limit

    def record(self, key: str) -> None:
        self._prune(key)
        self._hits[key].append(self.clock())

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)

    def _prune(self, key: str) -> None:
        hits = self._hits[key]
        now = self.clock()
        while hits and now - hits[0] >= self.window:
            hits.popleft()
