import dataclasses
import pytest
import raingist.llm as llm
from raingist.llm import ProviderUnavailable, Summary
from raingist.extract.common import Extraction, TransientFailure

ITEM = {"link": "https://www.tiktok.com/@u/video/1", "title": ""}

def two(settings):
    return dataclasses.replace(settings, llm_providers=("a", "b"), llm_keys={"a": "k", "b": "k"},
                               llm_models={"a": "model-a", "b": "model-b"},
                               llm_decision_models={"a": "decide-a", "b": "decide-b"})

def test_fallback_on_unavailable(settings, monkeypatch):
    def a(*_): raise ProviderUnavailable("429")
    monkeypatch.setattr(llm, "PROVIDERS", {"a": a, "b": lambda *_: Summary(summary="ok")})
    summary, model = llm.summarize(two(settings), ITEM, "tiktok", Extraction(), [])
    assert (summary.summary, model) == ("ok", "model-b")

def test_invalid_json_retried_then_next(settings, monkeypatch):
    calls = []
    def a(*_):
        calls.append(1); raise ValueError("bad json")
    monkeypatch.setattr(llm, "PROVIDERS", {"a": a, "b": lambda *_: Summary(summary="ok")})
    assert llm.summarize(two(settings), ITEM, "tiktok", Extraction(), [])[1] == "model-b"
    assert len(calls) == 2

def test_all_unavailable(settings, monkeypatch):
    def down(*_): raise ProviderUnavailable("503")
    monkeypatch.setattr(llm, "PROVIDERS", {"a": down, "b": down})
    with pytest.raises(TransientFailure, match="no LLM provider"):
        llm.summarize(two(settings), ITEM, "tiktok", Extraction(), [])

def test_user_message_optional_sections():
    from raingist.llm.prompt import build_user_message
    plain = build_user_message(ITEM, "tiktok", Extraction(), [])
    assert "AUDIO:" not in plain and "OWNER_NOTE:" not in plain
    msg = build_user_message(ITEM, "tiktok", Extraction(sound="Big Fun by Heathers"), [], "list the tools")
    assert "AUDIO: reused sound: Big Fun by Heathers" in msg
    assert msg.startswith("OWNER_NOTE:\nlist the tools\n")   # ahead of the material

def test_user_message_collections():
    from raingist.llm.prompt import build_user_message
    assert "COLLECTIONS" not in build_user_message(ITEM, "tiktok", Extraction(), [])
    assert "COLLECTIONS: (none)" in build_user_message(ITEM, "tiktok", Extraction(), [], catalog=[])
    msg = build_user_message(ITEM, "tiktok", Extraction(), [], catalog=[
        {"id": 7, "title": "Food / Recipes", "description": "eats", "examples": ["Pasta - Cacio.", ""],
         "not_here": ["NYC restaurants"], "members": [{"_id": 1}]},
        {"id": 8, "title": "music inspiration", "description": "", "examples": []}])
    assert ("7: Food / Recipes\n  scope: eats\n  examples: Pasta - Cacio.\n"
            "  not here: NYC restaurants\n8: music inspiration\n  scope: (none: infer it from the examples)\n"
            "  examples: (none)") in msg
    assert "_id" not in msg   # members stay out of the prompt

def test_decision_calls_use_decision_model(settings, monkeypatch):
    from raingist.llm.prompt import Assignment
    monkeypatch.setattr(llm, "PROVIDERS", {"a": lambda *_: Assignment(), "b": lambda *_: Assignment()})
    assert llm.rebalance(two(settings), "msg")[1] == "decide-a"
    assert llm.assign(two(settings), "msg")[1] == "decide-a"
