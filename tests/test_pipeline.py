import copy
import pytest
import raingist.pipeline as pipeline
from raingist.accounts import Account
from raingist.extract.common import Extraction, PermanentFailure, TransientFailure
from raingist.llm import Summary
from raingist.state import Attempts
from raingist import writeback

TT = "https://www.tiktok.com/@u/video/1"
INBOX = 5
CATALOG = [{"id": 77, "title": "Recipes", "description": "", "samples": ["Pasta"]}]
ROUTE_TO = [0]   # collection_id the fake summarizer returns

class FakeRaindrop:
    def __init__(self, items):
        self.items = {i["_id"]: i for i in items}
        self.updates = []

    def get(self, rid):
        return copy.deepcopy(self.items[rid])

    def update(self, rid, **fields):
        self.updates.append((rid, fields))
        return {}

def acct():
    return Account(id=1, name="owner", access_token="t", refresh_token="r", expires_at=0)

def item(rid=10, link=TT, tags=(), note="", cid=INBOX):
    return {"_id": rid, "link": link, "title": "", "note": note, "tags": list(tags), "collection": {"$id": cid}}

@pytest.fixture
def ok(monkeypatch):
    ROUTE_TO[0] = 0
    monkeypatch.setattr(pipeline, "extract", lambda s, ctype, it, want_ocr: Extraction(text="t", source="captions"))
    calls = []
    def summarize(s, it, ctype, ex, tags, owner_note="", catalog=None):
        calls.append(owner_note)
        return Summary(summary="New summary.", key_takeaways=["k"], tags=["Cooking"], title="A title",
                       collection_id=ROUTE_TO[0]), "m"
    monkeypatch.setattr(pipeline, "summarize", summarize)
    return calls

def run(settings, tmp_path, rd, rid=10):
    return pipeline.process_item(settings, acct(), rd, Attempts(tmp_path / "a.json", settings.retry_backoff),
                                 rid, [], INBOX, CATALOG)

def test_done_enriches_strips_tags_and_routes_in_one_put(settings, tmp_path, ok):
    rd = FakeRaindrop([item(note="mine", tags=["Mine", "raingist-ocr"])])
    assert run(settings, tmp_path, rd) == "done"
    (rid, fields), = rd.updates
    assert fields["note"].startswith("mine\n\n**AI summary**\nNew summary.")
    assert fields["tags"] == ["Mine", "cooking"]
    assert fields["title"] == "A title"
    assert fields["collection"] == {"$id": pipeline.UNSORTED}

@pytest.mark.parametrize("chosen,dest", [(77, 77), (0, pipeline.UNSORTED), (12345, pipeline.UNSORTED)])
def test_route(settings, tmp_path, ok, chosen, dest):
    ROUTE_TO[0] = chosen
    rd = FakeRaindrop([item()])
    run(settings, tmp_path, rd)
    assert rd.updates[0][1]["collection"] == {"$id": dest}

@pytest.mark.parametrize("bookmark", [item(link="https://example.com/x"), item(cid=99), item(tags=["raingist-skip"]),
                                      item(tags=["raingist-failed"])])
def test_noop(settings, tmp_path, ok, bookmark):
    rd = FakeRaindrop([bookmark])
    assert run(settings, tmp_path, rd) == "noop" and rd.updates == []

def test_redo_replaces_block(settings, tmp_path, ok):
    old = "mine\n\n**AI summary**\nOld summary.\n- x\n_source: captions · m · 2026-01-01_"
    rd = FakeRaindrop([item(note=old, tags=["raingist-failed", "raingist-redo"])])
    assert run(settings, tmp_path, rd) == "done"
    fields = rd.updates[0][1]
    assert fields["note"].count(writeback.MARKER) == 1
    assert "Old summary." not in fields["note"] and "New summary." in fields["note"]
    assert fields["tags"] == ["cooking"]

def test_moved_back_without_redo_keeps_summary(settings, tmp_path, ok):
    old = "**AI summary**\nOld summary.\n- x"
    rd = FakeRaindrop([item(note=old)])
    assert run(settings, tmp_path, rd) == "done"
    assert rd.updates[0][1]["note"] == old

def test_transient_retry(settings, tmp_path, monkeypatch):
    def boom(*a, **k): raise TransientFailure("network")
    monkeypatch.setattr(pipeline, "extract", boom)
    rd = FakeRaindrop([item()])
    assert run(settings, tmp_path, rd) == "retry" and rd.updates == []

def test_permanent_failure_stays_in_inbox(settings, tmp_path, monkeypatch):
    def gone(*a, **k): raise PermanentFailure("Video is private")
    monkeypatch.setattr(pipeline, "extract", gone)
    rd = FakeRaindrop([item(note="mine", tags=["Mine", "raingist-redo", "raingist-ocr"])])
    assert run(settings, tmp_path, rd) == "failed"
    fields = rd.updates[0][1]
    assert "collection" not in fields
    assert fields["note"].startswith("mine\n\n_raingist-failed: Video is private")
    assert fields["tags"] == ["Mine", "raingist-ocr", "raingist-failed"]

def test_marked_span_sent_then_cut(settings, tmp_path, ok):
    rd = FakeRaindrop([item(note="keep this $start. list every tool $end.")])
    assert run(settings, tmp_path, rd) == "done"
    assert ok == ["list every tool"]
    assert rd.updates[0][1]["note"].startswith("keep this\n\n**AI summary**")

def test_only_marked_span_leaves_just_the_block(settings, tmp_path, ok):
    rd = FakeRaindrop([item(note="$start. focus on the recipe $end.")])
    run(settings, tmp_path, rd)
    assert rd.updates[0][1]["note"].startswith("**AI summary**")

def test_unmarked_note_kept_not_sent(settings, tmp_path, ok):
    rd = FakeRaindrop([item(note="Claude skills")])
    run(settings, tmp_path, rd)
    assert ok == [""]
    assert rd.updates[0][1]["note"].startswith("Claude skills\n\n**AI summary**")

def test_failure_keeps_marked_span(settings, tmp_path, monkeypatch):
    def gone(*a, **k): raise PermanentFailure("Video is private")
    monkeypatch.setattr(pipeline, "extract", gone)
    note = "mine $start. focus $end."
    rd = FakeRaindrop([item(note=note)])
    assert run(settings, tmp_path, rd) == "failed"
    assert rd.updates[0][1]["note"].startswith(note + "\n\n_raingist-failed:")

def test_blocked(settings):
    assert not pipeline.blocked(settings, item())
    assert pipeline.blocked(settings, item(tags=["raingist-skip"]))
    assert pipeline.blocked(settings, item(tags=["Raingist-Failed"]))
    assert not pipeline.blocked(settings, item(tags=["raingist-failed", "raingist-redo"]))

@pytest.mark.parametrize("titles,expected", [(["Food", "raingist"], 1), (["Food", " Raingist "], 1)])
def test_find_inbox(titles, expected):
    assert pipeline.find_inbox([{"_id": i, "title": t} for i, t in enumerate(titles)]) == expected

@pytest.mark.parametrize("titles", [["Food"], ["raingist", "raingist"]])
def test_find_inbox_missing_or_ambiguous(titles):
    with pytest.raises(pipeline.InboxMissing):
        pipeline.find_inbox([{"_id": i, "title": t} for i, t in enumerate(titles)])

def test_collection_catalog_paths_and_skips_inbox():
    class RD:
        def recent_titles(self, cid, n): return [f"t{cid}"]
    cols = [{"_id": INBOX, "title": "raingist"}, {"_id": 1, "title": "Food", "description": "eats"},
            {"_id": 2, "title": "Recipes", "parent": {"$id": 1}}]
    assert pipeline.collection_catalog(RD(), cols, INBOX) == [
        {"id": 1, "title": "Food", "description": "eats", "samples": ["t1"]},
        {"id": 2, "title": "Food / Recipes", "description": "", "samples": ["t2"]}]
