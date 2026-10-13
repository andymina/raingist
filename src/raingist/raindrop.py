import time, datetime as dt
import httpx

BASE = "https://api.raindrop.io/rest/v1"
AUTHORIZE_URL = "https://raindrop.io/oauth/authorize"
TOKEN_URL = "https://raindrop.io/oauth/access_token"

class RaindropError(Exception): ...

def authorize_url(client_id: str, redirect_uri: str) -> str:
    return str(httpx.URL(AUTHORIZE_URL, params={"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri}))

def token_request(payload: dict) -> dict:
    """POST to the OAuth token endpoint. Returns {access_token, refresh_token, expires_in, ...}."""
    r = httpx.post(TOKEN_URL, json=payload, timeout=30)
    if r.status_code >= 400:
        raise RaindropError(f"oauth {payload['grant_type']} -> {r.status_code}: {r.text[:200]}")
    data = r.json()
    if not data.get("access_token"):
        raise RaindropError(f"oauth {payload['grant_type']}: no access_token in response")
    return data

class Raindrop:
    def __init__(self, token: str):
        self.c = httpx.Client(base_url=BASE, headers={"Authorization": f"Bearer {token}"}, timeout=30)

    def _req(self, method: str, path: str, **kw) -> dict:
        for attempt in range(3):
            try:
                r = self.c.request(method, path, **kw)
            except httpx.TransportError as e:
                if attempt == 2:
                    raise RaindropError(f"network: {e}") from e
                time.sleep(2 ** attempt); continue
            if r.status_code == 429:
                reset = float(r.headers.get("X-RateLimit-Reset", 0))
                time.sleep(max(1.0, min(60.0, reset - time.time()))); continue
            if r.status_code >= 500:
                time.sleep(2 ** attempt); continue
            if r.status_code >= 400:
                raise RaindropError(f"{method} {path} -> {r.status_code}: {r.text[:200]}")
            data = r.json()
            if not data.get("result", True):
                raise RaindropError(f"{method} {path} -> result=false: {data}")
            return data
        raise RaindropError(f"{method} {path}: retries exhausted")

    def search(self, query: str, max_pages: int = 10) -> list[dict]:
        items: list[dict] = []
        for page in range(max_pages):
            batch = self._req("GET", "/raindrops/0", params={
                "search": query, "sort": "-created", "perpage": 50, "page": page}).get("items", [])
            items.extend(batch)
            if len(batch) < 50:
                break
        return items

    def list_pending(self, lookback_days: int, state_tags: frozenset[str], redo_tag: str) -> list[dict]:
        since = (dt.datetime.now(dt.UTC) - dt.timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        new = self.search(" ".join(f"-#{t}" for t in sorted(state_tags)) + f" created:>{since}")
        new = [i for i in new if not ({t.lower() for t in i.get("tags", [])} & state_tags)]
        seen, out = set(), []
        for i in self.search(f"#{redo_tag}", max_pages=1) + new:
            if i["_id"] not in seen:
                seen.add(i["_id"]); out.append(i)
        return out

    def get(self, rid: int) -> dict:
        return self._req("GET", f"/raindrop/{rid}")["item"]

    def update(self, rid: int, **fields) -> dict:
        return self._req("PUT", f"/raindrop/{rid}", json=fields)["item"]

    def tags(self) -> list[str]:
        return [t["_id"] for t in self._req("GET", "/tags").get("items", [])]

    def me(self) -> dict:
        return self._req("GET", "/user")["user"]
