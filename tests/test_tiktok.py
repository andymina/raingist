import json
from pathlib import Path
import pytest
from raingist.extract import tiktok
from raingist.extract.common import Extraction, PermanentFailure, TransientFailure

FIXTURE = Path(__file__).parent / "fixtures" / "tiktok_slideshow.html"

def test_is_slideshow():
    assert tiktok.is_slideshow("https://www.tiktok.com/@u/photo/1")
    assert not tiktok.is_slideshow("https://www.tiktok.com/@u/video/1")

def test_parse_post_and_image_urls():
    item = tiktok.parse_post(FIXTURE.read_text())
    assert item["desc"] == "5 tips for better sleep #sleep"
    assert item["author"]["uniqueId"] == "sleepcoach"
    urls = tiktok.image_urls(item)
    assert len(urls) == 2 and all(u.endswith(".jpeg") for u in urls)

def _page(detail: dict) -> str:
    data = {"__DEFAULT_SCOPE__": {"webapp.video-detail": detail}}
    return f'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">{json.dumps(data)}</script>'

def test_parse_post_unavailable():
    with pytest.raises(PermanentFailure):
        tiktok.parse_post(_page({"statusCode": 10204, "statusMsg": "item doesn't exist"}))

def test_parse_post_no_post_data():
    data = {"__DEFAULT_SCOPE__": {"webapp.app-context": {}}}
    page = f'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">{json.dumps(data)}</script>'
    with pytest.raises(TransientFailure):
        tiktok.parse_post(page)
    with pytest.raises(TransientFailure):
        tiktok.parse_post(_page({"statusCode": 0}))

def test_data_url():
    assert tiktok.data_url("https://www.tiktok.com/@u/photo/7?_r=1&_t=x") == "https://www.tiktok.com/@u/video/7"

def test_parse_post_no_script():
    with pytest.raises(TransientFailure):
        tiktok.parse_post("<html><body>bot wall</body></html>")

@pytest.mark.parametrize("final_url,expected", [
    ("https://www.tiktok.com/@u/photo/1", "slideshow"),
    ("https://www.tiktok.com/@u/video/1", "video"),
])
def test_extract_routes(settings, monkeypatch, tmp_path, final_url, expected):
    fetched = []
    def fetch(client, url):
        fetched.append(url); return final_url, "<html></html>"
    monkeypatch.setattr(tiktok, "fetch_page", fetch)
    monkeypatch.setattr(tiktok, "extract_slideshow", lambda s, client, html, workdir: Extraction(format="slideshow"))
    monkeypatch.setattr(tiktok, "extract_video", lambda s, url, workdir, want_ocr: Extraction(format="video"))
    ex = tiktok.extract(settings, {"link": "https://vm.tiktok.com/ZM/"}, tmp_path / "w", False)
    assert ex.format == expected
    if expected == "slideshow":
        assert fetched == ["https://vm.tiktok.com/ZM/", "https://www.tiktok.com/@u/video/1"]

@pytest.mark.parametrize("info,expected", [
    ({"channel": "Usama's Board", "track": "original sound", "artists": ["Usama's Board"]}, None),
    ({"channel": "patroX", "track": "Big Fun", "artists": ["Evan Todd", "Alice Lee"]}, "Big Fun by Evan Todd, Alice Lee"),
    ({"channel": "me", "track": "original sound", "artists": ["someone else"]}, "original sound by someone else"),
    ({"channel": "Tom & Jerry", "track": "original sound", "artists": ["Tom", "Jerry"]}, None),
    ({"channel": "me", "track": None, "artists": None}, None),
])
def test_reused_sound(info, expected):
    assert tiktok.reused_sound(info) == expected
