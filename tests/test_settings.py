import pytest
from raingist.settings import load_settings, data_ready, SENTINEL

@pytest.mark.parametrize("key", ["DATA_DIR", "RAINDROP_CLIENT_ID", "RAINDROP_CLIENT_SECRET"])
def test_required(env, key):
    env.pop(key)
    with pytest.raises(SystemExit, match=key):
        load_settings(env)

@pytest.mark.parametrize("key,value", [
    ("TRANSCRIBER", "nope"), ("OCR_BACKEND", "nope"), ("ACCOUNT_STORE", "nope"),
    ("ENABLED_EXTRACTORS", "nope"), ("LLM_PROVIDERS", "nope"),
])
def test_unknown_choice_lists_choices(env, key, value):
    env[key] = value
    with pytest.raises(SystemExit, match="choose"):
        load_settings(env)

def test_empty_extractors(env):
    env["ENABLED_EXTRACTORS"] = " , "
    with pytest.raises(SystemExit, match="ENABLED_EXTRACTORS"):
        load_settings(env)

def test_provider_without_key(env):
    env["LLM_PROVIDERS"] = "gemini,anthropic"
    with pytest.raises(SystemExit, match="ANTHROPIC_API_KEY"):
        load_settings(env)

def test_backoff_minutes_to_seconds(env):
    env["RETRY_BACKOFF_MINUTES"] = "1, 5"
    assert load_settings(env).retry_backoff == (60, 300)
    assert load_settings({**env, "RETRY_BACKOFF_MINUTES": ""}).retry_backoff == (120, 600, 1800, 7200, 21600)

def test_bad_int(env):
    env["POLL_INTERVAL_SECONDS"] = "five"
    with pytest.raises(SystemExit, match="POLL_INTERVAL_SECONDS"):
        load_settings(env)

def test_duplicate_tags(env):
    env["TAG_SKIP"] = "Raingist-Done"
    with pytest.raises(SystemExit, match="distinct"):
        load_settings(env)

def test_tags_need_prefix(env):
    env["TAG_DONE"] = "ai-done"
    with pytest.raises(SystemExit, match="raingist-"):
        load_settings(env)

def test_data_ready(env, tmp_path):
    s = load_settings(env)
    assert not data_ready(s)
    assert not s.state_dir.exists()
    (tmp_path / SENTINEL).touch()
    assert data_ready(s)
    for d in (s.accounts_dir, s.cache_dir, s.state_dir, s.work_dir, s.model_dir, s.log_dir):
        assert d.is_dir()
