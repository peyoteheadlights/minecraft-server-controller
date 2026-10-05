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
a slow consumer. Console lines and metrics samples only go to pages showing
that server (the queue filters them before they are queued), so another
server's busy console can never push a crash alert out of a slow phone's
queue. A subscriber that raises is logged and ignored.

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

## Several servers

`AgentCore` holds what the agent has once: the event bus, the database, sign-in,
the notifier, the job tracker and the port manager. Each Minecraft server is a
`ServerContext` in `core.servers`, with its own process supervisor, players,
metrics, TPS, mods, backups, crash reporter and scheduler. A context sees the
shared pieces through thin wrappers: a `ServerConfig` view (its own `server`
settings, plus its `monitor`/`backups`/`mods` overrides on top of the shared
sections), a `ServerBus` that stamps `server_id` on every event it publishes,
and a `ServerDb` that scopes settings keys and audit rows to the server.

Events without a `server_id` are about the agent itself (the certificate,
machine-wide CPU and RAM alerts) and are stored under `_agent`.

REST routes for one server are mounted under `/api/servers/{server_id}`; the
`get_server` dependency turns the id into a context or a 404. The unprefixed
routes from before are the same routers mounted again with no id, so they act
on the first server. The WebSocket streams every server's events and the
dashboard filters by the selected one.

## Shared building blocks

- **Jobs** (`agent/jobs.py`): a long operation with honest progress, stored in
  the `jobs` table and streamed as `job` events. One risky job per server at a
  time: backups, restores and every mod change (install, upload, update,
  remove, turn on or off, roll back, dependencies). Jobs left running when the
  agent stopped are marked interrupted.
- **Safe change** (`agent/safechange.py`): stop if needed, take and verify a
  backup, make the change, check it, put the backup back if the change or the
  check fails, start again if asked. The backup is the change's one-click undo.
  Undo is `POST /api/jobs/<id>/undo`, the Undo button on Backups.
  Restoring a backup runs through it; later phases' risky changes will too.
  From the stop until the result is checked, the server is held: every
  start is refused with what it is waiting for.
- **Port manager** (`agent/ports.py`): which port each server uses (from its
  console, else `server.properties`, else Minecraft's default, and says which),
  start refusals on a port or folder another running server uses, and free
  port suggestions.
- **Permissions** (`agent/security/permissions.py`): every route declares the
  permission it needs with `Depends(require(...))`, and a test checks none is
  missing. Today every signed-in user has every permission; helper accounts
  later only change `permissions_for`.
- **Downloader** (`agent/downloads.py`): the one way anything is fetched.
  HTTPS only, an allow-list of official hosts re-checked on every redirect,
  size caps, `.part` file renamed into place only after the strongest
  published checksum matches, and an honest `verified: false` where a source
  publishes none. Tests replace its module-level `TRANSPORT`, so nothing in
  the suite touches the network.

## Server types

`agent/servertypes/` is where "what kind of server is this" lives, and
nothing outside it asks `if type == "fabric"`:

- `__init__.py` — one frozen `ServerType` per type (Vanilla, Fabric, Quilt,
  Forge, NeoForge, Paper, Purpur), saying what it accepts, what its add-ons
  are called and where they live, which metadata file they carry, which
  Modrinth loaders match, how it is launched (`-jar`, or `java @win_args.txt`
  for Forge and NeoForge; `unix_args.txt` off Windows), its installer's
  arguments, where its versions come from, which TPS commands to try, which
  folders a backup must hold besides the configured list (`backup_extra`),
  and whether GeyserMC publishes a build for it. The dashboard's
  comparison table is generated from exactly this, so it cannot drift.
- `versions.py` — one provider per type, each asking that project's own API
  (Mojang's piston-meta, meta.fabricmc.net, meta.quiltmc.org, the Forge and
  NeoForged Maven metadata, fill.papermc.io, api.purpurmc.org), and turning
  a chosen version into a `Plan` of files to fetch.
- `install.py` — putting that plan in place, running the loader installer
  where there is one (see `docs/security.md`), and changing a server's
  version or type through the safe-change routine, keeping the previous
  software for a one-step roll back.
- `create.py` — a brand-new server: check the folder, check Java, write
  `server.properties` and `eula.txt`, install, register. It is never started
  for you.

`agent/crossplay.py` sits beside them: Geyser and Floodgate installed into
the server's own add-on folder with `auth-type: floodgate`, a UDP port from
the port manager, and the differences a Bedrock player will notice written
out in plain words.

## The data folder

`agent/datafolder.py` moves an old `<server>/mcsc-data` to the fixed app-data
folder once, before anything else at startup touches the new folder: plan
(read-only), copy into a staging folder, verify (SQLite backup + integrity
check + row counts, SHA-256 per file), rewrite absolute paths in the copied
database and the certificate paths in `config.yaml`, then switch, with the
database moved in last. On any failure the staging folder goes and the old
folder is used for that run. If an attempt is cut off part way (a power
cut), the next start finishes it: entries already moved across that match the
staged copy byte for byte are accepted; anything else in the way stops the
move and the old folder is used. Tools that run before the first start
(`--check`, `make_certs`, setup) look at the old folder until the copy exists.

The CPU reading for the whole PC (`machine_cpu` in
`agent/monitoring/metrics.py`) is shared by every server's monitor and never
measured over less than a second, because psutil's own non-blocking reading
is "since the last call on this thread" and gave the second of two servers
about 0%.

## Layout

```
agent/
  config.py            layered config as typed sections (one place for
                       every default), the server list, secrets from env only
  core.py              AgentCore (shared) and ServerContext (one per server)
  datafolder.py        the one-time move of the data folder
  jobs.py              long operations with real progress
  ports.py             game ports and start conflicts between servers
  safechange.py        backup, change, check, undo
  events.py            event bus
  logging_setup.py     rotating agent logs
  main.py              FastAPI app, security headers, error handlers, entrypoint
  tailscale.py         what the Tailscale client reports about this machine
  api/                 deps.py, errors.py (domain error -> HTTP status), ws.py,
                       routes/ (one router per area: server, console, players,
                       mods, backups, schedules, server_settings (per server);
                       auth, settings, security, system, jobs (agent-wide))
  backups/manager.py
  database/db.py       schema + migrations
  minecraft/           state, process, console, commands, analyzer, crash
  crossplay.py         Geyser and Floodgate: Bedrock players on a Java server
  downloads.py         the one safe downloader (allow-list, size caps, checksums)
  mods/                jarinfo, modrinth, manager
  servertypes/         what each kind of server is, its versions, installs,
                       version and type changes, and making a new one
  monitoring/          metrics, players
  notifications/dispatcher.py
  scheduler/scheduler.py
  security/            auth, paths, permissions, certs, tls
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

The trade-off is no component framework. For a dozen pages of tables and graphs,
that is a trade worth making.

The JavaScript is split into native ES modules that the browser loads
directly, so there is still nothing to compile. `index.html` loads one module,
`js/main.js`, which imports the rest:

- `state.js` holds shared state and the page registry; it imports nothing.
- `ui.js` has the DOM helpers (`el`, `card`, `table`, `toast`, …).
- `api.js`, `auth.js`, `live.js` (WebSocket and status), `nav.js` (the page
  shell: server tabs, the server's colored sheet and its row of pages),
  `servers.js` (the server list, tabs and All servers page), `charts.js`
  and `prefs.js` (theme and Simple/Technical, saved per account) do one job
  each.
- `colors.js` tints the whole page with a server's color (page, header,
  cards, buttons) and re-derives every text color on the tint, checked for
  readable contrast on every theme. Theme colors in `styles.css` that it
  reads (`--desk`, `--sheet`, `--surface`, `--text-primary`) must be hex.
- `strings.js` holds every piece of text the dashboard shows, each with a
  Simple and a Technical version; pages look text up with `t(key)`.
  `tests/test_strings.py` checks both versions exist with the same
  placeholders, every key used exists, and every entry is used.
- `pages/*.js` each register a renderer for one page; `panels/*.js` are the
  TPS and dependency panels those pages embed.

The CSP allows no inline styles, so styling goes in `styles.css`. For a value
computed at runtime (a bar width, an indent), pass `el()` a style object; it is
applied through the CSSOM, which the CSP allows. `tests/test_dashboard_assets.py`
enforces this.
