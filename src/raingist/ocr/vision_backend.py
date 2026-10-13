import logging
from pathlib import Path
from ocrmac import ocrmac

log = logging.getLogger(__name__)
MIN_CONF = 0.5

def ocr_image(path: Path) -> list[str]:
    try:
        items = ocrmac.OCR(str(path), recognition_level="accurate", language_preference=["en-US"],
                           framework="vision").recognize()
    except Exception as e:   # Vision raises opaque ObjC errors; skip this image, logged
        log.warning("ocr failed on %s: %s", path.name, e)
        return []
    return [t.strip() for t, conf, _ in items if conf >= MIN_CONF and len(t.strip()) >= 3]
