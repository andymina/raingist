import copy
import pytest
import raingist.pipeline as pipeline
from raingist.accounts import Account
from raingist.extract.common import Extraction, PermanentFailure, TransientFailure
from raingist.llm import Summary
from raingist.state import Attempts
from raingist import writeback

TT = "https://www.tiktok.com/@u/video/1"

class FakeRaindrop:
    def __init__(self, items):
        self.items = {i["_id"]: i for i in items}
        self.updates = []

    def get(self, rid):
        return copy.deepcopy(self.items[rid])

    def update(self, rid, **fields):
        self.updates.append((rid, fields))
        return {}

def acct(**kw):
    return Account(id=1, name="owner", access_token="t", refresh_token="r", expires_at=0, **kw)

def item(rid=10, link=TT, tags=(), note="", cid=5):
    return {"_id": rid, "link": link, "title": "", "note": note, "tags": list(tags), "collection": {"$id": cid}}

@pytest.fixture
def ok(monkeypatch):
    monkeypatch.setattr(pipeline, "extract", lambda s, ctype, it, want_ocr: Extraction(text="t", source="captions"))
    calls = []
    def summarize(s, it, ctype, ex, tags, owner_note=""):
        calls.append(owner_note)
        return Summary(summary="New summary.", key_takeaways=["k"], tags=["Cooking"], title="A title"), "m"
    monkeypatch.setattr(pipeline, "summarize", summarize)
    return calls

def run(settings, tmp_path, rd, rid=10):
    return pipeline.process_item(settings, acct(), rd, Attempts(tmp_path / "a.json", settings.retry_backoff), rid, [])

def test_in_scope():
    assert pipeline.in_scope(acct(), item())
    assert pipeline.in_scope(acct(include_collections=[5]), item())
    assert not pipeline.in_scope(acct(include_collections=[6]), item())
    assert not pipeline.in_scope(acct(exclude_collections=[5]), item())

def test_new_tiktok_done(settings, tmp_path, ok):
    rd = FakeRaindrop([item(note="mine", tags=["Mine"])])
    assert run(settings, tmp_path, rd) == "done"
    (rid, fields), = rd.updates
    assert fields["note"].startswith("mine\n\n**AI summary**\nNew summary.")
    assert fields["tags"] == ["Mine", "cooking", "ai-done"]
    assert fields["title"] == "A title"

def test_non_tiktok_noop(settings, tmp_path, ok):
    rd = FakeRaindrop([item(link="https://example.com/x")])
    assert run(settings, tmp_path, rd) == "noop" and rd.updates == []

def test_redo_replaces_block(settings, tmp_path, ok):
    old = "mine\n\n**AI summary**\nOld summary.\n- x\n_source: captions · m · 2026-01-01_"
    rd = FakeRaindrop([item(note=old, tags=["ai-done", "ai-redo"])])
    assert run(settings, tmp_path, rd) == "done"
    fields = rd.updates[0][1]
    assert fields["note"].count(writeback.MARKER) == 1
    assert "Old summary." not in fields["note"] and "New summary." in fields["note"]
    assert "ai-redo" not in fields["tags"] and "ai-done" in fields["tags"]

def test_transient_retry(settings, tmp_path, monkeypatch):
    def boom(*a, **k): raise TransientFailure("network")
    monkeypatch.setattr(pipeline, "extract", boom)
    rd = FakeRaindrop([item()])
    assert run(settings, tmp_path, rd) == "retry" and rd.updates == []

def test_permanent_failed(settings, tmp_path, monkeypatch):
    def gone(*a, **k): raise PermanentFailure("Video is private")
    monkeypatch.setattr(pipeline, "extract", gone)
    rd = FakeRaindrop([item(note="mine")])
    assert run(settings, tmp_path, rd) == "failed"
    fields = rd.updates[0][1]
    assert fields["note"].startswith("mine\n\n_ai-failed: Video is private")
    assert fields["tags"] == ["ai-failed"]

def test_owner_note_forwarded(settings, tmp_path, ok):
    note = "keep this $start. list every tool $end."
    rd = FakeRaindrop([item(note=note)])
    assert run(settings, tmp_path, rd) == "done"
    assert ok == ["list every tool"]
    assert rd.updates[0][1]["note"].startswith(note + "\n\n**AI summary**")   # note itself untouched

def test_whole_note_forwarded_without_tokens(settings, tmp_path, ok):
    rd = FakeRaindrop([item(note="Claude skills")])
    run(settings, tmp_path, rd)
    assert ok == ["Claude skills"]
