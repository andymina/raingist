from . import instagram, tiktok

# name -> (matches(url) -> bool, extract(settings, item, workdir, want_ocr) -> Extraction)
# New source: module with matches/extract + one entry here + add to ENABLED_EXTRACTORS.
EXTRACTORS = {
    "tiktok": (tiktok.matches, tiktok.extract),
    "instagram": (instagram.matches, instagram.extract),
}

def detect(s, url: str) -> str | None:
    """Name of the first enabled extractor that handles this URL, else None."""
    for name in s.enabled_extractors:
        if EXTRACTORS[name][0](url):
            return name
    return None
