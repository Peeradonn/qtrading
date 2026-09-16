"""The 8-of-14 active-trading-days rule.

Backtests showed the core trades on a median of 8-10 days per fortnight and as few as 6 in calm periods, so the
engine watches the pace: once the days left are only just enough to reach the requirement, that cycle forces a
genuine rebalance to target (drift band zero) so a real strategy trade happens.
"""
import json
from datetime import date, timedelta


class ActivityTracker:
    def __init__(self, window_start: date, window_days: int = 14, required_days: int = 8, slack_days: int = 1,
                 active=()):
        self.start = window_start
        self.window_days = window_days
        self.required = required_days
        self.slack = slack_days
        self._active: set[date] = set(active)

    def record(self, day: date) -> None:
        self._active.add(day)

    def active_days(self) -> set[date]:
        return set(self._active)

    def in_window(self, day: date) -> bool:
        return self.start <= day < self.start + timedelta(days=self.window_days)

    def behind_pace(self, today: date) -> bool:
        if not self.in_window(today):
            return False
        active = len({d for d in self._active if self.in_window(d)})
        needed = self.required - active
        if needed <= 0:
            return False
        days_left = self.window_days - (today - self.start).days       # including today
        return days_left <= needed + self.slack

    def to_json(self) -> str:
        return json.dumps({"window_start": self.start.isoformat(), "window_days": self.window_days,
                           "required_days": self.required, "slack_days": self.slack,
                           "active": sorted(d.isoformat() for d in self._active)})

    @classmethod
    def from_json(cls, text: str) -> "ActivityTracker":
        d = json.loads(text)
        return cls(date.fromisoformat(d["window_start"]), d["window_days"], d["required_days"], d["slack_days"],
                   active=[date.fromisoformat(x) for x in d["active"]])
