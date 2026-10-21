from dataclasses import dataclass, asdict

class PermanentFailure(Exception): ...
class TransientFailure(Exception): ...

@dataclass
class Extraction:
    text: str = ""            # transcript
    onscreen: str = ""        # OCR text
    source: str = "metadata"  # captions | whisper | ocr | metadata
    format: str = "video"     # video | slideshow
    language: str | None = None
    author: str | None = None      # @handle
    creator: str | None = None     # display name
    description: str | None = None
    duration: float | None = None
    sound: str | None = None  # "<track> by <artists>" when the audio is a reused sound, not the creator's own

    def to_dict(self):
        return asdict(self)

PERMANENT_MARKERS = ("private", "unavailable", "not available", "removed", "deleted", "does not exist",
                     "log in", "login", "sign in", "not comfortable", "age-restricted", "geo", "region", "404")

def classify_ytdlp_error(msg: str) -> Exception:
    m = msg.lower()
    if ("ip" in m and "block" in m) or "rate-limit" in m or "rate limit" in m:   # Instagram's says "login page"
        return TransientFailure(msg[:300])
    if any(k in m for k in PERMANENT_MARKERS):
        return PermanentFailure(msg[:300])
    return TransientFailure(msg[:300])   # usually extractor breakage; retry
