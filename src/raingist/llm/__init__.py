import logging
from . import gemini_provider, anthropic_provider
from .prompt import (Summary, Proposal, Assignment, Descriptions, ProviderUnavailable, SYSTEM_PROMPT, PROPOSE_PROMPT,
                     ASSIGN_PROMPT, REBALANCE_PROMPT, DESCRIBE_PROMPT, build_user_message)
from ..extract.common import Extraction, TransientFailure

log = logging.getLogger(__name__)

# name -> fn(api_key, model, system, user_message, schema) -> instance of schema (a pydantic model)
PROVIDERS = {"gemini": gemini_provider.generate, "anthropic": anthropic_provider.generate}
DEFAULT_MODELS = {"gemini": "gemini-3.5-flash-lite", "anthropic": "claude-haiku-5-5"}

def summarize(s, item: dict, ctype: str, ex: Extraction, existing_tags: list[str],
              owner_note: str = "", catalog: list[dict] | None = None) -> tuple[Summary, str]:
    """Try LLM_PROVIDERS in order. Returns (summary, model). Raises TransientFailure if none work."""
    system = SYSTEM_PROMPT.format(language=s.summary_language)
    return _call(s, system, build_user_message(item, ctype, ex, existing_tags, owner_note, catalog), Summary)

def propose(s, message: str) -> tuple[Proposal, str]:
    """Organizing: new collections and merges."""
    return _call(s, PROPOSE_PROMPT.format(min_group=s.organize_min_group), message, Proposal, decision=True)

def assign(s, message: str) -> tuple[Assignment, str]:
    """Organizing: file each Unsorted bookmark into an existing collection, or leave it (0)."""
    return _call(s, ASSIGN_PROMPT, message, Assignment, decision=True)

def rebalance(s, message: str) -> tuple[Assignment, str]:
    """Organizing: re-check bookmarks the service filed; each one's best collection, its current one, or none (0)."""
    return _call(s, REBALANCE_PROMPT, message, Assignment, decision=True)

def describe(s, message: str) -> tuple[Descriptions, str]:
    """Draft scope descriptions for the owner's undescribed collections (printed, never written)."""
    return _call(s, DESCRIBE_PROMPT, message, Descriptions, decision=True)

def _call(s, system: str, message: str, schema, decision: bool = False):
    """decision=True uses <PROVIDER>_DECISION_MODEL (the Organizing calls), else <PROVIDER>_MODEL."""
    last: Exception | None = None
    for name in s.llm_providers:
        model = (s.llm_decision_models if decision else s.llm_models)[name]
        for attempt in range(2):   # one retry for malformed JSON
            try:
                return PROVIDERS[name](s.llm_keys[name], model, system, message, schema), model
            except ProviderUnavailable as e:
                last = e; log.warning("%s unavailable: %s", name, e); break
            except ValueError as e:
                last = e; log.warning("%s returned invalid JSON (attempt %d)", name, attempt + 1)
    raise TransientFailure(f"no LLM provider available: {last}")
