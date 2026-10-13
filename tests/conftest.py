import time
import pytest
from raingist.settings import load_settings, data_ready, SENTINEL
from raingist.accounts import Account, store

BASE_ENV = {"RAINDROP_CLIENT_ID": "id", "RAINDROP_CLIENT_SECRET": "secret", "GEMINI_API_KEY": "k"}

@pytest.fixture
def env(tmp_path):
    return {"DATA_DIR": str(tmp_path), **BASE_ENV}

@pytest.fixture
def settings(tmp_path, env):
    s = load_settings(env)
    (tmp_path / SENTINEL).touch()
    assert data_ready(s)
    return s

def _make_account(settings, id, **kw):
    fields = {"name": f"user{id}", "access_token": "at", "refresh_token": "rt",
              "expires_at": time.time() + 30 * 86400, **kw}
    acct = Account(id=id, **fields)
    store(settings).save(settings, acct)
    return acct

@pytest.fixture
def make_account():
    return _make_account

class FakeAlerts:
    def __init__(self):
        self.sent = []

    def send(self, key, message):
        self.sent.append((key, message))

    @property
    def keys(self):
        return [k for k, _ in self.sent]

@pytest.fixture
def alerts():
    return FakeAlerts()
