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
import os
from pathlib import Path
from typing import Any

import yaml

# --------------------------------------------------------------------------
# Defaults
# --------------------------------------------------------------------------

DEFAULTS: dict[str, Any] = {
    "server": {
        "id": "main",
        "name": "Minecraft Server",
        # No default: the folder differs on every machine, and guessing one
        # would silently manage the wrong place. Set it in config/config.yaml.
        "directory": "",
        "jar": "fabric-server-launch.jar",
        "java": "java",
        "jvm_args": ["-Xmx6G"],
        "server_args": ["nogui"],
        # raw_command, if set, replaces the whole argv. Used by tests and by
        # people with an existing start script. It is a list, never a shell
        # string, and is never taken from the API.
        "raw_command": None,
        "port": 25565,
        "max_players": 20,
        "stop_timeout": 90,
        "start_timeout": 300,
        "autostart_minecraft": False,
    },
    "monitor": {
        "auto_restart": True,
        "restart_delay": 10,
        "max_crashes": 5,
        "crash_window_minutes": 10,
        "sample_interval": 10,
        "tps_poll_interval": 60,
        # "auto" detects tick query / tps / spark tps once per server start.
        # Any other value is used as-is; "" or "off" disables TPS monitoring.
        "tps_command": "auto",
        "history_days": 14,
    },
    "thresholds": {
        "cpu_percent": 90.0,
        "ram_percent": 90.0,
        "disk_free_gb": 20.0,
        "tps_min": 18.0,
        "mspt_max": 50.0,
    },
    "network": {
        "host": "127.0.0.1",
        "port": 8765,
        "allowed_origins": [],
        "trust_proxy_headers": False,
        # At boot the Tailscale address can appear seconds after the agent
        # starts. Wait this long for it rather than exiting.
        "bind_wait_seconds": 300,
    },
    "tls": {
        # HTTPS is the production interface. Turning this off is only
        # appropriate for local development on 127.0.0.1.
        "enabled": True,
        "certificate": "certs/agent.crt",   # relative paths resolve inside data_dir
        "private_key": "certs/agent.key",
        "ca_certificate": "certs/ca.crt",   # empty when Tailscale issued the cert
        # The name you actually type in the browser. Used to check that the
        # certificate covers it, and for the HTTPS self-test.
        "hostname": "",
        "http_redirect": True,              # small HTTP listener that only redirects
        "http_redirect_port": 8080,
        "hsts": True,                       # only ever sent over HTTPS, never over HTTP
        "hsts_max_age": 31536000,
        "hsts_include_subdomains": False,
        "expiry_warn_days": 14,
        "expiry_critical_days": 3,
        "check_interval_hours": 6,
    },
    "security": {
        "session_hours": 12,
        "max_failed_logins": 5,
        "lockout_minutes": 15,
        "rate_limit_requests": 120,
        "rate_limit_window": 60,
    },
    "backups": {
        "directory": "backups",
        "include": [
            "world",
            "world_nether",
            "world_the_end",
            "server.properties",
            "config",
            "mods",
        ],
        "keep_daily": 7,
        "keep_weekly": 4,
        "keep_monthly": 3,
        "compression": "deflate",
        "stop_server_for_backup": False,
    },
    "mods": {
        "directory": "mods",
        "backup_directory": "mod-backups",
        "trash_directory": "mod-trash",
        "modrinth_api": "https://api.modrinth.com/v2",
        "user_agent": "minecraft-server-control/1.0 (self-hosted)",
        "backup_before_install": True,
        "auto_stop_for_install": False,
        "update_check_hours": 12,
    },
    "notifications": {
        "discord_enabled": False,
        "email_enabled": False,
        "events": {
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
        },
        "email": {
            "host": "",
            "port": 587,
            "use_tls": True,
            "use_ssl": False,
            "from_address": "",
            "to_addresses": [],
            "attach_crash_report": True,
            "attach_log_tail": True,
        },
        "min_interval_seconds": 300,
    },
    "logging": {
        "directory": "logs",
        "level": "INFO",
        "max_bytes": 5_000_000,
        "backup_count": 7,
    },
    "paths": {
        # Where the agent keeps its own data. Relative paths resolve against
        # the agent data root (see Config.data_dir).
        "data_dir": "",  # empty -> <server.directory>/mcsc-data
        "database": "mcsc.sqlite3",
    },
    "maintenance": {
        "enabled": False,
        "block_auto_restart": True,
        "block_scheduled_tasks": True,
        "message": "Maintenance in progress",
    },
}

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


class ConfigError(RuntimeError):
    pass


class Config:
    """Immutable-ish view over merged configuration."""

    def __init__(self, data: dict[str, Any], source: Path | None = None):
        self._data = data
        self.source = source

    # -- loading ----------------------------------------------------------
    @classmethod
    def load(cls, path: str | os.PathLike | None = None, env_file: str | os.PathLike | None = None) -> "Config":
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
        return cfg

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

    def as_dict(self, redact_secrets: bool = True) -> dict[str, Any]:
        data = copy.deepcopy(self._data)
        if redact_secrets:
            data.setdefault("notifications", {})["discord_webhook_configured"] = bool(self.discord_webhook)
            data["notifications"]["smtp_credentials_configured"] = bool(self.smtp_password)
        return data

    def save(self, path: str | os.PathLike | None = None) -> Path:
        target = Path(path) if path else (self.source or Path(__file__).resolve().parent.parent / "config" / "config.yaml")
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
        return bool(str(self.get("server.directory") or "").strip())

    @property
    def server_dir(self) -> Path:
        """The Minecraft server folder.

        When it is not configured this returns a path that cannot exist,
        rather than Path(""), which Python treats as the current working
        directory. Every check that looks at it then fails with a clear
        "not configured" message instead of quietly using the wrong folder.
        """
        value = str(self.get("server.directory") or "").strip()
        if not value:
            return PROJECT_ROOT / "<server.directory is not set in config.yaml>"
        return Path(value).expanduser()

    @property
    def data_dir(self) -> Path:
        configured = self.get("paths.data_dir") or ""
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
        return self.resolve_data(self.get("paths.database"))

    @property
    def log_dir(self) -> Path:
        return self.resolve_data(self.get("logging.directory"))

    @property
    def backup_dir(self) -> Path:
        return self.resolve_data(self.get("backups.directory"))

    @property
    def mods_dir(self) -> Path:
        return self.resolve_server(self.get("mods.directory"))

    @property
    def mod_backup_dir(self) -> Path:
        return self.resolve_data(self.get("mods.backup_directory"))

    @property
    def mod_trash_dir(self) -> Path:
        return self.resolve_data(self.get("mods.trash_directory"))

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
        return bool(self.get("tls.enabled", True))

    @property
    def cert_dir(self) -> Path:
        return self.resolve_data("certs")

    @property
    def tls_certificate(self) -> Path | None:
        value = self.get("tls.certificate") or ""
        return self.resolve_data(value) if value else None

    @property
    def tls_private_key(self) -> Path | None:
        value = self.get("tls.private_key") or ""
        return self.resolve_data(value) if value else None

    @property
    def tls_ca_certificate(self) -> Path | None:
        value = self.get("tls.ca_certificate") or ""
        path = self.resolve_data(value) if value else None
        return path if path and path.is_file() else None

    @property
    def dashboard_hostname(self) -> str:
        """The name the browser will use. Empty means "not configured"; the
        agent reports that rather than inventing one."""
        return str(self.get("tls.hostname") or "").strip()

    @property
    def base_url(self) -> str:
        scheme = "https" if self.tls_enabled else "http"
        host = self.dashboard_hostname or str(self.get("network.host", "127.0.0.1"))
        return f"{scheme}://{host}:{self.get('network.port', 8765)}"

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.log_dir, self.backup_dir, self.mod_backup_dir, self.mod_trash_dir):
            path.mkdir(parents=True, exist_ok=True)
