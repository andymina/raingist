import logging, datetime as dt, json, uuid
from .settings import Settings
from .accounts import Account, AccountError, store, access_token
from .raindrop import Raindrop
from .extract import EXTRACTORS, detect
from .extract.common import Extraction, PermanentFailure, TransientFailure
from .extract import ytdl
from . import cache, writeback
from .llm import summarize
from .state import Attempts
from .notify import Alerts

log = logging.getLogger(__name__)
SYSTEMIC_STREAK = 3

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

def in_scope(acct: Account, item: dict) -> bool:
    cid = item.get("collection", {}).get("$id")
    if acct.include_collections and cid not in acct.include_collections:
        return False
    return cid not in acct.exclude_collections

def process_item(s: Settings, acct: Account, rd: Raindrop, attempts: Attempts, rid: int,
                 existing_tags: list[str], dry_run: bool = False) -> str:
    """Returns one of: done, failed, retry, noop."""
    item = rd.get(rid)   # fresh, right before writing
    tags = {t.lower() for t in item.get("tags", [])}
    redo = s.tag_redo in tags
    ctype = detect(s, item.get("link", ""))
    if ctype is None or not in_scope(acct, item) or (not redo and tags & s.state_tags):
        return "noop"
    note = writeback.strip_ai_block(item.get("note", "")) if redo else item.get("note", "")
    drop = s.state_tags | {s.tag_redo}
    owner_note = writeback.owner_note(note)
    if owner_note:
        log.info("[%s] item %s: forwarding %d chars of owner note", acct.id, rid, len(owner_note))
    try:
        ex = extract(s, ctype, item, want_ocr=s.tag_ocr in tags)
        summary, model = summarize(s, item, ctype, ex, existing_tags, owner_note)
    except PermanentFailure as e:
        attempts.clear(rid)
        return _finish(s, acct, rd, item, s.tag_failed, drop, dry_run, note=writeback.merge_failure(note, str(e), today()))
    except TransientFailure as e:
        n = attempts.record_failure(rid, str(e))
        log.warning("[%s] item %s transient failure %d/%d: %s", acct.id, rid, n, attempts.max_attempts, e)
        if n < attempts.max_attempts:
            return "retry"
        attempts.clear(rid)
        return _finish(s, acct, rd, item, s.tag_failed, drop, dry_run,
                       note=writeback.merge_failure(note, f"gave up after {n} attempts: {e}", today()))
    chosen = writeback.choose_tags(summary.tags, existing_tags, s.reserved_tags)
    block = writeback.build_block(summary)
    log.info("[%s] item %s summarized from %s by %s (confidence %s, lang %s)",
             acct.id, rid, ex.source, model, summary.confidence, summary.language)
    fields = {"note": writeback.merge_note(note, block),
              "tags": writeback.merge_tags(item.get("tags", []), chosen, s.tag_done, drop)}
    if writeback.is_placeholder_title(item.get("title"), item["link"]) and summary.title.strip():
        fields["title"] = summary.title.strip()[:1000]
    attempts.clear(rid)
    return _finish(s, acct, rd, item, s.tag_done, drop, dry_run, **fields)

def _finish(s: Settings, acct: Account, rd: Raindrop, item: dict, state_tag: str, drop: frozenset[str],
            dry_run: bool, **fields) -> str:
    fields.setdefault("tags", writeback.merge_tags(item.get("tags", []), [], state_tag, drop))
    if dry_run:
        log.info("[%s] DRY-RUN PUT /raindrop/%s %s", acct.id, item["_id"], fields)
    else:
        rd.update(item["_id"], **fields)
    return {s.tag_done: "done", s.tag_failed: "failed"}[state_tag]

def run_account_cycle(s: Settings, acct: Account, alerts: Alerts, dry_run: bool = False, limit: int | None = None) -> dict:
    rd = Raindrop(access_token(s, acct))
    state_dir = s.state_dir / str(acct.id)
    state_dir.mkdir(parents=True, exist_ok=True)
    attempts = Attempts(state_dir / "attempts.json", s.retry_backoff)
    pending = [i for i in rd.list_pending(s.lookback_days, s.state_tags, s.tag_redo)
               if detect(s, i.get("link", "")) and in_scope(acct, i) and attempts.due(i["_id"])]
    pending = pending[: limit or s.max_items_per_account]
    existing_tags = rd.tags() if pending else []
    counts: dict[str, int] = {}
    streak, last_error = 0, ""
    for item in pending:
        rid = item["_id"]
        try:
            r = process_item(s, acct, rd, attempts, rid, existing_tags, dry_run=dry_run)
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
