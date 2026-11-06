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

def test_placements_record_and_reload(tmp_path):
    from raingist.state import Placements
    p = Placements(tmp_path / "placements.json")
    p.record([1, 2], 10); p.record([1], 10); p.record([1], 20)
    again = Placements(tmp_path / "placements.json")
    assert again.filed_into(1) == {10, 20} and again.filed_into(3) == set()
    assert again.placed_by_service(10) == {1, 2}

def test_load_placements_backfills_from_journals(tmp_path):
    import json
    from raingist.state import load_placements
    (tmp_path / "organize").mkdir()
    (tmp_path / "organize" / "20261026T140048Z.json").write_text(json.dumps([
        {"step": "moved", "to": 10, "item_ids": [1, 2]},
        {"step": "created", "id": 30, "title": "New", "item_ids": [3]},
        {"step": "merged", "into": 10, "moved": [4], "removed": {"_id": 40}}]))
    p = load_placements(tmp_path)
    assert {i: p.filed_into(i) for i in (1, 3, 4)} == {1: {10}, 3: {30}, 4: {10}}
    (tmp_path / "organize" / "20261027T140007Z.json").write_text(json.dumps([{"step": "moved", "to": 50, "item_ids": [9]}]))
    assert load_placements(tmp_path).filed_into(9) == set()   # backfill runs once; later moves are recorded live
