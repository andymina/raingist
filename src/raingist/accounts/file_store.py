import json, os
from pathlib import Path

def _path(s, aid: int) -> Path:
    return s.accounts_dir / f"{aid}.json"

def ids(s) -> list[int]:
    return sorted(int(p.stem) for p in s.accounts_dir.glob("*.json") if p.stem.isdigit())

def load(s, aid: int):
    from . import Account, AccountError
    p = _path(s, aid)
    if not p.exists():
        raise AccountError(f"account {aid} not connected")
    try:
        return Account(**json.loads(p.read_text()))
    except (json.JSONDecodeError, TypeError) as e:
        raise AccountError(f"account file {p.name} is invalid: {e}") from e

def save(s, account) -> None:
    p = _path(s, account.id)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(account.to_dict(), indent=1))
    os.chmod(tmp, 0o600)
    tmp.replace(p)

def delete(s, aid: int) -> None:
    _path(s, aid).unlink(missing_ok=True)
