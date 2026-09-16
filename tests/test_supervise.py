"""Restart backoff for the supervisor that keeps a bot alive on a machine without a service manager."""
import pytest

from qtrading.engine.supervise import next_delay


def test_a_long_healthy_run_restarts_immediately():
    assert next_delay(ran_for_s=3600, previous=60, minimum=5, maximum=300, healthy_s=300) == 0


def test_repeated_fast_exits_back_off_and_are_capped():
    delays, previous = [], 0
    for _ in range(8):
        previous = next_delay(ran_for_s=1, previous=previous, minimum=5, maximum=300, healthy_s=300)
        delays.append(previous)
    assert delays[:4] == [5, 10, 20, 40]
    assert delays[-1] == 300                       # capped
    assert all(d <= 300 for d in delays)


def test_backoff_resets_after_a_healthy_run():
    assert next_delay(ran_for_s=600, previous=160, minimum=5, maximum=300, healthy_s=300) == 0


@pytest.mark.parametrize("ran_for", [0, 0.5, 299])
def test_any_short_run_counts_as_a_failure(ran_for):
    assert next_delay(ran_for_s=ran_for, previous=0, minimum=5, maximum=300, healthy_s=300) == 5
