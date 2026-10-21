from raingist.extract import detect

def test_detect(settings):
    assert detect(settings, "https://www.tiktok.com/@x/video/1") == "tiktok"
    assert detect(settings, "https://vm.tiktok.com/ZM/") == "tiktok"
    assert detect(settings, "https://www.instagram.com/reel/C1abc/?igsh=x") == "instagram"
    assert detect(settings, "https://instagram.com/someone/reels/C1abc") == "instagram"
    assert detect(settings, "https://www.instagram.com/p/C1abc/") is None
    assert detect(settings, "https://www.instagram.com/reels/audio/123/") is None
    assert detect(settings, "https://youtu.be/abc") is None
    assert detect(settings, "https://example.com/post") is None
