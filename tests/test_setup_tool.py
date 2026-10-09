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
    shutil.copy(PROJECT / "pyproject.toml", r / "pyproject.toml")
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
    monkeypatch.delenv("MCSC_SETUP_PUSH_CONTACT", raising=False)
    # Loading the new .env puts its values in the environment; registering
    # the keys here makes sure they are taken out again after the test.
    for key in setup_tool.PUSH_KEYS:
        monkeypatch.setenv(key, "")
        monkeypatch.delenv(key)
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
    # The last answer skips the optional phone-alert contact address.
    answers = iter(["C:\\does\\not\\exist", str(server.parent), str(server), ""])
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
    (r / "pyproject.toml").write_text(
        '[project]\ndependencies = ["fastapi>=0.1", "definitely-not-installed-pkg>=1.0"]\n'
    )
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


# ---------------------------------------------------------------- phone alert keys
def test_setup_makes_the_phone_alert_keys(root, monkeypatch):
    from agent.notifications.push import key_problem

    r, _ = root
    monkeypatch.setenv("MCSC_SETUP_PUSH_CONTACT", "owner@example.com")
    code, out = configure(root, monkeypatch)
    assert code == setup_tool.EXIT_OK, "\n".join(out)
    env = read_env(r / ".env")
    assert key_problem(env["MCSC_VAPID_PUBLIC_KEY"], env["MCSC_VAPID_PRIVATE_KEY"]) is None
    assert env["MCSC_PUSH_SUBJECT"] == "mailto:owner@example.com"
    printed = "\n".join(out)
    assert "[OK] Phone alert keys" in printed
    # The private half is a secret like the password: never on screen.
    assert env["MCSC_VAPID_PRIVATE_KEY"] not in printed


def test_setup_keeps_working_phone_alert_keys(root, monkeypatch):
    r, _ = root
    configure(root, monkeypatch)
    before = read_env(r / ".env")
    _code, out = configure(root, monkeypatch)
    after = read_env(r / ".env")
    # Replacing them would sign every phone out.
    for key in setup_tool.PUSH_KEYS:
        assert after[key] == before[key]
    assert "existing keys kept" in "\n".join(out)


def test_setup_replaces_phone_alert_keys_that_cannot_work(root, monkeypatch):
    from agent.notifications.push import generate_keys, key_problem

    r, _ = root
    configure(root, monkeypatch)
    other_public, _private = generate_keys()
    write_env_value(r / ".env", "MCSC_VAPID_PUBLIC_KEY", other_public)

    ctx, out = ctx_for(r, mode="check")
    setup_tool.run(ctx)
    assert "[FAIL] Phone alert keys" in "\n".join(out)

    _code, out = configure(root, monkeypatch)
    env = read_env(r / ".env")
    assert key_problem(env["MCSC_VAPID_PUBLIC_KEY"], env["MCSC_VAPID_PRIVATE_KEY"]) is None
    assert "replaced keys" in "\n".join(out)


def test_an_install_from_before_phone_alerts_is_a_warning_not_a_failure(root, monkeypatch):
    r, _ = root
    configure(root, monkeypatch)
    lines = [
        line
        for line in (r / ".env").read_text().splitlines()
        if not line.startswith(setup_tool.PUSH_KEYS)
    ]
    (r / ".env").write_text("\n".join(lines) + "\n")

    ctx, out = ctx_for(r, mode="check")
    assert setup_tool.run(ctx) == setup_tool.EXIT_OK, "\n".join(out)
    assert "[WARN] Phone alert keys" in "\n".join(out)


def test_a_contact_that_is_not_an_email_is_not_saved(root, monkeypatch):
    r, _ = root
    monkeypatch.setenv("MCSC_SETUP_PUSH_CONTACT", "not an email")
    configure(root, monkeypatch)
    assert read_env(r / ".env")["MCSC_PUSH_SUBJECT"] == ""


# ---------------------------------------------------------------- .env lock-down
def test_a_failed_lock_down_is_a_failed_step_with_what_to_do(root, monkeypatch):
    """icacls failing used to be swallowed; now setup says so and fails."""
    monkeypatch.setattr(
        "agent.security.certs._restrict_file", lambda path: "icacls exit 5: Access is denied."
    )
    code, out = configure(root, monkeypatch)
    text = "\n".join(out)
    assert code == setup_tool.EXIT_FAILED
    assert "[FAIL] Dashboard password" in text and "Access is denied" in text
    assert "What to do: Run the setup again as an administrator" in text
    assert PASSWORD not in text


def test_check_reports_a_secrets_file_others_can_read(root, monkeypatch):
    r, _ = root
    assert configure(root, monkeypatch)[0] == setup_tool.EXIT_OK
    ctx, out = ctx_for(r, mode="check")
    setup_tool.run(ctx)
    assert any(line.startswith("[OK] Secrets file privacy") for line in out) or os.name == "nt"
    monkeypatch.setattr(
        "agent.security.certs.folder_access",
        lambda path: ("shared", "Other accounts on this PC can open it: Users"),
    )
    ctx, out = ctx_for(r, mode="check")
    setup_tool.run(ctx)
    text = "\n".join(out)
    assert "[FAIL] Secrets file privacy - Other accounts on this PC can open it: Users" in text
    assert "Run the setup again as an administrator to lock it." in text


def test_env_is_never_left_cut_off_or_unlocked(tmp_path, monkeypatch):
    """.env is written beside itself, locked down, then swapped in: a failed
    lock-down leaves the old file exactly as it was."""
    env = tmp_path / ".env"
    env.write_text("MCSC_ADMIN_PASSWORD_HASH=old\n", encoding="utf-8")
    monkeypatch.setattr("agent.security.certs._restrict_file", lambda path: "icacls exit 5")
    with pytest.raises(setup_tool.LockDownError, match=r"\.env couldn't be made private"):
        write_env_value(env, "MCSC_ADMIN_PASSWORD_HASH", "new")
    assert env.read_text(encoding="utf-8") == "MCSC_ADMIN_PASSWORD_HASH=old\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == [".env"]
    monkeypatch.setattr("agent.security.certs._restrict_file", lambda path: None)
    write_env_value(env, "MCSC_ADMIN_PASSWORD_HASH", "new")
    assert read_env(env)["MCSC_ADMIN_PASSWORD_HASH"] == "new"
    assert sorted(p.name for p in tmp_path.iterdir()) == [".env"]
