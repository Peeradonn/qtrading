"""Restart policy for a bot running without a service manager.

On EC2 this job belongs to systemd (`Restart=always`). On a workstation there is no supervisor at all: a
detached process that dies takes the trading with it and says nothing — which is exactly what happened to the
paper bot on 2026-09-16. This gives the same guarantee in ~30 lines: restart immediately after a healthy run,
back off exponentially when the bot dies quickly (so a crash loop cannot hammer the exchange or the logs).
"""


def next_delay(ran_for_s: float, previous: float, minimum: float = 5.0, maximum: float = 300.0,
               healthy_s: float = 300.0) -> float:
    """Seconds to wait before the next restart.

    A run of at least ``healthy_s`` is treated as healthy and clears the backoff; anything shorter doubles it,
    starting at ``minimum`` and capped at ``maximum``.
    """
    if ran_for_s >= healthy_s:
        return 0.0
    if previous <= 0:
        return minimum
    return min(previous * 2, maximum)
