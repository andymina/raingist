from raingist.extract import instagram, ytdl
from raingist.extract.common import Extraction

def test_extract_maps_handle_and_strips_query(settings, monkeypatch, tmp_path):
    seen = {}
    def fake(s, url, workdir, want_ocr, cookiefile):
        seen["url"] = url
        return Extraction(text="hi", source="captions"), {"channel": "handle", "uploader": "Display Name"}
    monkeypatch.setattr(ytdl, "extract_video", fake)
    ex = instagram.extract(settings, {"link": "https://www.instagram.com/reel/C1abc/?igsh=x"}, tmp_path, False)
    assert seen["url"] == "https://www.instagram.com/reel/C1abc/"
    assert (ex.author, ex.creator, ex.text) == ("handle", "Display Name", "hi")
