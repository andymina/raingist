from raingist.subtitles import parse_subtitle_file, captions_text

def test_vtt(tmp_path):
    p = tmp_path / "1.en.vtt"
    p.write_text("WEBVTT\nKind: captions\nLanguage: en\n\n00:00:00.000 --> 00:00:02.000\n<c>hello</c> world\n\n"
                 "00:00:02.000 --> 00:00:04.000\nhello world\n\n00:00:04.000 --> 00:00:06.000\nsecond line\n")
    assert parse_subtitle_file(p) == "hello world second line"

def test_srt(tmp_path):
    p = tmp_path / "1.srt"
    p.write_text("1\n00:00:00,000 --> 00:00:02,000\nfirst\n\n2\n00:00:02,000 --> 00:00:04,000\nsecond\n")
    assert parse_subtitle_file(p) == "first second"

def test_json_utterances(tmp_path):
    p = tmp_path / "1.json"
    p.write_text('{"utterances": [{"text": "a"}, {"text": "b"}]}')
    assert parse_subtitle_file(p) == "a b"

def test_captions_text_too_short(tmp_path):
    (tmp_path / "1.en.vtt").write_text("WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nonly four words here\n")
    assert captions_text(tmp_path) == ("", None)

def test_captions_text_language(tmp_path):
    (tmp_path / "1.en.vtt").write_text("WEBVTT\n\n00:00:00.000 --> 00:00:02.000\none two three four five six\n")
    assert captions_text(tmp_path) == ("one two three four five six", "en")
