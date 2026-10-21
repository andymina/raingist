import re
from pathlib import Path
from urllib.parse import urlparse
from .common import Extraction
from . import ytdl

# /reel/<id>, /reels/<id>, optionally under /<user>/ (yt-dlp's pattern); /reels/audio/ is a sound page, not a post
REEL_PATH = re.compile(r"^/(?:[^/]+/)?reels?/(?!audio/)[^/?#]+")

def matches(url: str) -> bool:
    u = urlparse(url or "")
    host = (u.hostname or "").lower().removeprefix("www.")
    return host in {"instagram.com", "m.instagram.com"} and bool(REEL_PATH.match(u.path))

def extract(s, item: dict, workdir: Path, want_ocr: bool) -> Extraction:
    ex, info = ytdl.extract_video(s, item["link"].split("?")[0], workdir, want_ocr, s.instagram_cookies_file)
    # Instagram's yt-dlp fields are the reverse of TikTok's: channel is the handle, uploader the display name
    ex.author, ex.creator = info.get("channel"), info.get("uploader")
    return ex
