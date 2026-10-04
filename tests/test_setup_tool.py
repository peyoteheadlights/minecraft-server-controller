"""Setup: read-only checks, idempotent repeat runs, comment-preserving edits,
and secrets that never reach the screen, a log, or a file in plain text."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from installer import setup_tool
from installer.setup_tool import Context, read_env, set_yaml_value, write_env_value

PROJECT = Path(__file__).resolve().parent.parent
PASSWORD = "a secret password 9"


@pytest.fixture
def root(tmp_path, monkeypatch):
    """A fresh, unconfigured copy of the files setup looks at."""
    r = tmp_path / "project"
    (r / "config").mkdir(parents=True)
    shutil.copy(PROJECT / "config" / "config.example.yaml", r / "config" / "config.example.yaml")
    shutil.copy(PROJECT / "requirements.txt", r / "requirements.txt")
    (r / "installer").mkdir()
    server = tmp_path / "Minecraft Server"
    server.mkdir()
    (server / "fabric-server-launch.jar").write_bytes(b"jar")
    monkeypatch.setattr(setup_tool.shutil, "which", lambda name: "/opt/java/bin/java")
    monkeypatch.setattr("agent.tailscale.tailscale_binary", lambda: None)
    monkeypatch.delenv("MCSC_SETUP_SERVER_DIR", raising=False)
    monkeypatch.delenv("MCSC_SETUP_PASSWORD", raising=False)
    monkeypatch.delenv("MCSC_ADMIN_PASSWORD_HASH", raising=False)
    monkeypatch.delenv("MCSC_SETUP_PRE", raising=False)
    return r, server


def ctx_for(r, mode="setup", **kw):
    out = []
    ctx = Context(
        mode=mode,
        root=r,
        interactive=False,
        skip_firewall=True,
        skip_startup=True,
        say=out.append,
        **kw,
    )
    return ctx, out


def snapshot(path: Path) -> dict:
    return {p.relative_to(path).as_posix(): p.read_bytes() for p in path.rglob("*") if p.is_file()}


# ---------------------------------------------------------------- file helpers
def test_yaml_edit_keeps_comments_and_layout():
    text = "server:\n  # the folder\n  directory: ''   # required\n  jar: x.jar\nnetwork:\n  host: 127.0.0.1\n"
    new, changed = set_yaml_value(text, "server.directory", r"C:\Games\MC")
    assert changed
    assert "  # the folder\n" in new
    assert r"  directory: 'C:\Games\MC'   # required" in new
    assert "  jar: x.jar" in new and "  host: 127.0.0.1" in new


def test_yaml_edit_reports_a_missing_key_instead_of_guessing():
    new, changed = set_yaml_value("server:\n  jar: x\n", "server.directory", "y")
    assert changed is False and new == "server:\n  jar: x\n"
    _, changed = set_yaml_value("network:\n  directory: x\n", "server.directory", "y")
    assert changed is False, "a same-named key in another section must not be edited"


def test_env_edit_changes_only_one_line(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# keep me\nMCSC_DISCORD_WEBHOOK=https://example/hook\nMCSC_API_TOKEN=old\n")
    write_env_value(env, "MCSC_API_TOKEN", "new")
    text = env.read_text()
    assert "# keep me" in text and "MCSC_DISCORD_WEBHOOK=https://example/hook" in text
    assert read_env(env)["MCSC_API_TOKEN"] == "new"


# ---------------------------------------------------------------- check is read-only
def test_check_on_a_fresh_copy_changes_nothing_and_explains(root):
    r, _ = root
    before = snapshot(r)
    ctx, out = ctx_for(r, mode="check")
    code = setup_tool.run(ctx)
    assert code == setup_tool.EXIT_FAILED
    assert snapshot(r) == before, "--check must not create or modify any file"
    text = "\n".join(out)
    assert "[FAIL] Configuration" in text and "config/config.yaml does not exist" in text
    assert "[FAIL] Dashboard password" in text
    assert "What to do:" in text


# ---------------------------------------------------------------- setup
def configure(root, monkeypatch):
    r, server = root
    monkeypatch.setenv("MCSC_SETUP_SERVER_DIR", str(server))
    monkeypatch.setenv("MCSC_SETUP_PASSWORD", PASSWORD)
    ctx, out = ctx_for(r)
    return setup_tool.run(ctx), out


def test_setup_configures_a_fresh_copy(root, monkeypatch):
    r, server = root
    code, out = configure(root, monkeypatch)
    assert code == setup_tool.EXIT_OK, "\n".join(out)
    config_text = (r / "config" / "config.yaml").read_text()
    assert str(server) in config_text
    assert "# Required. The folder that contains your server jar." in config_text, "comments kept"
    env = read_env(r / ".env")
    assert env["MCSC_ADMIN_PASSWORD_HASH"].startswith("pbkdf2_sha256$")
    assert env["MCSC_API_TOKEN"]
    assert "Setup completed successfully." in "\n".join(out)


def test_secrets_never_appear_in_output_or_plain_text(root, monkeypatch):
    r, _ = root
    code, out = configure(root, monkeypatch)
    printed = "\n".join(out)
    token = read_env(r / ".env")["MCSC_API_TOKEN"]
    assert PASSWORD not in printed and token not in printed
    for path in r.rglob("*"):
        if path.is_file():
            assert PASSWORD.encode() not in path.read_bytes(), f"plain password found in {path}"
    logs = PROJECT / "logs"
    for log in logs.glob("*.log") if logs.exists() else []:
        assert PASSWORD not in log.read_text(errors="replace")


def test_repeated_setup_reuses_everything(root, monkeypatch):
    r, _ = root
    configure(root, monkeypatch)
    env_before = (r / ".env").read_bytes()
    config_before = (r / "config" / "config.yaml").read_bytes()
    code, out = configure(root, monkeypatch)
    assert code == setup_tool.EXIT_OK
    assert (r / ".env").read_bytes() == env_before, "an existing password must be kept"
    assert (r / "config" / "config.yaml").read_bytes() == config_before
    text = "\n".join(out)
    assert "existing password kept" in text and "existing certificate kept" in text


def test_check_passes_on_a_configured_installation(root, monkeypatch):
    r, _ = root
    configure(root, monkeypatch)
    before = snapshot(r)
    ctx, out = ctx_for(r, mode="check")
    assert setup_tool.run(ctx) == setup_tool.EXIT_OK, "\n".join(out)
    assert snapshot(r) == before


def test_an_invalid_folder_is_rejected_then_a_valid_one_accepted(root):
    r, server = root
    answers = iter(["C:\\does\\not\\exist", str(server.parent), str(server)])
    out = []
    ctx = Context(
        mode="setup",
        root=r,
        interactive=True,
        skip_firewall=True,
        skip_startup=True,
        skip_certs=True,
        say=out.append,
        ask=lambda _: next(answers),
        ask_secret=lambda _: PASSWORD,
    )
    setup_tool.run(ctx)
    text = "\n".join(out)
    assert "The folder does not exist" in text
    assert "No .jar file was found" in text
    assert str(server) in (r / "config" / "config.yaml").read_text()


def test_mismatched_password_entries_are_retried(root, monkeypatch):
    r, server = root
    monkeypatch.setenv("MCSC_SETUP_SERVER_DIR", str(server))
    entries = iter(["short", PASSWORD, "different one 1", PASSWORD, PASSWORD])
    out = []
    ctx = Context(
        mode="setup",
        root=r,
        interactive=True,
        skip_firewall=True,
        skip_startup=True,
        skip_certs=True,
        say=out.append,
        ask=lambda _: "",
        ask_secret=lambda _: next(entries),
    )
    setup_tool.run(ctx)
    text = "\n".join(out)
    assert "Too short" in text and "did not match" in text
    assert read_env(r / ".env")["MCSC_ADMIN_PASSWORD_HASH"].startswith("pbkdf2_sha256$")


def test_a_missing_dependency_is_named(root, monkeypatch):
    r, _ = root
    (r / "requirements.txt").write_text("fastapi>=0.1\ndefinitely-not-installed-pkg>=1.0\n")
    ctx, out = ctx_for(r, mode="check")
    step = setup_tool.step_dependencies(ctx)
    assert step.status == "FAIL"
    assert "definitely-not-installed-pkg" in step.detail


def test_an_old_python_is_refused_with_instructions(root, monkeypatch):
    r, _ = root
    monkeypatch.setattr(setup_tool.sys, "version_info", (3, 9, 1, "final", 0))
    ctx, _ = ctx_for(r)
    step = setup_tool.step_python(ctx)
    assert step.status == "FAIL" and "python.org" in step.fix


def test_admin_only_steps_are_reported_not_attempted(root, monkeypatch):
    r, _ = root
    monkeypatch.setattr(setup_tool, "IS_WINDOWS", True)
    monkeypatch.setattr(setup_tool, "firewall_rule_scope", lambda: None)
    monkeypatch.setattr("installer.autostart.is_admin", lambda: False)
    ctx, out = ctx_for(r)
    ctx.skip_firewall = False
    assert setup_tool.step_firewall(ctx).status == "ADMIN"


def test_the_python_half_works_from_another_directory(tmp_path):
    """setup.ps1 changes directory itself; this proves the tool does not
    depend on it either."""
    elsewhere = tmp_path / "somewhere-else"
    elsewhere.mkdir()
    env = dict(os.environ, MCSC_STARTUP_LOG_DIR=str(tmp_path / "logs"))
    proc = subprocess.run(
        [
            sys.executable,
            str(PROJECT / "installer" / "setup_tool.py"),
            "check",
            "--skip-firewall",
            "--skip-startup",
        ],
        cwd=elsewhere,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert "Minecraft Server Controller Health Check" in proc.stdout, proc.stderr[-800:]
    assert "[" in proc.stdout and "Python" in proc.stdout
    assert list(elsewhere.iterdir()) == [], "nothing may be written to the working directory"
