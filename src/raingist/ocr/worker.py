"""Child process for OCR: `python -m raingist.ocr.worker <backend> <image>...` prints a JSON list of line lists.
Apple Vision can hang forever on an internal semaphore; running it here lets the parent kill it on timeout."""
import json, sys
from pathlib import Path
from . import OCR_BACKENDS

if __name__ == "__main__":
    backend = OCR_BACKENDS[sys.argv[1]]
    print(json.dumps([backend(Path(p)) for p in sys.argv[2:]]))
