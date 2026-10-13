import sys
from pathlib import Path
import pytest
from PIL import Image, ImageDraw, ImageFont
import raingist.ocr as ocr
from raingist.extract.common import TransientFailure

def test_ocr_images_in_worker(settings, tmp_path):
    img = Image.new("RGB", (900, 200), "white")
    ImageDraw.Draw(img).text((40, 60), "Budget rule: save 20 percent", fill="black",
                             font=ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 48))
    img.save(tmp_path / "a.jpg")
    assert ocr.ocr_images(settings, [tmp_path / "a.jpg"]) == "Budget rule: save 20 percent"

def test_ocr_timeout_is_transient(settings, monkeypatch):
    monkeypatch.setattr(ocr, "worker_cmd", lambda b, p: [sys.executable, "-c", "import time; time.sleep(30)"])
    monkeypatch.setattr(ocr, "TIMEOUT_BASE", 1)
    with pytest.raises(TransientFailure, match="timed out"):
        ocr.ocr_images(settings, [Path("x.jpg")])

def test_ocr_worker_crash_is_transient(settings, monkeypatch):
    monkeypatch.setattr(ocr, "worker_cmd", lambda b, p: [sys.executable, "-c", "raise SystemExit('boom')"])
    with pytest.raises(TransientFailure, match="boom"):
        ocr.ocr_images(settings, [Path("x.jpg")])
