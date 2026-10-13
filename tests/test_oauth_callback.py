import time
from concurrent.futures import ThreadPoolExecutor
import httpx
import pytest
from raingist.oauth_callback import wait_for_code

URI = "http://localhost:8799/callback"

def _get(path):
    for _ in range(50):   # server binds in the other thread
        try:
            return httpx.get(f"http://127.0.0.1:8799{path}", timeout=5)
        except httpx.ConnectError:
            time.sleep(0.05)
    raise AssertionError("callback server never came up")

def _run(*paths):
    with ThreadPoolExecutor(1) as pool:
        fut = pool.submit(wait_for_code, URI, 5)
        responses = [_get(p) for p in paths]
        return fut, responses

def test_code():
    fut, (r,) = _run("/callback?code=abc")
    assert fut.result() == "abc" and r.status_code == 200

def test_denied():
    fut, _ = _run("/callback?error=access_denied")
    with pytest.raises(RuntimeError, match="access_denied"):
        fut.result()

def test_stray_request_first():
    fut, (r1, r2) = _run("/favicon.ico", "/callback?code=xyz")
    assert r1.status_code == 404 and r2.status_code == 200
    assert fut.result() == "xyz"
