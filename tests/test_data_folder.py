"""Moving the agent's data folder from <server>/mcsc-data to the fixed
app-data folder: copied, checked, the old folder left exactly as it was."""

import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

from agent import datafolder
from agent.config import Config
from agent.database.db import Database
from agent.datafolder import apply_at_startup, plan_move, use_data_in_use

from .conftest import FAKE_SERVER, make_server_folder

CONFIG_TEMPLATE = """\
# My settings - this comment must survive
server:
  id: main
  name: Survival
  directory: '{server}'
  raw_command: ['{python}', '{fake}']

paths:
  data_dir: ""               # empty = the app-data folder

tls:
  enabled: true
  certificate: '{crt}'   # keep this comment
  private_key: '{key}'
  ca_certificate: ''
"""


def snapshot(folder: Path) -> dict[str, str]:
    """Every file under folder with its content hash and modification time."""
    result = {}
    for root, _, names in os.walk(folder):
        for name in names:
            path = Path(root) / name
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            result[str(path.relative_to(folder))] = f"{digest}:{path.stat().st_mtime_ns}"
    return result


@pytest.fixture
def legacy(tmp_path):
    """An install as it was before Phase 1: data inside the server folder."""
    server = make_server_folder(tmp_path / "Minecraft Server")
    old = server / "mcsc-data"
    (old / "backups").mkdir(parents=True)
    (old / "certs").mkdir()
    (old / "crashes" / "1").mkdir(parents=True)
    (old / "backups" / "manual-1.zip").write_bytes(b"PK backup bytes")
    (old / "certs" / "server.crt").write_text("CERT", encoding="utf-8")
    (old / "certs" / "server.key").write_text("KEY", encoding="utf-8")
    (old / "crashes" / "1" / "report.txt").write_text("boom", encoding="utf-8")
    db = Database(old / "mcsc.sqlite3")
    db.register_server("main", "Survival", str(server))
    db.insert(
        "backups",
        {
            "server_id": "main",
            "name": "manual-1.zip",
            "path": str(old / "backups" / "manual-1.zip"),
            "size_bytes": 15,
            "kind": "manual",
            "created_at": 1.0,
        },
    )
    db.close()
    path = tmp_path / "config.yaml"
    path.write_text(
        CONFIG_TEMPLATE.format(
            server=server,
            crt=old / "certs" / "server.crt",
            key=old / "certs" / "server.key",
            python=sys.executable,
            fake=FAKE_SERVER,
        ),
        encoding="utf-8",
    )
    return Config.load(path), old


def test_the_new_place_is_the_app_data_folder(legacy, isolated_app_data):
    config, _ = legacy
    expected = (
        Path(isolated_app_data) / "Minecraft Server Controller"
        if os.name == "nt"
        else Path(isolated_app_data) / "minecraft-server-controller"
    )
    assert config.data_dir == expected
    assert not config.data_dir_configured


def test_the_plan_is_read_only(legacy):
    config, old = legacy
    before = snapshot(old)
    plan = plan_move(config)
    assert plan.status == "pending"
    assert plan.source == old
    assert plan.target == config.data_dir
    assert plan.files == 5  # the database and four files
    assert not config.data_dir.exists()
    assert snapshot(old) == before


def test_the_move_copies_checks_and_leaves_the_old_folder(legacy):
    config, old = legacy
    before = snapshot(old)
    target = config.data_dir

    result = apply_at_startup(config)

    assert result is not None and result.ok, result.message
    assert snapshot(old) == before  # not one byte changed
    assert config.data_dir == target
    assert (target / "backups" / "manual-1.zip").read_bytes() == b"PK backup bytes"
    assert (target / "crashes" / "1" / "report.txt").read_text() == "boom"
    assert not (target / datafolder.STAGING).exists()
    record = json.loads((target / datafolder.RECORD_FILE).read_text())
    assert record["moved_from"] == str(old)
    assert json.loads((target / "layout.json").read_text())["flat_server"] == "main"

    # The database is a verified copy, with its paths pointing at the copies.
    conn = sqlite3.connect(target / "mcsc.sqlite3")
    (path,) = conn.execute("SELECT path FROM backups").fetchone()
    conn.close()
    assert Path(path) == target / "backups" / "manual-1.zip"
    assert result.tables["backups"] == 1

    # The first server's files are where they were, relative to the folder.
    assert config.for_server("main").backup_dir == target / "backups"


def test_certificate_paths_in_config_follow_the_copy(legacy):
    config, old = legacy
    target = config.data_dir
    apply_at_startup(config)
    text = config.source.read_text(encoding="utf-8")
    assert "# My settings - this comment must survive" in text
    assert "# keep this comment" in text
    assert str(target / "certs" / "server.crt") in text
    assert str(old / "certs") not in text
    assert config.tls_certificate == target / "certs" / "server.crt"
    backup = config.source.with_name("config.yaml" + datafolder.CONFIG_BACKUP_SUFFIX)
    assert str(old / "certs" / "server.crt") in backup.read_text(encoding="utf-8")


def test_the_move_happens_once(legacy):
    config, _ = legacy
    assert apply_at_startup(config).ok
    again = Config.load(config.source)
    assert plan_move(again).status == "done"
    assert apply_at_startup(again) is None


def test_an_explicit_data_folder_never_moves(legacy, tmp_path):
    config, old = legacy
    config.set("paths.data_dir", str(old))
    plan = plan_move(config)
    assert plan.status == "not_needed"
    assert apply_at_startup(config) is None
    assert config.data_dir == old


def test_a_fresh_install_has_nothing_to_move(tmp_path):
    server = make_server_folder(tmp_path / "Fresh")
    path = tmp_path / "config.yaml"
    path.write_text(f"server:\n  directory: '{server}'\n", encoding="utf-8")
    config = Config.load(path)
    assert plan_move(config).status == "not_needed"
    assert apply_at_startup(config) is None


def test_not_enough_space_keeps_the_old_folder(legacy, monkeypatch):
    config, old = legacy
    monkeypatch.setattr(datafolder, "_free_bytes", lambda path: 1024)
    target = config.data_dir
    result = apply_at_startup(config)
    assert result is not None and not result.ok
    assert "Not enough free space" in result.message
    assert config.data_dir == old  # used for this run
    assert not target.exists()


def test_a_failed_copy_keeps_the_old_folder_and_tries_again(legacy, monkeypatch):
    config, old = legacy
    before = snapshot(old)
    target = config.data_dir

    def broken(src, dst):
        raise datafolder.MoveError(f"The copy of {src} does not match the original")

    monkeypatch.setattr(datafolder, "_copy_verified", broken)
    result = apply_at_startup(config)
    assert result is not None and not result.ok
    assert "will try again" in result.message
    assert config.data_dir == old
    assert not target.exists()
    assert snapshot(old) == before
    monkeypatch.undo()
    assert plan_move(Config.load(config.source)).status == "pending"


def test_a_clashing_file_in_the_new_folder_stops_the_move_before_anything_moves(legacy):
    config, old = legacy
    target = config.data_dir
    (target / "backups").mkdir(parents=True)
    (target / "backups" / "someone-elses.zip").write_bytes(b"x")
    result = apply_at_startup(config)
    assert not result.ok
    assert config.data_dir == old
    assert not (target / "mcsc.sqlite3").exists()
    assert not (target / "certs").exists()
    assert (target / "backups" / "someone-elses.zip").exists()  # not ours, not touched


class PowerCut(BaseException):
    """Stops the move where a power cut would: no clean-up runs."""


real_write_record = datafolder._write_record


def test_a_move_cut_off_half_way_finishes_on_the_next_start(legacy, monkeypatch):
    config, old = legacy
    target = config.data_dir
    before = snapshot(old)

    def cut(*args, **kwargs):
        raise PowerCut

    monkeypatch.setattr(datafolder, "_write_record", cut)
    with pytest.raises(PowerCut):
        apply_at_startup(config)
    # Some folders made it across; the database did not.
    assert (target / "backups" / "manual-1.zip").exists()
    assert not (target / "mcsc.sqlite3").exists()
    monkeypatch.setattr(datafolder, "_write_record", real_write_record)

    again = Config.load(config.source)
    assert plan_move(again).status == "pending"
    result = apply_at_startup(again)
    assert result.ok, result.message
    assert (target / "mcsc.sqlite3").is_file()
    assert (target / "backups" / "manual-1.zip").read_bytes() == b"PK backup bytes"
    assert snapshot(old) == before


def test_a_half_moved_folder_that_was_changed_since_still_stops_the_move(legacy, monkeypatch):
    config, old = legacy
    target = config.data_dir

    def cut(*args, **kwargs):
        raise PowerCut

    monkeypatch.setattr(datafolder, "_write_record", cut)
    with pytest.raises(PowerCut):
        apply_at_startup(config)
    monkeypatch.setattr(datafolder, "_write_record", real_write_record)
    (target / "backups" / "manual-1.zip").write_bytes(b"changed")  # not our copy any more

    again = Config.load(config.source)
    result = apply_at_startup(again)
    assert not result.ok
    assert again.data_dir == old
    assert (target / "backups" / "manual-1.zip").read_bytes() == b"changed"  # not touched


def test_folders_a_tool_created_early_do_not_stop_the_move(legacy):
    config, _ = legacy
    target = config.data_dir
    (target / "logs").mkdir(parents=True)
    (target / "certs").mkdir()
    (target / "layout.json").write_text('{"layout": 1, "flat_server": null}')
    result = apply_at_startup(config)
    assert result.ok, result.message
    assert (target / "certs" / "server.crt").is_file()
    assert json.loads((target / "layout.json").read_text())["flat_server"] == "main"


def test_tools_before_the_first_start_use_the_old_folder(legacy):
    """--check, make_certs and setup run before the agent copies the folder;
    they must not create a database or certificates in the new one."""
    from agent.diagnostics import run_diagnostics

    config, old = legacy
    target = config.data_dir
    plan = use_data_in_use(config)
    assert plan.status == "pending"
    assert config.data_dir == old
    config.ensure_dirs()
    report = run_diagnostics(config, data_plan=plan)
    assert not (target / "mcsc.sqlite3").exists()
    move = [c for c in report.sections["Storage"] if c.name == "Data folder move"]
    assert move and move[0].status == "WARN"
    # The real start still copies everything.
    fresh = Config.load(config.source)
    assert apply_at_startup(fresh).ok
    assert (target / "mcsc.sqlite3").is_file()


def test_the_command_line_report_changes_nothing(legacy, capsys):
    config, old = legacy
    before = snapshot(old)
    assert datafolder.main(["--config", str(config.source), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "pending"
    assert snapshot(old) == before
    assert not config.data_dir.exists()


# ------------------------------------------------------------------ access
def test_shared_groups_are_found_in_any_windows_language():
    from agent.security.certs import shared_groups_in_sddl

    private = "D:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;S-1-5-21-1-2-3-1001)"
    assert shared_groups_in_sddl(private) == []
    programdata = "D:AI(A;OICIID;FA;;;SY)(A;OICIID;FA;;;BA)(A;OICIID;0x1200a9;;;BU)"
    assert shared_groups_in_sddl(programdata) == ["Users"]
    denied = "D:P(D;;FA;;;WD)(A;;FA;;;SY)"
    assert shared_groups_in_sddl(denied) == []  # a deny entry grants nothing


def test_the_app_data_folder_is_made_private_at_startup(isolated_app_data):
    from agent import startup_diag
    from agent.main import lock_down_data_folder
    from agent.security.certs import folder_access

    config = Config({"server": {"directory": ""}})
    config.data_dir.mkdir(parents=True)
    if os.name != "nt":
        config.data_dir.chmod(0o755)
        assert folder_access(config.data_dir)[0] == "shared"
    lock_down_data_folder(config, startup_diag)
    assert folder_access(config.data_dir)[0] == "private"


def test_a_data_folder_set_in_config_is_left_alone(tmp_path):
    from agent import startup_diag
    from agent.main import lock_down_data_folder

    mine = tmp_path / "mine"
    mine.mkdir()
    mine.chmod(0o755)
    config = Config({"server": {"directory": ""}, "paths": {"data_dir": str(mine)}})
    lock_down_data_folder(config, startup_diag)
    if os.name != "nt":
        assert mine.stat().st_mode & 0o777 == 0o755
