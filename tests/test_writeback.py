from raingist.llm.prompt import Summary
from raingist import writeback as wb

RESERVED = frozenset({"ai-done", "ai-failed", "ai-skip", "ai-ocr", "ai-redo"})
STATE = frozenset({"ai-done", "ai-failed", "ai-skip"})

def block(text="Sum."):
    return wb.build_block(Summary(summary=text, key_takeaways=["a"], language="en"), "captions", "m", "2026-10-13", "en")

def test_merge_note_append_and_idempotent():
    note = wb.merge_note("mine", block())
    assert note.startswith("mine\n\n**AI summary**\nSum.")
    assert wb.merge_note(note, block("Other.")) == note

def test_merge_note_empty_and_strips_failure():
    assert wb.merge_note("", block()) == block()
    note = wb.merge_note("mine\n\n_ai-failed: x · 2026-10-01_", block())
    assert "_ai-failed:" not in note and note.startswith("mine")

def test_merge_note_truncates():
    note = wb.merge_note("x" * 9500, block())
    assert len(note) == wb.MAX_NOTE and note.endswith("…")

def test_strip_ai_block():
    note = "before\n\n" + block() + "\nafter"
    assert wb.strip_ai_block(note) == "before\n\nafter"

def test_merge_tags():
    out = wb.merge_tags(["Mine", "ai-redo", "ai-ocr"], ["cooking", "mine"], "ai-done", STATE | {"ai-redo"})
    assert out == ["Mine", "ai-ocr", "cooking", "ai-done"]
    assert wb.merge_tags(["ai-done", "ai-failed"], [], "ai-failed", STATE) == ["ai-failed"]

def test_choose_tags():
    gen = ["Cooking", "ai-done", "Personal Finance", "a", "b", "c", "d", "e", "f", "g"]
    out = wb.choose_tags(gen, ["cooking", "personal-finance"], RESERVED)
    assert out[:2] == ["cooking", "personal-finance"]
    assert "ai-done" not in out
    assert len(out) == 2 + 6
    assert wb.choose_tags(["Swift_UI"], ["SwiftUI", "swift-ui"], RESERVED) == ["swift-ui"]

def test_build_block_lang():
    assert "lang:" not in block()
    b = wb.build_block(Summary(summary="S", language="es"), "whisper", "m", "2026-10-13", "en")
    assert b.splitlines()[-1] == "_source: whisper · m · 2026-10-13 · lang: es_"

def test_is_placeholder_title():
    assert wb.is_placeholder_title("", "https://t/x")
    assert wb.is_placeholder_title("TikTok - Make Your Day", "https://t/x")
    assert wb.is_placeholder_title("https://t/x", "https://t/x")
    assert not wb.is_placeholder_title("Real title", "https://t/x")
