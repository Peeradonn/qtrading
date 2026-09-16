"""Journal: one JSON line per event, stamped with time and the running commit."""
import json

import pandas as pd

from qtrading.engine.journal import Journal


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
