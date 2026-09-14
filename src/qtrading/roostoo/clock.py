"""Server-synchronised clock. Roostoo rejects timestamps more than 60 s from its own time."""
import time


class Clock:
    def __init__(self, fetch_server_ms, local_ms=None, monotonic=None, refresh_s: float = 600.0):
        self._fetch = fetch_server_ms
        self._local_ms = local_ms or (lambda: int(time.time() * 1000))
        self._mono = monotonic or time.monotonic
        self._refresh_s = refresh_s
        self._offset_ms = 0
        self._synced_at = None

    def sync(self) -> None:
        self._offset_ms = int(self._fetch()) - int(self._local_ms())
        self._synced_at = self._mono()

    def invalidate(self) -> None:
        """Force a resync on the next call (e.g. after the server rejects a timestamp)."""
        self._synced_at = None

    def now_ms(self) -> int:
        if self._synced_at is None or self._mono() - self._synced_at >= self._refresh_s:
            self.sync()
        return int(self._local_ms()) + self._offset_ms
