import pytest
from raingist.state import Attempts, RunLock, Busy

def test_attempts(tmp_path):
    a = Attempts(tmp_path / "attempts.json", (120, 600))
    assert a.due(1)
    assert a.record_failure(1, "boom") == 1
    assert not a.due(1)
    assert a.record_failure(1, "boom") == 2 == a.max_attempts
    assert Attempts(tmp_path / "attempts.json", (120, 600)).data["1"]["attempts"] == 2   # persisted
    a.clear(1)
    assert a.due(1)

def test_run_lock(tmp_path):
    with RunLock(tmp_path / "run.lock"):
        with pytest.raises(Busy):
            with RunLock(tmp_path / "run.lock"):
                pass
    with RunLock(tmp_path / "run.lock"):   # released
        pass
