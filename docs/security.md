# Security

## Assumptions

- The dashboard is reachable only over your tailnet, over HTTPS. It binds to
  one address, and that address isn't routable from the internet.
- The Minecraft PC is trusted — anyone with a login there can already do
  everything the agent can.
- The threat model: someone on your network, a malicious web page in another
  browser tab, a hostile file name from Modrinth, and your own mistakes.

## Authentication

- Passwords are stored as PBKDF2-HMAC-SHA256, 240,000 rounds, per-install
  salt. The password itself never touches disk, logs, or the database.
- Signing in returns a random 256-bit session token; only its SHA-256 is
  stored, so a stolen database yields no usable tokens.
- Sessions expire after 12 hours by default, and can be rotated or revoked.
- A long-lived API token is supported for scripts, compared in constant time.
- Failed attempts are counted per user and per address. Five failures locks
  sign-in for 15 minutes, with `Retry-After` in the response. Helpers are
  locked out per account, the same way.
- All API requests are rate limited (120/minute per address by default),
  and again per signed-in account. Rejected requests don't count, so
  retrying doesn't extend the block.
- Helper passwords are hashed exactly like the owner's, in the `accounts`
  table. A sign-in for an unknown name still runs a full-strength hash, so
  the time taken doesn't reveal which names exist.
- The owner's password can't be changed over the network. It is reset on
  the PC with `python -m installer.reset_password`, which asks twice, writes
  only the hash to `.env`, never shows or logs the password, and deletes
  every session. A running agent notices `.env` changed and uses the new
  hash at once. `tests/test_helpers.py` checks no route reaches it.

## Secrets

Secrets are read from environment variables via `.env`:
`MCSC_ADMIN_PASSWORD_HASH`, `MCSC_API_TOKEN`, `MCSC_DISCORD_WEBHOOK`,
`MCSC_SMTP_USERNAME`, `MCSC_SMTP_PASSWORD`, `MCSC_VAPID_PRIVATE_KEY`.

Two files leave the PC on purpose, and both are built to hold no secrets
unless asked:

- **Export everything** (Move to a new PC) holds settings, data and server
  folders. `.env`'s values, helpers' password hashes, phone subscriptions
  and `server.properties`' RCON and management passwords go in only when
  "Passwords and keys" is ticked, and then only inside `secrets.bin`,
  encrypted with AES-256-GCM under a key derived from a passphrase with
  scrypt (n=2^15, r=8, p=1). The passphrase is never stored. Without it, the
  plain parts have those passwords blanked.
- **Get help** holds this app's logs, the install logs, a fresh `--check`
  report and version facts. Never `.env`, `config.yaml`, the database,
  certificates, worlds, backups or Minecraft's own logs (they hold players'
  addresses). Every line is passed through redaction first: the actual
  secret values in use, password hashes, bearer tokens, webhook URLs and
  `password=`-style pairs are cut. The file list is shown before it's made.

`tests/test_first_run_safety.py` builds both with known secret values and
fails if any of them is found inside.

None of these appear in `config.yaml`, in source, or in the browser, and
`.env` is gitignored. The settings API reports only whether a secret is
configured, never its value.

## Command injection

There's no endpoint that runs a shell command. Minecraft is launched with an
argument list and no shell, from a fixed working directory, using values
that only come from `config.yaml`.

The Players page's buttons (whitelist, operator, kick, ban, unban) never
take a command from the browser. The API takes an action name from a fixed
list and a player name that must be a Minecraft name (`^\.?[A-Za-z0-9_]{1,16}$`,
Floodgate's `.` allowed); kick and ban take an optional reason limited to
one short line of letters, numbers and basic punctuation. The command is
built from a fixed template and then passes the same validation as anything
typed in the console (`agent/minecraft/commands.py`). Kick and ban need
`confirm: true`. See `agent/minecraft/playeractions.py`.

The chat box is the same story. A message sent from the Chat page becomes a
`say` command and passes exactly the same validation
(`agent/minecraft/chat.py` calls `agent/minecraft/commands.py`), with a
narrower character set still: letters, digits and basic punctuation, up to
220 characters, no newline or carriage return, so one message can never
become two commands. Chat shown in the dashboard is read from the server's
own console output; nothing is reconstructed from what this app sent.

Auto-sleep adds no new way to run anything either: it stops a server through
the same code path as a scheduled stop.

Keeping the PC awake runs no program either. It calls Windows'
`SetThreadExecutionState` directly through `ctypes` from the agent's own
thread, and reads the battery (psutil) and the lid setting
(`powrprof.dll`, read only). The dashboard can only turn it on or off.

The folder picker (`GET /api/folders`, owner only) lists folder names inside
one folder, and whether each holds a `level.dat`. It never lists files or
reads their contents, and it follows no links. Whatever folder is picked is
checked again by the feature that uses it: an off-PC copy folder must exist,
be writable, not be a system folder and not overlap the servers or the
app's data (`agent/backups/offsite.py`); a world folder must hold a
`level.dat`.

A world brought in as a `.zip` is read through the same zip-slip check every
extraction uses (`check_archive_member`) before anything is written; a zip
with a path that would land outside the server folder is refused whole.

### The one program the agent runs that isn't Minecraft

Forge, NeoForge and Quilt publish an installer rather than a server jar: it
has to be run once so it can write out the libraries and, for Forge and
NeoForge, the `win_args.txt` the server is launched from. `agent/servertypes/
install.py` is the only place that does it, and the rules are:

- the command is built in that module as a list — `[java, "-jar",
  <installer>, *arguments]` — never a string, never through a shell. The
  arguments are fixed per type in its capabilities (`installer_args`):
  `--installServer` for Forge and NeoForge, and `install server <minecraft>
  <loader> --download-server --install-dir=.` for Quilt. The only values
  filled in are the Minecraft and loader versions, after `check_version`
  and after matching the list the official source returned;
- the installer's file name is generated by this app from the plan it built
  out of the official source's answer, never taken from a request, and the
  resolved path is checked to be inside that server's own folder;
- the working directory is fixed to the server folder, `stdin` is
  `DEVNULL`, and output is captured into a timestamped file under the
  server's own `install-log` folder rather than a console;
- it is killed after 20 minutes, and a non-zero exit is an error with the
  log's path, not a silent success;
- the version is checked against the list the official source returned
  before anything is downloaded, and a version string that isn't a version
  never reaches a URL or a file name (`check_version`).

`tests/test_command_isolation.py` pins all of this down, and also keeps a
list of every file in the agent that starts a program at all: a new one
fails that test until it is added on purpose.

Updating this app itself (Phase 7) will be the second such exception. Both
are listed here, and nowhere else does the dashboard run a program.

Console commands pass through `agent/minecraft/commands.py`: single line,
length capped, restricted character set, first token must look like a
Minecraft command, and shell metacharacters (`` ` ``, `;`, `&&`, `||`, `$(`,
newlines, NUL) are rejected. `MinecraftServer.send_command` also refuses
anything containing a newline, so one call can't become two commands.

## Path traversal and arbitrary writes

`agent/security/paths.py` is the only way file names from outside reach
disk. It enforces a single path component, no separators, no `..`, no
Windows reserved device names, an extension allow-list, and a blocklist for
executable extensions. Every resolved path is checked to be inside its base
directory; symlinks and NTFS reparse points are refused rather than
followed.

Backup restore also validates every member of a zip before extracting, so a
crafted archive can't write outside the server folder (zip-slip). The check
is `check_archive_member` in `paths.py`, shared with modpack import and
server duplication: an absolute path, a drive letter, `..` that climbs out,
or a link (a zip entry marked as a symlink) is refused.

**Game settings** write only `server.properties` in the server's own folder,
through a temporary file and a rename, after every known key's value has
passed its check. A copy of the old file is kept as a safety backup first.

**Duplicating a server** writes only inside the new folder, which passes
`check_new_server_folder` (below). It reads only the source server's own
folder, never follows links out of it, and leaves the agent's own folders
behind if they sit inside it. A running source is told to save and pause
saving (`save-all flush`, `save-off`, then `save-on`), so the world is never
copied while Minecraft is writing it; a server that is starting or stopping
is refused. A copy that fails its check is deleted again.

**Modpack import** (`agent/modpack.py`) refuses the whole pack if any
override path would land outside the server folder or is a link, and
refuses any mod whose path isn't a safe single file name inside the folder.
Client-only folders and files with executable extensions in the overrides
are skipped. An uploaded pack is kept in the data folder under a random
token, at most 1 GB, and cleared after 24 hours if not imported.

Two routes take a folder path: adding a server that already exists (`POST
/api/servers`) and creating a new one (`POST /api/new-server`). The second
goes through `check_new_server_folder`, which requires an absolute path
whose parent exists, and a folder that is either absent or empty — never a
drive root, the home folder, a system folder, this app's own folder or
another server's. Creating a server writes `server.properties` and
`eula.txt` and installs the software there; it starts nothing.

For a server that already exists: `check_server_folder` requires an existing, absolute, real
folder (no symlink or reparse point) that holds the named `.jar`, is not a
drive root, the home folder or a system folder, and does not overlap the
agent's own folders or another server's. Registering a folder changes nothing
in it and starts nothing. The Java program and any launch command are never
taken from the dashboard: a new server uses the first server's `java`, and
`raw_command` is config-file only. Removing a server only takes it off the
list; its folder is never deleted.

The CPU core limit (`server.cpu_cores`) is a list of core numbers, checked
against the cores the PC really has. The agent applies it with the operating
system's own call on the process it started (psutil), never with a command,
and adds only the `-XX:ActiveProcessorCount=<n>` JVM flag it builds itself.

## The data folder

The default data folder (`C:\ProgramData\Minecraft Server Controller`) holds
the database, with its sign-in sessions, and the HTTPS private key. A folder
made inside ProgramData lets every account on the PC read it, so on every
start the agent checks the folder's real permissions and, if other accounts
can open it, makes it private to the agent's account, SYSTEM and
Administrators. `python -m agent.main --check` shows the result under Storage
("Data folder access"), read from the folder itself, in any Windows language.
A folder you set in `paths.data_dir` is left as you set it, and `--check`
tells you if other accounts can read it.

## Minecraft's rules (the EULA)

`eula.txt` is written with `eula=false` unless the person has ticked the box
themselves. `POST /api/servers/{id}/eula` is the only thing that writes
`eula=true`, and only from their own tick: the agent never accepts Mojang's
rules on somebody's behalf, and a new server is refused outright without it.

## Permissions

Every REST route declares the permission it needs (`server.control`,
`backups.restore`, `servers.manage`, …, listed in
`agent/security/permissions.py`), and a test fails if a route is added without
one. WebSocket messages are checked the same way.

There are two roles. The **owner** (the account in `.env`, and the API
token) holds every permission. A **helper** can start, stop and restart,
manage players, chat, take a backup and view everything, and nothing else:
no settings, no restoring, downloading or deleting backups, no mods or
versions, no console commands, no user management, and no security page
(it shows sign-in addresses). A permission added later is the owner's
alone until it is added to the helper role on purpose. A helper can also be
limited to some servers: every per-server route is refused for the others
(`server_access`), the server list and jobs leave them out, and the live
connection carries none of their events. `tests/test_helpers.py` walks every
route as a helper and expects 403 wherever the role doesn't allow it.
The player buttons need `players.manage`, game settings and importing a
modpack into a server need `settings.edit`, reading a modpack needs
`mods.manage`, and duplicating or creating a server from a pack needs
`servers.manage`.

## Downloads

Everything the agent downloads — server software, loader installers, mods
and plugins, Geyser and Floodgate — goes through `agent/downloads.py`, which:

- allows HTTPS only, to an allow-list of hosts (Mojang, FabricMC, QuiltMC,
  Forge, NeoForged, PaperMC, PurpurMC, Modrinth, GeyserMC). The host is
  re-checked on every redirect hop, and redirects are followed by hand
  rather than by the HTTP client, so a redirect can't leave the list;
- caps the size of a list (20 MB) and of a file (300 MB), and stops reading
  rather than filling the disk;
- writes to `<name>.part` and renames it into place only after the file has
  been checked, so a failed download leaves nothing behind;
- verifies the strongest checksum the source publishes (SHA-512, SHA-256,
  SHA-1 or MD5 in that order) and deletes the file on a mismatch.

Where a source publishes no checksum — the Fabric launcher jar is one — the
file is recorded as **unverified** and the dashboard says so, rather than
the result being presented as checked (see `docs/honesty.md`). Mod downloads
additionally refuse anything Modrinth hasn't published a checksum for.

Modpack mods are stricter still: each one must be on `cdn.modrinth.com`
and must come with a SHA-512 in the pack; anything else blocks the import
before a single file is downloaded. Each file is checked against that
SHA-512 (`allow_unverified=False`), and a mismatch stops the import: a new
server is removed again, and an existing one is put back from the backup
taken first.

Nothing downloaded is executed by the agent, with the single documented
exception of the loader installer described under Command injection.

## Web surface

- Bearer tokens, not cookies, so CSRF doesn't apply.
- CORS is off by default — the dashboard is served from the same origin.
- `Content-Security-Policy` blocks inline scripts and inline styles and restricts connections
  to the same origin; `X-Frame-Options: DENY` blocks clickjacking;
  `X-Content-Type-Options: nosniff` and a strict referrer policy are set.
- The dashboard builds the DOM through `document.createElement` and text
  nodes, so console output and mod descriptions can't inject markup.
- The WebSocket authenticates in its first message rather than the query
  string, so tokens don't end up in logs or browser history. It checks the
  `Origin` header and is read-only — actions go through the audited REST
  API.
- The CSP gained exactly two directives for installing the dashboard on a
  phone: `worker-src 'self'` and `manifest-src 'self'`. Nothing was
  loosened; inline scripts and styles are still refused.

## The service worker

`agent/web/sw.js` is served from the site root so it covers the whole
dashboard. It exists to open the app full screen from a phone's home screen
and to deliver phone alerts.

- It caches **only** this origin's own static files (the page, the
  stylesheet, the scripts, the icons and the manifest). Anything under
  `/api` or `/ws` returns before the caching branch, so no world data, no
  player name and no sign-in token is ever written to the phone's storage.
- It asks the network first and falls back to the cache, so the dashboard is
  never a stale copy of itself. When the PC can't be reached at all,
  opening any dashboard address gets the cached page, whose offline screen
  ("Can't reach your PC") tries `/api/health` again by itself.
- It calls no `eval`, no `Function` and no `importScripts`, so nothing it is
  sent can become code.
- A phone alert is rendered from the JSON in the push message alone; the
  worker fetches nothing while showing one.
- `tests/test_install_on_phone.py` checks each of these points.

## Phone alerts

The VAPID key pair lives in `.env` with the other secrets, made by setup
(`.\setup.ps1`, or `python -m installer.make_push_keys` for just that step),
which keeps a pair that works and never prints the private half. The public
half is handed to each phone's browser, which is what it is for; the private
half never leaves the PC, and `/api/push` serves only the public one. A pair
whose halves don't belong together counts as not set up.

Each message is encrypted for one subscription (RFC 8291) before it is
posted, so the browser vendor's push service carries text it cannot read,
and every request is signed with the VAPID key (RFC 8292) so a push service
can tell this app's messages apart from anyone else's. Both are implemented
in `agent/notifications/push.py` with `cryptography` — no extra dependency,
no third-party service account.

The agent sends each alert to the endpoint the browser supplied, so only
endpoints on the browser makers' push services are accepted (HTTPS, port
443, and a host under `fcm.googleapis.com`, `push.services.mozilla.com`,
`push.apple.com` or `notify.windows.com`). An address on the home network or
anywhere else is refused, so the subscribe endpoint can't be used to make
the agent post to another machine.

A subscription is stored only with the endpoint and the two keys the browser
supplied, and is deleted the first time its push service answers 404 or 410.
At most 20 phones can be signed up. The list shown in the dashboard never
includes the keys.

## Auditing

Every privileged action is written to `audit_log` with the time, user,
source address, action, target and result. Routes write their own, more
specific entries; any other signed-in POST, PUT or DELETE gets a plain one
from a middleware in `agent/main.py`, refused ones (403) included, so a
helper's every attempt is recorded under their name. The Security page shows it. Mod
changes also get a record in `mod_history` with checksums and source URLs.

## Transport

- HTTPS is mandatory in practice — the agent refuses to serve plain HTTP on
  any address other than `127.0.0.1`, and exits with an explanation rather
  than starting insecurely.
- The certificate is real: either Let's Encrypt via Tailscale, or a local CA
  you trust once per device. No permanent click-through warnings.
- Startup is gated on TLS validity — a missing, unparseable, expired or
  mismatched certificate stops the agent rather than being worked around.
- HSTS is sent over HTTPS only, never on loopback.
- HTTP, if enabled at all, is a redirect-only listener that refuses anything
  except `GET`/`HEAD` and serves no API or data.
- WebSockets inherit the page scheme, so an HTTPS dashboard always uses
  `wss://`, and the socket authenticates in its first message.
- Certificate verification is never disabled — the agent's own HTTPS
  self-check loads the CA bundle and verifies.
