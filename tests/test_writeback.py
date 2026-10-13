from raingist.llm.prompt import Summary
from raingist import writeback as wb

RESERVED = frozenset({"raingist-done", "raingist-failed", "raingist-skip", "raingist-ocr", "raingist-redo"})
STATE = frozenset({"raingist-done", "raingist-failed", "raingist-skip"})

def block(text="Sum."):
    return wb.build_block(Summary(summary=text, key_takeaways=["a"], language="en"), "captions", "m", "2026-10-13", "en")

def test_merge_note_append_and_idempotent():
    note = wb.merge_note("mine", block())
    assert note.startswith("mine\n\n**AI summary**\nSum.")
    assert wb.merge_note(note, block("Other.")) == note

def test_merge_note_empty_and_strips_failure():
    assert wb.merge_note("", block()) == block()
    note = wb.merge_note("mine\n\n_raingist-failed: x · 2026-10-01_", block())
    assert "_raingist-failed:" not in note and note.startswith("mine")

def test_merge_note_truncates():
    note = wb.merge_note("x" * 9500, block())
    assert len(note) == wb.MAX_NOTE and note.endswith("…")

def test_strip_ai_block():
    note = "before\n\n" + block() + "\nafter"
    assert wb.strip_ai_block(note) == "before\n\nafter"

def test_merge_tags():
    out = wb.merge_tags(["Mine", "raingist-redo", "raingist-ocr"], ["cooking", "mine"], "raingist-done", STATE | {"raingist-redo"})
    assert out == ["Mine", "raingist-ocr", "cooking", "raingist-done"]
    assert wb.merge_tags(["raingist-done", "raingist-failed"], [], "raingist-failed", STATE) == ["raingist-failed"]

def test_choose_tags():
    gen = ["Cooking", "raingist-done", "Personal Finance", "a", "b", "c", "d", "e", "f", "g"]
    out = wb.choose_tags(gen, ["cooking", "personal-finance"], RESERVED)
    assert out[:2] == ["cooking", "personal-finance"]
    assert "raingist-done" not in out
    assert len(out) == 2 + 6
    assert wb.choose_tags(["Swift_UI"], ["SwiftUI", "swift-ui"], RESERVED) == ["swift-ui"]
    assert wb.choose_tags(["raingist-tools", "Raingist Notes", "raingist"], ["raingist-tools"], RESERVED) == ["raingist"]

def test_build_block_lang():
    assert "lang:" not in block()
    b = wb.build_block(Summary(summary="S", language="es"), "whisper", "m", "2026-10-13", "en")
    assert b.splitlines()[-1] == "_source: whisper · m · 2026-10-13 · lang: es_"

def test_is_placeholder_title():
    assert wb.is_placeholder_title("", "https://t/x")
    assert wb.is_placeholder_title("TikTok - Make Your Day", "https://t/x")
    assert wb.is_placeholder_title("https://t/x", "https://t/x")
    assert not wb.is_placeholder_title("Real title", "https://t/x")

def test_owner_note():
    assert wb.owner_note("") == ""
    assert wb.owner_note("  just my note \n") == "just my note"   # no tokens: whole note
    assert wb.owner_note("mine $start. list every tool $end. more") == "list every tool"
    assert wb.owner_note("$start.one$end.\nx\n$start. two $end.") == "one\ntwo"
    assert wb.owner_note("intro\n$start. focus on\nthe recipe") == "focus on\nthe recipe"   # $start. alone
    assert wb.owner_note("send this $end. keep this private") == "send this"   # $end. alone
    assert wb.owner_note("$start. $end. private") == ""   # explicit empty span sends nothing
    note = "$start. mine $end.\n\n" + block("$start. not mine $end.")
    assert wb.owner_note(note) == "mine"   # never the AI block
    assert wb.owner_note("plain\n\n" + block("Sum.")) == "plain"
    assert wb.owner_note("plain\n\n_raingist-failed: x · 2026-10-01_") == "plain"
