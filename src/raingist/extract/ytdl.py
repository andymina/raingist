import shutil
from pathlib import Path
import yt_dlp
from yt_dlp.utils import DownloadError
from .common import Extraction, TransientFailure, classify_ytdlp_error
from ..subtitles import captions_text
from ..transcribe import transcribe
from ..ocr import ocr_video

def base_opts(workdir: Path, cookiefile: Path | None = None) -> dict:
    opts = {
        "quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True,
        "socket_timeout": 30, "retries": 2,
        "outtmpl": str(workdir / "%(id)s.%(ext)s"),
        "writesubtitles": True, "writeautomaticsub": True,
        "subtitlesformat": "vtt/srt/best",
    }
    if cookiefile:
        opts["cookiefile"] = str(cookiefile)
    return opts

def run(url: str, workdir: Path, opts: dict) -> dict:
    """Raises PermanentFailure / TransientFailure."""
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.sanitize_info(ydl.extract_info(url, download=not opts.get("skip_download", False)))
    except DownloadError as e:
        raise classify_ytdlp_error(str(e)) from e

def cleanup(workdir: Path) -> None:
    shutil.rmtree(workdir, ignore_errors=True)

def extract_video(s, url: str, workdir: Path, want_ocr: bool, cookiefile: Path | None) -> tuple[Extraction, dict]:
    """Download with yt-dlp, then captions, else Whisper; OCR if asked. Callers map author fields from the info dict."""
    opts = base_opts(workdir, cookiefile) | {
        "subtitleslangs": ["all"],
        "format": "bv*[height<=720]+ba/b[height<=720]/b",
        "merge_output_format": "mp4",
    }
    info = run(url, workdir, opts)
    ex = Extraction(description=info.get("description"), duration=info.get("duration"))
    video = next(iter(sorted(workdir.glob("*.mp4"))), None)
    if not video:
        raise TransientFailure("yt-dlp produced no video file")
    ex.text, ex.language = captions_text(workdir)
    if ex.text:
        ex.source = "captions"
    elif info.get("acodec") != "none":   # silent reels exist; Whisper crashes on a file with no audio stream
        text, lang = transcribe(s, video)
        if text:
            ex.text, ex.source, ex.language = text, "whisper", lang
    if want_ocr:
        ex.onscreen = ocr_video(s, video, workdir / "frames")
        if not ex.text and ex.onscreen:
            ex.source = "ocr"
    return ex, info
