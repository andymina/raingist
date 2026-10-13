import hashlib, json, datetime as dt
from pathlib import Path
from .extract.common import Extraction

def _path(cache_dir: Path, url: str, ocr: bool) -> Path:
    key = url.strip() + ("|ocr" if ocr else "")
    return cache_dir / f"{hashlib.sha256(key.encode()).hexdigest()}.json"

def load(cache_dir: Path, url: str, ocr: bool) -> Extraction | None:
    p = _path(cache_dir, url, ocr)
    if not p.exists():
        return None
    d = json.loads(p.read_text())
    d.pop("url", None); d.pop("extracted_at", None)
    return Extraction(**d)

def save(cache_dir: Path, url: str, ocr: bool, ex: Extraction) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    p = _path(cache_dir, url, ocr)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"url": url, "extracted_at": dt.datetime.now(dt.UTC).isoformat(), **ex.to_dict()},
                              ensure_ascii=False, indent=1))
    tmp.replace(p)
