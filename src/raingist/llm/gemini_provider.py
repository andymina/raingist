from google import genai
from google.genai import types, errors
from .prompt import Summary, ProviderUnavailable
from ..extract.common import TransientFailure

def generate(api_key: str, model: str, system: str, user: str, schema=Summary):
    client = genai.Client(api_key=api_key)   # keep a reference: a GC'd Client closes its HTTP connection mid-call
    try:
        resp = client.models.generate_content(
            model=model, contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system, response_mime_type="application/json",
                response_json_schema=schema.model_json_schema(), temperature=0.2))
    except errors.APIError as e:
        if e.code in (429, 503):
            raise ProviderUnavailable(f"gemini {e.code}: {e.message}") from e
        raise TransientFailure(f"gemini {e.code}: {e.message}") from e
    return schema.model_validate_json(resp.text)   # ValueError on bad JSON
