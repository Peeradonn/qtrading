"""Append-only JSONL journal: every cycle, every order, every error — stamped with time and the running commit.

This is the trade-log evidence for rule compliance, tied to the code that produced it.
"""
import datetime as dt
import json
import subprocess
import time
from pathlib import Path

UNKNOWN_COMMIT = "unknown"


def _default(o):
    if hasattr(o, "isoformat"):
        return o.isoformat()
    if hasattr(o, "item"):                    # numpy scalars
        return o.item()
    return str(o)


def current_commit(repo_root=None, attempts: int = 3, pause_s: float = 0.5, run=subprocess.check_output,
                   sleep=time.sleep) -> str:
    """The commit of the code about to run, asked of git once at start-up and then fixed for the process's life.

    Fixed on purpose: after a config-only `git pull` HEAD moves while the process still runs the old code, so
    asking again later could stamp a commit that is not what is loaded. The price is that a failure in this one
    second marks every record until the next restart, so it is retried briefly here and `commit_warning` makes a
    failure loud instead of silent.
    """
    for attempt in range(attempts):
        try:
            return run(["git", "rev-parse", "--short", "HEAD"], cwd=repo_root, text=True,
                       stderr=subprocess.DEVNULL).strip()
        except Exception:
            if attempt + 1 < attempts:
                sleep(pause_s)
    return UNKNOWN_COMMIT


def commit_warning(bot_name: str, commit: str) -> str | None:
    """What to tell the operator when the journal cannot name its code, or None when it can."""
    if commit != UNKNOWN_COMMIT:
        return None
    return (f"[{bot_name}] WARNING: git could not name the running commit, so every journal record is stamped "
            f"'{UNKNOWN_COMMIT}' until a restart and the trade log cannot be tied to the code that produced it. "
            f"Check that this user can run `git rev-parse` in the install directory (ownership, safe.directory, "
            f"a complete .git), then restart the bot.")


class Journal:
    def __init__(self, path, commit: str):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._commit = commit

    @property
    def commit(self) -> str:
        return self._commit

    def record(self, kind: str, **fields) -> dict:
        rec = {"time": dt.datetime.now(dt.timezone.utc).isoformat(), "commit": self._commit, "kind": kind, **fields}
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=_default) + "\n")
        return rec

    def last(self, kind: str) -> dict | None:
        if not self._path.exists():
            return None
        found = None
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("kind") == kind:
                found = rec
        return found
