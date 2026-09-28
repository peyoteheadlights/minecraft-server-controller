# API reference

Base URL: `https://<agent-host>:8765`. Plain HTTP is only served on
`127.0.0.1`, and only when TLS is explicitly disabled. Interactive docs are served at
`/api/docs` when the agent is running.

Every route except `/api/health` and `/api/auth/login` requires:

```
Authorization: Bearer <token>
```

where the token is either a session token from `/api/auth/login` or the
`MCSC_API_TOKEN` value from `.env`.

## Authentication

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/auth/login` | `{username, password}` → `{token, expires_at}` |
| POST | `/api/auth/logout` | Invalidate this session |
| POST | `/api/auth/rotate` | New token, old one invalidated |
| GET | `/api/auth/me` | Who this token belongs to |

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

## Players and performance

`GET /api/players`, `GET /api/players/sessions?username=`,
`GET /api/performance?hours=`, `GET /api/health/server`,
`GET /api/worlds`, `POST /api/worlds/save`.

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
`POST /api/notifications/test?channel=`, `GET /api/notifications/history`,
`GET /api/security`, `GET /api/security/tls`, `GET /api/security/audit`,
`POST /api/security/revoke-sessions`, `GET /api/servers`.

## WebSocket `/ws`

Connect, then send the auth message **first**:

```json
{"type": "auth", "token": "…"}
```

The server replies with `{"type":"ready", status, console}` and then streams:

| Message | Contents |
| --- | --- |
| `{"type":"event","type":"console",…}` | One console line |
| `{"type":"event","type":"state",…}` | State change |
| `{"type":"event","type":"metrics",…}` | Performance sample |
| `{"type":"event", …}` | Any other agent event |
| `{"type":"ping"}` | Heartbeat every 25 seconds |

The client may send `{"type":"tail","lines":N}` or `{"type":"status"}`.
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

## Example

```bash
# --cacert, never --insecure: the certificate is actually verified
TOKEN=$(curl -s --cacert ca.crt -X POST https://minecraft-pc.tail1234.ts.net:8765/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"…"}' | jq -r .token)

curl -s --cacert ca.crt https://minecraft-pc.tail1234.ts.net:8765/api/status \
  -H "Authorization: Bearer $TOKEN" | jq .state
```
