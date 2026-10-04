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
import os
import types
import typing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# --------------------------------------------------------------------------
# Typed sections. Each field's default here is the only default anywhere:
# code reads ``config.monitor.restart_delay``, never
# ``config.get("monitor.restart_delay", 10)``. ServerSettings is
# self-contained so a later version can hold one per server.
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
    # Where the agent keeps its own data. Relative paths resolve against
    # the agent data root (see Config.data_dir).
    data_dir: str = ""  # empty -> <server.directory>/mcsc-data
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


class Config:
    """Immutable-ish view over merged configuration."""

    def __init__(self, data: dict[str, Any], source: Path | None = None):
        self._data = data
        self.source = source
        self._sections: dict[str, Section] = {}

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
        merged = _deep_merge(DEFAULTS, file_data)
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
        for name in SECTIONS:
            self.section(name)

    def _apply_env_overrides(self) -> None:
        env = os.environ
        if env.get("MCSC_HOST"):
            self._data["network"]["host"] = env["MCSC_HOST"]
        if env.get("MCSC_PORT"):
            self._data["network"]["port"] = int(env["MCSC_PORT"])
        if env.get("MCSC_SERVER_DIR"):
            self._data["server"]["directory"] = env["MCSC_SERVER_DIR"]
        if env.get("MCSC_DATA_DIR"):
            self._data["paths"]["data_dir"] = env["MCSC_DATA_DIR"]
        self._sections.clear()

    # -- access -----------------------------------------------------------
    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, dotted: str, value: Any) -> None:
        parts = dotted.split(".")
        node = self._data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
        self._sections.pop(parts[0], None)

    # -- typed sections ----------------------------------------------------
    def section(self, name: str) -> Any:
        cached = self._sections.get(name)
        if cached is None:
            cached = SECTIONS[name].from_dict(self._data.get(name), prefix=name)
            self._sections[name] = cached
        return cached

    @property
    def server(self) -> ServerSettings:
        return self.section("server")

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

    def as_dict(self, redact_secrets: bool = True) -> dict[str, Any]:
        data = copy.deepcopy(self._data)
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
        target.write_text(
            yaml.safe_dump(self._data, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        self.source = target
        return target

    # -- derived paths ----------------------------------------------------
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
        configured = self.paths.data_dir
        if configured:
            return Path(configured).expanduser()
        if self.server_dir_configured:
            return self.server_dir / "mcsc-data"
        # Unconfigured: keep agent data beside the code, never in the cwd.
        return PROJECT_ROOT / "mcsc-data"

    def resolve_data(self, value: str) -> Path:
        p = Path(value).expanduser()
        return p if p.is_absolute() else self.data_dir / p

    def resolve_server(self, value: str) -> Path:
        p = Path(value).expanduser()
        return p if p.is_absolute() else self.server_dir / p

    @property
    def database_path(self) -> Path:
        return self.resolve_data(self.paths.database)

    @property
    def log_dir(self) -> Path:
        return self.resolve_data(self.logging.directory)

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
        for path in (
            self.data_dir,
            self.log_dir,
            self.backup_dir,
            self.mod_backup_dir,
            self.mod_trash_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
