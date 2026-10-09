"""The in-app updater, signed releases, the pairing code, the version
numbers a client checks, and removing the old setup.ps1 copy.

Nothing here touches the network: GitHub is a fake behind the safe
downloader's transport."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import httpx
import pytest

from agent import API_VERSION, __version__, downloads, oldcopy, signing, updates
from installer import apply_update

from .conftest import PASSWORD
from .test_helpers import add_helper

REPO = downloads.REPO
NEXT = "9.0.0"
SETUP = updates.asset_name(NEXT)
SETUP_BYTES = b"MZ pretend setup program " * 400


@pytest.fixture
def key(monkeypatch):
    private, public = signing.new_key()
    monkeypatch.setattr(signing, "UPDATE_PUBLIC_KEY", public)
    return private


def signed_files(private: str, version: str = NEXT, data: bytes = SETUP_BYTES, **change):
    fields = {
        "repo": REPO,
        "version": version,
        "file": updates.asset_name(version),
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        **change,
    }
    document = signing.release_document(**fields)
    return document, signing.sign(document, private)


def release_json(version: str = NEXT, **extra):
    base = f"https://github.com/{REPO}/releases/download/v{version}/"
    names = [
        updates.asset_name(version),
        signing.release_file_name(version),
        signing.release_file_name(version) + ".sig",
    ]
    data = {
        "tag_name": f"v{version}",
        "draft": False,
        "prerelease": False,
        "body": "- Plain words about what changed",
        "html_url": f"https://github.com/{REPO}/releases/tag/v{version}",
        "published_at": "2026-10-09T00:00:00Z",
        "assets": [
            {"name": n, "browser_download_url": base + n, "size": len(SETUP_BYTES)} for n in names
        ],
    }
    data.update(extra)
    return data


@pytest.fixture
def github(monkeypatch, key):
    """A fake GitHub with one newer release. Change .files to tamper."""

    class Fake:
        release = release_json()
        document, signature = signed_files(key)
        setup = SETUP_BYTES
        asked: list[str] = []

        def handler(self, request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            self.asked.append(url)
            if url.endswith("/releases/latest"):
                return httpx.Response(200, json=self.release)
            if url.endswith("/update.json"):
                return httpx.Response(200, content=self.document)
            if url.endswith("/update.json.sig"):
                return httpx.Response(200, text=self.signature)
            if url.endswith(".exe"):
                return httpx.Response(200, content=self.setup)
            return httpx.Response(404)

    fake = Fake()
    monkeypatch.setattr(downloads, "TRANSPORT", httpx.MockTransport(fake.handler))
    return fake


@pytest.fixture
def installed(tmp_path, monkeypatch, multi_client):
    """Make the running app look installed by the Windows installer."""
    program = tmp_path / "Program Files" / "Minecraft Server Controller"
    program.mkdir(parents=True)
    core = multi_client.app.state.core
    (program / "install.json").write_text(
        json.dumps({"version": __version__, "data_root": str(core.config.data_dir)}),
        encoding="utf-8",
    )
    monkeypatch.setenv("MCSC_PROGRAM_DIR", str(program))
    return program


@pytest.fixture
def task_runs(monkeypatch):
    calls: list[bool] = []
    monkeypatch.setattr(updates, "run_updater_task", lambda: calls.append(True))
    return calls


def wait(client, job_id):
    for _ in range(200):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("the job never finished")


# ====================================================================
# signed release files
# ====================================================================
def test_a_good_signature_is_accepted(key):
    document, signature = signed_files(key)
    signed = signing.verify(document, signature, repo=REPO, version=NEXT, file=SETUP)
    assert signed.sha256 == hashlib.sha256(SETUP_BYTES).hexdigest()
    assert signed.size == len(SETUP_BYTES)


def test_a_release_signed_with_another_key_is_refused(key):
    other, _ = signing.new_key()
    document, signature = signed_files(other)
    with pytest.raises(signing.SignatureError, match="isn't signed with this app's key"):
        signing.verify(document, signature, repo=REPO, version=NEXT, file=SETUP)


def test_a_changed_release_file_is_refused(key):
    document, signature = signed_files(key)
    tampered = document.replace(b'"size"', b'"size" ')
    with pytest.raises(signing.SignatureError):
        signing.verify(tampered, signature, repo=REPO, version=NEXT, file=SETUP)


@pytest.mark.parametrize(
    "change",
    [{"repo": "someone/else"}, {"version": "9.0.1"}, {"file": "other.exe"}],
)
def test_a_signed_file_for_something_else_is_refused(key, change):
    document, signature = signed_files(key, **change)
    with pytest.raises(signing.SignatureError, match="different"):
        signing.verify(document, signature, repo=REPO, version=NEXT, file=SETUP)


def test_without_a_built_in_key_nothing_is_installed(monkeypatch):
    monkeypatch.setattr(signing, "UPDATE_PUBLIC_KEY", "")
    with pytest.raises(signing.SignatureError, match="no key"):
        signing.verify(b"{}", "", repo=REPO, version=NEXT, file=SETUP)
    assert not signing.has_key()


def test_the_release_script_refuses_a_key_that_isnt_built_in(key, tmp_path):
    from scripts.sign_release import sign_setup

    setup = tmp_path / SETUP
    setup.write_bytes(SETUP_BYTES)
    document, sig = sign_setup(setup, key)
    signed = signing.verify(
        document.read_bytes(), sig.read_text(), repo=REPO, version=NEXT, file=SETUP
    )
    assert signed.sha256 == hashlib.sha256(SETUP_BYTES).hexdigest()
    other, _ = signing.new_key()
    with pytest.raises(SystemExit, match="isn't the key built into"):
        sign_setup(setup, other)


def test_the_key_script_writes_only_the_public_half(tmp_path):
    from scripts.make_update_key import write_public_key

    copy = tmp_path / "signing.py"
    copy.write_text(Path(signing.__file__).read_text(encoding="utf-8"), encoding="utf-8")
    private, public = signing.new_key()
    write_public_key(public, copy)
    text = copy.read_text(encoding="utf-8")
    assert f'UPDATE_PUBLIC_KEY = "{public}"' in text
    assert private not in text


# ====================================================================
# what GitHub says
# ====================================================================
def test_only_finished_releases_of_this_repo_are_offered():
    assert updates.parse_release(release_json()).version == NEXT
    with pytest.raises(updates.UpdateError, match="test version"):
        updates.parse_release(release_json(prerelease=True))
    with pytest.raises(updates.UpdateError, match="test version"):
        updates.parse_release(release_json(draft=True))
    missing = release_json()
    missing["assets"] = missing["assets"][:1]
    with pytest.raises(updates.UpdateError, match="signed release file"):
        updates.parse_release(missing)
    elsewhere = release_json()
    elsewhere["assets"][0]["browser_download_url"] = "https://example.com/" + SETUP
    with pytest.raises(updates.UpdateError, match="own GitHub page"):
        updates.parse_release(elsewhere)


def test_versions_compare_as_numbers():
    assert updates.is_newer("1.10.0", "1.9.9")
    assert not updates.is_newer("1.2.0", "1.2.0")
    assert not updates.is_newer("1.1.9", "1.2.0")
    assert not updates.is_newer("latest", "1.2.0")


def test_only_this_apps_release_addresses_are_allowed():
    downloads.check_url(f"https://api.github.com/repos/{REPO}/releases/latest")
    downloads.check_url(f"https://github.com/{REPO}/releases/download/v1.2.0/{SETUP}")
    for url in (
        "https://api.github.com/repos/someone/else/releases/latest",
        f"https://github.com/someone/else/releases/download/v1.2.0/{SETUP}",
        "https://github.com/login",
    ):
        with pytest.raises(downloads.DownloadError):
            downloads.check_url(url)


# ====================================================================
# checking and installing from the dashboard
# ====================================================================
def test_check_now_finds_the_new_version_and_says_so_once(multi_client, github, installed):
    status = multi_client.post("/api/updates/check").json()
    assert status["available"] is True
    assert status["latest"]["version"] == NEXT
    assert status["can_install"] is True
    assert "Plain words" in status["latest"]["notes"]
    core = multi_client.app.state.core
    assert core.db.get_setting("updates:announced", None) == NEXT
    asked = [u for u in github.asked if "releases/latest" in u]
    assert asked == [f"https://api.github.com/repos/{REPO}/releases/latest"]


def test_an_older_release_is_not_offered(multi_client, github, installed):
    github.release = release_json("0.0.1")
    status = multi_client.post("/api/updates/check").json()
    assert status["available"] is False
    assert status["can_install"] is False
    assert multi_client.post("/api/updates/install").status_code == 400


def test_install_downloads_checks_backs_up_and_hands_over(
    multi_client, github, installed, task_runs
):
    multi_client.post("/api/updates/check")
    preflight = multi_client.get("/api/updates/preflight").json()
    assert preflight["players_online"] in (0, None)
    started = multi_client.post("/api/updates/install")
    assert started.status_code == 200, started.text
    job = wait(multi_client, started.json()["job"]["id"])
    assert job["state"] == "succeeded", job["message"]
    assert task_runs == [True]
    core = multi_client.app.state.core
    folder = updates.updates_dir(core.config)
    request = json.loads((folder / "request.json").read_text(encoding="utf-8"))
    assert request["version"] == NEXT
    assert request["sha256"] == hashlib.sha256(SETUP_BYTES).hexdigest()
    assert (folder / NEXT / updates.download_name(NEXT)).read_bytes() == SETUP_BYTES
    assert not list(folder.rglob("*.exe"))  # the agent never writes a program
    backup = Path(request["backup"])
    assert (backup / Path(core.config.database_path).name).is_file()


def test_a_setup_file_that_doesnt_match_the_signature_is_refused(
    multi_client, github, installed, task_runs
):
    github.setup = SETUP_BYTES + b"something added"
    multi_client.post("/api/updates/check")
    job = wait(multi_client, multi_client.post("/api/updates/install").json()["job"]["id"])
    assert job["state"] == "failed"
    assert task_runs == []
    folder = updates.updates_dir(multi_client.app.state.core.config)
    assert not (folder / "request.json").exists()
    assert not list((folder / NEXT).glob("*")) if (folder / NEXT).exists() else True


def test_a_release_signed_by_someone_else_is_refused(multi_client, github, installed, task_runs):
    other, _ = signing.new_key()
    github.document, github.signature = signed_files(other)
    multi_client.post("/api/updates/check")
    job = wait(multi_client, multi_client.post("/api/updates/install").json()["job"]["id"])
    assert job["state"] == "failed"
    assert "isn't signed with this app's key" in (job["message"] or "")
    assert task_runs == []
    assert not any(u.endswith(".exe") for u in github.asked)  # never even downloaded


def test_a_setup_ps1_copy_is_told_to_run_the_installer_once(multi_client, github, task_runs):
    status = multi_client.post("/api/updates/check").json()
    assert status["install_kind"] == "project"
    assert status["can_install"] is False
    assert "setup.ps1" in status["cannot_install_reason"]
    assert multi_client.post("/api/updates/install").status_code == 400
    assert task_runs == []


def test_a_copy_without_the_key_does_not_install(
    multi_client, github, installed, task_runs, monkeypatch
):
    multi_client.post("/api/updates/check")
    monkeypatch.setattr(signing, "UPDATE_PUBLIC_KEY", "")
    status = multi_client.get("/api/updates").json()
    assert status["can_install"] is False
    assert "key" in status["cannot_install_reason"]
    assert multi_client.post("/api/updates/install").status_code == 400


def test_a_helper_can_see_but_not_install(multi_client, github, installed, task_runs):
    owner = dict(multi_client.headers)
    helper = add_helper(multi_client, owner)
    multi_client.post("/api/updates/check")
    assert multi_client.get("/api/updates", headers=helper).status_code == 200
    for method, path in (
        ("post", "/api/updates/check"),
        ("get", "/api/updates/preflight"),
        ("post", "/api/updates/install"),
        ("post", "/api/updates/old-copy/remove"),
    ):
        assert getattr(multi_client, method)(path, headers=helper).status_code == 403
    assert task_runs == []


def test_the_outcome_of_an_update_is_announced_once(multi_client):
    core = multi_client.app.state.core
    folder = updates.updates_dir(core.config)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / updates.RESULT_FILE).write_text(
        json.dumps(
            {"ok": False, "version": NEXT, "rolled_back": True, "from_app": True, "message": "x"}
        ),
        encoding="utf-8",
    )
    seen = []
    core.bus.subscribe(lambda event: seen.append(event))
    import asyncio

    asyncio.run(core.updates._announce_last_result())
    asyncio.run(core.updates._announce_last_result())
    failed = [e for e in seen if e.type == "update_failed"]
    assert len(failed) == 1
    assert "previous version was put back" in failed[0].message
    assert multi_client.get("/api/updates").json()["last_result"]["rolled_back"] is True


# ====================================================================
# the update task's own checks (installer/apply_update.py)
# ====================================================================
@pytest.fixture
def update_task(tmp_path, monkeypatch, key, github):
    program = tmp_path / "program"
    data = tmp_path / "data"
    program.mkdir()
    (program / "install.json").write_text(
        json.dumps({"version": "1.2.0", "data_root": str(data)}), encoding="utf-8"
    )
    monkeypatch.setenv("MCSC_PROGRAM_DIR", str(program))
    folder = data / "updates"
    (folder / NEXT).mkdir(parents=True)
    (folder / NEXT / updates.download_name(NEXT)).write_bytes(SETUP_BYTES)
    started: list[tuple[Path, list[str]]] = []
    monkeypatch.setattr(apply_update, "start", lambda setup, args: started.append((setup, args)))

    def request(**body):
        (folder / "request.json").write_text(json.dumps({"version": NEXT, **body}), "utf-8")

    def result():
        path = folder / updates.RESULT_FILE
        return json.loads(path.read_text("utf-8")) if path.exists() else None

    return request, result, started, folder, program


def test_the_update_task_runs_a_checked_file_with_fixed_arguments(update_task):
    request, result, started, folder, program = update_task
    request(file="anything-else.exe", arguments=["--evil"])
    assert apply_update.main() == 0
    staged = program.with_name("program.update") / SETUP
    assert started == [
        (staged, ["--update", "--quiet", "--from-app", "--program-dir", str(program)])
    ]
    assert staged.read_bytes() == SETUP_BYTES
    assert not (folder / "request.json").exists()


def test_the_update_task_refuses_a_changed_file(update_task):
    request, result, started, folder, _ = update_task
    (folder / NEXT / updates.download_name(NEXT)).write_bytes(SETUP_BYTES + b"!")
    request()
    assert apply_update.main() == 1
    assert started == []
    assert "doesn't match the signed release" in result()["message"]


def test_the_update_task_refuses_going_backwards(update_task):
    request, result, started, folder, _ = update_task
    (folder / "request.json").write_text(json.dumps({"version": "1.0.0"}), "utf-8")
    assert apply_update.main() == 1
    assert started == []
    assert "isn't newer" in result()["message"]


def test_the_update_task_refuses_a_bad_signature(update_task, github):
    request, result, started, _, _ = update_task
    other, _ = signing.new_key()
    github.document, github.signature = signed_files(other)
    request()
    assert apply_update.main() == 1
    assert started == []
    assert "isn't signed" in result()["message"]


# ====================================================================
# version, health and the pairing code
# ====================================================================
def test_health_and_version_name_the_api_version(multi_client):
    health = multi_client.get("/api/health", headers={"Authorization": ""}).json()
    assert health["api_version"] == API_VERSION
    assert "version" not in health  # the app's version only after sign-in
    version = multi_client.get("/api/version").json()
    assert version == {"version": __version__, "api_version": API_VERSION}


def test_the_pairing_code_holds_the_address_fingerprint_and_api_version(config, monkeypatch):
    from agent.pairing import pairing_code
    from agent.security import certs
    from agent.security.tls import fingerprint

    certs.issue_server_certificate(config.cert_dir, ["pc.ts.net"], [])
    monkeypatch.setattr(type(config), "dashboard_hostname", property(lambda self: "pc.ts.net"))
    monkeypatch.setattr(type(config), "tls_enabled", property(lambda self: True))
    monkeypatch.setenv("MCSC_ADMIN_PASSWORD_HASH", "pbkdf2$secret-hash")
    monkeypatch.setenv("MCSC_API_TOKEN", "secret-token-value")
    code = pairing_code(config)
    assert code["ok"] is True, code["reason"]
    expected = fingerprint(config.tls_certificate).replace(":", "").lower()
    assert code["fingerprint"] == expected and len(expected) == 64
    port = config.network.port
    assert code["url"] == f"https://pc.ts.net:{port}/?pair=1&fp={expected}&api={API_VERSION}"
    rows = code["qr"]
    assert len(rows) == len(rows[0]) >= 21 and set("".join(rows)) == {"0", "1"}
    text = json.dumps(code)
    for secret in ("secret-hash", "secret-token-value", PASSWORD):
        assert secret not in text


def test_no_pairing_code_without_https(config, monkeypatch):
    from agent.pairing import pairing_code

    monkeypatch.setattr(type(config), "tls_enabled", property(lambda self: False))
    code = pairing_code(config)
    assert code["ok"] is False
    assert "HTTPS" in code["reason"]
    assert code["url"] is None


def test_the_pairing_route_needs_sign_in(multi_client):
    assert multi_client.get("/api/pairing", headers={"Authorization": ""}).status_code == 401
    assert multi_client.get("/api/pairing").json()["api_version"] == API_VERSION


# ====================================================================
# the old setup.ps1 copy
# ====================================================================
@pytest.fixture
def old_copy(tmp_path, config, monkeypatch):
    old = tmp_path / "old-copy"
    for name in ("agent", "installer", "config", ".venv"):
        (old / name).mkdir(parents=True)
        (old / name / "file.txt").write_text("x", encoding="utf-8")
    (old / ".env").write_text("MCSC_API_TOKEN=old", encoding="utf-8")
    (old / "setup.ps1").write_text("x", encoding="utf-8")
    (old / "my notes.txt").write_text("mine", encoding="utf-8")
    (old / "backups").mkdir()
    (old / "backups" / "world.zip").write_bytes(b"zip")
    program = tmp_path / "program"
    program.mkdir()
    (program / "install.json").write_text(
        json.dumps({"version": "1.2.0", "data_root": str(config.data_dir)}), encoding="utf-8"
    )
    monkeypatch.setenv("MCSC_PROGRAM_DIR", str(program))
    moved = time.time() - 8 * 86400
    record = {
        "path": str(old),
        "version": "1.1.0",
        "moved_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(moved)),
    }
    (Path(config.data_dir) / oldcopy.RECORD).write_text(json.dumps(record), encoding="utf-8")
    return old


def test_the_old_copy_is_offered_after_a_few_days(config, old_copy):
    status = oldcopy.status(config)
    assert status["offer"] is True
    assert status["problems"] == []
    assert status["path"] == str(old_copy)
    soon = oldcopy.status(config, now=time.time() - 7.5 * 86400)
    assert soon["offer"] is False


def test_removing_the_old_copy_keeps_backups_and_unknown_files(config, old_copy):
    result = oldcopy.remove(config)
    assert result["ok"] is True
    assert sorted(result["kept"]) == ["backups", "my notes.txt"]
    assert (old_copy / "backups" / "world.zip").read_bytes() == b"zip"
    assert (old_copy / "my notes.txt").is_file()
    for name in ("agent", "installer", "config", ".venv", ".env", "setup.ps1"):
        assert not (old_copy / name).exists()
    assert oldcopy.status(config) is None  # not offered again


def test_a_git_checkout_is_never_removed(config, old_copy):
    (old_copy / ".git").mkdir()
    assert oldcopy.status(config)["problems"]
    with pytest.raises(oldcopy.OldCopyError, match="git checkout"):
        oldcopy.remove(config)
    assert (old_copy / "agent").is_dir()


def test_a_folder_holding_a_server_is_never_removed(config, old_copy, monkeypatch):
    server = config.for_server(config.server_ids[0])
    monkeypatch.setattr(type(server), "server_dir", property(lambda self: old_copy / "world"))
    with pytest.raises(oldcopy.OldCopyError, match="server folder"):
        oldcopy.remove(config)
    assert (old_copy / "agent").is_dir()
