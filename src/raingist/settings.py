from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
import os, sys
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]   # ~/raingist
SENTINEL = ".raingist"

@dataclass(frozen=True)
class Settings:
    data_dir: Path
    raindrop_client_id: str
    raindrop_client_secret: str
    raindrop_redirect_uri: str
    account_store: str
    llm_providers: tuple[str, ...]
    llm_keys: dict
    llm_models: dict
    summary_language: str
    enabled_extractors: tuple[str, ...]
    tiktok_cookies_file: Path | None
    transcriber: str
    whisper_model: str
    ocr_backend: str
    poll_interval: int
    lookback_days: int
    max_items_per_account: int
    retry_backoff: tuple[int, ...]   # seconds
    tag_done: str
    tag_failed: str
    tag_skip: str
    tag_ocr: str
    tag_redo: str
    notify_url: str | None

    @property
    def state_tags(self) -> frozenset[str]:
        return frozenset({self.tag_done, self.tag_failed, self.tag_skip})

    @property
    def reserved_tags(self) -> frozenset[str]:
        return self.state_tags | {self.tag_ocr, self.tag_redo}

    @property
    def accounts_dir(self) -> Path: return self.data_dir / "accounts"
    @property
    def cache_dir(self) -> Path: return self.data_dir / "transcripts"
    @property
    def state_dir(self) -> Path: return self.data_dir / "state"
    @property
    def work_dir(self) -> Path: return self.data_dir / "work"
    @property
    def model_dir(self) -> Path: return self.data_dir / "models"
    @property
    def log_dir(self) -> Path: return self.data_dir / "logs"

def fail(msg: str):
    sys.exit(f"config error: {msg}")

def _ints(raw: str | None, key: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in (raw or "").split(",") if x.strip())
    except ValueError:
        fail(f"{key} must be comma-separated integers")

def _int(env: Mapping, key: str, default: int) -> int:
    try:
        return int(env.get(key) or default)
    except ValueError:
        fail(f"{key} must be an integer")

def _names(env: Mapping, key: str, default: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in (env.get(key) or default).split(",") if x.strip())

def _choose(env: Mapping, key: str, default: str, registry) -> str:
    value = env.get(key) or default
    if value not in registry:
        fail(f"{key}={value!r}; choose one of {sorted(registry)}")
    return value

def load_settings(env: Mapping | None = None) -> Settings:
    if env is None:
        load_dotenv(ROOT / ".env")
        env = os.environ
    from .accounts import ACCOUNT_STORES
    from .extract import EXTRACTORS
    from .transcribe import TRANSCRIBERS
    from .ocr import OCR_BACKENDS
    from .llm import PROVIDERS, DEFAULT_MODELS
    for key in ("DATA_DIR", "RAINDROP_CLIENT_ID", "RAINDROP_CLIENT_SECRET"):
        if not env.get(key):
            fail(f"{key} is required")
    providers = _names(env, "LLM_PROVIDERS", "gemini")
    keys, models = {}, {}
    for p in providers:
        if p not in PROVIDERS:
            fail(f"unknown LLM provider {p!r}; choose from {sorted(PROVIDERS)}")
        keys[p] = env.get(f"{p.upper()}_API_KEY") or fail(f"{p.upper()}_API_KEY is required for LLM_PROVIDERS={p}")
        models[p] = env.get(f"{p.upper()}_MODEL") or DEFAULT_MODELS[p]
    extractors = _names(env, "ENABLED_EXTRACTORS", "tiktok")
    unknown = [e for e in extractors if e not in EXTRACTORS]
    if unknown or not extractors:
        fail(f"ENABLED_EXTRACTORS has unknown/no entries {unknown}; choose from {sorted(EXTRACTORS)}")
    cookies = Path(env["TIKTOK_COOKIES_FILE"]).expanduser() if env.get("TIKTOK_COOKIES_FILE") else None
    if cookies and not cookies.is_file():
        fail(f"TIKTOK_COOKIES_FILE {cookies} does not exist")
    tags = {k: (env.get(k) or d).strip().lower() for k, d in (
        ("TAG_DONE", "ai-done"), ("TAG_FAILED", "ai-failed"), ("TAG_SKIP", "ai-skip"),
        ("TAG_OCR", "ai-ocr"), ("TAG_REDO", "ai-redo"))}
    if len(set(tags.values())) != len(tags):
        fail("TAG_* values must be distinct")
    backoff = _ints(env.get("RETRY_BACKOFF_MINUTES"), "RETRY_BACKOFF_MINUTES") or (2, 10, 30, 120, 360)
    return Settings(
        data_dir=Path(env["DATA_DIR"]).expanduser(),
        raindrop_client_id=env["RAINDROP_CLIENT_ID"],
        raindrop_client_secret=env["RAINDROP_CLIENT_SECRET"],
        raindrop_redirect_uri=env.get("RAINDROP_REDIRECT_URI") or "http://localhost:8765/callback",
        account_store=_choose(env, "ACCOUNT_STORE", "files", ACCOUNT_STORES),
        llm_providers=providers, llm_keys=keys, llm_models=models,
        summary_language=env.get("SUMMARY_LANGUAGE") or "en",
        enabled_extractors=extractors,
        tiktok_cookies_file=cookies,
        transcriber=_choose(env, "TRANSCRIBER", "mlx-whisper", TRANSCRIBERS),
        whisper_model=env.get("WHISPER_MODEL") or "mlx-community/whisper-large-v3-turbo",
        ocr_backend=_choose(env, "OCR_BACKEND", "vision", OCR_BACKENDS),
        poll_interval=_int(env, "POLL_INTERVAL_SECONDS", 300),
        lookback_days=_int(env, "POLL_LOOKBACK_DAYS", 14),
        max_items_per_account=_int(env, "MAX_ITEMS_PER_ACCOUNT", 10),
        retry_backoff=tuple(m * 60 for m in backoff),
        tag_done=tags["TAG_DONE"], tag_failed=tags["TAG_FAILED"], tag_skip=tags["TAG_SKIP"],
        tag_ocr=tags["TAG_OCR"], tag_redo=tags["TAG_REDO"],
        notify_url=env.get("NOTIFY_URL") or None,
    )

def data_ready(s: Settings) -> bool:
    """True when the data volume is mounted (sentinel present). Creates subdirs."""
    if not (s.data_dir / SENTINEL).exists():
        return False
    for d in (s.accounts_dir, s.cache_dir, s.state_dir, s.work_dir, s.model_dir, s.log_dir):
        d.mkdir(parents=True, exist_ok=True)
    return True
