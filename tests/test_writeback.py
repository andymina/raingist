from raingist.llm.prompt import Summary
from raingist import writeback as wb

RESERVED = frozenset({"raingist-failed", "raingist-skip", "raingist-ocr", "raingist-redo"})

def block(text="Sum."):
    return wb.build_block(Summary(summary=text, key_takeaways=["a"], language="en"))

def test_merge_note_append_and_idempotent():
    note = wb.merge_note("mine", block())
    assert note.startswith("mine\n\n**AI summary**\nSum.")
    assert wb.merge_note(note, block("Other.")) == note

def test_merge_note_empty_and_strips_failure():
    assert wb.merge_note("", block()) == block()
    note = wb.merge_note("mine\n\n_raingist-failed: x · 2026-10-01_", block())
    assert "_raingist-failed:" not in note and note.startswith("mine")

def test_merge_note_truncates():
    note = wb.merge_note("x" * 10500, block())
    assert len(note) == wb.MAX_NOTE and note.endswith("…")

def test_strip_ai_block():
    note = "before\n\n" + block() + "\nafter"
    assert wb.strip_ai_block(note) == "before\n\nafter"

def test_merge_tags():
    assert wb.merge_tags(["Mine", "raingist-ocr"], ["cooking", "mine"]) == ["Mine", "raingist-ocr", "cooking"]
    assert wb.strip_reserved(["Mine", "Raingist-OCR", "raingist-redo", "cooking"]) == ["Mine", "cooking"]

def test_choose_tags():
    gen = ["Cooking", "raingist-done", "Personal Finance", "a", "b", "c", "d", "e", "f", "g"]
    out = wb.choose_tags(gen, ["cooking", "personal-finance"], RESERVED)
    assert out[:2] == ["cooking", "personal-finance"]
    assert "raingist-done" not in out
    assert len(out) == 2 + 6
    assert wb.choose_tags(["Swift_UI"], ["SwiftUI", "swift-ui"], RESERVED) == ["swift-ui"]
    assert wb.choose_tags(["raingist-tools", "Raingist Notes", "raingist"], ["raingist-tools"], RESERVED) == ["raingist"]

def test_build_block():
    b = wb.build_block(Summary(summary="Four plugins:\n setup, skills.", key_takeaways=["Setup: scans\nrepos", " "]))
    assert b == "**AI summary**\nFour plugins: setup, skills.\n- Setup: scans repos"
    assert "_source" not in b

def test_strip_ai_block_legacy_footer():
    old = "mine\n\n**AI summary**\nOld.\n- x\n_source: captions · m · 2026-01-01_\nafter"
    assert wb.strip_ai_block(old) == "mine\n\nafter"

def test_is_placeholder_title():
    assert wb.is_placeholder_title("", "https://t/x")
    assert wb.is_placeholder_title("TikTok - Make Your Day", "https://t/x")
    assert wb.is_placeholder_title("https://t/x", "https://t/x")
    assert wb.is_placeholder_title("TikTok · Tyler Mommsen", "https://t/x")
    assert not wb.is_placeholder_title("Real title", "https://t/x")
    assert not wb.is_placeholder_title("TikTok tips · my list", "https://t/x")

def test_split_note():
    sp = wb.split_note
    assert sp("") == ("", "")
    assert sp("  just my note \n") == ("", "  just my note \n")   # no tokens: nothing sent, kept as written
    assert sp("thoughts $start. focus on X $end. more") == ("focus on X", "thoughts more")
    assert sp("$start.one$end.\nx\n$start. two $end.") == ("one\ntwo", "x")
    assert sp("intro\n$start. focus on\nthe recipe") == ("focus on\nthe recipe", "intro")   # $start. alone
    assert sp("send this $end. keep this") == ("send this", "keep this")   # $end. alone
    assert sp("$start. $end. private") == ("", "private")   # empty span: nothing sent, still cut
    assert sp("$start. only this $end.") == ("only this", "")
    assert sp("line1\n$start. X $end.\nline2") == ("X", "line1\nline2")   # span on its own line leaves no gap
    assert sp("para1\n\n$start. X $end.\n\npara2") == ("X", "para1\n\npara2")
    assert sp("$start. X $end.\n\n_raingist-failed: x · 2026-10-01_") == ("X", "")

def test_recipe_credits_creator():
    recipe = Summary(summary="Curry udon.", key_takeaways=["Ingredients: 2 eggs"], recipe=True)
    b = wb.build_block(recipe, "Cassie Yeung (@cassyeungmoney)")
    assert b.splitlines()[2] == "- Creator: Cassie Yeung (@cassyeungmoney)"
    assert wb.strip_ai_block("mine\n\n" + b) == "mine"
    assert "Creator:" not in wb.build_block(Summary(summary="Plugins.", key_takeaways=["x"]), "@someone")
    assert "Creator:" not in wb.build_block(recipe, None)

def test_creator_label():
    assert wb.creator_label("Cassie Yeung", "cassyeungmoney") == "Cassie Yeung (@cassyeungmoney)"
    assert wb.creator_label("patrox", "patrox") == "@patrox"
    assert wb.creator_label(None, "patrox") == "@patrox"
    assert wb.creator_label("Name Only", None) == "Name Only"
    assert wb.creator_label(None, None) is None
