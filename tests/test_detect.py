from raingist.extract import detect

def test_detect(settings):
    assert detect(settings, "https://www.tiktok.com/@x/video/1") == "tiktok"
    assert detect(settings, "https://vm.tiktok.com/ZM/") == "tiktok"
    assert detect(settings, "https://youtu.be/abc") is None
    assert detect(settings, "https://example.com/post") is None
