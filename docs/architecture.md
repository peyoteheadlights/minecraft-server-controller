# Architecture

## Processes

```
uvicorn (one process)
 └── FastAPI app
      └── AgentCore
           ├── MinecraftServer   supervises the java child process
           ├── PlayerTracker     hooked into every console line
           ├── MetricsMonitor    background sampling + tick-rate polling
           ├── ModManager        mods folder + Modrinth client
           ├── BackupManager     zip create / verify / restore
           ├── CrashReporter     evidence collection + analysis
           ├── Notifier          Discord + SMTP, subscribed to the bus
           ├── Scheduler         due-task loop
           ├── AuthManager       sessions, lockout, rate limits
           ├── EventBus          fan-out to websockets, DB, notifications
           └── Database          SQLite (WAL) with migrations

java -Xmx6G -jar fabric-server-launch.jar nogui   (child process)
```

Minecraft is a **child process**, launched with an argument list and no shell.
Its stdout and stderr are merged and read line by line into a bounded ring
buffer, and every line is parsed for facts (startup complete, versions, joins,
leaves, tick rate, shutdown) before being published on the event bus.

## The event bus

Everything interesting is an `Event` with a type, message, level and data.
Subscribers: the database writer, the notifier, and every open WebSocket.

Each WebSocket gets its **own bounded queue**. If a phone on a weak connection
falls behind, its oldest events are dropped — the agent is never slowed down by
a slow consumer. A subscriber that raises is logged and ignored.

The notifier never sends from inside `publish`: it queues the alert and returns
at once, and its own background task does the Discord and email sends. That is
why a Discord outage or a slow mail server cannot stall the console reader or
the Minecraft server. Fire-and-forget publishes (`publish_soon`) are held by
the bus until they have run.

The database writer works the same way: publishing appends the event to a
list, and a background task writes whatever has collected once a second, in
one transaction, in a worker thread. Other slow calls (`tailscale status`,
`java -version`, the health checks' TCP probe, the storage walk) also run in
worker threads, never on the event loop.

## Why a crash is not a shutdown

Getting this wrong means 3am alerts every time you stop the server. The
supervisor tracks intent, not just the exit code:

| Situation | Classified as | Alert? |
| --- | --- | --- |
| Operator pressed Stop | `user_stop` | stopped |
| Scheduled stop ran | `scheduled_stop` | stopped |
| `/stop` typed in game, clean shutdown lines seen | `clean_exit` | stopped |
| Graceful stop timed out, process terminated | `force_killed` | stopped |
| Process died while ONLINE, no stop requested | `crash` | **crash** |
| Process died while STARTING | `startup_failure` | **crash** |

Only the last two collect evidence, run the analyzer, and trigger auto-restart.

## Storage split

- **SQLite** holds small structured rows: events, players, sessions, metrics,
  crash metadata, backup metadata, mod history and versions, schedules, audit
  log, notification log, sessions, login attempts.
- **Files** hold everything large: console tails, copied crash reports, copied
  logs, backup zips, archived mod jars. The database stores paths to them.

Migrations are forward-only and numbered in `agent/database/db.py`. The runner
applies anything newer than the recorded version at startup. Each migration and
the row recording it run in one transaction, so a migration that fails part way
leaves the database exactly as it was.

## Multi-server groundwork

Every table carries `server_id`, every manager takes it as a parameter, and
`/api/servers` already returns a list. Supporting a second server means holding
several `AgentCore`-like contexts and choosing one per request. Nothing more
was built for it, because building a distributed control plane for one server
would be the wrong trade.

## Layout

```
agent/
  config.py            layered config as typed sections (one place for
                       every default), secrets from env only
  core.py              wiring and lifecycle
  events.py            event bus
  logging_setup.py     rotating agent logs
  main.py              FastAPI app, security headers, error handlers, entrypoint
  tailscale.py         what the Tailscale client reports about this machine
  api/                 deps.py, errors.py (domain error -> HTTP status), ws.py,
                       routes/ (one router per area: server, console, players,
                       mods, backups, schedules, settings, security, system)
  backups/manager.py
  database/db.py       schema + migrations
  minecraft/           state, process, console, commands, analyzer, crash
  mods/                jarinfo, modrinth, manager
  monitoring/          metrics, players
  notifications/dispatcher.py
  scheduler/scheduler.py
  security/            auth, paths
  web/                 index.html, styles.css, theme.js, js/ (ES modules: main.js, pages/, panels/)
installer/             setup_tool, autostart, make_certs, make_secrets, firewall.ps1
tests/                 the suite, plus a fake Minecraft server
```

## Why the dashboard has no build step

It is plain HTML, CSS and JavaScript served by the agent itself. That means:

- no Node, npm or build toolchain on the Minecraft PC
- same origin, so no CORS and no token crossing an origin boundary
- updating is copying files
- it still works on a phone over a slow tailnet link

The trade-off is no component framework. For eleven pages of tables, that is a
trade worth making.

The JavaScript is split into native ES modules that the browser loads
directly, so there is still nothing to compile. `index.html` loads one module,
`js/main.js`, which imports the rest:

- `state.js` holds shared state and the page registry; it imports nothing.
- `ui.js` has the DOM helpers (`el`, `card`, `table`, `toast`, …).
- `api.js`, `auth.js`, `live.js` (WebSocket and status), `nav.js` (sidebar and
  page switching), `charts.js` and `appearance.js` do one job each.
- `pages/*.js` each register a renderer for one page; `panels/*.js` are the
  TPS and dependency panels those pages embed.

The CSP allows no inline styles, so styling goes in `styles.css`. For a value
computed at runtime (a bar width, an indent), pass `el()` a style object; it is
applied through the CSSOM, which the CSP allows. `tests/test_dashboard_assets.py`
enforces this.
