"""Journal: one JSON line per event, stamped with time and the running commit."""
import json

import pandas as pd

from qtrading.engine.journal import UNKNOWN_COMMIT, Journal, commit_warning, current_commit


def test_records_are_json_lines_stamped_with_commit_and_time(tmp_path):
    j = Journal(tmp_path / "j.jsonl", commit="abc123")
    j.record("cycle", equity=1_000_000.0, targets={"BTC/USD": 0.5}, at=pd.Timestamp("2026-09-30", tz="UTC"))
    j.record("fill", pair="BTC/USD", side="BUY", quantity=0.5)
    lines = [json.loads(line) for line in (tmp_path / "j.jsonl").read_text().splitlines()]
    assert [line["kind"] for line in lines] == ["cycle", "fill"]
    assert lines[0]["commit"] == "abc123"
    assert lines[0]["equity"] == 1_000_000.0
    assert lines[0]["at"].startswith("2026-09-30")
    assert "time" in lines[0]


def test_last_returns_the_most_recent_record_of_a_kind(tmp_path):
    j = Journal(tmp_path / "j.jsonl", commit="abc123")
    j.record("cycle", equity=1.0)
    j.record("fill", pair="X")
    j.record("cycle", equity=2.0)
    assert j.last("cycle")["equity"] == 2.0
    assert j.last("nothing") is None


# --- the commit stamp: asked once at start-up, retried briefly, and loud when it fails -----------------------------

class FlakyGit:
    """Stands in for subprocess.check_output: fails a set number of times, then answers."""

    def __init__(self, failures: int):
        self.failures, self.calls = failures, 0

    def __call__(self, cmd, **kwargs):
        self.calls += 1
        if self.calls <= self.failures:
            raise OSError("fatal: detected dubious ownership in repository")
        return "abc1234\n"


def test_current_commit_retries_a_transient_failure_and_returns_the_hash():
    git, naps = FlakyGit(failures=1), []
    assert current_commit(run=git, sleep=naps.append) == "abc1234"
    assert git.calls == 2 and naps == [0.5]


def test_current_commit_gives_up_after_its_attempts_and_says_unknown():
    git, naps = FlakyGit(failures=99), []
    assert current_commit(attempts=3, run=git, sleep=naps.append) == UNKNOWN_COMMIT
    assert git.calls == 3 and len(naps) == 2             # no pointless sleep after the last attempt


def test_a_journal_that_cannot_name_its_code_produces_a_warning_and_a_good_one_does_not(tmp_path):
    assert commit_warning("eqvt3", "abc1234") is None
    message = commit_warning("eqvt3", UNKNOWN_COMMIT)
    assert "[eqvt3]" in message and "restart" in message and "git rev-parse" in message


def test_the_journal_exposes_the_commit_it_stamps_so_the_log_and_the_alert_can_agree(tmp_path):
    assert Journal(tmp_path / "j.jsonl", commit="abc1234").commit == "abc1234"
