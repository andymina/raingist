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
CONFIDENCE = ["high"]   # and its collection_confidence

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
    ROUTE_TO[0], CONFIDENCE[0] = 0, "high"
    monkeypatch.setattr(pipeline, "extract", lambda s, ctype, it, want_ocr: Extraction(text="t", source="captions"))
    calls = []
    def summarize(s, it, ctype, ex, tags, owner_note="", catalog=None):
        calls.append(owner_note)
        return Summary(summary="New summary.", key_takeaways=["k"], tags=["Cooking"], title="A title",
                       collection_id=ROUTE_TO[0], collection_confidence=CONFIDENCE[0]), "m"
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

@pytest.mark.parametrize("chosen,confidence,dest", [(77, "high", 77), (77, "medium", pipeline.UNSORTED),
                                                    (0, "high", pipeline.UNSORTED), (12345, "high", pipeline.UNSORTED)])
def test_route(settings, tmp_path, ok, chosen, confidence, dest):
    ROUTE_TO[0], CONFIDENCE[0] = chosen, confidence
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

class MembersRD:
    """Collections' bookmarks by id; get() for "not here" titles."""
    def __init__(self, members, gone=None):
        self.members, self.gone, self.gets = members, gone or {}, []
    def search(self, query, max_pages=10, collection=0, sort="-created"):
        return self.members.get(collection, [])
    def get(self, rid):
        self.gets.append(rid)
        if rid not in self.gone:
            raise pipeline.RaindropError("404")
        return {"_id": rid, "title": self.gone[rid]}

def bm(rid, title, tags=(), summary=""):
    return {"_id": rid, "title": title, "tags": list(tags), "note": f"{writeback.MARKER}\n{summary}" if summary else ""}

def test_collection_catalog_paths_and_skips_inbox():
    cols = [{"_id": INBOX, "title": "raingist"}, {"_id": 1, "title": "Food", "description": "eats", "count": 1},
            {"_id": 2, "title": "Recipes", "parent": {"$id": 1}}]
    rd = MembersRD({1: [bm(10, "Pasta", ["cooking"], "Cacio e pepe.")], 2: []})
    catalog = pipeline.collection_catalog(rd, cols, INBOX)
    assert [(c["id"], c["title"], c["description"], c["made_by"], c["size"]) for c in catalog] == [
        (1, "Food", "eats", "owner", 1), (2, "Food / Recipes", "", "owner", 0)]
    assert catalog[0]["examples"] == ["Pasta - Cacio e pepe."]

def test_catalog_profile_uses_owner_picks_and_lists_moved_out(tmp_path):
    from raingist.state import Placements
    p = Placements(tmp_path / "p.json")
    p.record([100, 101], 1); p.record([102], 2)
    p.record([200, 201], 1)   # filed into 1, since moved out by the owner (201 was deleted)
    cols = [{"_id": 1, "title": "music inspiration"},
            {"_id": 2, "title": "Tools", "description": f"Dev tools. {pipeline.PROVENANCE}"}]
    rd = MembersRD({1: [bm(100, "NYC restaurants", ["nyc", "food"]), bm(101, "Vinyl bars", ["nyc"]),
                        bm(5, "Synex", ["music"], "Beat-making session.")],
                    2: [bm(102, "Orca", ["github"])]}, gone={200: "Thai restaurants"})
    music, tools = pipeline.collection_catalog(rd, cols, INBOX, p)
    assert music["examples"] == ["Synex - Beat-making session."]   # service filings ignored
    assert music["not_here"] == ["Thai restaurants"] and music["members"][0]["_id"] == 100
    assert tools["examples"] == ["Orca"] and tools["made_by"] == "raingist"   # its own collection keeps every example
    pipeline.collection_catalog(rd, cols, INBOX, p)
    assert rd.gets.count(200) == 1 and rd.gets.count(201) == 2   # titles cached; a deleted one is retried, not cached

def test_spread_covers_the_whole_collection():
    assert pipeline.spread(list(range(5)), 10) == [0, 1, 2, 3, 4]
    assert pipeline.spread(list(range(100)), 4) == [0, 33, 66, 99]

@pytest.mark.parametrize("chosen,dry_run,recorded", [(77, False, {77}), (0, False, set()), (77, True, set())])
def test_routing_records_placement(settings, tmp_path, ok, chosen, dry_run, recorded):
    from raingist.state import Placements
    ROUTE_TO[0] = chosen
    p = Placements(tmp_path / "p.json")
    pipeline.process_item(settings, acct(), FakeRaindrop([item()]), Attempts(tmp_path / "a.json", settings.retry_backoff),
                          10, [], INBOX, CATALOG, dry_run=dry_run, placements=p)
    assert p.filed_into(10) == recorded
