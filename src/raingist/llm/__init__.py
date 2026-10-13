import logging
from . import gemini_provider, anthropic_provider
from .prompt import Summary, ProviderUnavailable, SYSTEM_PROMPT, build_user_message, length_class
from ..extract.common import Extraction, TransientFailure

log = logging.getLogger(__name__)

# name -> fn(api_key, model, system, user_message) -> Summary
PROVIDERS = {"gemini": gemini_provider.generate, "anthropic": anthropic_provider.generate}
DEFAULT_MODELS = {"gemini": "gemini-3.5-flash-lite", "anthropic": "claude-haiku-5-5"}
MAX_TAKEAWAYS = {"SHORT": 4, "LONG": 5}

def summarize(s, item: dict, ctype: str, ex: Extraction, existing_tags: list[str]) -> tuple[Summary, str]:
    """Try LLM_PROVIDERS in order. Returns (summary, model). Raises TransientFailure if none work."""
    system = SYSTEM_PROMPT.format(language=s.summary_language)
    message = build_user_message(item, ctype, ex, existing_tags)
    last: Exception | None = None
    for name in s.llm_providers:
        model = s.llm_models[name]
        for attempt in range(2):   # one retry for malformed JSON
            try:
                summary = PROVIDERS[name](s.llm_keys[name], model, system, message)
                summary.key_takeaways = summary.key_takeaways[:MAX_TAKEAWAYS[length_class(ex)]]   # models overshoot
                return summary, model
            except ProviderUnavailable as e:
                last = e; log.warning("%s unavailable: %s", name, e); break
            except ValueError as e:
                last = e; log.warning("%s returned invalid JSON (attempt %d)", name, attempt + 1)
    raise TransientFailure(f"no LLM provider available: {last}")
