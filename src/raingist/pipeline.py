import logging, datetime as dt, json, uuid
from .settings import Settings
from .accounts import Account, AccountError, store, access_token
from .raindrop import Raindrop, RaindropError
from .extract import EXTRACTORS, detect
from .extract.common import Extraction, PermanentFailure, TransientFailure
from .extract import ytdl
from . import cache, writeback
from .llm import summarize
from .state import Attempts, Placements, load_placements
from .notify import Alerts

log = logging.getLogger(__name__)
SYSTEMIC_STREAK = 3
INBOX_TITLE = "raingist"       # each account's processing inbox, found by name
UNSORTED = -1                  # Raindrop's "Unsorted" collection
MAX_COLLECTIONS = 50
EXAMPLES, NOT_HERE, MEMBER_PAGES = 15, 5, 4   # per collection profile; members are read 50 a page
EXCLUDE_MARK = "#raingist-exclude"         # in a collection's description: the service never touches it
PROVENANCE = "(created by raingist)"       # ends the description of collections Organizing created

def today() -> str:
    return dt.date.today().isoformat()

def extract(s: Settings, ctype: str, item: dict, want_ocr: bool, cache_dir=None) -> Extraction:
    url = item["link"]
    cache_dir = cache_dir or s.cache_dir
    cached = cache.load(cache_dir, url, want_ocr)
    if cached:
        log.info("cache hit for %s", url)
        return cached
    workdir = s.work_dir / uuid.uuid4().hex
    try:
        ex = EXTRACTORS[ctype][1](s, item, workdir, want_ocr)
    finally:
        ytdl.cleanup(workdir)
    if ex.source != "metadata":
        cache.save(cache_dir, url, want_ocr, ex)
    return ex

class InboxMissing(Exception): ...

def find_inbox(collections: list[dict]) -> int:
    """Id of the account's one collection named INBOX_TITLE (any letter case)."""
    ids = [c["_id"] for c in collections if c["title"].strip().lower() == INBOX_TITLE]
    if len(ids) != 1:
        raise InboxMissing(f"expected exactly one collection named '{INBOX_TITLE}', found {len(ids)}")
    return ids[0]

def blocked(s: Settings, item: dict) -> bool:
    """raingist-failed / raingist-skip keep a bookmark waiting in the inbox; raingist-redo overrides them."""
    tags = {t.lower() for t in item.get("tags", [])}
    return s.tag_redo not in tags and bool(tags & s.state_tags)

def pending_items(s: Settings, rd: Raindrop, inbox: int) -> list[dict]:
    """Supported bookmarks in the inbox, any age: dragging a bookmark in queues it."""
    return [i for i in rd.search("", collection=inbox) if detect(s, i.get("link", "")) and not blocked(s, i)]

def excluded(c: dict) -> bool:
    return EXCLUDE_MARK in (c.get("description") or "").lower()

def spread(items: list, n: int) -> list:
    """Up to n items evenly spaced across the list (newest to oldest), so a profile is not just the latest additions."""
    if len(items) <= n:
        return items
    return [items[round(i * (len(items) - 1) / (n - 1))] for i in range(n)]

def example(item: dict) -> str:
    title, summary = (item.get("title") or "").strip(), writeback.summary_line(item.get("note"))
    return f"{title} - {summary}"[:220] if summary else title[:220]

def moved_out_titles(rd: Raindrop, placements: Placements, ids: list[int]) -> list[str]:
    """Titles of bookmarks the owner moved out of a collection, cached; a deleted bookmark is skipped."""
    titles = []
    for rid in ids:
        title = placements.titles.get(str(rid))
        if title is None:
            try:
                title = rd.get(rid).get("title") or ""
            except RaindropError:
                continue
            placements.remember_title(rid, title)
        if title:
            titles.append(title)
    return titles

def collection_catalog(rd: Raindrop, collections: list[dict], inbox: int,
                       placements: Placements | None = None) -> list[dict]:
    """Routing candidates (every collection except the inbox and excluded ones), each with a profile for the LLM:
    path, description (the scope, which decides), up to EXAMPLES bookmarks spread across the collection,
    and "not here" bookmarks the service filed there that the owner moved out. In an owner's collection only bookmarks
    the service did not file count as evidence, so a wrong filing never pulls in more like it. `members` (the bookmarks
    read, newest first) is for Organizing and never sent to the LLM."""
    cols = [c for c in collections if c["_id"] != inbox and not excluded(c)]
    by_id = {c["_id"]: c for c in cols}
    def path(c):
        parent = by_id.get((c.get("parent") or {}).get("$id"))
        return f"{path(parent)} / {c['title']}" if parent else c["title"]
    catalog = []
    for c in cols[:MAX_COLLECTIONS]:
        description = c.get("description") or ""
        made_by = "raingist" if PROVENANCE in description else "owner"
        members = rd.search("", max_pages=MEMBER_PAGES, collection=c["_id"])
        placed = placements.placed_by_service(c["_id"]) if placements else set()
        evidence = members if made_by == "raingist" else [m for m in members if m["_id"] not in placed]
        gone = sorted(placed - {m["_id"] for m in members}, reverse=True)[:NOT_HERE]   # newest ids first
        catalog.append({"id": c["_id"], "title": path(c), "description": description, "made_by": made_by,
                        "size": c.get("count", len(members)),
                        "examples": [example(m) for m in spread(evidence, EXAMPLES)],
                        "not_here": moved_out_titles(rd, placements, gone) if placements else [],
                        "members": members})
    return catalog

def route(summary, catalog: list[dict]) -> int:
    """The chosen collection when it is a candidate and the model is highly confident it fits, else Unsorted."""
    if summary.collection_id in {c["id"] for c in catalog} and summary.collection_confidence == "high":
        return summary.collection_id
    return UNSORTED

def process_item(s: Settings, acct: Account, rd: Raindrop, attempts: Attempts, rid: int, existing_tags: list[str],
                 inbox: int, catalog: list[dict], dry_run: bool = False, placements: Placements | None = None) -> str:
    """Returns one of: done, failed, retry, noop. Done = enriched and routed out of the inbox in one PUT."""
    item = rd.get(rid)   # fresh, right before writing
    tags = {t.lower() for t in item.get("tags", [])}
    redo = s.tag_redo in tags
    ctype = detect(s, item.get("link", ""))
    if ctype is None or item.get("collection", {}).get("$id") != inbox or blocked(s, item):
        return "noop"
    note = writeback.strip_ai_block(item.get("note", "")) if redo else item.get("note", "")
    owner_note, kept = writeback.split_note(note)   # kept: marked spans cut, applied only on success
    if owner_note:
        log.info("[%s] item %s: forwarding %d chars of owner note", acct.id, rid, len(owner_note))
    try:
        ex = extract(s, ctype, item, want_ocr=s.tag_ocr in tags)
        summary, model = summarize(s, item, ctype, ex, existing_tags, owner_note, catalog)
    except PermanentFailure as e:
        attempts.clear(rid)
        return _fail(s, acct, rd, item, writeback.merge_failure(note, str(e), today()), dry_run)
    except TransientFailure as e:
        n = attempts.record_failure(rid, str(e))
        log.warning("[%s] item %s transient failure %d/%d: %s", acct.id, rid, n, attempts.max_attempts, e)
        if n < attempts.max_attempts:
            return "retry"
        attempts.clear(rid)
        return _fail(s, acct, rd, item, writeback.merge_failure(note, f"gave up after {n} attempts: {e}", today()), dry_run)
    chosen = writeback.choose_tags(summary.tags, existing_tags, s.reserved_tags)
    log.info("[%s] item %s summarized from %s by %s (confidence %s, lang %s, tags %s)",
             acct.id, rid, ex.source, model, summary.confidence, summary.language, chosen)
    dest = route(summary, catalog)
    fields = {"note": writeback.merge_note(kept, writeback.build_block(summary, writeback.creator_label(ex.creator, ex.author))),
              "tags": writeback.strip_reserved(writeback.merge_tags(item.get("tags", []), chosen)),
              "collection": {"$id": dest}}
    if writeback.is_placeholder_title(item.get("title"), item["link"]) and summary.title.strip():
        fields["title"] = summary.title.strip()[:1000]
    log.info("[%s] item %s -> collection %s (picked %s, %s: %s)", acct.id, rid,
             next((c["title"] for c in catalog if c["id"] == dest), "Unsorted"), summary.collection_id,
             summary.collection_confidence, summary.collection_reason)
    attempts.clear(rid)
    _put(acct, rd, item, dry_run, fields)
    if placements is not None and dest != UNSORTED and not dry_run:
        placements.record([rid], dest)
    return "done"

def _fail(s: Settings, acct: Account, rd: Raindrop, item: dict, note: str, dry_run: bool) -> str:
    """Stays in the inbox, tagged raingist-failed (redo dropped so it doesn't loop), with the reason in the note."""
    tags = [t for t in item.get("tags", []) if t.lower() != s.tag_redo]
    _put(acct, rd, item, dry_run, {"note": note, "tags": writeback.merge_tags(tags, [s.tag_failed])})
    return "failed"

def _put(acct: Account, rd: Raindrop, item: dict, dry_run: bool, fields: dict) -> None:
    if dry_run:
        log.info("[%s] DRY-RUN PUT /raindrop/%s %s", acct.id, item["_id"], fields)
    else:
        rd.update(item["_id"], **fields)

def run_account_cycle(s: Settings, acct: Account, alerts: Alerts, dry_run: bool = False, limit: int | None = None) -> dict:
    rd = Raindrop(access_token(s, acct))
    state_dir = s.state_dir / str(acct.id)
    state_dir.mkdir(parents=True, exist_ok=True)
    attempts = Attempts(state_dir / "attempts.json", s.retry_backoff)
    collections = rd.collections()
    inbox = find_inbox(collections)
    pending = [i for i in pending_items(s, rd, inbox) if attempts.due(i["_id"])]
    pending = pending[: limit or s.max_items_per_account]
    existing_tags = rd.tags() if pending else []
    placements = load_placements(state_dir)
    catalog = collection_catalog(rd, collections, inbox, placements) if pending else []
    counts: dict[str, int] = {}
    streak, last_error = 0, ""
    for item in pending:
        rid = item["_id"]
        try:
            r = process_item(s, acct, rd, attempts, rid, existing_tags, inbox, catalog, dry_run=dry_run,
                             placements=placements)
        except Exception as e:   # one bad item must not stop the rest; logged with traceback, alerted via streak
            log.exception("[%s] item %s crashed: %s", acct.id, rid, e)
            r, last_error = "crash", str(e)
        if r == "retry":
            last_error = attempts.data.get(str(rid), {}).get("last_error", "")
        if r == "failed":
            alerts.send(f"failed:{acct.id}:{rid}", f"[{acct.name}] bookmark marked {s.tag_failed}: {item.get('link')}")
        streak = streak + 1 if r in ("retry", "crash") else 0
        if streak == SYSTEMIC_STREAK:
            alerts.send(f"systemic:{acct.id}", f"[{acct.name}] {streak} bookmarks in a row failed: {last_error[:300]}")
        counts[r] = counts.get(r, 0) + 1
        log.info("[%s] item %s -> %s", acct.id, rid, r)
    log.info("[%s] cycle complete: %s", acct.id, counts)
    if not dry_run:
        status = {"last_cycle_at": dt.datetime.now(dt.UTC).isoformat(), "counts": counts, "last_error": last_error}
        (state_dir / "status.json").write_text(json.dumps(status, indent=1))
    return counts

def run_cycle(s: Settings, alerts: Alerts, only: int | None = None, dry_run: bool = False, limit: int | None = None) -> dict:
    """Process every enabled account (or just `only`). One account's failure never blocks the others."""
    results = {}
    for aid in ([only] if only else store(s).ids(s)):
        try:
            acct = store(s).load(s, aid)
        except AccountError as e:
            alerts.send(f"account-file:{aid}", str(e)); continue
        if not acct.enabled:
            log.info("[%s] disabled, skipping", aid); continue
        try:
            results[aid] = run_account_cycle(s, acct, alerts, dry_run=dry_run, limit=limit)
        except Exception as e:   # e.g. revoked grant; logged with traceback and alerted
            log.exception("[%s] account cycle failed", aid)
            alerts.send(f"account:{aid}", f"[{acct.name}] cycle failed (reconnect if 401): {e}"[:300])
    return results
