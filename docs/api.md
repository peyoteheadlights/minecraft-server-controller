# API reference

Base URL: `https://<agent-host>:8765`. Plain HTTP is only served on
`127.0.0.1`, and only when TLS is explicitly disabled. Interactive docs are served at
`/api/docs` when the agent is running.

Every route except `/api/health` and `/api/auth/login` requires:

```
Authorization: Bearer <token>
```

where the token is either a session token from `/api/auth/login` or the
`MCSC_API_TOKEN` value from `.env`. Every route declares the permission it
needs (`agent/security/permissions.py`); today every signed-in user has all of
them.

## One server or several

Everything about one Minecraft server lives under
`/api/servers/{server_id}/`: status, info, server control, console and logs,
events, crashes, players, performance, worlds, TPS, mods, backups, schedules
and that server's own settings. An unknown id answers 404.

The paths from before multi-server (`/api/status`, `/api/backups`, …, as
listed below) still work for one release and act on the first server in the
config. They answer with a `Deprecation: true` header and a `Link` to the
new path. In the tables below, put `/servers/{server_id}` after `/api` for the
new form, e.g. `POST /api/servers/survival/server/start`.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/servers` | Every server with its measured state, players, uptime and port |
| POST | `/api/servers` | `{name, directory, jar?, id?}` — register an existing server folder. Nothing in it is changed and Minecraft is not started. The folder must exist, hold the jar, not be a drive root, home or system folder, and not overlap the agent or another server. |
| DELETE | `/api/servers/{id}` | Take a server off the list. Its folder, world and backups are not touched. Refused while it runs. |
| GET | `/api/servers/{id}/settings` | That server's settings and its overrides |
| PUT | `/api/servers/{id}/settings` | `{updates: {"monitor.auto_restart": false, …}}` |
| GET | `/api/ports/suggest?protocol=tcp` | A free port no server uses, and which ports are taken |

## Jobs

Long operations (backups, restores) are jobs with real progress: `done` and
`total` are counted, and `progress` is `null` until the total is known, never
an estimate. A server runs one risky job at a time; a second gets 409.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/jobs?server_id=&running=&limit=` | Recent jobs, newest first |
| GET | `/api/jobs/{id}` | One job, with its result |
| POST | `/api/jobs/{id}/undo` | Undo a finished change by restoring the safety backup it took first (itself undoable) |

## Authentication

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/auth/login` | `{username, password, remember?, device?}` → `{token, expires_at, remember}`. `remember: true` is "Keep me signed in": the session lasts `security.remember_days` from its last use. `device` names it on the Security page (the phone app sends its name) |
| POST | `/api/auth/logout` | Invalidate this session |
| POST | `/api/auth/rotate` | New token, old one invalidated |
| GET | `/api/auth/me` | Who this token belongs to |
| POST | `/api/account/password` | `{current, new}`: a helper changes their own password (other sessions end). The owner is refused: reset it on the PC |

## Versions, pairing, devices and updates

What a client (the dashboard, or the phone app) needs to know about the app
itself. Every one of these declares its answer's shape in `/api/openapi.json`
(`agent/api/responses.py`).

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | No sign-in. `{ok, auth_configured, api_version}` |
| GET | `/api/version` | `{version, api_version}`. `api_version` (an integer) goes up only for a change a client must handle; CHANGELOG.md lists them under "API" |
| GET | `/api/pairing` | "Open on your phone": `{ok, address, port, fingerprint, api_version, url, qr}` or `{ok: false, reason}`. `url` is `https://<address>:<port>/?pair=1&fp=<64 hex>&api=<n>`, what the QR code holds; it carries no password or token. `fingerprint` is the SHA-256 of the agent's certificate, so an app can check it reached the right PC. `qr` is the code's rows, `"1"` a dark square, no border |
| GET | `/api/sessions` | Signed-in devices: `{sessions: [{id, user, label, created_at, last_used, expires_at, source_ip, remember, current}], remember_days}`. A helper sees only their own |
| DELETE | `/api/sessions/{id}` | Sign one device out at once (the owner: any; a helper: their own) |
| GET | `/api/updates` | `{current, latest, available, checked_at, error, checking, install_kind, can_install, cannot_install_reason, last_result}`. `latest` is `{version, page, notes, published_at}` |
| POST | `/api/updates/check` | Check GitHub now (`app.update`) |
| GET | `/api/updates/preflight` | The same, plus `players_online` (null when unknown) and who: what the confirmation shows |
| POST | `/api/updates/install` | Start the update (`app.update`, owner only, no body) → `{ok, job}`. See [security](security.md#updating-the-app-itself) |
| GET | `/api/updates/old-copy` | `{old_copy}`: a `setup.ps1` copy left behind after moving, what removing it would delete, and why it can't (`problems`) |
| POST | `/api/updates/old-copy/remove` | Remove that copy's app files (`app.update`) → `{ok, path, removed, kept, failed, folder_removed}` |

**Links.** Dashboard addresses name the server and page: `/#<server id>/<page>`
(`/#survival/console`), or `/#<page>` for app-wide pages (`/#app-settings`).
Older links (`/#console`) still open that page on the last server used. Phone
alerts carry `url` and `page` and open that place.

**The contract.** `docs/api/released.txt` names the saved copy of the last
released API. `tests/test_api_contract.py` fails if a route or a field of an
answer disappears without having been marked deprecated in a release first,
and if a new route declares no response model. Older routes without one are
listed in `tests/api_untyped_routes.txt`; the list only shrinks.

## Helpers, moving, getting help (owner only)

A helper gets 403 from each of these. See [security.md](security.md#permissions).

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/accounts` | The owner's name, every helper (no hashes), what helpers may do |
| POST | `/api/accounts` | `{username, password, servers?}`; `servers` null is every server |
| PUT | `/api/accounts/{username}` | `{all_servers?, servers?, password?}`; a new password signs them out |
| DELETE | `/api/accounts/{username}` | Remove a helper and end their sessions |
| GET | `/api/folders?path=` | The folder picker: folder names in one folder, or drives and shortcuts |
| GET | `/api/power` | Keep awake: on or off, active now, what can still sleep the PC |
| GET | `/api/export` | Measured sizes of each part, before exporting |
| POST | `/api/export` | `{worlds, backups, secrets, passphrase?}` starts a job; its result has the token |
| GET | `/api/export/{token}` | The export file |
| GET | `/api/help-bundle` | The Get help file's list of files, before it is made |
| POST | `/api/help-bundle` | `{confirm: true}` makes it; returns a token |
| GET | `/api/help-bundle/{token}` | The Get help file |

Per server, under `/api/servers/{id}/`:

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `memory` | The PC's measured RAM, this server's `-Xmx`, running servers' limits added up |
| PUT | `memory` | `{memory_mb}` sets `-Xmx` only; refused when the PC's RAM can't be read |
| GET / PUT | `backups/offsite` | The folder for second copies (`{directory}`, empty is off) |
| POST | `backups/{id}/copy` | Copy one backup off the PC now |
| POST | `world/import/upload` | A world `.zip` (multipart); read and described, nothing replaced |
| POST | `world/import/folder` | `{path}` of a world folder; read and described |
| GET | `world/saves` | Single-player's saved worlds on this PC |
| POST | `world/import` | `{token, confirm: true}` replaces the world (server stopped; backup first) |
| DELETE | `world/import/{token}` | Throw an uploaded world away |
| POST | `world/download` | Pack the world as a single-player `.zip`; returns a token |
| GET | `world/download/{token}` | The world `.zip` |

## Server control

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Unauthenticated liveness probe |
| GET | `/api/status` | State, uptime, versions, players, metrics |
| GET | `/api/info` | Versions, launch command, paths, machine specs |
| POST | `/api/server/start` | Start Minecraft |
| POST | `/api/server/stop` | `{timeout?, force?}` |
| POST | `/api/server/restart` | Stop then start |
| POST | `/api/server/restart-now` | During an automatic-restart countdown: start immediately |
| POST | `/api/server/cancel-restart` | During a countdown: cancel it; the server stays stopped |
| POST | `/api/server/clear-crash-block` | Re-enable auto-restart after a crash loop |
| POST | `/api/server/command` | `{command, confirm}` — one Minecraft command |
| GET | `/api/server/command/check?command=` | Does it need confirmation? |

## Console, logs, events

`GET /api/logs?lines=&since=&search=&level=`,
`GET /api/logs/download`, `POST /api/logs/clear`,
`GET /api/events?limit=`.

## Chat and the getting-started checklist

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/chat?lines=` | The chat the console printed, newest last, plus `running` and how many lines are kept |
| POST | `/api/chat` | `{"message": "..."}` sent as **Server**. Becomes a `say` command and passes the same validation as a console command; letters, digits and basic punctuation only, 220 characters. Answers `{"result": "SENT", ...}`: the message appears in `/api/chat` once the console prints it |
| GET | `/api/getting-started` | The four checklist items, each with `done`, the page it leads to, and the evidence it was ticked from |
| POST | `/api/getting-started/dismiss` | Hide the card for this server |

Chat is not stored in the database and not replayed on reconnect: it is as
chatty as the console itself. Live messages arrive on the WebSocket as
`chat` events, and only for the server the page is watching.

## Restore world

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/world/timeline` | The points this world can be put back to, newest first, with `age_seconds`, `played_seconds` (`null` when no sessions were recorded), `checked`, plus `server_running`, `can_restore` and `blocked_by` |
| POST | `/api/world/undo` | `{"backup_id": 7, "confirm": true}`. 409 while the server is running or a change holds it; always takes a safety backup first and answers with it |

## Phone alerts

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/push` | `configured`, `enabled`, the VAPID **public** key, the phones signed up (no keys), and the command that makes the keys |
| POST | `/api/push/subscribe` | `{"subscription": <the browser's PushSubscription JSON>, "label": "Pixel"}`. 409 when no keys are set up |
| POST | `/api/push/unsubscribe` | `{"endpoint": "..."}` |
| POST | `/api/push/test` | One test alert to every phone signed up |

These are agent-wide, not per server. The private VAPID key is never served.

## Players and performance

`GET /api/players`, `GET /api/players/sessions?username=`,
`GET /api/performance?hours=`, `GET /api/health/server`,
`GET /api/worlds`, `POST /api/worlds/save`.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/players` | Online and known players, plus `lists` (whitelist, ops, banned from Minecraft's own files; `players: null` with a `reason` when a file isn't there yet), `running`, and the last `actions` |
| POST | `/api/players/actions` | `{"action": "whitelist_add" \| "whitelist_remove" \| "op" \| "deop" \| "kick" \| "ban" \| "pardon", "name", "reason"?, "confirm"?}`. Kick and ban need `confirm: true`. Answers `{"result": "SENT", "action": {...}}` |
| GET | `/api/players/actions/{id}` | The action's `state`: `sent`, then `done`, `unchanged` or `failed` once the console answers, or `no_answer` after 20 seconds |
| GET | `/api/join` | The "How friends join" card: `java.port` and where it came from, `java.local` (adapter addresses), `java.tailscale`, `bedrock` (with crossplay on), and `internet: {"known": false}` |

`/api/performance` also takes `storage=false` to leave out the disk-use
breakdown, which walks the whole server folder (the Overview's hover
summaries use this).

## Backups

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/backups` | List, with retention settings |
| POST | `/api/backups` | Create one |
| GET | `/api/backups/{id}/verify` | Zip integrity plus SHA-256 |
| GET | `/api/backups/{id}/download` | Download the zip |
| POST | `/api/backups/{id}/restore` | `{confirm:false}` returns the plan; `{confirm:true}` performs it |
| DELETE | `/api/backups/{id}` | Delete one |

## Mods

`GET /api/mods`, `GET /api/mods/search?q=&minecraft_version=`,
`GET /api/mods/project/{slug}`, `POST /api/mods/install`,
`POST /api/mods/upload` (multipart), `GET /api/mods/impact?filename=`,
`POST /api/mods/remove`, `POST /api/mods/enable`, `POST /api/mods/disable`,
`GET /api/mods/updates?refresh=`, `POST /api/mods/update`,
`GET /api/mods/versions/{mod_id}`, `POST /api/mods/rollback`,
`GET /api/mods/history`, `GET /api/mods/check`,
`GET /api/mods/dependencies` (readable report), `POST /api/mods/dependencies/plan`
(what would be downloaded, recursively; downloads nothing),
`POST /api/mods/dependencies/install` (`{"mod_ids": [...]}` or all missing).

## Game settings

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/game-settings` | The known `server.properties` keys with value, whether the file sets it, Minecraft's default, limits and any problem; the whole file as `text`; `running` and `restart_needed` |
| PUT | `/api/game-settings` | `{"values": {"difficulty": "hard", ...}}`. Only the form's keys; everything else in the file is kept as it was. A bad value answers 400 with `problems` per key and writes nothing |
| PUT | `/api/game-settings/raw` | `{"text": "..."}`, the whole file (Technical mode). Known keys are still checked |

Both saves keep a safety backup of the old file and answer with `changed`,
`undo` and `restart_needed`. A server's port and player limit in
`config.yaml` follow the file.

## Duplicate and modpacks

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/servers/{id}/duplicate` | A suggested name and folder for a copy |
| POST | `/api/servers/{id}/duplicate` | `{"name", "directory", "world": "copy" \| "fresh"}`. Runs as a job; the copy gets the next free port and an unused color |
| POST | `/api/modpacks/inspect` | Multipart upload of a `.mrpack` (`?server_id=` adds `into`, what importing into that server would do). Reads it and answers with a `token` and the `pack`: versions, every file with `download`, `client_only` or `refused` and why, `problems`, `can_import`. Changes nothing |
| DELETE | `/api/modpacks/{token}` | Throw an uploaded pack away |
| POST | `/api/modpacks/{token}/new-server` | Make a new server from the pack: `{"name", "directory", "eula_accepted": true}` |
| POST | `/api/servers/{id}/modpack` | Import into this server: `{"token", "confirm": true}`. Stops it, backs it up, moves its mods aside, changes its version first if needed |

## Server types, versions and crossplay

Agent-wide:

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/server-types` | Every type with its capabilities. The dashboard's comparison table is generated from this |
| GET | `/api/server-types/{type}/versions` | The Minecraft versions that type offers, from its own official source, with the loader or build versions for each |
| GET | `/api/new-server/options` | What the New server panel needs: types, default memory and why, a free port, a free color, the EULA link |
| POST | `/api/new-server` | Create one. Refused without `eula_accepted: true` (for Bedrock this accepts Mojang's EULA and Privacy Policy, recorded before anything is downloaded). Downloads, installs and registers; starts nothing |
| GET\|POST | `/api/bedrock/terms` | Whether Mojang's EULA and Privacy Policy were accepted, by whom and when; `POST {"accepted": true}` records the person's own tick |
| GET | `/api/bedrock/versions` | The Bedrock server zips this app downloaded and kept (Mojang only offers the newest) |

Per server:

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/servers/{id}/version` | What it is, as observed, plus what the last change kept to go back to |
| POST | `/api/servers/{id}/version/preflight` | What a change would do, before anything happens: direction, Java verdict, which add-ons would be moved aside, which declare nothing |
| POST | `/api/servers/{id}/version` | Make the change. Needs `confirm: true`. Stops the server, takes a verified backup, installs, checks |
| POST | `/api/servers/{id}/version/roll-back` | Put the previous software back |
| POST | `/api/servers/{id}/eula` | Record that the person accepted Minecraft's rules. The only thing that writes `eula=true` |
| GET\|PUT | `/api/servers/{id}/crossplay` | Whether Bedrock players can join, the port, and the differences; `PUT {"enabled": true}` installs Geyser and Floodgate |

Bedrock add-ons (only on Bedrock servers; others answer 400):

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/servers/{id}/addons` | The packs someone added, read from their manifest.json, and whether this world has each on |
| POST | `/api/servers/{id}/addons/upload` | Upload a `.mcpack`, `.mcaddon` or `.mctemplate`; each pack is checked, installed and turned on |
| PUT | `/api/servers/{id}/addons/{uuid}` | `{"enabled": true\|false}` in this world |
| DELETE | `/api/servers/{id}/addons/{uuid}` | Turn it off and move it to the data folder |

The server list rows carry `edition` (`java` or `bedrock`) and
`capabilities` (`memory_limit`, `speed`, `crossplay`, `reads_chat`, `bans`,
`addons`, `mods`); `false` means not applicable, and the dashboard shows
that instead of the control. The world import routes also take a `.mcworld`
for a Bedrock server, and their answers add `edition_matches` and
`newer_than_server`.

A version change does **not** set the version. The chosen one is kept as
`pending_version` and becomes `minecraft_version` only when that server's own
console reports it — see `docs/honesty.md`.

## TPS monitoring

`GET /api/tps` (state, command, how it was detected, what was tried),
`POST /api/tps/detect` (detect again; server must be online),
`PUT /api/tps` with `{"command": "auto" | "off" | "<minecraft command>"}`.

The server state `RESTART_PENDING` means crashed with an automatic restart
counting down; `restart_at` in `/api/status` is the deadline (Unix time).

## Crashes, schedules, settings, security

`GET /api/crashes`, `GET /api/crashes/{id}`,
`GET|POST /api/schedules`, `PUT|DELETE /api/schedules/{id}`,
`POST /api/schedules/{id}/run`,
`GET|PUT /api/settings`, `POST /api/maintenance`,
`POST /api/notifications/test?channel=` (`discord`, `email` or `push`),
`GET /api/notifications/history`,
`GET /api/security`, `GET /api/security/tls`, `GET /api/security/audit`,
`POST /api/security/revoke-sessions`.

`/api/settings` holds the agent's settings, including the defaults every
server uses; `/api/servers/{id}/settings` holds one server's own.

## WebSocket `/ws`

Connect, then send the auth message **first**:

```json
{"type": "auth", "token": "…", "server_id": "survival"}
```

`server_id` is optional (the first server otherwise). The server replies with
`{"type":"ready", server_id, servers, status, console}` and then streams every
server's events. Each event carries `server_id` (`null` for the agent itself,
such as a certificate warning), so the client shows the selected server's and
notices another server's crash:

| Message | Contents |
| --- | --- |
| `{"type":"event","type":"console",…}` | One console line |
| `{"type":"event","type":"state",…}` | State change |
| `{"type":"event","type":"metrics",…}` | Performance sample |
| `{"type":"event", …}` | Any other agent event |
| `{"type":"ping"}` | Heartbeat every 25 seconds |

The client may send `{"type":"tail","lines":N,"server_id":…}` or
`{"type":"status","server_id":…}`. Long jobs send `"type":"job"` events with
their progress.
Everything else is ignored: the socket cannot perform actions, because actions
belong on the audited REST API.

## Result semantics

Control endpoints distinguish what was **requested** from what has been
**verified**, because a command that was sent is not an outcome that happened:

| `result` | Meaning |
| --- | --- |
| `REQUESTED` | the agent acted on your instruction; the outcome is not known yet |
| `SENT` | the text reached Minecraft's console input |
| `IN_PROGRESS` | underway, not finished |
| `VERIFIED` | the agent observed the outcome itself |
| *(HTTP error)* | it failed, with a reason |

For example `POST /api/server/start` returns `REQUESTED` with the process id.
"The server started" only arrives later, as a `server_started` event, once the
startup line appears in the console.

## Unknown values

Any field that could not be measured is `null`, and comes with a sibling field
explaining why. `"tps": null` is always accompanied by
`"tps_unavailable_reason"`. `"players_online": null` means the player list has
not been established - it is not zero. Never treat `null` as a default.

## Errors

Standard HTTP codes with a readable `detail` string: 400 invalid input,
401 unauthenticated, 409 wrong state (for example, a command while offline),
429 rate limited or locked out (with `Retry-After`), 502 Modrinth unreachable,
500 unexpected.

Every answer has an `X-Request-ID` header, and every error answer repeats it
as `request_id` in its body. The agent's log lines written while handling
that request end with `[request <id>]`, so an error someone saw can be found
in a "Get help" file. A client may send its own `X-Request-ID` (8 to 64
letters, digits or dashes); anything else is replaced with a new ID. The
dashboard shows the ID as "Error number" on 500 answers.

## Example

```bash
# --cacert, never --insecure: the certificate is actually verified
TOKEN=$(curl -s --cacert ca.crt -X POST https://minecraft-pc.tail1234.ts.net:8765/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"…"}' | jq -r .token)

curl -s --cacert ca.crt https://minecraft-pc.tail1234.ts.net:8765/api/status \
  -H "Authorization: Bearer $TOKEN" | jq .state
```
