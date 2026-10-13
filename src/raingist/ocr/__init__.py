import json, logging, re, subprocess, sys
from pathlib import Path
from . import vision_backend
from ..extract.common import TransientFailure

log = logging.getLogger(__name__)
MAX_CHARS = 8000   # an 11-image slideshow of prompts runs ~5,000 chars
MAX_FRAMES = 60
TIMEOUT_BASE, TIMEOUT_PER_IMAGE = 90, 10   # seconds; the first Vision call after install takes ~60 s

# name -> fn(image_path) -> list of text lines. Linux hosting: add a Tesseract backend here.
OCR_BACKENDS = {"vision": vision_backend.ocr_image}

def _dedupe(lines: list[str]) -> str:
    seen, out = set(), []
    for s in lines:
        key = re.sub(r"\W+", "", s.lower())
        if len(key) >= 3 and key not in seen:
            seen.add(key); out.append(s)
    return "\n".join(out)[:MAX_CHARS]

def worker_cmd(backend: str, paths: list[Path]) -> list[str]:
    return [sys.executable, "-m", "raingist.ocr.worker", backend, *map(str, paths)]

def ocr_images(s, paths: list[Path]) -> str:
    """OCR in a child process with a timeout, so a hung backend can't freeze the service."""
    paths = paths[:MAX_FRAMES]
    timeout = TIMEOUT_BASE + TIMEOUT_PER_IMAGE * len(paths)
    try:
        r = subprocess.run(worker_cmd(s.ocr_backend, paths), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise TransientFailure(f"OCR timed out after {timeout}s on {len(paths)} images") from e
    if r.returncode != 0:
        raise TransientFailure(f"OCR worker exited {r.returncode}: {r.stderr.strip()[-300:]}")
    for line in r.stderr.splitlines():   # per-image warnings logged by the backend
        log.warning("ocr worker: %s", line)
    return _dedupe([line for lines in json.loads(r.stdout) for line in lines])

def ocr_video(s, video: Path, frames_dir: Path) -> str:
    frames_dir.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-vf", "fps=0.5,scale=720:-2",
           "-frames:v", str(MAX_FRAMES), str(frames_dir / "%03d.png")]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        log.warning("ffmpeg frame extraction failed: %s", r.stderr[:300])
        return ""
    return ocr_images(s, sorted(frames_dir.glob("*.png")))
