import re, json
from pathlib import Path

_TS = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?[.,]\d{3}\s+-->\s+")
_TAG = re.compile(r"<[^>]+>")

def parse_subtitle_file(path: Path) -> str:
    """SRT/VTT/TikTok-json -> plain text, consecutive duplicate lines collapsed."""
    raw = path.read_text(encoding="utf-8", errors="ignore")
    if path.suffix == ".json":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return ""
        lines = [u.get("text", "") for u in (data.get("utterances") or data.get("captions") or [])]
    else:
        lines = []
        for line in raw.splitlines():
            s = _TAG.sub("", line).strip()
            if not s or s.isdigit() or s.startswith(("WEBVTT", "NOTE", "Kind:", "Language:")) or _TS.match(s):
                continue
            lines.append(s)
    out: list[str] = []
    for s in lines:
        if not out or s != out[-1]:
            out.append(s)
    return " ".join(out).strip()

def pick_subtitle_file(workdir: Path) -> Path | None:
    files = [p for p in workdir.iterdir() if p.suffix in (".vtt", ".srt", ".json") and p.stem != "info"]
    if not files:
        return None
    return min(files, key=lambda p: (0 if ".en" in p.name.lower() else 1, {".vtt": 0, ".srt": 1, ".json": 2}[p.suffix]))

def captions_text(workdir: Path) -> tuple[str, str | None]:
    """(text, language) from the best subtitle file, or ('', None) if fewer than 5 words."""
    sub = pick_subtitle_file(workdir)
    if not sub:
        return "", None
    text = parse_subtitle_file(sub)
    if len(text.split()) < 5:
        return "", None
    return text, (sub.suffixes[0].lstrip(".") if len(sub.suffixes) > 1 else None)
