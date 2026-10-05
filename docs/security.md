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
  sign-in for 15 minutes, with `Retry-After` in the response.
- All API requests are rate limited (120/minute per address by default).
  Rejected requests don't count, so retrying doesn't extend the block.

## Secrets

Secrets are read from environment variables via `.env`:
`MCSC_ADMIN_PASSWORD_HASH`, `MCSC_API_TOKEN`, `MCSC_DISCORD_WEBHOOK`,
`MCSC_SMTP_USERNAME`, `MCSC_SMTP_PASSWORD`.

None of these appear in `config.yaml`, in source, or in the browser, and
`.env` is gitignored. The settings API reports only whether a secret is
configured, never its value.

## Command injection

There's no endpoint that runs a shell command. Minecraft is launched with an
argument list and no shell, from a fixed working directory, using values
that only come from `config.yaml`.

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
crafted archive can't write outside the server folder (zip-slip).

The one route that takes a folder path is adding a server (`POST
/api/servers`). `check_server_folder` requires an existing, absolute, real
folder (no symlink or reparse point) that holds the named `.jar`, is not a
drive root, the home folder or a system folder, and does not overlap the
agent's own folders or another server's. Registering a folder changes nothing
in it and starts nothing. The Java program and any launch command are never
taken from the dashboard: a new server uses the first server's `java`, and
`raw_command` is config-file only. Removing a server only takes it off the
list; its folder is never deleted.

## Permissions

Every REST route declares the permission it needs (`server.control`,
`backups.restore`, `servers.manage`, …, listed in
`agent/security/permissions.py`), and a test fails if a route is added without
one. WebSocket messages are checked the same way. Today every signed-in
account has every permission; this is the hook helper accounts will use.

## Downloads

Mod downloads are HTTPS-only, restricted to Modrinth's CDN, verified
against the SHA-512 Modrinth publishes, size-checked, confirmed to be real
zip archives containing `fabric.mod.json`, and refused if no checksum was
published. Nothing downloaded is executed by the agent.

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

## Auditing

Every privileged action is written to `audit_log` with the time, user,
source address, action, target and result. The Security page shows it. Mod
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
