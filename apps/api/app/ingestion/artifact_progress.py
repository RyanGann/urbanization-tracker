"""Time-throttled lease heartbeats during bounded file and network streaming."""

from __future__ import annotations

import time
from collections.abc import Callable


class LeaseProgress:
    def __init__(
        self,
        heartbeat: Callable[[], None],
        *,
        interval: float = 30,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 0 < interval <= 60:
            raise ValueError("Lease heartbeat interval must be between zero and 60 seconds")
        self.heartbeat = heartbeat
        self.interval = interval
        self.clock = clock
        self.last: float | None = None

    def __call__(self) -> None:
        now = self.clock()
        if self.last is None or now - self.last >= self.interval:
            self.heartbeat()
            self.last = now
