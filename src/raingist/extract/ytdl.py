import shutil
from pathlib import Path
import yt_dlp
from yt_dlp.utils import DownloadError
from .common import classify_ytdlp_error

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
