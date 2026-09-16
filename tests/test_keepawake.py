"""Keeping the host awake while a bot runs. A suspended laptop silently stops trading."""
from qtrading.engine.keepawake import keep_system_awake


def test_disabled_does_nothing():
    calls = []
    assert keep_system_awake(False, setter=calls.append, on_windows=True) is False
    assert calls == []


def test_on_windows_requests_the_system_stays_available():
    calls = []
    assert keep_system_awake(True, setter=calls.append, on_windows=True) is True
    assert calls == [0x80000001]        # ES_CONTINUOUS | ES_SYSTEM_REQUIRED


def test_elsewhere_it_is_a_no_op_because_the_service_manager_handles_it():
    calls = []
    assert keep_system_awake(True, setter=calls.append, on_windows=False) is False
    assert calls == []


def test_a_failing_platform_call_never_stops_the_bot():
    def boom(flags):
        raise OSError("not supported")
    assert keep_system_awake(True, setter=boom, on_windows=True) is False
