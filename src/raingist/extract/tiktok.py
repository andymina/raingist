import json, logging, re
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from urllib.parse import urlparse
import httpx
from .common import Extraction, PermanentFailure, TransientFailure
from . import ytdl
from ..subtitles import captions_text
from ..transcribe import transcribe
from ..ocr import ocr_video, ocr_images

log = logging.getLogger(__name__)
HOSTS = {"tiktok.com", "vm.tiktok.com", "vt.tiktok.com", "m.tiktok.com"}
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
DATA_SCRIPT = re.compile(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', re.S)
MAX_IMAGES = 35

def matches(url: str) -> bool:
    host = (urlparse(url or "").hostname or "").lower().removeprefix("www.")
    return host in HOSTS or host.endswith(".tiktok.com")

def is_slideshow(url: str) -> bool:
    return "/photo/" in urlparse(url).path

def _client(cookiefile: Path | None) -> httpx.Client:
    cookies = None
    if cookiefile:
        jar = MozillaCookieJar(str(cookiefile)); jar.load(ignore_discard=True, ignore_expires=True)
        cookies = jar
    return httpx.Client(headers={"User-Agent": UA}, cookies=cookies, follow_redirects=True, timeout=20)

def fetch_page(client: httpx.Client, url: str) -> tuple[str, str]:
    """(canonical URL after redirects, HTML)."""
    try:
        r = client.get(url)
    except httpx.HTTPError as e:
        raise TransientFailure(f"tiktok page fetch: {e}") from e
    if r.status_code == 404:
        raise PermanentFailure("tiktok post not found (404)")
    if r.status_code >= 400:
        raise TransientFailure(f"tiktok page fetch -> {r.status_code}")
    return str(r.url), r.text

def parse_post(html: str) -> dict:
    """itemStruct from the page's embedded JSON. PermanentFailure for private/removed posts."""
    m = DATA_SCRIPT.search(html)
    if not m:
        raise TransientFailure("tiktok page has no embedded data (layout change or bot wall)")
    detail = json.loads(m.group(1)).get("__DEFAULT_SCOPE__", {}).get("webapp.video-detail", {})
    item = detail.get("itemInfo", {}).get("itemStruct")
    if detail.get("statusCode", 0) != 0 or not item:
        raise PermanentFailure(f"tiktok post unavailable: {detail.get('statusMsg') or detail.get('statusCode')}")
    return item

def image_urls(item: dict) -> list[str]:
    urls = []
    for img in item.get("imagePost", {}).get("images", [])[:MAX_IMAGES]:
        variants = img.get("imageURL", {}).get("urlList", [])
        if variants:
            urls.append(next((u for u in variants if "jpeg" in u), variants[0]))
    return urls

def extract(s, item: dict, workdir: Path, want_ocr: bool) -> Extraction:
    with _client(s.tiktok_cookies_file) as client:
        url, html = fetch_page(client, item["link"])
        if is_slideshow(url):
            return extract_slideshow(s, client, html, workdir)
    return extract_video(s, url, workdir, want_ocr)

def extract_slideshow(s, client: httpx.Client, html: str, workdir: Path) -> Extraction:
    post = parse_post(html)
    ex = Extraction(format="slideshow", author=post.get("author", {}).get("uniqueId"), description=post.get("desc"))
    urls = image_urls(post)
    if not urls:
        raise TransientFailure("slideshow: no image URLs in page data")
    workdir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, u in enumerate(urls):
        try:
            r = client.get(u)
            r.raise_for_status()
        except httpx.HTTPError as e:
            log.warning("slideshow image %d failed: %s", i, e); continue
        p = workdir / f"{i:03d}.jpg"; p.write_bytes(r.content); paths.append(p)
    if not paths:
        raise TransientFailure("slideshow: every image download failed")
    ex.onscreen = ocr_images(s, paths)
    if ex.onscreen:
        ex.source = "ocr"
    return ex

def oembed(url: str) -> dict:
    try:
        r = httpx.get("https://www.tiktok.com/oembed", params={"url": url}, timeout=15)
        return r.json() if r.status_code == 200 else {}
    except (httpx.HTTPError, ValueError):
        return {}

def extract_video(s, url: str, workdir: Path, want_ocr: bool) -> Extraction:
    opts = ytdl.base_opts(workdir, s.tiktok_cookies_file) | {
        "subtitleslangs": ["all"],
        "format": "bv*[height<=720]+ba/b[height<=720]/b",
        "merge_output_format": "mp4",
    }
    info = ytdl.run(url, workdir, opts)
    ex = Extraction(author=info.get("uploader") or info.get("channel"),
                    description=info.get("description") or oembed(url).get("title"),
                    duration=info.get("duration"))
    video = next(iter(sorted(workdir.glob("*.mp4"))), None)
    if not video:
        raise TransientFailure("yt-dlp produced no video file")
    ex.text, ex.language = captions_text(workdir)
    if ex.text:
        ex.source = "captions"
    else:
        text, lang = transcribe(s, video)
        if text:
            ex.text, ex.source, ex.language = text, "whisper", lang
    if want_ocr:
        ex.onscreen = ocr_video(s, video, workdir / "frames")
        if not ex.text and ex.onscreen:
            ex.source = "ocr"
    return ex
