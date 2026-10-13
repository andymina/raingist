import logging, time
import httpx

log = logging.getLogger(__name__)
THROTTLE = 6 * 3600

class Alerts:
    """POST alerts to the ntfy URL. Throttled per key in memory (serve is long-lived)."""
    def __init__(self, url: str | None):
        self.url, self.sent = url, {}

    def send(self, key: str, message: str) -> None:
        log.error("ALERT [%s] %s", key, message)
        if not self.url or time.time() - self.sent.get(key, 0) < THROTTLE:
            return
        try:
            httpx.post(self.url, content=message.encode(), headers={"Title": "raingist"}, timeout=10)
        except httpx.HTTPError as e:
            log.error("alert delivery failed: %s", e); return
        self.sent[key] = time.time()
