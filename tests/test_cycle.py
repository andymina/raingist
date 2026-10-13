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
    acct = make_account(settings, 1)
    items = [{"_id": i, "link": f"https://www.tiktok.com/@u/video/{i}", "tags": []} for i in (1, 2, 3)]
    items.append({"_id": 4, "link": "https://example.com/x", "tags": []})

    class FakeRD:
        def __init__(self, token): assert token == "t"
        def list_pending(self, *a): return items
        def tags(self): return []

    seen = []
    def fake_process(s, a, rd, attempts, rid, tags, dry_run=False):
        seen.append(rid); return "retry"
    monkeypatch.setattr(pipeline, "Raindrop", FakeRD)
    monkeypatch.setattr(pipeline, "access_token", lambda s, a: "t")
    monkeypatch.setattr(pipeline, "process_item", fake_process)
    assert pipeline.run_account_cycle(settings, acct, alerts) == {"retry": 3}
    assert seen == [1, 2, 3]
    assert alerts.keys == ["systemic:1"]
    status = json.loads((settings.state_dir / "1" / "status.json").read_text())
    assert status["counts"] == {"retry": 3}
