import anthropic
from .prompt import Summary, ProviderUnavailable
from ..extract.common import TransientFailure

def generate(api_key: str, model: str, system: str, user: str) -> Summary:
    try:
        resp = anthropic.Anthropic(api_key=api_key).messages.parse(
            model=model, max_tokens=4096, system=system,
            messages=[{"role": "user", "content": user}],
            output_format=Summary, output_config={"effort": "low"})
    except (anthropic.RateLimitError, anthropic.APIConnectionError) as e:
        raise ProviderUnavailable(f"anthropic: {e}") from e
    except anthropic.APIStatusError as e:
        raise TransientFailure(f"anthropic {e.status_code}: {e.message}") from e
    return resp.parsed_output
