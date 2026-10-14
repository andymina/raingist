import dataclasses, datetime as dt, json
import pytest
import raingist.organize as organize
from raingist.organize import due, validate_proposal, validate_assignment, OrganizeError
from raingist.llm.prompt import Proposal, Assignment, NewCollection, Merge, Move
from raingist.pipeline import PROVENANCE, collection_catalog
from raingist.settings import load_settings

ET = organize.TZ

def at(y, m, d, h, mi=0):
    return dt.datetime(y, m, d, h, mi, tzinfo=ET)

# --- schedule ---

def test_due_first_run_and_retry_gate():
    now = at(2026, 10, 13, 9)
    assert due({}, now)
    assert not due({"last_attempt_at": (now - dt.timedelta(minutes=59)).isoformat()}, now)
    assert due({"last_attempt_at": (now - dt.timedelta(minutes=61)).isoformat()}, now)

def test_due_daily_at_10_et():
    ran = {"last_run_at": at(2026, 10, 12, 15).isoformat()}   # first run happened mid-afternoon
    assert not due(ran, at(2026, 10, 12, 23))
    assert not due(ran, at(2026, 10, 13, 9, 59))
    assert due(ran, at(2026, 10, 13, 10))
    assert not due({"last_run_at": at(2026, 10, 13, 10, 1).isoformat()}, at(2026, 10, 13, 18))

def test_run_before_10_covers_that_day():
    early = {"last_run_at": at(2026, 10, 13, 9, 30).isoformat()}   # first run crossed the threshold early
    assert not due(early, at(2026, 10, 13, 10, 30))
    assert due(early, at(2026, 10, 14, 10))

def test_due_across_dst_end():
    ran = {"last_run_at": at(2026, 10, 31, 10, 5).astimezone(dt.UTC).isoformat()}   # EDT
    assert not due(ran, dt.datetime(2026, 11, 1, 14, 59, tzinfo=dt.UTC))   # 09:59 EST
    assert due(ran, dt.datetime(2026, 11, 1, 15, 0, tzinfo=dt.UTC))        # 10:00 EST

# --- proposal validation ---

COLLECTIONS = [
    {"_id": 5, "title": "raingist"},
    {"_id": 10, "title": "Recipes", "count": 40},
    {"_id": 11, "title": "Cooking", "count": 90, "description": f"Food stuff {PROVENANCE}"},
    {"_id": 12, "title": "Tech", "count": 3},
    {"_id": 13, "title": "Gadgets", "count": 2, "parent": {"$id": 12}},
    {"_id": 14, "title": "Private", "count": 1, "description": "keep out #raingist-exclude"},
    {"_id": 15, "title": "Shared", "count": 1, "collaborators": {"$id": 1}},
    {"_id": 16, "title": "Travel", "count": 9},
]
CATALOG = [{"id": c["_id"], "title": c["title"], "description": c.get("description", ""), "samples": []}
           for c in COLLECTIONS if c["_id"] not in (5, 14)]
UNSORTED_IDS = set(range(100, 120))

def check(new=(), merges=(), min_group=3):
    return validate_proposal(Proposal(new_collections=list(new), merges=list(merges)), CATALOG, COLLECTIONS,
                             UNSORTED_IDS, min_group)

def nc(title, ids, parent=0, description="Things."):
    return NewCollection(title=title, description=description, parent_id=parent, item_ids=list(ids))

def test_new_collection_kept_with_provenance_and_title_cap():
    creates, moves, merges = check([nc("A" * 50, [100, 101, 102], description=f"Desc. {PROVENANCE}")])
    assert creates == [{"title": "A" * 40, "description": f"Desc. {PROVENANCE}", "parent": 0,
                        "item_ids": [100, 101, 102]}]
    assert moves == {} and merges == []

def test_new_collection_below_min_group_or_bad_ids_dropped():
    creates, _, _ = check([nc("Birds", [100, 101, 999, 101])])   # 999 not unsorted, 101 duplicate
    assert creates == []

def test_bookmark_in_one_new_collection_only():
    creates, _, _ = check([nc("Birds", [100, 101, 102]), nc("Fish", [102, 103, 104])])
    assert [c["title"] for c in creates] == ["Birds"]   # Fish lost 102, so it fell below the minimum

def test_parent_must_be_valid_and_not_merged_away():
    assert check([nc("Phones", [100, 101, 102], parent=12)])[0][0]["parent"] == 12
    assert check([nc("Phones", [100, 101, 102], parent=14)])[0] == []   # excluded parent
    assert check([nc("Phones", [100, 101, 102], parent=11)], [Merge(from_id=10, into_id=11)])[0] == []   # 11 merged away

def test_name_clash_becomes_moves_into_existing():
    creates, moves, _ = check([nc("recipes 🍝", [100, 101])])   # clash needs no minimum
    assert creates == [] and moves == {100: 10, 101: 10}

def test_name_clash_with_excluded_or_inbox_dropped():
    for title in ("Private", "Raingist"):
        assert check([nc(title, [100, 101, 102])])[:2] == ([], {})

def test_duplicate_new_titles_keep_first():
    creates, moves, _ = check([nc("Birds", [100, 101, 102]), nc("birds!", [103, 104, 105])])
    assert [c["item_ids"] for c in creates] == [[100, 101, 102]] and moves == {}

# --- merges ---

def test_owner_collection_survives_raingist_one():
    assert check(merges=[Merge(from_id=10, into_id=11)])[2] == [(11, 10)]   # 11 is raingist-made though larger

def test_larger_survives_between_owner_collections():
    assert check(merges=[Merge(from_id=10, into_id=16)])[2] == [(16, 10)]   # Recipes 40 outlives Travel 9
    assert check(merges=[Merge(from_id=16, into_id=10)])[2] == [(16, 10)]

def test_merge_rules():
    assert check(merges=[Merge(from_id=13, into_id=12)])[2] == []   # child and parent
    assert check(merges=[Merge(from_id=12, into_id=10)])[2] == []   # source 12 has a child
    assert check(merges=[Merge(from_id=15, into_id=16)])[2] == []   # shared source
    assert check(merges=[Merge(from_id=14, into_id=16)])[2] == []   # excluded
    assert check(merges=[Merge(from_id=5, into_id=16)])[2] == []    # inbox
    assert check(merges=[Merge(from_id=16, into_id=16)])[2] == []
    chain = check(merges=[Merge(from_id=10, into_id=16), Merge(from_id=16, into_id=13)])[2]
    assert chain == [(16, 10)]

# --- assignment ---

def test_assignment_validation():
    a = Assignment(moves=[Move(item_id=100, collection_id=10), Move(item_id=100, collection_id=16),
                          Move(item_id=101, collection_id=0), Move(item_id=102, collection_id=14),
                          Move(item_id=999, collection_id=10)])
    assert validate_assignment(a, {10, 16}, {100, 101, 102}) == {100: 10}

# --- catalog ---

def test_catalog_skips_excluded():
    class RD:
        def recent_titles(self, cid, n): return []
    assert [c["id"] for c in collection_catalog(RD(), COLLECTIONS, 5)] == [10, 11, 12, 13, 15, 16]

# --- settings ---

def test_settings(env):
    s = load_settings(env)
    assert (s.organize_enabled, s.organize_first_run, s.organize_min_group, s.organize_max_items) == (True, 30, 5, 200)
    assert not load_settings({**env, "ORGANIZE_ENABLED": "0"}).organize_enabled
    with pytest.raises(SystemExit, match="ORGANIZE_ENABLED"):
        load_settings({**env, "ORGANIZE_ENABLED": "yes please"})
    with pytest.raises(SystemExit, match="ORGANIZE_MIN_GROUP"):
        load_settings({**env, "ORGANIZE_MIN_GROUP": "0"})

# --- a whole run against a fake Raindrop ---

class FakeRD:
    def __init__(self, token):
        self.calls, self.leftover = [], False
        self.unsorted = [{"_id": i, "title": f"t{i}", "tags": [], "note": "x"} for i in range(100, 106)]
        self.unsorted.append({"_id": 106, "title": "keep", "tags": ["raingist-skip"]})
        RUNS.append(self)
    def collections(self): return COLLECTIONS
    def search(self, query, max_pages=10, collection=0, sort="-created"):
        if collection == -1:
            assert sort == "created"; return self.unsorted
        return [{"_id": 900}] if collection == 16 and (max_pages > 1 or self.leftover) else []
    def recent_titles(self, cid, n): return []
    def create_collection(self, title, description, parent=0):
        self.calls.append(("create", title)); return {"_id": 50}
    def move_many(self, src, ids, to):
        self.calls.append(("move", src, tuple(ids), to)); return len(ids)
    def delete_collection(self, cid): self.calls.append(("delete", cid))

RUNS: list = []

@pytest.fixture
def run(settings, make_account, alerts, monkeypatch):
    RUNS.clear()
    s = dataclasses.replace(settings, organize_min_group=2, organize_first_run=3)
    acct = make_account(s, 1)
    monkeypatch.setattr(organize, "Raindrop", FakeRD)
    monkeypatch.setattr(organize, "access_token", lambda s, a: "t")
    sent = {}
    def propose(s, msg):
        sent["propose"] = msg
        return Proposal(new_collections=[nc("Birds", [100, 101])], merges=[Merge(from_id=10, into_id=16)]), "m"
    def assign(s, msg):
        sent["assign"] = msg
        return Assignment(moves=[Move(item_id=102, collection_id=10), Move(item_id=103, collection_id=16),
                                 Move(item_id=104, collection_id=999)]), "m"
    monkeypatch.setattr(organize.llm, "propose", propose)
    monkeypatch.setattr(organize.llm, "assign", assign)
    return lambda **kw: organize.run_account(s, acct, alerts, **kw), s, sent

def test_run_order_state_journal_and_alert(run, alerts):
    go, s, sent = run
    assert go() == {"created": 1, "moved": 4, "merged": 1}
    assert RUNS[0].calls == [("move", 16, (900,), 10), ("delete", 16),   # flipped: Recipes (40) outlives Travel (9)
                             ("move", -1, (102, 103), 10),                # 103 was filed into Travel: follows the merge
                             ("create", "Birds"), ("move", -1, (100, 101), 50)]
    assert "100:" in sent["assign"] and "106:" not in sent["assign"]      # raingist-skip stays in Unsorted
    unsorted_part = sent["propose"].split("UNSORTED")[1]
    assert "100:" in unsorted_part and "102:" not in unsorted_part         # propose sees only the leftovers
    state = json.loads((s.state_dir / "1" / "organize.json").read_text())
    assert state["last_counts"] == {"created": 1, "moved": 4, "merged": 1}
    journal = json.loads(next((s.state_dir / "1" / "organize").iterdir()).read_text())
    assert [j["step"] for j in journal] == ["merged", "moved", "created"]
    assert journal[0]["removed"]["title"] == "Travel"
    assert alerts.sent == [(alerts.keys[0], "[user1] organized: 1 new (Birds), 4 moved, merged Travel → Recipes")]
    assert go() is None   # not due again until the next 10:00 ET

def test_few_leftovers_send_no_bookmarks_to_propose(run, monkeypatch):
    go, s, sent = run
    monkeypatch.setattr(organize.llm, "assign", lambda s, msg: (Assignment(moves=[
        Move(item_id=i, collection_id=10) for i in (100, 101, 102, 103, 104)]), "m"))   # only 105 left over
    go()
    assert sent["propose"].endswith("UNSORTED (id: title | tags | excerpt | note):\n(none)")

def test_no_collections_skips_assign_and_needs_leftovers_for_propose(run, monkeypatch):
    go, s, sent = run
    monkeypatch.setattr(FakeRD, "collections", lambda self: [COLLECTIONS[0]])   # only the inbox
    def propose(s, msg):
        sent["propose"] = msg; return Proposal(), "m"
    monkeypatch.setattr(organize.llm, "propose", propose)
    go()
    assert "assign" not in sent and "100:" in sent["propose"]

def test_dry_run_writes_nothing(run, alerts):
    go, s, _ = run
    assert go(dry_run=True)["created"] == 1
    assert RUNS[0].calls == [] and alerts.sent == []
    assert not (s.state_dir / "1" / "organize.json").exists()

def test_merge_not_deleted_when_bookmarks_remain(run):
    go, s, _ = run
    FakeRD_init = FakeRD.__init__
    def leftover(self, token):
        FakeRD_init(self, token); self.leftover = True
    FakeRD.__init__ = leftover
    try:
        with pytest.raises(OrganizeError, match="still holds bookmarks"):
            go()
    finally:
        FakeRD.__init__ = FakeRD_init
    assert ("delete", 16) not in RUNS[0].calls
    state = json.loads((s.state_dir / "1" / "organize.json").read_text())
    assert "last_run_at" not in state and "last_attempt_at" in state   # retried after an hour

def test_first_run_waits_for_threshold(run):
    go, s, _ = run
    organize_first = dataclasses.replace(s, organize_first_run=50)
    acct = organize.store(s).load(s, 1)
    assert organize.run_account(organize_first, acct, None) is None
    assert RUNS[0].calls == []

def test_run_due_alerts_failure(run, settings, alerts, monkeypatch):
    monkeypatch.setattr(organize, "run_account", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert organize.run_due(settings, alerts) == {}
    assert alerts.keys == ["organize:1"]
