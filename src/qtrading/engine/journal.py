"""Append-only JSONL journal: every cycle, every order, every error — stamped with time and the running commit.

This is the trade-log evidence for rule compliance, tied to the code that produced it.
"""
import datetime as dt
import json
import subprocess
from pathlib import Path


def _default(o):
    if hasattr(o, "isoformat"):
        return o.isoformat()
    if hasattr(o, "item"):                    # numpy scalars
        return o.item()
    return str(o)


def current_commit(repo_root=None) -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=repo_root, text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"


class Journal:
    def __init__(self, path, commit: str):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._commit = commit

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
