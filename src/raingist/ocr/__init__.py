import logging, re, subprocess
from pathlib import Path
from . import vision_backend

log = logging.getLogger(__name__)
MAX_CHARS = 8000   # an 11-image slideshow of prompts runs ~5,000 chars
MAX_FRAMES = 60

# name -> fn(image_path) -> list of text lines. Linux hosting: add a Tesseract backend here.
OCR_BACKENDS = {"vision": vision_backend.ocr_image}

def _dedupe(lines: list[str]) -> str:
    seen, out = set(), []
    for s in lines:
        key = re.sub(r"\W+", "", s.lower())
        if len(key) >= 3 and key not in seen:
            seen.add(key); out.append(s)
    return "\n".join(out)[:MAX_CHARS]

def ocr_images(s, paths: list[Path]) -> str:
    backend = OCR_BACKENDS[s.ocr_backend]
    return _dedupe([line for p in paths[:MAX_FRAMES] for line in backend(p)])

def ocr_video(s, video: Path, frames_dir: Path) -> str:
    frames_dir.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-vf", "fps=0.5,scale=720:-2",
           "-frames:v", str(MAX_FRAMES), str(frames_dir / "%03d.png")]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        log.warning("ffmpeg frame extraction failed: %s", r.stderr[:300])
        return ""
    return ocr_images(s, sorted(frames_dir.glob("*.png")))
