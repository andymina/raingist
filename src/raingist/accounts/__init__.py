import time
from dataclasses import dataclass, asdict
from . import file_store
from ..raindrop import token_request, Raindrop

REFRESH_MARGIN = 3600   # refresh when less than 1 h left

class AccountError(Exception): ...

@dataclass
class Account:
    id: int
    name: str
    access_token: str
    refresh_token: str
    expires_at: float
    enabled: bool = True

    def to_dict(self):
        return asdict(self)

# name -> module with ids(s), load(s, id), save(s, account), delete(s, id)
ACCOUNT_STORES = {"files": file_store}

def store(s):
    return ACCOUNT_STORES[s.account_store]

def connect(s, code: str) -> Account:
    """Exchange an OAuth code for tokens and save the account (new or reconnected)."""
    t = token_request({"grant_type": "authorization_code", "code": code.strip(),
                       "client_id": s.raindrop_client_id, "client_secret": s.raindrop_client_secret,
                       "redirect_uri": s.raindrop_redirect_uri})
    me = Raindrop(t["access_token"]).me()
    acct = Account(id=int(me["_id"]), name=me.get("fullName") or str(me["_id"]),
                   access_token=t["access_token"], refresh_token=t["refresh_token"],
                   expires_at=time.time() + float(t.get("expires_in", 0)))
    try:
        old = store(s).load(s, acct.id)   # keep the on/off switch on reconnect
        acct.enabled = old.enabled
    except AccountError:
        pass   # new account
    store(s).save(s, acct)
    return acct

def access_token(s, acct: Account) -> str:
    """Valid access token, refreshing and saving when close to expiry."""
    if acct.expires_at - time.time() > REFRESH_MARGIN:
        return acct.access_token
    t = token_request({"grant_type": "refresh_token", "refresh_token": acct.refresh_token,
                       "client_id": s.raindrop_client_id, "client_secret": s.raindrop_client_secret})
    acct.access_token = t["access_token"]
    acct.refresh_token = t.get("refresh_token") or acct.refresh_token
    acct.expires_at = time.time() + float(t.get("expires_in", 0))
    store(s).save(s, acct)
    return acct.access_token
