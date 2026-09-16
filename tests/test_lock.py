"""Single-instance lock: two copies of one bot must never trade the same account."""
import json
import os

import pytest

from qtrading.engine.lock import AlreadyRunning, acquire, release


def test_acquiring_a_free_lock_records_the_pid(tmp_path):
    path = tmp_path / "core.lock"
    acquire(path, pid=111, is_alive=lambda pid: False)
    assert json.loads(path.read_text())["pid"] == 111


def test_a_lock_held_by_a_live_process_is_refused(tmp_path):
    path = tmp_path / "core.lock"
    acquire(path, pid=111, is_alive=lambda pid: False)
    with pytest.raises(AlreadyRunning, match="111"):
        acquire(path, pid=222, is_alive=lambda pid: pid == 111)
    assert json.loads(path.read_text())["pid"] == 111          # the holder keeps it


def test_a_stale_lock_from_a_dead_process_is_taken_over(tmp_path):
    path = tmp_path / "core.lock"
    acquire(path, pid=111, is_alive=lambda pid: False)
    acquire(path, pid=222, is_alive=lambda pid: False)
    assert json.loads(path.read_text())["pid"] == 222


def test_a_corrupt_lock_file_is_taken_over(tmp_path):
    path = tmp_path / "core.lock"
    path.write_text("not json")
    acquire(path, pid=222, is_alive=lambda pid: True)
    assert json.loads(path.read_text())["pid"] == 222


def test_release_frees_the_lock_for_the_next_process(tmp_path):
    path = tmp_path / "core.lock"
    acquire(path, pid=111, is_alive=lambda pid: False)
    release(path)
    assert not path.exists()
    acquire(path, pid=222, is_alive=lambda pid: True)          # no holder to conflict with


# The default liveness check must be characterised against the real OS: on Windows os.kill(pid, 0) TERMINATES
# the target process rather than testing it, which once killed a running bot.

def test_default_liveness_check_sees_this_process_as_alive():
    from qtrading.engine.lock import _is_alive
    assert _is_alive(os.getpid()) is True


def test_default_liveness_check_does_not_kill_the_process_it_checks():
    import subprocess
    import sys
    import time
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        from qtrading.engine.lock import _is_alive
        assert _is_alive(child.pid) is True
        time.sleep(0.5)
        assert child.poll() is None, "the liveness check terminated the process it was asked about"
    finally:
        child.kill()
        child.wait(timeout=10)


def test_default_liveness_check_reports_an_exited_process_as_dead():
    import subprocess
    import sys
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait(timeout=10)
    from qtrading.engine.lock import _is_alive
    assert _is_alive(child.pid) is False
