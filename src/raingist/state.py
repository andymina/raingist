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

class Placements:
    """Collections the service filed each bookmark into (routing and Organizing), {bookmark id: [collection ids]}.
    A bookmark found outside all of them was moved there by the owner, so they stay off limits for it.
    `titles` caches the titles of bookmarks the owner moved out, shown as "not here" examples."""
    def __init__(self, path: Path):
        self.path = path
        raw = json.loads(path.read_text()) if path.exists() else {}
        self.data: dict[str, list[int]] = raw.get("filed", {})
        self.titles: dict[str, str] = raw.get("titles", {})

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"filed": self.data, "titles": self.titles}, indent=1, ensure_ascii=False))
        tmp.replace(self.path)

    def remember_title(self, rid: int, title: str) -> None:
        self.titles[str(rid)] = title
        self._save()

    def record(self, ids, collection: int) -> None:
        for rid in ids:
            cids = self.data.setdefault(str(rid), [])
            if collection not in cids:
                cids.append(collection)
        self._save()

    def filed_into(self, rid: int) -> set[int]:
        return set(self.data.get(str(rid), []))

    def placed_by_service(self, collection: int) -> set[int]:
        """Bookmarks the service filed into `collection` (some may have been moved out since)."""
        return {int(rid) for rid, cids in self.data.items() if collection in cids}

def load_placements(state_dir: Path) -> Placements:
    """The account's placements; the first load backfills them from the Organizing journals."""
    p = Placements(state_dir / "placements.json")
    if p.path.exists():
        return p
    for journal in sorted((state_dir / "organize").glob("*.json")):
        for step in json.loads(journal.read_text()):
            if step["step"] == "moved":
                p.record(step["item_ids"], step["to"])
            elif step["step"] == "created" and step.get("id"):
                p.record(step["item_ids"], step["id"])
            elif step["step"] == "merged":
                p.record(step["moved"], step["into"])
    p._save()
    return p

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
