from pathlib import Path
from . import mlx_backend

# name -> fn(settings, path) -> (text, language). Linux hosting: add a faster-whisper backend here.
TRANSCRIBERS = {"mlx-whisper": mlx_backend.transcribe}

def transcribe(s, path: Path) -> tuple[str, str | None]:
    return TRANSCRIBERS[s.transcriber](s, path)
