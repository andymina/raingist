"""Organizing: file Unsorted bookmarks, create collections for new topics, merge same-purpose collections (ADR 0008)."""
import logging, re, json, datetime as dt
from zoneinfo import ZoneInfo
from .settings import Settings
from .accounts import Account, AccountError, store, access_token
from .raindrop import Raindrop
from .notify import Alerts
from . import llm
from .llm.prompt import Proposal, Assignment
from .pipeline import UNSORTED, PROVENANCE, collection_catalog, find_inbox

log = logging.getLogger(__name__)
TZ, RUN_HOUR = ZoneInfo("America/New_York"), 10   # daily runs start on the first cycle after 10:00 ET
RETRY = dt.timedelta(hours=1)                      # after a failure or a below-threshold first check
NOTE_CHARS, EXCERPT_CHARS, TITLE_MAX = 600, 300, 40

class OrganizeError(Exception): ...

def due(state: dict, now: dt.datetime) -> bool:
    """Never ran, or it is past 10:00 ET on the day after the last run (a run covers its whole ET day)."""
    if state.get("last_attempt_at") and now - dt.datetime.fromisoformat(state["last_attempt_at"]) < RETRY:
        return False
    if not state.get("last_run_at"):
        return True
    next_day = dt.datetime.fromisoformat(state["last_run_at"]).astimezone(TZ).date() + dt.timedelta(days=1)
    return now.astimezone(TZ) >= dt.datetime.combine(next_day, dt.time(RUN_HOUR), TZ)   # wall clock, so DST-safe

def norm(title: str) -> str:
    """Title identity for clash checks: letter case, emoji, spaces and punctuation ignored."""
    return re.sub(r"[^a-z0-9]", "", title.lower())

def made_by_raingist(c: dict) -> bool:
    return PROVENANCE in (c.get("description") or "")

def unsorted_items(s: Settings, rd: Raindrop) -> list[dict]:
    """Unsorted bookmarks, oldest first; raingist-skip keeps one there."""
    return [i for i in rd.search("", collection=UNSORTED, sort="created")
            if s.tag_skip not in {t.lower() for t in i.get("tags", [])}]

def flat(text: str | None, n: int) -> str:
    return " ".join((text or "").split())[:n]

def build_message(catalog: list[dict], raw: dict, items: list[dict]) -> str:
    cols = [f"{c['id']}: {c['title']} | {c['description']} | {raw.get(c['id'], {}).get('count', 0)} bookmarks"
            f" | {'raingist' if made_by_raingist(c) else 'owner'} | {'; '.join(t for t in c['samples'] if t)}"
            for c in catalog]
    entries = [f"{i['_id']}: {i.get('title', '')} | tags: {', '.join(i.get('tags', []))}"
               f" | {flat(i.get('excerpt'), EXCERPT_CHARS)} | note: {flat(i.get('note'), NOTE_CHARS)}" for i in items]
    return "\n".join(["COLLECTIONS (id: path | description | size | made by | recent bookmarks):", *(cols or ["(none)"]),
                      "UNSORTED (id: title | tags | excerpt | note):", *(entries or ["(none)"])])

def validate_proposal(p: Proposal, catalog: list[dict], collections: list[dict], unsorted_ids: set[int],
                      min_group: int) -> tuple[list[dict], dict[int, int], list[tuple[int, int]]]:
    """Returns (creates, clash moves {item: collection}, merges [(from, into)]). Invalid parts are dropped and logged."""
    by_id = {c["id"]: c for c in catalog}
    raw = {c["_id"]: c for c in collections}
    parent = {c["_id"]: (c.get("parent") or {}).get("$id") for c in collections}
    has_children = set(parent.values())
    rank = lambda cid: (not made_by_raingist(raw[cid]), raw[cid].get("count", 0))   # owner-made, then larger, survives

    merges, used = [], set()
    for m in p.merges:
        a, b = m.from_id, m.into_id
        if a not in by_id or b not in by_id or a == b or {a, b} & used or parent[a] == b or parent[b] == a:
            log.info("dropped merge %s -> %s", a, b); continue
        src, dst = (a, b) if rank(b) >= rank(a) else (b, a)
        if src in has_children or raw[src].get("collaborators"):
            log.info("dropped merge %s -> %s: source has children or is shared", src, dst); continue
        merges.append((src, dst)); used |= {a, b}
    gone = {src for src, _ in merges}

    existing = {norm(c["title"]): c["_id"] for c in collections}   # every collection, including excluded and the inbox
    creates, moves, placed = [], {}, set()
    for n in p.new_collections:
        title, key = n.title.strip()[:TITLE_MAX], norm(n.title[:TITLE_MAX])
        ids = [i for i in dict.fromkeys(n.item_ids) if i in unsorted_ids and i not in placed]
        if key in existing:   # name clash: file into that collection if it is a valid target, else drop
            cid = existing[key]
            if cid in by_id and cid not in gone:
                moves |= {i: cid for i in ids}; placed |= set(ids)
            else:
                log.info("dropped new collection %r: clashes with an untouchable collection", title)
            continue
        if not key or (n.parent_id and (n.parent_id not in by_id or n.parent_id in gone)) or len(ids) < min_group:
            log.info("dropped new collection %r (parent %s, %d items)", title, n.parent_id, len(ids)); continue
        description = f"{n.description.replace(PROVENANCE, '').strip()} {PROVENANCE}".strip()
        creates.append({"title": title, "description": description, "parent": n.parent_id, "item_ids": ids})
        existing[key] = None; placed |= set(ids)
    return creates, moves, merges

def validate_assignment(a: Assignment, targets: set[int], remaining: set[int]) -> dict[int, int]:
    moves: dict[int, int] = {}
    for m in a.moves:
        if m.item_id in remaining and m.item_id not in moves and m.collection_id in targets:
            moves[m.item_id] = m.collection_id
    return moves

class Journal:
    """Every applied step, rewritten after each one so a partial run is recorded too."""
    def __init__(self, path, dry_run: bool):
        self.path, self.dry_run, self.steps = path, dry_run, []

    def add(self, step: str, **data) -> None:
        self.steps.append({"step": step, **data})
        if not self.dry_run:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.steps, indent=1, ensure_ascii=False))

def _by_dest(moves: dict[int, int]) -> dict[int, list[int]]:
    groups: dict[int, list[int]] = {}
    for item, dest in moves.items():
        groups.setdefault(dest, []).append(item)
    return groups

def run_account(s: Settings, acct: Account, alerts: Alerts, dry_run: bool = False, force: bool = False) -> dict | None:
    """One Organizing run for one account, if due. Returns counts, or None when it did not run."""
    state_dir = s.state_dir / str(acct.id)
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / "organize.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    now = dt.datetime.now(dt.UTC)
    if not force and not due(state, now):
        return None
    def save(**kw):
        if not dry_run:
            state.update(kw); state_path.write_text(json.dumps(state, indent=1))
    save(last_attempt_at=now.isoformat())

    rd = Raindrop(access_token(s, acct))
    collections = rd.collections()
    inbox = find_inbox(collections)
    items = unsorted_items(s, rd)
    if not force and not state.get("last_run_at") and len(items) < s.organize_first_run:
        log.info("[%s] organize: %d unsorted, first run waits for %d", acct.id, len(items), s.organize_first_run)
        return None
    items = items[: s.organize_max_items]
    raw = {c["_id"]: c for c in collections}
    catalog = collection_catalog(rd, collections, inbox)
    journal = Journal(state_dir / "organize" / f"{now:%Y%m%dT%H%M%SZ}.json", dry_run)

    def move(from_collection: int, ids: list[int], to: int) -> None:
        if dry_run:
            log.info("[%s] DRY-RUN PUT /raindrops/%s move %d to %s: %s", acct.id, from_collection, len(ids), to, ids)
        elif rd.move_many(from_collection, ids, to) != len(ids):
            log.warning("[%s] move of %d bookmarks to %s reported a different count", acct.id, len(ids), to)

    # 1. assign first, so propose only sees what no existing collection takes (each bookmark reaches the LLM once,
    #    plus again only if it is left over)
    moves: dict[int, int] = {}
    if catalog and items:
        assignment, model = llm.assign(s, build_message(catalog, raw, items))
        moves = validate_assignment(assignment, {c["id"] for c in catalog}, {i["_id"] for i in items})
    leftovers = [i for i in items if i["_id"] not in moves]
    if len(leftovers) < s.organize_min_group:
        leftovers = []   # too few to form a new collection; propose then only looks at merges
    proposal = Proposal()
    if leftovers or len(catalog) > 1:
        proposal, model = llm.propose(s, build_message(catalog, raw, leftovers))
        log.info("[%s] organize proposal from %s: %s", acct.id, model, proposal.model_dump_json())
    creates, clash_moves, merges = validate_proposal(proposal, catalog, collections, {i["_id"] for i in leftovers},
                                                     s.organize_min_group)
    survivor = dict(merges)
    moves = {i: survivor.get(c, c) for i, c in moves.items()} | clash_moves   # filed into a merged-away one: follow it
    created, moved, merged = [], 0, []

    for src, dst in merges:
        members = [i["_id"] for i in rd.search("", max_pages=100, collection=src)]
        if members:
            move(src, members, dst)
        if not dry_run:
            if rd.search("", max_pages=1, collection=src):
                raise OrganizeError(f"collection {src} still holds bookmarks after the merge; not deleted")
            rd.delete_collection(src)
        else:
            log.info("[%s] DRY-RUN DELETE /collection/%s", acct.id, src)
        journal.add("merged", into=dst, moved=members, removed=raw[src])
        merged.append(f"{raw[src]['title']} → {raw[dst]['title']}")

    for dest, ids in _by_dest(moves).items():
        move(UNSORTED, ids, dest); moved += len(ids)
        journal.add("moved", to=dest, item_ids=ids)

    for n in creates:
        if dry_run:
            cid = None
            log.info("[%s] DRY-RUN POST /collection %s", acct.id, {k: n[k] for k in ("title", "description", "parent")})
        else:
            cid = rd.create_collection(n["title"], n["description"], n["parent"])["_id"]
        journal.add("created", id=cid, **n)
        move(UNSORTED, n["item_ids"], cid)
        created.append(n["title"]); moved += len(n["item_ids"])

    counts = {"created": len(created), "moved": moved, "merged": len(merged)}
    log.info("[%s] organize complete: %s", acct.id, counts)
    save(last_run_at=now.isoformat(), last_counts=counts)
    if (created or moved or merged) and not dry_run:
        parts = [f"{len(created)} new ({', '.join(created)})" if created else "", f"{moved} moved" if moved else "",
                 f"merged {', '.join(merged)}" if merged else ""]
        alerts.send(f"organized:{acct.id}:{now:%Y%m%d%H%M}", f"[{acct.name}] organized: {', '.join(p for p in parts if p)}")
    return counts

def run_due(s: Settings, alerts: Alerts, only: int | None = None, dry_run: bool = False, force: bool = False) -> dict:
    """Organize every enabled account (or just `only`) that is due. One account's failure never blocks the others."""
    results = {}
    for aid in ([only] if only else store(s).ids(s)):
        try:
            acct = store(s).load(s, aid)
        except AccountError as e:
            alerts.send(f"account-file:{aid}", str(e)); continue
        if not acct.enabled:
            continue
        try:
            results[aid] = run_account(s, acct, alerts, dry_run=dry_run, force=force)
        except Exception as e:   # partial runs stay as applied (see the journal); retried after RETRY
            log.exception("[%s] organize failed", aid)
            alerts.send(f"organize:{aid}", f"[{acct.name}] organize failed: {e}"[:300])
    return results
