"""Single-instance lock.

Two copies of one bot trading the same account would double every order and race on the state files. Nothing
in an operating system prevents that by itself — a stray manual start alongside a service is enough — so the
bot claims a lock file at startup and refuses to run if a live process already holds it. A lock left behind by
a crashed process is taken over.
"""
import json
import os
from pathlib import Path


class AlreadyRunning(Exception):
    """Another live process holds this bot's lock."""


def _is_alive(pid: int) -> bool:
    """Does a process with this pid exist? Never disturbs it.

    os.kill(pid, 0) is the POSIX idiom, but on Windows os.kill maps any signal other than the console-control
    events to TerminateProcess — so the "check" would kill the very bot it is asking about. Windows therefore
    goes through OpenProcess/GetExitCodeProcess instead.
    """
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True

    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False                      # no such process (or not permitted to query it)
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)                       # POSIX: signal 0 is an existence check, no signal delivered
    except ProcessLookupError:
        return False
    except PermissionError:                   # exists but owned by another user
        return True
    except OSError:
        return False
    # after a hard crash or power loss the lock outlives its process, and on the next boot its pid can belong to
    # something else entirely; where /proc can tell, only a bot counts as the holder
    if not Path("/proc/self").exists():
        return True                           # no /proc (macOS): the existence check is all there is
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return False                          # exited between the two checks
    return b"run_bot" in cmdline


def acquire(path, pid: int | None = None, is_alive=_is_alive) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pid = os.getpid() if pid is None else pid

    if path.exists():
        try:
            holder = int(json.loads(path.read_text(encoding="utf-8"))["pid"])
        except (ValueError, KeyError, TypeError, OSError):
            holder = None                     # unreadable lock: treat as stale
        if holder is not None and holder != pid and is_alive(holder):
            raise AlreadyRunning(f"pid {holder} already holds {path}")

    path.write_text(json.dumps({"pid": pid}), encoding="utf-8")


def release(path) -> None:
    Path(path).unlink(missing_ok=True)
