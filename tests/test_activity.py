"""Activity floor: force a genuine rebalance when the remaining days are only just enough to reach 8 of 14."""
from datetime import date, timedelta

from qtrading.engine.activity import ActivityTracker


def tracker(active=()):
    t = ActivityTracker(window_start=date(2026, 9, 30), window_days=14, required_days=8, slack_days=1)
    for d in active:
        t.record(d)
    return t


def test_not_behind_while_there_is_still_spare_time():
    t = tracker(active=[date(2026, 9, 30), date(2026, 10, 1)])
    assert t.behind_pace(date(2026, 10, 6)) is False          # need 6 more, 8 days left incl. today


def test_behind_once_remaining_days_only_just_cover_the_need():
    t = tracker(active=[date(2026, 9, 30), date(2026, 10, 1)])
    assert t.behind_pace(date(2026, 10, 7)) is True           # need 6 more, 7 days left incl. today, slack 1


def test_never_behind_once_the_requirement_is_met():
    t = tracker(active=[date(2026, 9, 30) + timedelta(days=i) for i in range(8)])
    assert t.behind_pace(date(2026, 10, 13)) is False


def test_outside_the_competition_window_is_never_behind():
    t = tracker()
    assert t.behind_pace(date(2026, 9, 20)) is False
    assert t.behind_pace(date(2026, 10, 20)) is False


def test_round_trips_through_json():
    t = tracker(active=[date(2026, 9, 30)])
    back = ActivityTracker.from_json(t.to_json())
    assert back.active_days() == {date(2026, 9, 30)}
    assert back.behind_pace(date(2026, 10, 8)) is True
