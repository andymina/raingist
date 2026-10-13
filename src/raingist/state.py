import json, fcntl, datetime as dt
from pathlib import Path

class Busy(Exception): ...

class Attempts:
    def __init__(self, path: Path, backoff: tuple[int, ...]):
        self.path, self.backoff = path, backoff
        self.data = json.loads(path.read_text()) if path.exists() else {}

    def _save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1)); tmp.replace(self.path)

    @property
    def max_attempts(self) -> int:
        return len(self.backoff)

    def due(self, rid: int) -> bool:
        e = self.data.get(str(rid))
        return not e or dt.datetime.fromisoformat(e["next_retry_at"]) <= dt.datetime.now(dt.UTC)

    def record_failure(self, rid: int, error: str) -> int:
        n = self.data.get(str(rid), {"attempts": 0})["attempts"] + 1
        delay = self.backoff[min(n, self.max_attempts) - 1]
        self.data[str(rid)] = {"attempts": n, "last_error": error[:300],
                               "next_retry_at": (dt.datetime.now(dt.UTC) + dt.timedelta(seconds=delay)).isoformat()}
        self._save()
        return n

    def clear(self, rid: int) -> None:
        if self.data.pop(str(rid), None) is not None:
            self._save()

class RunLock:
    def __init__(self, path: Path):
        self.f = open(path, "w")

    def __enter__(self):
        try:
            fcntl.flock(self.f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.f.close()
            raise Busy("another cycle is in progress")
        return self

    def __exit__(self, *a):
        fcntl.flock(self.f, fcntl.LOCK_UN); self.f.close()
