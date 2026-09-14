class RoostooError(Exception):
    """Base class for all client errors."""


class RoostooNetworkError(RoostooError):
    """Connection failure, timeout, or 5xx — the response was never parsed. Transient; safe to retry reads."""


class RoostooAPIError(RoostooError):
    """The server answered with Success=false (or a non-JSON 4xx). Not transient."""

    def __init__(self, message: str, payload: dict | None = None):
        super().__init__(message)
        self.payload = payload or {}


class OrderUncertain(RoostooError):
    """place_order was sent but no response arrived. The order may or may not exist —
    the caller must reconcile via query_order before doing anything else."""
