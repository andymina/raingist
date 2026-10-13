import json
import pytest
import raingist.pipeline as pipeline

def test_failing_account_isolated(settings, make_account, alerts, monkeypatch):
    make_account(settings, 1); make_account(settings, 2)
    def fake(s, acct, alerts, dry_run=False, limit=None):
        if acct.id == 1:
            raise RuntimeError("401 revoked")
        return {"done": 1}
    monkeypatch.setattr(pipeline, "run_account_cycle", fake)
    assert pipeline.run_cycle(settings, alerts) == {2: {"done": 1}}
    assert alerts.keys == ["account:1"]

def test_invalid_account_file(settings, make_account, alerts, monkeypatch):
    make_account(settings, 2)
    (settings.accounts_dir / "5.json").write_text("{")
    monkeypatch.setattr(pipeline, "run_account_cycle", lambda s, a, al, dry_run=False, limit=None: {"done": 0})
    assert list(pipeline.run_cycle(settings, alerts)) == [2]
    assert alerts.keys == ["account-file:5"]

def test_disabled_skipped(settings, make_account, alerts, monkeypatch):
    make_account(settings, 3, enabled=False)
    monkeypatch.setattr(pipeline, "run_account_cycle", lambda *a, **k: pytest.fail("disabled account ran"))
    assert pipeline.run_cycle(settings, alerts) == {}

def test_account_cycle_systemic(settings, make_account, alerts, monkeypatch):
    acct = make_account(settings, 1, exclude_collections=[99])
    items = [{"_id": i, "link": f"https://www.tiktok.com/@u/video/{i}", "tags": []} for i in (1, 2, 3)]
    items.append({"_id": 4, "link": "https://example.com/x", "tags": []})
    items.append({"_id": 5, "link": "https://www.tiktok.com/@u/video/5", "tags": [], "collection": {"$id": 99}})

    class FakeRD:
        def __init__(self, token): assert token == "t"
        def list_pending(self, *a): return items
        def tags(self): return []

    seen = []
    def fake_process(s, a, rd, attempts, rid, tags, dry_run=False, catalog=None):
        assert catalog is None   # tag mode never routes
        seen.append(rid); return "retry"
    monkeypatch.setattr(pipeline, "Raindrop", FakeRD)
    monkeypatch.setattr(pipeline, "access_token", lambda s, a: "t")
    monkeypatch.setattr(pipeline, "process_item", fake_process)
    assert pipeline.run_account_cycle(settings, acct, alerts) == {"retry": 3}
    assert seen == [1, 2, 3]
    assert alerts.keys == ["systemic:1"]
    status = json.loads((settings.state_dir / "1" / "status.json").read_text())
    assert status["counts"] == {"retry": 3}


def test_account_cycle_inbox_mode(settings, make_account, alerts, monkeypatch):
    acct = make_account(settings, 1, inbox_collection=5)
    inbox = [{"_id": 1, "link": "https://www.tiktok.com/@u/video/1", "tags": [], "collection": {"$id": 5}},
             {"_id": 2, "link": "https://www.tiktok.com/@u/video/2", "tags": ["raingist-skip"], "collection": {"$id": 5}},
             {"_id": 3, "link": "https://example.com/x", "tags": [], "collection": {"$id": 5}}]

    class FakeRD:
        def __init__(self, token): pass
        def search(self, query, max_pages=10, collection=0):
            assert collection == 5; return inbox
        def tags(self): return []
        def collections(self): return [{"_id": 5, "title": "raingist"}, {"_id": 8, "title": "Recipes"}]
        def recent_titles(self, cid, n): return ["Pasta"]

    seen = []
    def fake_process(s, a, rd, attempts, rid, tags, dry_run=False, catalog=None):
        seen.append((rid, [c["id"] for c in catalog])); return "done"
    monkeypatch.setattr(pipeline, "Raindrop", FakeRD)
    monkeypatch.setattr(pipeline, "access_token", lambda s, a: "t")
    monkeypatch.setattr(pipeline, "process_item", fake_process)
    assert pipeline.run_account_cycle(settings, acct, alerts) == {"done": 1}
    assert seen == [(1, [8])]   # skip-tagged and non-TikTok stay; inbox is not a destination
