import functools, logging
from pathlib import Path
import mlx_whisper
from huggingface_hub import snapshot_download

log = logging.getLogger(__name__)
MAX_SECONDS = 600

@functools.cache
def model_path(repo: str, cache_dir: str) -> str:
    """Download (once) into DATA_DIR/models on T7 and return the local path; never the home-dir cache."""
    return snapshot_download(repo, cache_dir=cache_dir)

def transcribe(s, path: Path) -> tuple[str, str | None]:
    r = mlx_whisper.transcribe(str(path), path_or_hf_repo=model_path(s.whisper_model, str(s.model_dir)),
                               condition_on_previous_text=False, no_speech_threshold=0.6,
                               clip_timestamps=f"0,{MAX_SECONDS}")
    text = " ".join(seg["text"].strip() for seg in r.get("segments", []) if seg.get("no_speech_prob", 0) < 0.6).strip()
    if len(text.split()) < 8:
        log.info("whisper: no speech detected")
        return "", None
    return text, r.get("language")
