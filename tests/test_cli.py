import json, os
from raingist import cli

def test_service_line_states(settings):
    assert "never ran" in cli.service_line(settings)
    cli.write_heartbeat(settings, 42)
    line = cli.service_line(settings)
    assert line.startswith(f"service: running (pid {os.getpid()}), next poll at ") and "(in 4" in line
    hb = json.loads(cli.heartbeat_path(settings).read_text())
    cli.heartbeat_path(settings).write_text(json.dumps({**hb, "pid": 999_999}))
    assert "NOT RUNNING" in cli.service_line(settings)

def test_heartbeat_skipped_without_volume(settings, tmp_path):
    import dataclasses
    gone = dataclasses.replace(settings, data_dir=tmp_path / "unplugged")
    cli.write_heartbeat(gone, 5)
    assert not (tmp_path / "unplugged").exists()
