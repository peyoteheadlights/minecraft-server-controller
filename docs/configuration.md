# Configuration reference

Two files, both in the project folder:

- `config/config.yaml` — everything that is not secret
- `.env` — secrets only

Settings changed in the dashboard are written back to `config.yaml`.

Any key you leave out uses its default. The defaults live in one place, the
typed sections at the top of `agent/config.py`, and every value is checked
when the agent starts: a number that isn't a number stops startup with the
key's name (for example `thresholds.cpu_percent must be a number`), and the
dashboard refuses to save one. On/off settings take `true`/`false`,
`yes`/`no`, `on`/`off` or `1`/`0`; anything else (such as `maybe`) stops
startup rather than being guessed at. An empty value (`jar:`) means empty text, an
empty list or "off"; for a number it means the default.

## server, or servers

One Minecraft server is a `server:` block. Several are a `servers:` list, one
entry per server, each with the keys below. Use one form or the other, never
both; the agent refuses to start with both. A lone `server:` block stays a
`server:` block when the dashboard saves settings, and becomes a list only
when you add a second server.

```yaml
servers:
  - id: survival
    name: Survival
    directory: 'C:\Minecraft\Survival'
    port: 25565
  - id: creative
    name: Creative
    directory: 'C:\Minecraft\Creative'
    port: 25566
    monitor:                 # this server's own overrides (optional)
      auto_restart: false
    backups:
      keep_daily: 3
```

Each entry may override `monitor`, `backups` and `mods` for that server; any
key it leaves out comes from the top-level section. Everything else
(notifications, thresholds, TLS, security) is shared by all servers.

Two servers can never use the same folder, or folders inside each other.
A server will not start while another running server uses its port or its
folder; the refusal names the other server.

| Key | Default | Meaning |
| --- | --- | --- |
| `id` | `main` | Internal identifier: letters, digits, `-` and `_`, up to 64 characters, unique. It appears in URLs (`/api/servers/<id>/…`) and folder names and cannot be changed later. Every database row carries it. |
| `name` | | Display name in the dashboard and alerts |
| `directory` | | The Minecraft server folder. Use single quotes on Windows. |
| `jar` | `fabric-server-launch.jar` | Jar to launch, relative to `directory` |
| `java` | `java` | `java` from PATH, or a full path to `java.exe` |
| `jvm_args` | `["-Xmx6G"]` | JVM arguments. This is where you change memory. |
| `server_args` | `["nogui"]` | Arguments passed after the jar |
| `raw_command` | `null` | Full argv list replacing everything above. Config-file only — the API cannot set it. |
| `port` | `25565` | Minecraft's port, used for the listening check. `server-port` in `server.properties` wins when it is set. |
| `max_players` | `20` | Shown in the dashboard |
| `stop_timeout` | `90` | Seconds to wait after `stop` before terminating the process |
| `start_timeout` | `300` | Seconds to wait for `Done (…)!` before giving up |
| `autostart_minecraft` | `false` | Start Minecraft when the agent starts |

## monitor

| Key | Default | Meaning |
| --- | --- | --- |
| `auto_restart` | `true` | Restart automatically after a crash |
| `restart_delay` | `10` | Length of the automatic-restart countdown, in seconds. Restart Now and Cancel are available during it. |
| `max_crashes` | `5` | Give up after this many crashes… |
| `crash_window_minutes` | `10` | …inside this many minutes |
| `sample_interval` | `10` | Seconds between performance samples |
| `tps_poll_interval` | `60` | Seconds between tick-rate queries |
| `tps_command` | `auto` | `auto` detects `tick query` / `tps` / `spark tps` once per server start and remembers it. A command forces it; `off` disables. TPS is never estimated. |
| `history_days` | `14` | How long metrics are kept |

## thresholds

`cpu_percent` 90, `ram_percent` 90, `disk_free_gb` 20, `tps_min` 18,
`mspt_max` 50. These drive both the health page and the alerts.

## tls

| Key | Default | Meaning |
| --- | --- | --- |
| `enabled` | `true` | Serve HTTPS. When false, the agent only binds `127.0.0.1` and refuses any other address. |
| `certificate` | `certs/agent.crt` | Certificate path. Relative paths resolve inside the data folder. Written by `make_certs`. |
| `private_key` | `certs/agent.key` | Private key path. Never exposed by any endpoint. |
| `ca_certificate` | `certs/ca.crt` | The local CA, when one is used. Empty for a Tailscale-issued certificate. |
| `hostname` | `""` | The name you type in the browser. The agent checks the certificate covers it. Empty means the check is reported as unknown. |
| `http_redirect` | `true` | Run a redirect-only HTTP listener |
| `http_redirect_port` | `8080` | Its port |
| `hsts` | `true` | Send Strict-Transport-Security on HTTPS responses (never on loopback) |
| `hsts_max_age` | `31536000` | One year |
| `expiry_warn_days` | `14` | Warn this far ahead |
| `expiry_critical_days` | `3` | Escalate to error this far ahead |
| `check_interval_hours` | `6` | How often the certificate file is re-read |

## network

| Key | Default | Meaning |
| --- | --- | --- |
| `host` | `127.0.0.1` | Bind address. Set to your Tailscale address for remote access. Never `0.0.0.0` on a forwarded network. |
| `port` | `8765` | Dashboard port |
| `allowed_origins` | `[]` | Leave empty. Only needed if you host the UI separately. |
| `trust_proxy_headers` | `false` | Only enable behind a reverse proxy you control |

## security

`session_hours` 12, `max_failed_logins` 5, `lockout_minutes` 15,
`rate_limit_requests` 120, `rate_limit_window` 60.

## backups

`directory`, `include` (list of folders/files), `keep_daily` 7, `keep_weekly` 4,
`keep_monthly` 3, `compression` (`deflate` or `store` — `store` is far faster
and far larger), `stop_server_for_backup`.

## mods

`directory` (relative to the server folder), `backup_directory`,
`trash_directory`, `modrinth_api`, `user_agent`, `backup_before_install`,
`update_check_hours` 12.

## notifications

`discord_enabled`, `email_enabled`, `min_interval_seconds` 300, an `events`
block with one boolean per event type, and an `email` block with host, port,
TLS/SSL, from and to addresses, and attachment options.

## logging / paths / maintenance

`logging`: directory, level, rotation size and count.
`paths.database`: SQLite filename.
`maintenance`: `enabled`, `block_auto_restart`, `block_scheduled_tasks`,
`message`.

## The data folder (`paths.data_dir`)

Where the agent keeps its database, backups, crash evidence, mod archives,
certificates and logs. Empty (the default) means the fixed app-data folder:

- Windows: `C:\ProgramData\Minecraft Server Controller`
- Linux and macOS: `~/.local/share/minecraft-server-controller`
  (or `$XDG_DATA_HOME/minecraft-server-controller`)

The folder is created readable only by SYSTEM, Administrators and the user
the agent runs as, because it holds the private key.

Inside it, the first server of an install from before multi-server keeps its
files at the top (`backups/`, `crashes/`, `mod-backups/`, …), exactly as they
were. Every other server gets its own `servers/<id>/` folder. `layout.json`
records which is which.

**Moving from the old place.** Before Phase 1 the default was
`<server directory>/mcsc-data`. On the first start after upgrading, when
`paths.data_dir` is empty and that old folder has a database, the agent copies
it to the app-data folder: the database through SQLite's backup API, checked
with `PRAGMA integrity_check` and a row count of every table, and every other
file with a SHA-256 comparison. Paths the database records (backups, crash
reports, mod archives) and certificate paths in `config.yaml` are pointed at
the copies; `config.yaml` is saved first as `config.yaml.before-data-move`.
The old folder is never changed or deleted. If there is not enough free space,
or anything fails a check, nothing in the new folder is kept, the agent keeps
using the old folder for that run and tries again next start.
`data-folder-move.json` in the new folder records when and from where.

To see what will happen without changing anything:

```powershell
python -m agent.datafolder
```

Set `paths.data_dir` explicitly to keep the data wherever you want it; an
explicit folder is never moved.
## Environment variables

Secrets: `MCSC_ADMIN_USERNAME`, `MCSC_ADMIN_PASSWORD_HASH`, `MCSC_API_TOKEN`,
`MCSC_DISCORD_WEBHOOK`, `MCSC_SMTP_USERNAME`, `MCSC_SMTP_PASSWORD`.

Overrides: `MCSC_HOST`, `MCSC_PORT`, `MCSC_SERVER_DIR` (the first server's
folder), `MCSC_DATA_DIR`.
