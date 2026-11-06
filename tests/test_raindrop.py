from raingist.raindrop import Raindrop

def test_recent_titles_skips_ids(monkeypatch):
    rd = Raindrop("t")
    asked = []
    def req(method, path, **kw):
        asked.append(kw["params"]["perpage"])
        return {"items": [{"_id": i, "title": f"t{i}"} for i in range(1, kw["params"]["perpage"] + 1)]}
    monkeypatch.setattr(rd, "_req", req)
    assert rd.recent_titles(9, 2) == ["t1", "t2"]
    assert rd.recent_titles(9, 2, skip={1, 3}) == ["t2", "t4"]
    assert asked == [2, 4]
