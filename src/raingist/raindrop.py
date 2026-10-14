import time
import httpx

BASE = "https://api.raindrop.io/rest/v1"
AUTHORIZE_URL = "https://raindrop.io/oauth/authorize"
TOKEN_URL = "https://api.raindrop.io/v1/oauth/access_token"   # raindrop.io/oauth/access_token 307s here

class RaindropError(Exception): ...

def authorize_url(client_id: str, redirect_uri: str) -> str:
    return str(httpx.URL(AUTHORIZE_URL, params={"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri}))

def token_request(payload: dict) -> dict:
    """POST to the OAuth token endpoint. Returns {access_token, refresh_token, expires_in, ...}."""
    r = httpx.post(TOKEN_URL, json=payload, timeout=30)
    try:
        data = r.json()
    except ValueError:
        raise RaindropError(f"oauth {payload['grant_type']} -> {r.status_code}, not JSON: {r.text[:200]}") from None
    if r.status_code >= 400 or not data.get("access_token"):   # errors can come back as 200 + result:false
        reason = data.get("errorMessage") or data.get("error") or "no access_token in response"
        raise RaindropError(f"oauth {payload['grant_type']} -> {r.status_code}: {reason}")
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

    def search(self, query: str, max_pages: int = 10, collection: int = 0, sort: str = "-created") -> list[dict]:
        """Bookmarks matching `query` in `collection` (0 = all except Trash), newest first by default."""
        items: list[dict] = []
        for page in range(max_pages):
            params = {"sort": sort, "perpage": 50, "page": page} | ({"search": query} if query else {})
            batch = self._req("GET", f"/raindrops/{collection}", params=params).get("items", [])
            items.extend(batch)
            if len(batch) < 50:
                break
        return items

    def get(self, rid: int) -> dict:
        return self._req("GET", f"/raindrop/{rid}")["item"]

    def update(self, rid: int, **fields) -> dict:
        return self._req("PUT", f"/raindrop/{rid}", json=fields)["item"]

    def collections(self) -> list[dict]:
        """Every collection, top-level and nested, once each (/collections/childrens also returns top-level ones)."""
        both = self._req("GET", "/collections")["items"] + self._req("GET", "/collections/childrens")["items"]
        return list({c["_id"]: c for c in both}.values())

    def create_collection(self, title: str, description: str, parent: int = 0) -> dict:
        body = {"title": title, "description": description} | ({"parent": {"$id": parent}} if parent else {})
        return self._req("POST", "/collection", json=body)["item"]

    def move_many(self, from_collection: int, ids: list[int], to: int) -> int:
        """Move `ids` (all in `from_collection`) to collection `to`. Returns how many Raindrop reports modified."""
        moved = 0
        for i in range(0, len(ids), 100):   # shortcut: chunk size is a guess, the API documents no limit
            moved += self._req("PUT", f"/raindrops/{from_collection}",
                               json={"ids": ids[i:i + 100], "collection": {"$id": to}}).get("modified", 0)
        return moved

    def delete_collection(self, cid: int) -> None:
        """Deletes the collection and its descendants; any bookmarks still in it go to Trash, so empty it first."""
        self._req("DELETE", f"/collection/{cid}")

    def recent_titles(self, collection: int, n: int) -> list[str]:
        items = self._req("GET", f"/raindrops/{collection}", params={"sort": "-created", "perpage": n}).get("items", [])
        return [i.get("title", "") for i in items]

    def tags(self) -> list[str]:
        return [t["_id"] for t in self._req("GET", "/tags").get("items", [])]

    def me(self) -> dict:
        return self._req("GET", "/user")["user"]
