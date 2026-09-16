"""Ask the host to stay available while a bot is trading.

A suspended laptop stops trading without failing: no crash, no error, just missing cycles — which on a 14-day
competition with an 8-active-day rule is a real risk. On Windows, SetThreadExecutionState lets a process say
"the system is required" for as long as it runs; the request is dropped automatically when the process exits.
On Linux the bot runs under systemd on a server that does not suspend, so this is a no-op there.

This does not keep the *screen* on, only the machine.
"""
import logging
import os

log = logging.getLogger(__name__)

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def _windows_setter(flags: int) -> None:
    import ctypes
    if not ctypes.windll.kernel32.SetThreadExecutionState(ctypes.c_uint(flags)):
        raise OSError("SetThreadExecutionState refused the request")


def keep_system_awake(enabled: bool, setter=_windows_setter, on_windows: bool | None = None) -> bool:
    """Returns True if the host was asked to stay awake."""
    if not enabled:
        return False
    if on_windows is None:
        on_windows = os.name == "nt"
    if not on_windows:
        return False
    try:
        setter(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
    except Exception as e:                            # a power request must never stop the bot
        log.warning("could not keep the system awake: %s", e)
        return False
    return True
