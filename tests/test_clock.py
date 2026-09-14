"""Clock: all request timestamps come from local time corrected by the measured server offset."""
from qtrading.roostoo.clock import Clock


class FakeEnv:
    def __init__(self, local_ms=1_000, mono_s=0.0, server_ms=5_000):
        self.local_ms = local_ms
        self.mono_s = mono_s
        self.server_ms = server_ms
        self.server_calls = 0

    def local(self):
        return self.local_ms

    def mono(self):
        return self.mono_s

    def server(self):
        self.server_calls += 1
        return self.server_ms


def make(env, refresh_s=600):
    return Clock(fetch_server_ms=env.server, local_ms=env.local, monotonic=env.mono, refresh_s=refresh_s)


def test_now_ms_is_local_time_shifted_by_measured_server_offset():
    env = FakeEnv(local_ms=1_000, server_ms=5_000)      # server is 4000 ms ahead
    clock = make(env)
    clock.sync()                                         # offset measured while local == 1000
    env.local_ms = 1_500
    assert clock.now_ms() == 5_500


def test_server_time_is_not_refetched_within_refresh_interval():
    env = FakeEnv()
    clock = make(env, refresh_s=600)
    clock.now_ms()
    env.mono_s = 599.0
    clock.now_ms()
    assert env.server_calls == 1


def test_server_time_is_refetched_after_refresh_interval():
    env = FakeEnv(local_ms=1_000, server_ms=5_000)
    clock = make(env, refresh_s=600)
    clock.now_ms()
    env.mono_s = 600.5
    env.server_ms = 9_000                                # offset is now 8000
    assert clock.now_ms() == 9_000


def test_invalidate_forces_resync_on_next_call():
    env = FakeEnv(local_ms=1_000, server_ms=5_000)
    clock = make(env)
    clock.now_ms()
    env.server_ms = 7_000
    clock.invalidate()
    assert clock.now_ms() == 7_000
