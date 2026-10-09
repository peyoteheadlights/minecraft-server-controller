import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.config import DEFAULTS, Config, _deep_merge  # noqa: E402

FAKE_SERVER = Path(__file__).resolve().parent / "fixtures" / "fake_server.py"
FAKE_BEDROCK = Path(__file__).resolve().parent / "fixtures" / "fake_bedrock_server.py"
PASSWORD = "correct horse battery"


def api_routes_source() -> str:
    """The source of every API router, for tests that inspect route code."""
    import inspect

    from agent.api import routes

    return "\n".join(inspect.getsource(module) for module in (routes, *routes.MODULES))


def make_server_folder(folder: Path, port: int = 25565) -> Path:
    """A throwaway Minecraft server folder with a jar, worlds and a log."""
    for sub in (
        "mods",
        "config",
        "world",
        "world_nether",
        "world_the_end",
        "logs",
        "crash-reports",
    ):
        (folder / sub).mkdir(parents=True, exist_ok=True)
    (folder / "fabric-server-launch.jar").write_bytes(b"not a real jar")
    (folder / "server.properties").write_text(
        f"server-port={port}\nmax-players=20\n", encoding="utf-8"
    )
    (folder / "world" / "level.dat").write_bytes(b"x" * 2048)
    (folder / "logs" / "latest.log").write_text(
        "[10:00:00] [Server thread/INFO]: hello\n", encoding="utf-8"
    )
    return folder


def fake_server_entry(server_id: str, name: str, folder: Path, port: int = 25565) -> dict:
    return {
        "id": server_id,
        "name": name,
        "directory": str(folder),
        "raw_command": [sys.executable, str(FAKE_SERVER)],
        "port": port,
        "stop_timeout": 10,
        "start_timeout": 20,
    }


def make_bedrock_folder(folder: Path, port: int = 19132, level: str = "Bedrock level") -> Path:
    """A throwaway Bedrock Dedicated Server folder laid out like Mojang's
    download after a first start: the program, server.properties, the
    player files and a world with a LevelDB folder."""
    from agent.minecraft import nbt

    world = folder / "worlds" / level
    (world / "db").mkdir(parents=True, exist_ok=True)
    (world / "db" / "000005.ldb").write_bytes(b"L" * 4096)
    (world / "db" / "CURRENT").write_text("MANIFEST-000004\n", encoding="utf-8")
    (world / "level.dat").write_bytes(nbt.bedrock_level_for_tests(level, [1, 21, 95, 1, 0]))
    (world / "levelname.txt").write_text(level, encoding="utf-8")
    (folder / "bedrock_server.exe").write_bytes(b"MZ not a real program")
    (folder / "behavior_packs" / "vanilla").mkdir(parents=True, exist_ok=True)
    (folder / "resource_packs" / "vanilla").mkdir(parents=True, exist_ok=True)
    (folder / "server.properties").write_text(
        "# Mojang's comments stay\n"
        "server-name=Dedicated Server\n"
        "gamemode=survival\n"
        f"server-port={port}\n"
        f"server-portv6={port + 1}\n"
        f"level-name={level}\n"
        "max-players=10\n"
        "allow-list=false\n",
        encoding="utf-8",
    )
    (folder / "allowlist.json").write_text("[]", encoding="utf-8")
    (folder / "permissions.json").write_text("[]", encoding="utf-8")
    return folder


def bedrock_entry(server_id: str, name: str, folder: Path, port: int = 19132) -> dict:
    return {
        "id": server_id,
        "name": name,
        "directory": str(folder),
        "type": "bedrock",
        "jar": "bedrock_server.exe",
        "jvm_args": [],
        "raw_command": [sys.executable, str(FAKE_BEDROCK)],
        "port": port,
        "stop_timeout": 10,
        "start_timeout": 20,
    }


def build_bedrock_config(tmp_path: Path, java: bool = False, **overrides) -> Config:
    """One fake Bedrock server (and, with ``java``, a fake Java one too)."""
    entries = [bedrock_entry("bedrock", "Bedrock", make_bedrock_folder(tmp_path / "bedrock"))]
    if java:
        folder = make_server_folder(tmp_path / "servers" / "Java", 25565)
        entries.append(fake_server_entry("java", "Java", folder, 25565))
    data = {
        "servers": entries,
        "paths": {"data_dir": str(tmp_path / "mcsc-data")},
        "monitor": {"auto_restart": False, "restart_delay": 0.2, "sample_interval": 1},
        "notifications": {"discord_enabled": False, "email_enabled": False},
    }
    merged = _deep_merge({k: v for k, v in DEFAULTS.items() if k != "server"}, data)
    for key, value in overrides.items():
        node = merged
        parts = key.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    cfg = Config(merged, tmp_path / "config.yaml")
    cfg.ensure_dirs()
    return cfg


def build_multi_config(tmp_path: Path, servers=None, **overrides) -> Config:
    """Two (or more) fake servers side by side in one agent."""
    servers = servers or [("survival", "Survival", 25565), ("creative", "Creative", 25566)]
    entries = []
    for server_id, name, port in servers:
        folder = make_server_folder(tmp_path / "servers" / name, port)
        entries.append(fake_server_entry(server_id, name, folder, port))
    data = {
        "servers": entries,
        "paths": {"data_dir": str(tmp_path / "mcsc-data")},
        "monitor": {"auto_restart": False, "restart_delay": 0.2, "sample_interval": 1},
        "notifications": {"discord_enabled": False, "email_enabled": False},
    }
    merged = _deep_merge({k: v for k, v in DEFAULTS.items() if k != "server"}, data)
    for key, value in overrides.items():
        node = merged
        parts = key.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    cfg = Config(merged, tmp_path / "config.yaml")
    cfg.ensure_dirs()
    return cfg


def build_config(tmp_path: Path, **overrides) -> Config:
    """A config pointing at a throwaway 'Minecraft Server' folder.

    The launch command is replaced with a small Python fake server, so the
    whole lifecycle is exercised without a JVM and without touching a real
    world folder.
    """
    mc_dir = tmp_path / "Minecraft Server"
    for sub in (
        "mods",
        "config",
        "world",
        "world_nether",
        "world_the_end",
        "logs",
        "crash-reports",
    ):
        (mc_dir / sub).mkdir(parents=True, exist_ok=True)
    (mc_dir / "fabric-server-launch.jar").write_bytes(b"not a real jar")
    (mc_dir / "server.properties").write_text(
        "server-port=25565\nmax-players=20\n", encoding="utf-8"
    )
    (mc_dir / "world" / "level.dat").write_bytes(b"x" * 2048)
    (mc_dir / "logs" / "latest.log").write_text(
        "[10:00:00] [Server thread/INFO]: hello\n", encoding="utf-8"
    )

    data = {
        "server": {
            "id": "test",
            "name": "Test Server",
            "directory": str(mc_dir),
            "raw_command": [sys.executable, str(FAKE_SERVER)],
            "stop_timeout": 10,
            "start_timeout": 20,
        },
        "paths": {"data_dir": str(tmp_path / "mcsc-data")},
        "monitor": {"auto_restart": False, "restart_delay": 0.2, "sample_interval": 1},
        "notifications": {"discord_enabled": False, "email_enabled": False},
    }
    merged = _deep_merge(DEFAULTS, data)
    for key, value in overrides.items():
        node = merged
        parts = key.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    # Point the config at a throwaway file so anything that calls save()
    # (the settings API, for instance) writes into tmp_path, never into
    # the real project folder.
    cfg = Config(merged, tmp_path / "config.yaml")
    cfg.ensure_dirs()
    return cfg


@pytest.fixture
def config(tmp_path):
    return build_config(tmp_path)


@pytest.fixture
def make_config(tmp_path):
    def _make(**overrides):
        return build_config(tmp_path, **overrides)

    return _make


@pytest.fixture
def client(config, monkeypatch):
    """The real app, signed in as admin with PASSWORD."""
    from fastapi.testclient import TestClient

    from agent.main import create_app
    from agent.security.auth import hash_password

    monkeypatch.setenv("MCSC_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("MCSC_ADMIN_PASSWORD_HASH", hash_password(PASSWORD, rounds=1000))
    monkeypatch.delenv("MCSC_API_TOKEN", raising=False)
    with TestClient(create_app(config)) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def quick_password_hashing(monkeypatch):
    """Tests hash with 1,000 rounds (the real count takes about half a
    second per sign-in); test_password_rehash covers the real figure."""
    from agent.security import auth

    monkeypatch.setattr(auth, "PBKDF2_ROUNDS", 1000)


@pytest.fixture(autouse=True)
def isolated_startup_log(tmp_path_factory, monkeypatch):
    """Never let a test write into the project's real logs/startup.log."""
    from agent import startup_diag

    directory = tmp_path_factory.mktemp("startup-logs")
    monkeypatch.setenv("MCSC_STARTUP_LOG_DIR", str(directory))
    startup_diag.set_log_dir(directory)
    yield directory
    startup_diag.set_log_dir(directory)


@pytest.fixture(autouse=True)
def isolated_app_data(tmp_path_factory, monkeypatch):
    """The default data folder (%ProgramData% or ~/.local/share) always
    points into a throwaway folder, never at the real one."""
    base = tmp_path_factory.mktemp("app-data")
    monkeypatch.setenv("ProgramData", str(base))
    monkeypatch.setenv("XDG_DATA_HOME", str(base))
    return base


@pytest.fixture(autouse=True)
def clean_fake_env():
    keys = [
        "FAKE_CRASH_ON_START",
        "FAKE_MIXIN_CRASH",
        "FAKE_HANG",
        "FAKE_BOOT_DELAY",
        "FAKE_TYPE",
        "FAKE_MC_VERSION",
        "FAKE_LOADER_VERSION",
        "FAKE_CHECK_EULA",
        "FAKE_BEDROCK_VERSION",
        "FAKE_SAVE_QUERY",
    ]
    saved = {k: os.environ.pop(k, None) for k in keys}
    yield
    for k, v in saved.items():
        os.environ.pop(k, None)
        if v is not None:
            os.environ[k] = v


@pytest.fixture
def multi(tmp_path):
    return build_multi_config(tmp_path)


@pytest.fixture
def multi_client(multi, monkeypatch):
    """The real app with several servers, signed in as admin."""
    from fastapi.testclient import TestClient

    from agent.main import create_app
    from agent.security.auth import hash_password

    monkeypatch.setenv("MCSC_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("MCSC_ADMIN_PASSWORD_HASH", hash_password(PASSWORD, rounds=1000))
    monkeypatch.delenv("MCSC_API_TOKEN", raising=False)
    with TestClient(create_app(multi)) as client:
        token = client.post(
            "/api/auth/login", json={"username": "admin", "password": PASSWORD}
        ).json()["token"]
        client.headers["Authorization"] = f"Bearer {token}"
        yield client
