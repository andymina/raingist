import argparse, json, logging, sys, time, webbrowser
from logging.handlers import RotatingFileHandler
from .settings import load_settings, data_ready
from .accounts import AccountError, store, connect, access_token
from .raindrop import Raindrop, authorize_url
from .oauth_callback import wait_for_code
from .state import Attempts, RunLock, Busy
from .pipeline import run_cycle, process_item, extract
from .extract import detect
from .llm import summarize
from .notify import Alerts

log = logging.getLogger("raingist")
FMT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_file_handler: RotatingFileHandler | None = None

def attach_file_log(s) -> None:
    """Log to DATA_DIR/logs on T7 once it is mounted; reattach if T7 was unplugged and came back."""
    global _file_handler
    path = s.log_dir / "raingist.log"
    if _file_handler and path.parent.exists():
        return
    if _file_handler:
        logging.getLogger().removeHandler(_file_handler); _file_handler.close()
    _file_handler = RotatingFileHandler(path, maxBytes=10_000_000, backupCount=3)
    _file_handler.setFormatter(logging.Formatter(FMT))
    logging.getLogger().addHandler(_file_handler)

def require_data(s):
    if not data_ready(s):
        sys.stderr.write(f"abort: {s.data_dir} is not the mounted data volume (missing .raingist)\n")
        sys.exit(2)
    attach_file_log(s)

def load_account_or_exit(s, aid):
    try:
        return store(s).load(s, aid)
    except AccountError as e:
        sys.exit(f"error: {e}")

def cmd_serve(s, args):
    alerts = Alerts(s.notify_url)
    log.info("serving every %ss (extractors: %s)", s.poll_interval, ",".join(s.enabled_extractors))
    while True:
        start = time.monotonic()
        if not data_ready(s):
            alerts.send("volume", f"{s.data_dir} not mounted; skipping cycles until it is back")
        else:
            attach_file_log(s)
            try:
                with RunLock(s.state_dir / "run.lock"):
                    run_cycle(s, alerts)
            except Busy as e:
                log.info("%s; skipping", e)
            except Exception as e:   # keep serving; the alert makes it visible
                log.exception("cycle failed")
                alerts.send("cycle", f"cycle failed: {e}"[:300])
        time.sleep(max(5, s.poll_interval - (time.monotonic() - start)))

def cmd_once(s, args):
    require_data(s)
    with RunLock(s.state_dir / "run.lock"):
        print(run_cycle(s, Alerts(s.notify_url), only=args.account, dry_run=args.dry_run, limit=args.limit))

def cmd_process(s, args):
    require_data(s)
    acct = load_account_or_exit(s, args.account)
    rd = Raindrop(access_token(s, acct))
    with RunLock(s.state_dir / "run.lock"):
        state_dir = s.state_dir / str(acct.id); state_dir.mkdir(parents=True, exist_ok=True)
        print(process_item(s, acct, rd, Attempts(state_dir / "attempts.json", s.retry_backoff),
                           args.id, rd.tags(), dry_run=args.dry_run))

def cmd_test(s, args):
    """Extract + summarize one URL. No Raindrop access; cache goes to work/test-cache."""
    require_data(s)
    item = {"_id": 0, "link": args.url, "title": "", "excerpt": "", "note": "", "tags": []}
    ctype = detect(s, args.url)
    if ctype is None:
        sys.exit(f"unsupported URL (enabled extractors: {', '.join(s.enabled_extractors)})")
    t0 = time.monotonic()
    ex = extract(s, ctype, item, want_ocr=args.ocr, cache_dir=s.work_dir / "test-cache")
    print(json.dumps({"content_type": ctype, **ex.to_dict()}, indent=1, ensure_ascii=False)[:4000])
    summary, model = summarize(s, item, ctype, ex, [])
    print(model)
    print(summary.model_dump_json(indent=1))
    print(f"elapsed: {time.monotonic() - t0:.1f}s")

def cmd_connect(s, args):
    """OAuth via a temporary localhost callback server."""
    require_data(s)
    url = authorize_url(s.raindrop_client_id, s.raindrop_redirect_uri)
    print(f"Opening browser to authorize. If it doesn't open, visit:\n{url}")
    webbrowser.open(url)
    acct = connect(s, wait_for_code(s.raindrop_redirect_uri))
    print(f"connected account {acct.id} ({acct.name})")

def cmd_accounts(s, args):
    require_data(s)
    if args.action in ("enable", "disable"):
        acct = load_account_or_exit(s, args.id)
        acct.enabled = args.action == "enable"
        store(s).save(s, acct)
    elif args.action == "disconnect":
        store(s).delete(s, args.id)
    for aid in store(s).ids(s):
        try:
            a = store(s).load(s, aid)
            print(f"{a.id}\t{a.name}\tenabled={a.enabled}\tinclude={a.include_collections}\texclude={a.exclude_collections}")
        except AccountError as e:
            print(f"{aid}\tINVALID: {e}")

def cmd_status(s, args):
    require_data(s)
    for aid in store(s).ids(s):
        acct = load_account_or_exit(s, aid)
        rd = Raindrop(access_token(s, acct))
        status = s.state_dir / str(aid) / "status.json"
        attempts = Attempts(s.state_dir / str(aid) / "attempts.json", s.retry_backoff)
        print(f"== {aid} {acct.name} enabled={acct.enabled} "
              f"pending={len(rd.list_pending(s.lookback_days, s.state_tags, s.tag_redo))}")
        print("   last cycle:", status.read_text().strip() if status.exists() else "never")
        print("   retrying:", json.dumps(attempts.data))

def main():
    ap = argparse.ArgumentParser(prog="raingist")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve")
    o = sub.add_parser("once"); o.add_argument("--account", type=int); o.add_argument("--dry-run", action="store_true"); o.add_argument("--limit", type=int)
    p = sub.add_parser("process"); p.add_argument("--account", type=int, required=True); p.add_argument("--id", type=int, required=True); p.add_argument("--dry-run", action="store_true")
    t = sub.add_parser("test"); t.add_argument("--url", required=True); t.add_argument("--ocr", action="store_true")
    sub.add_parser("connect")
    a = sub.add_parser("accounts"); a.add_argument("action", nargs="?", choices=["list", "enable", "disable", "disconnect"], default="list"); a.add_argument("id", nargs="?", type=int)
    sub.add_parser("status")
    args = ap.parse_args()
    if args.cmd == "accounts" and args.action != "list" and args.id is None:
        ap.error(f"accounts {args.action} needs an account id")
    logging.basicConfig(level=logging.INFO, format=FMT, stream=sys.stdout)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    s = load_settings()
    {"serve": cmd_serve, "once": cmd_once, "process": cmd_process, "test": cmd_test,
     "connect": cmd_connect, "accounts": cmd_accounts, "status": cmd_status}[args.cmd](s, args)
