"""Configuration loading for the Minecraft Server Control agent.

Configuration comes from three layers, later layers win:

1. Built-in defaults (this file)
2. config/config.yaml
3. Environment variables / .env file (secrets only)

Secrets are NEVER read from config.yaml paths that get committed; they are
read from the environment. config.yaml may reference them but the loader
only accepts secret values from the environment.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import os
import re
import types
import typing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# --------------------------------------------------------------------------
# Typed sections. Each field's default here is the only default anywhere:
# code reads ``config.monitor.restart_delay``, never
# ``config.get("monitor.restart_delay", 10)``. There is one ServerSettings
# per managed server; each server may also override parts of the monitor,
# backups and mods sections.
# --------------------------------------------------------------------------


class ConfigError(RuntimeError):
    pass


_BOOL_WORDS = {
    "1": True,
    "true": True,
    "yes": True,
    "on": True,
    "0": False,
    "false": False,
    "no": False,
    "off": False,
    "": False,
}


_EMPTY: dict[Any, Any] = {str: str, list: list, dict: dict, bool: bool}


def _coerce(name: str, hint: Any, value: Any) -> Any:
    """Turn a YAML value into the field's declared type, or raise ConfigError."""
    if value is None:
        return None
    if isinstance(hint, type) and issubclass(hint, Section):
        if not isinstance(value, dict):
            raise ConfigError(f"{name} must be a mapping")
        return hint.from_dict(value, prefix=name)
    if hint is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, int) and value in (0, 1):
            return bool(value)
        if isinstance(value, str) and value.strip().lower() in _BOOL_WORDS:
            return _BOOL_WORDS[value.strip().lower()]
        # Anything else would be a guess at what was meant.
        raise ConfigError(f"{name} must be true or false, not {value!r}")
    if hint in (int, float):
        if isinstance(value, bool):
            raise ConfigError(f"{name} must be a number, not {value!r}")
        try:
            return hint(value)
        except (TypeError, ValueError):
            raise ConfigError(f"{name} must be a number, not {value!r}") from None
    if hint is str:
        return str(value)
    return copy.deepcopy(value)


class Section:
    """Base for one config section: built from a dict, defaults filled in."""

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None, prefix: str = "") -> Any:
        data = data or {}
        hints = typing.get_type_hints(cls)
        values = {}
        for f in dataclasses.fields(cls):  # type: ignore[arg-type]
            if f.name not in data:
                continue
            hint = hints[f.name]
            value = data[f.name]
            if typing.get_origin(hint) in (typing.Union, types.UnionType):
                # "X | None": coerce to X unless the value is None.
                hint = next(a for a in typing.get_args(hint) if a is not type(None))
            elif value is None:
                # An empty YAML value ("jar:") on a field that can't be None
                # means empty for text, lists and switches, and the default
                # for numbers.
                empty = _EMPTY.get(typing.get_origin(hint) or hint)
                if empty is None:
                    continue
                value = empty()
            values[f.name] = _coerce(f"{prefix}.{f.name}".strip("."), hint, value)
        return cls(**values)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)  # type: ignore[call-overload]


@dataclass(frozen=True)
class ServerSettings(Section):
    id: str = "main"
    name: str = "Minecraft Server"
    # No default: the folder differs on every machine, and guessing one
    # would silently manage the wrong place. Set it in config/config.yaml.
    directory: str = ""
    jar: str = "fabric-server-launch.jar"
    java: str = "java"
    jvm_args: list[str] = field(default_factory=lambda: ["-Xmx6G"])
    server_args: list[str] = field(default_factory=lambda: ["nogui"])
    # raw_command, if set, replaces the whole argv. Used by tests and by
    # people with an existing start script. It is a list, never a shell
    # string, and is never taken from the API.
    raw_command: list[str] | None = None
    port: int = 25565
    max_players: int = 20
    stop_timeout: float = 90
    start_timeout: float = 300
    autostart_minecraft: bool = False


@dataclass(frozen=True)
class MonitorSettings(Section):
    auto_restart: bool = True
    restart_delay: float = 10
    max_crashes: int = 5
    crash_window_minutes: float = 10
    sample_interval: float = 10
    tps_poll_interval: float = 60
    # "auto" detects tick query / tps / spark tps once per server start.
    # Any other value is used as-is; "" or "off" disables TPS monitoring.
    tps_command: str = "auto"
    history_days: int = 14


@dataclass(frozen=True)
class ThresholdSettings(Section):
    cpu_percent: float = 90.0
    ram_percent: float = 90.0
    disk_free_gb: float = 20.0
    tps_min: float = 18.0
    mspt_max: float = 50.0


@dataclass(frozen=True)
class NetworkSettings(Section):
    host: str = "127.0.0.1"
    port: int = 8765
    allowed_origins: list[str] = field(default_factory=list)
    trust_proxy_headers: bool = False
    # At boot the Tailscale address can appear seconds after the agent
    # starts. Wait this long for it rather than exiting.
    bind_wait_seconds: float = 300


@dataclass(frozen=True)
class TlsSettings(Section):
    # HTTPS is the production interface. Turning this off is only
    # appropriate for local development on 127.0.0.1.
    enabled: bool = True
    certificate: str = "certs/agent.crt"  # relative paths resolve inside data_dir
    private_key: str = "certs/agent.key"
    ca_certificate: str = "certs/ca.crt"  # empty when Tailscale issued the cert
    # The name you actually type in the browser. Used to check that the
    # certificate covers it, and for the HTTPS self-test.
    hostname: str = ""
    http_redirect: bool = True  # small HTTP listener that only redirects
    http_redirect_port: int = 8080
    hsts: bool = True  # only ever sent over HTTPS, never over HTTP
    hsts_max_age: int = 31536000
    hsts_include_subdomains: bool = False
    expiry_warn_days: float = 14
    expiry_critical_days: float = 3
    check_interval_hours: float = 6


@dataclass(frozen=True)
class SecuritySettings(Section):
    session_hours: float = 12
    max_failed_logins: int = 5
    lockout_minutes: float = 15
    rate_limit_requests: int = 120
    rate_limit_window: float = 60


@dataclass(frozen=True)
class BackupSettings(Section):
    directory: str = "backups"
    include: list[str] = field(
        default_factory=lambda: [
            "world",
            "world_nether",
            "world_the_end",
            "server.properties",
            "config",
            "mods",
        ]
    )
    keep_daily: int = 7
    keep_weekly: int = 4
    keep_monthly: int = 3
    compression: str = "deflate"
    stop_server_for_backup: bool = False


@dataclass(frozen=True)
class ModSettings(Section):
    directory: str = "mods"
    backup_directory: str = "mod-backups"
    trash_directory: str = "mod-trash"
    modrinth_api: str = "https://api.modrinth.com/v2"
    user_agent: str = "minecraft-server-control/1.0 (self-hosted)"
    backup_before_install: bool = True
    auto_stop_for_install: bool = False
    update_check_hours: float = 12


@dataclass(frozen=True)
class EmailSettings(Section):
    host: str = ""
    port: int = 587
    use_tls: bool = True
    use_ssl: bool = False
    from_address: str = ""
    to_addresses: list[str] = field(default_factory=list)
    attach_crash_report: bool = True
    attach_log_tail: bool = True


@dataclass(frozen=True)
class NotificationSettings(Section):
    discord_enabled: bool = False
    email_enabled: bool = False
    # Which events send an alert. An event type not listed here sends none.
    events: dict[str, bool] = field(
        default_factory=lambda: {
            "server_started": True,
            "server_stopped": True,
            "server_crashed": True,
            "server_restarted": True,
            "server_recovered": True,
            "player_joined": True,
            "player_left": False,
            "high_ram": True,
            "high_cpu": True,
            "low_disk": True,
            "low_tps": True,
            "high_mspt": True,
            "backup_completed": True,
            "backup_failed": True,
            "mod_installed": True,
            "mod_removed": True,
            "mod_updated": True,
            "mod_dependency_problem": True,
            "auth_failure": True,
            "maintenance_mode": True,
            "certificate_expiring": True,
            "servers_changed": True,
        }
    )
    email: EmailSettings = field(default_factory=EmailSettings)
    min_interval_seconds: float = 300

    def event_enabled(self, key: str) -> bool:
        return bool(self.events.get(key, False))


@dataclass(frozen=True)
class LoggingSettings(Section):
    directory: str = "logs"
    level: str = "INFO"
    max_bytes: int = 5_000_000
    backup_count: int = 7


@dataclass(frozen=True)
class PathSettings(Section):
    # Where the agent keeps its own data. Empty means the fixed app-data
    # folder (see default_data_root); an existing <server>/mcsc-data is
    # copied there once on first run (agent/datafolder.py).
    data_dir: str = ""
    database: str = "mcsc.sqlite3"


@dataclass(frozen=True)
class MaintenanceSettings(Section):
    enabled: bool = False
    block_auto_restart: bool = True
    block_scheduled_tasks: bool = True
    message: str = "Maintenance in progress"


SECTIONS: dict[str, type[Section]] = {
    "server": ServerSettings,
    "monitor": MonitorSettings,
    "thresholds": ThresholdSettings,
    "network": NetworkSettings,
    "tls": TlsSettings,
    "security": SecuritySettings,
    "backups": BackupSettings,
    "mods": ModSettings,
    "notifications": NotificationSettings,
    "logging": LoggingSettings,
    "paths": PathSettings,
    "maintenance": MaintenanceSettings,
}

# Agent-wide sections. "server" is not one of them: each entry of the
# servers list is its own ServerSettings.
GLOBAL_SECTIONS = tuple(name for name in SECTIONS if name != "server")

# Sections a server entry may override, key by key, e.g.
#   servers:
#     - id: creative
#       monitor: {auto_restart: false}
SERVER_OVERRIDES = ("monitor", "backups", "mods")

# The same defaults as a plain nested dict, for merging with config.yaml.
DEFAULTS: dict[str, Any] = {name: cls().to_dict() for name, cls in SECTIONS.items()}

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SECRET_ENV_KEYS = (
    "MCSC_ADMIN_PASSWORD_HASH",
    "MCSC_API_TOKEN",
    "MCSC_SECRET_KEY",
    "MCSC_DISCORD_WEBHOOK",
    "MCSC_SMTP_USERNAME",
    "MCSC_SMTP_PASSWORD",
)

# A server id is used as a folder name, in URLs and in database rows, so it
# is kept to characters that are safe in all three on every platform.
SERVER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(10))} | {
    f"lpt{i}" for i in range(10)
}

# Written into the data folder to record which server, if any, keeps its
# files at the top level (the layout every install had before multi-server).
LAYOUT_FILE = "layout.json"
LAYOUT_VERSION = 1


def check_server_id(value: Any) -> str:
    """Return the id if it is safe as a path component, URL segment and key."""
    text = str(value if value is not None else "").strip()
    if not SERVER_ID_RE.match(text) or text.lower() in _WINDOWS_RESERVED:
        raise ConfigError(
            f"Server id {text!r} is not allowed. Use up to 64 letters, digits, '-' or '_', "
            "starting with a letter or digit."
        )
    return text


def default_data_root() -> Path:
    """The fixed app-data folder: the same place the Windows installer uses,
    so an install's data only ever moves once."""
    if os.name == "nt":
        base = os.environ.get("ProgramData") or r"C:\ProgramData"
        return Path(base) / "Minecraft Server Controller"
    xdg = os.environ.get("XDG_DATA_HOME")
    base_dir = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base_dir / "minecraft-server-controller"


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_dotenv(path: Path) -> None:
    """Minimal .env reader. Does not overwrite already-set variables."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def set_yaml_value(text: str, dotted: str, value: str) -> tuple[str, bool]:
    """Replace `section: key: value` in place, keeping comments and layout.

    Returns (new_text, changed). Only handles the two-level form this
    project's config uses; returns changed=False when the key is absent so
    the caller can fall back to a full rewrite.
    """
    section, key = dotted.split(".", 1)
    lines = text.splitlines(keepends=True)
    in_section = False
    quoted = "'" + str(value).replace("'", "''") + "'"
    for index, line in enumerate(lines):
        if re.match(rf"^{re.escape(section)}:\s*(#.*)?$", line.rstrip("\n")):
            in_section = True
            continue
        if in_section and re.match(r"^\S", line):
            break  # next top-level section
        match = re.match(rf"^(\s+){re.escape(key)}:(\s*)([^#\n]*?)(\s*#.*)?(\r?\n)?$", line)
        if in_section and match:
            indent, space, _, comment, newline = match.groups()
            lines[index] = f"{indent}{key}:{space or ' '}{quoted}{comment or ''}{newline or ''}"
            return "".join(lines), True
    return text, False


def _normalise_servers(data: dict[str, Any]) -> bool:
    """Turn a lone ``server:`` block into a one-item ``servers:`` list.

    Returns True when the data used the single-block form, so save() can
    write it back the same way while there is still only one server.
    """
    servers = data.pop("servers", None)
    single = data.pop("server", None)
    if servers:
        if not isinstance(servers, list) or not all(isinstance(s, dict) for s in servers):
            raise ConfigError("servers must be a list of server entries")
        data["servers"] = [copy.deepcopy(s) for s in servers]
        return False
    if single is not None and not isinstance(single, dict):
        raise ConfigError("server must be a mapping")
    data["servers"] = [copy.deepcopy(single or {})]
    return True


class Config:
    """Immutable-ish view over merged configuration.

    Agent-wide sections are read straight off this object
    (``config.notifications``). Everything about one Minecraft server is read
    through ``config.for_server(server_id)``. For code written before there
    were several servers, ``config.server``, ``config.server_dir``,
    ``config.backup_dir`` and friends still work and mean the first server.
    """

    def __init__(self, data: dict[str, Any], source: Path | None = None):
        self._data = data
        self._single_block = _normalise_servers(self._data)
        self.source = source
        self._sections: dict[str, Section] = {}
        self._server_cache: dict[str, dict[str, Any]] = {}
        self._views: dict[str, ServerConfig] = {}
        # Set when the data folder could not be moved: the agent then keeps
        # using the old folder for this run (see agent/datafolder.py).
        self._data_dir_override: Path | None = None
        self._layout: dict[str, Any] | None = None

    # -- loading ----------------------------------------------------------
    @classmethod
    def load(
        cls, path: str | os.PathLike | None = None, env_file: str | os.PathLike | None = None
    ) -> Config:
        root = Path(__file__).resolve().parent.parent
        env_path = Path(env_file) if env_file else root / ".env"
        load_dotenv(env_path)

        cfg_path = Path(path) if path else root / "config" / "config.yaml"
        file_data: dict[str, Any] = {}
        if cfg_path.is_file():
            loaded = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
            if loaded and not isinstance(loaded, dict):
                raise ConfigError(f"{cfg_path} must contain a YAML mapping")
            file_data = loaded or {}
        if file_data.get("server") is not None and file_data.get("servers"):
            raise ConfigError(
                f"{cfg_path} has both 'server:' and 'servers:'. Keep one: a single "
                "server can stay as 'server:', several go in the 'servers:' list."
            )
        defaults = {k: v for k, v in DEFAULTS.items() if k != "server"}
        merged = _deep_merge(defaults, file_data)
        # Record the path even when the file does not exist yet, so a later
        # save() writes back to where we were told to look rather than to a
        # guessed default location.
        cfg = cls(merged, cfg_path)
        cfg._apply_env_overrides()
        cfg.validate()
        return cfg

    def validate(self) -> None:
        """Build every typed section once, so a bad value fails at startup
        with its key name rather than later, wherever it is first used."""
        for name in GLOBAL_SECTIONS:
            self.section(name)
        seen: dict[str, str] = {}
        for index, entry in enumerate(self._data["servers"]):
            settings = self._build_server(index, entry)["server"]
            key = settings.id.lower()
            if key in seen:
                raise ConfigError(
                    f"Two servers have the id '{settings.id}'. Each id must be unique."
                )
            seen[key] = settings.id

    def _apply_env_overrides(self) -> None:
        env = os.environ
        if env.get("MCSC_HOST"):
            self._data["network"]["host"] = env["MCSC_HOST"]
        if env.get("MCSC_PORT"):
            self._data["network"]["port"] = int(env["MCSC_PORT"])
        if env.get("MCSC_SERVER_DIR"):
            self._data["servers"][0]["directory"] = env["MCSC_SERVER_DIR"]
        if env.get("MCSC_DATA_DIR"):
            self._data["paths"]["data_dir"] = env["MCSC_DATA_DIR"]
        self._invalidate()

    def _invalidate(self) -> None:
        self._sections.clear()
        self._server_cache.clear()

    # -- access -----------------------------------------------------------
    def get(self, dotted: str, default: Any = None) -> Any:
        parts = dotted.split(".")
        if parts[0] == "server":
            return self.for_server(self.default_server_id).get(dotted, default)
        node: Any = self._data
        for part in parts:
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, dotted: str, value: Any) -> None:
        parts = dotted.split(".")
        if parts[0] == "server":
            self.set_server_value(self.default_server_id, dotted, value)
            return
        node = self._data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
        self._sections.pop(parts[0], None)
        self._server_cache.clear()  # per-server sections are built on top of these

    # -- typed sections ----------------------------------------------------
    def section(self, name: str) -> Any:
        if name == "server":
            return self.server
        cached = self._sections.get(name)
        if cached is None:
            cached = SECTIONS[name].from_dict(self._data.get(name), prefix=name)
            self._sections[name] = cached
        return cached

    @property
    def monitor(self) -> MonitorSettings:
        return self.section("monitor")

    @property
    def thresholds(self) -> ThresholdSettings:
        return self.section("thresholds")

    @property
    def network(self) -> NetworkSettings:
        return self.section("network")

    @property
    def tls(self) -> TlsSettings:
        return self.section("tls")

    @property
    def security(self) -> SecuritySettings:
        return self.section("security")

    @property
    def backups(self) -> BackupSettings:
        return self.section("backups")

    @property
    def mods(self) -> ModSettings:
        return self.section("mods")

    @property
    def notifications(self) -> NotificationSettings:
        return self.section("notifications")

    @property
    def logging(self) -> LoggingSettings:
        return self.section("logging")

    @property
    def paths(self) -> PathSettings:
        return self.section("paths")

    @property
    def maintenance(self) -> MaintenanceSettings:
        return self.section("maintenance")

    # -- servers -------------------------------------------------------------
    def _build_server(self, index: int, entry: dict[str, Any]) -> dict[str, Any]:
        prefix = f"servers[{index}]" if not self._single_block else "server"
        base = {k: v for k, v in entry.items() if k not in SERVER_OVERRIDES}
        settings = ServerSettings.from_dict(base, prefix=prefix)
        check_server_id(settings.id)
        built: dict[str, Any] = {"server": settings}
        for name in SERVER_OVERRIDES:
            override = entry.get(name) or {}
            if not isinstance(override, dict):
                raise ConfigError(f"{prefix}.{name} must be a mapping")
            merged = _deep_merge(self._data.get(name) or {}, override)
            built[name] = SECTIONS[name].from_dict(merged, prefix=f"{prefix}.{name}")
        return built

    def _server_entry(self, server_id: str) -> tuple[int, dict[str, Any]]:
        for index, entry in enumerate(self._data["servers"]):
            if str(entry.get("id", ServerSettings.id)) == server_id:
                return index, entry
        raise KeyError(server_id)

    def _server_built(self, server_id: str) -> dict[str, Any]:
        cached = self._server_cache.get(server_id)
        if cached is None:
            index, entry = self._server_entry(server_id)
            cached = self._build_server(index, entry)
            self._server_cache[server_id] = cached
        return cached

    @property
    def server_ids(self) -> list[str]:
        return [str(e.get("id", ServerSettings.id)) for e in self._data["servers"]]

    @property
    def default_server_id(self) -> str:
        """The first server: what the unprefixed (pre multi-server) API and
        ``config.server`` refer to."""
        return self.server_ids[0]

    def has_server(self, server_id: str) -> bool:
        return server_id in self.server_ids

    def server_settings(self, server_id: str) -> ServerSettings:
        return self._server_built(server_id)["server"]

    def server_section(self, server_id: str, name: str) -> Any:
        return self._server_built(server_id)[name]

    def server_entry(self, server_id: str) -> dict[str, Any]:
        return copy.deepcopy(self._server_entry(server_id)[1])

    def for_server(self, server_id: str) -> ServerConfig:
        if not self.has_server(server_id):
            raise KeyError(server_id)
        view = self._views.get(server_id)
        if view is None:
            view = self._views[server_id] = ServerConfig(self, server_id)
        return view

    def set_server_value(self, server_id: str, dotted: str, value: Any) -> None:
        """Set ``server.x``, ``monitor.x``, ``backups.x`` or ``mods.x`` for one
        server. The last three become overrides on that server's entry."""
        _, entry = self._server_entry(server_id)
        parts = dotted.split(".")
        if parts[0] == "server":
            if parts[1:] == ["id"]:
                raise ConfigError("A server's id cannot be changed")
            node = entry
            keys = parts[1:]
        elif parts[0] in SERVER_OVERRIDES:
            node = entry.setdefault(parts[0], {})
            keys = parts[1:]
        else:
            raise ConfigError(f"{dotted} is not a per-server setting")
        for part in keys[:-1]:
            node = node.setdefault(part, {})
        node[keys[-1]] = value
        self._server_cache.pop(server_id, None)

    def add_server(self, entry: dict[str, Any]) -> ServerSettings:
        """Register another server. Validates before anything changes."""
        entry = copy.deepcopy(entry)
        server_id = check_server_id(entry.get("id"))
        if server_id.lower() in (s.lower() for s in self.server_ids):
            raise ConfigError(f"A server with the id '{server_id}' already exists")
        settings = self._build_server(len(self._data["servers"]), entry)["server"]
        self._data["servers"].append(entry)
        self._single_block = False
        return settings

    def remove_server(self, server_id: str) -> dict[str, Any]:
        """Unregister a server. Its folder and data are left untouched."""
        index, entry = self._server_entry(server_id)
        if len(self._data["servers"]) == 1:
            raise ConfigError("The only server cannot be removed")
        del self._data["servers"][index]
        self._server_cache.pop(server_id, None)
        self._views.pop(server_id, None)
        return entry

    def as_dict(self, redact_secrets: bool = True) -> dict[str, Any]:
        data = copy.deepcopy(self._data)
        # The first server is also given as "server", the shape the
        # dashboard and API clients have always read.
        data["server"] = self.server.to_dict()
        if redact_secrets:
            data.setdefault("notifications", {})["discord_webhook_configured"] = bool(
                self.discord_webhook
            )
            data["notifications"]["smtp_credentials_configured"] = bool(self.smtp_password)
        return data

    def save(self, path: str | os.PathLike | None = None) -> Path:
        target = (
            Path(path)
            if path
            else (self.source or Path(__file__).resolve().parent.parent / "config" / "config.yaml")
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        data = copy.deepcopy(self._data)
        servers = data.pop("servers")
        if self._single_block and len(servers) == 1:
            # Written back the way it was read while there is one server, so
            # an existing config.yaml keeps its familiar shape.
            out = {"server": servers[0], **data}
        else:
            out = {"servers": servers, **data}
        target.write_text(
            yaml.safe_dump(out, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        self.source = target
        return target

    # -- data folder -----------------------------------------------------
    @property
    def data_dir_configured(self) -> bool:
        return bool(self.paths.data_dir.strip())

    @property
    def data_dir(self) -> Path:
        if self._data_dir_override is not None:
            return self._data_dir_override
        configured = self.paths.data_dir.strip()
        if configured:
            return Path(configured).expanduser()
        return default_data_root()

    @property
    def legacy_data_dir(self) -> Path | None:
        """Where agent data lived before it moved to the app-data folder:
        ``<first server folder>/mcsc-data``. None when a data folder is set
        explicitly (it never moves then) or the server folder is not set."""
        if self.data_dir_configured or not self.server_dir_configured:
            return None
        return self.server_dir / "mcsc-data"

    def use_data_dir_for_this_run(self, path: Path) -> None:
        """Point at another data folder in memory only (never saved)."""
        self._data_dir_override = Path(path)
        self._layout = None

    @property
    def layout_path(self) -> Path:
        return self.data_dir / LAYOUT_FILE

    def layout(self) -> dict[str, Any]:
        """How the data folder is organised.

        Before multi-server, a server's backups, crash evidence and mod
        archives sat at the top of the data folder. That server keeps them
        there ("flat_server"); every other server gets servers/<id>/. Read
        from layout.json, or worked out from what is on disk when that file
        does not exist yet.
        """
        if self._layout is None:
            layout: dict[str, Any] | None = None
            try:
                loaded = json.loads(self.layout_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    layout = loaded
            except (OSError, ValueError):
                layout = None
            if layout is None:
                existing = (self.data_dir / self.paths.database).is_file()
                layout = {
                    "layout": LAYOUT_VERSION,
                    "flat_server": self.default_server_id if existing else None,
                }
            self._layout = layout
        return self._layout

    def write_layout(self) -> None:
        layout = self.layout()
        if not self.layout_path.is_file():
            self.layout_path.parent.mkdir(parents=True, exist_ok=True)
            self.layout_path.write_text(json.dumps(layout, indent=2), encoding="utf-8")

    def server_data_dir(self, server_id: str) -> Path:
        if self.layout().get("flat_server") == server_id:
            return self.data_dir
        return self.data_dir / "servers" / server_id

    def resolve_data(self, value: str) -> Path:
        p = Path(value).expanduser()
        return p if p.is_absolute() else self.data_dir / p

    @property
    def database_path(self) -> Path:
        return self.resolve_data(self.paths.database)

    @property
    def log_dir(self) -> Path:
        return self.resolve_data(self.logging.directory)

    # -- the first server (pre multi-server shorthand) ---------------------
    @property
    def server(self) -> ServerSettings:
        return self.server_settings(self.default_server_id)

    @property
    def _first(self) -> ServerConfig:
        return self.for_server(self.default_server_id)

    @property
    def server_dir_configured(self) -> bool:
        return self._first.server_dir_configured

    @property
    def server_dir(self) -> Path:
        return self._first.server_dir

    def resolve_server(self, value: str) -> Path:
        return self._first.resolve_server(value)

    @property
    def backup_dir(self) -> Path:
        return self._first.backup_dir

    @property
    def mods_dir(self) -> Path:
        return self._first.mods_dir

    @property
    def mod_backup_dir(self) -> Path:
        return self._first.mod_backup_dir

    @property
    def mod_trash_dir(self) -> Path:
        return self._first.mod_trash_dir

    @property
    def crash_dir(self) -> Path:
        return self._first.crash_dir

    # -- secrets (environment only) ---------------------------------------
    @property
    def admin_password_hash(self) -> str:
        return os.environ.get("MCSC_ADMIN_PASSWORD_HASH", "")

    @property
    def admin_username(self) -> str:
        return os.environ.get("MCSC_ADMIN_USERNAME", "admin")

    @property
    def api_token(self) -> str:
        return os.environ.get("MCSC_API_TOKEN", "")

    @property
    def discord_webhook(self) -> str:
        return os.environ.get("MCSC_DISCORD_WEBHOOK", "")

    @property
    def smtp_username(self) -> str:
        return os.environ.get("MCSC_SMTP_USERNAME", "")

    @property
    def smtp_password(self) -> str:
        return os.environ.get("MCSC_SMTP_PASSWORD", "")

    # -- TLS paths ---------------------------------------------------------
    @property
    def tls_enabled(self) -> bool:
        return self.tls.enabled

    @property
    def cert_dir(self) -> Path:
        return self.resolve_data("certs")

    @property
    def tls_certificate(self) -> Path | None:
        value = self.tls.certificate
        return self.resolve_data(value) if value else None

    @property
    def tls_private_key(self) -> Path | None:
        value = self.tls.private_key
        return self.resolve_data(value) if value else None

    @property
    def tls_ca_certificate(self) -> Path | None:
        value = self.tls.ca_certificate
        path = self.resolve_data(value) if value else None
        return path if path and path.is_file() else None

    @property
    def dashboard_hostname(self) -> str:
        """The name the browser will use. Empty means "not configured"; the
        agent reports that rather than inventing one."""
        return self.tls.hostname.strip()

    @property
    def base_url(self) -> str:
        scheme = "https" if self.tls_enabled else "http"
        host = self.dashboard_hostname or self.network.host
        return f"{scheme}://{host}:{self.network.port}"

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.log_dir):
            path.mkdir(parents=True, exist_ok=True)
        self.write_layout()
        for server_id in self.server_ids:
            self.for_server(server_id).ensure_dirs()


class ServerConfig:
    """One server's view of the configuration.

    Managers that work on one server (the process supervisor, backups, mods
    and so on) are handed one of these. It answers the same questions as
    Config did when there was only one server: ``.server`` is this server's
    settings, ``.monitor``/``.backups``/``.mods`` include its overrides, and
    the folder properties point into its own server folder and data folder.
    Anything agent-wide (notifications, thresholds, TLS, secrets) is read
    from the shared Config.
    """

    def __init__(self, root: Config, server_id: str):
        self.root = root
        self.server_id = server_id

    def __getattr__(self, name: str) -> Any:
        return getattr(self.root, name)

    @property
    def server(self) -> ServerSettings:
        return self.root.server_settings(self.server_id)

    @property
    def monitor(self) -> MonitorSettings:
        return self.root.server_section(self.server_id, "monitor")

    @property
    def backups(self) -> BackupSettings:
        return self.root.server_section(self.server_id, "backups")

    @property
    def mods(self) -> ModSettings:
        return self.root.server_section(self.server_id, "mods")

    def section(self, name: str) -> Any:
        if name == "server" or name in SERVER_OVERRIDES:
            return getattr(self, name)
        return self.root.section(name)

    def get(self, dotted: str, default: Any = None) -> Any:
        parts = dotted.split(".")
        if parts[0] == "server" and len(parts) == 2:
            entry = self.root._server_entry(self.server_id)[1]
            if parts[1] in entry:
                return entry[parts[1]]
            return getattr(self.server, parts[1], default)
        if parts[0] in SERVER_OVERRIDES:
            node: Any = getattr(self, parts[0]).to_dict()
            for part in parts[1:]:
                if not isinstance(node, dict) or part not in node:
                    return default
                node = node[part]
            return node
        return self.root.get(dotted, default)

    def set(self, dotted: str, value: Any) -> None:
        head = dotted.split(".", 1)[0]
        if head == "server" or head in SERVER_OVERRIDES:
            self.root.set_server_value(self.server_id, dotted, value)
        else:
            self.root.set(dotted, value)

    def save(self, path: str | os.PathLike | None = None) -> Path:
        return self.root.save(path)

    # -- folders -----------------------------------------------------------
    @property
    def server_dir_configured(self) -> bool:
        return bool(self.server.directory.strip())

    @property
    def server_dir(self) -> Path:
        """The Minecraft server folder.

        When it is not configured this returns a path that cannot exist,
        rather than Path(""), which Python treats as the current working
        directory. Every check that looks at it then fails with a clear
        "not configured" message instead of quietly using the wrong folder.
        """
        value = self.server.directory.strip()
        if not value:
            return PROJECT_ROOT / "<server.directory is not set in config.yaml>"
        return Path(value).expanduser()

    @property
    def data_dir(self) -> Path:
        """This server's own part of the agent data folder."""
        return self.root.server_data_dir(self.server_id)

    def resolve_data(self, value: str) -> Path:
        p = Path(value).expanduser()
        return p if p.is_absolute() else self.data_dir / p

    def resolve_server(self, value: str) -> Path:
        p = Path(value).expanduser()
        return p if p.is_absolute() else self.server_dir / p

    @property
    def backup_dir(self) -> Path:
        return self.resolve_data(self.backups.directory)

    @property
    def mods_dir(self) -> Path:
        return self.resolve_server(self.mods.directory)

    @property
    def mod_backup_dir(self) -> Path:
        return self.resolve_data(self.mods.backup_directory)

    @property
    def mod_trash_dir(self) -> Path:
        return self.resolve_data(self.mods.trash_directory)

    @property
    def crash_dir(self) -> Path:
        return self.resolve_data("crashes")

    def ensure_dirs(self) -> None:
        for path in (
            self.data_dir,
            self.backup_dir,
            self.mod_backup_dir,
            self.mod_trash_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
