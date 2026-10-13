import os, stat, time
import httpx
import pytest
import raingist.accounts as accounts
from raingist.accounts import AccountError, store

def test_round_trip_and_mode(settings, make_account):
    acct = make_account(settings, 7, include_collections=[3])
    assert store(settings).load(settings, 7) == acct
    assert stat.S_IMODE(os.stat(settings.accounts_dir / "7.json").st_mode) == 0o600
    assert store(settings).ids(settings) == [7]

def test_invalid_json(settings):
    (settings.accounts_dir / "8.json").write_text("{")
    with pytest.raises(AccountError):
        store(settings).load(settings, 8)

def test_missing(settings):
    with pytest.raises(AccountError):
        store(settings).load(settings, 9)

def test_access_token_fresh(settings, make_account, monkeypatch):
    acct = make_account(settings, 1)
    monkeypatch.setattr(accounts, "token_request", lambda p: pytest.fail("no refresh expected"))
    assert accounts.access_token(settings, acct) == "at"

def test_access_token_refresh(settings, make_account, monkeypatch):
    acct = make_account(settings, 1, expires_at=time.time() + 60)
    calls = []
    def fake(payload):
        calls.append(payload)
        return {"access_token": "new", "refresh_token": "rt2", "expires_in": 86400}
    monkeypatch.setattr(accounts, "token_request", fake)
    assert accounts.access_token(settings, acct) == "new"
    assert calls[0]["grant_type"] == "refresh_token" and calls[0]["refresh_token"] == "rt"
    saved = store(settings).load(settings, 1)
    assert (saved.access_token, saved.refresh_token) == ("new", "rt2")
    assert saved.expires_at > time.time() + 80000

def test_connect_new_and_reconnect(settings, monkeypatch):
    payloads = []
    def fake(payload):
        payloads.append(payload)
        return {"access_token": f"at{len(payloads)}", "refresh_token": "rt", "expires_in": 1209600}
    monkeypatch.setattr(accounts, "token_request", fake)
    monkeypatch.setattr(accounts.Raindrop, "me", lambda self: {"_id": 42, "fullName": "Owner"})
    acct = accounts.connect(settings, " code1 ")
    assert payloads[0]["grant_type"] == "authorization_code" and payloads[0]["code"] == "code1"
    assert (acct.id, acct.name, acct.enabled) == (42, "Owner", True)
    acct.enabled, acct.include_collections, acct.exclude_collections, acct.inbox_collection = False, [1], [2], 3
    store(settings).save(settings, acct)
    again = accounts.connect(settings, "code2")
    assert again.access_token == "at2"
    assert (again.enabled, again.include_collections, again.exclude_collections, again.inbox_collection) == (False, [1], [2], 3)

def test_authorize_url():
    from raingist.raindrop import authorize_url
    assert authorize_url("cid", "http://localhost:8765/callback") == (
        "https://raindrop.io/oauth/authorize?response_type=code&client_id=cid"
        "&redirect_uri=http%3A%2F%2Flocalhost%3A8765%2Fcallback")

@pytest.mark.parametrize("response,match", [
    (httpx.Response(200, json={"result": False, "status": 400, "errorMessage": "client_id or client_secret is invalid"}),
     "client_id or client_secret is invalid"),
    (httpx.Response(307, text="https://api.raindrop.io/v1/oauth/access_token"), "not JSON"),
    (httpx.Response(400, json={"error": "bad_authorization_code"}), "bad_authorization_code"),
])
def test_token_request_errors(monkeypatch, response, match):
    from raingist import raindrop
    monkeypatch.setattr(raindrop.httpx, "post", lambda *a, **k: response)
    with pytest.raises(raindrop.RaindropError, match=match):
        raindrop.token_request({"grant_type": "authorization_code"})
