# Security

## Assumptions

- The dashboard is reachable **only** over your tailnet, over HTTPS. It binds
  to one address and that address is not routable from the internet.
- The Minecraft PC is trusted. Anyone with a login on that machine can already
  do everything the agent can.
- The threat being defended against is: someone on your network, a malicious
  web page in another browser tab, a hostile file name from Modrinth, and your
  own mistakes.

## Authentication

- Passwords are stored as **PBKDF2-HMAC-SHA256, 240,000 rounds, per-install
  salt**. The password itself never touches disk, logs, or the database.
- Signing in returns a random 256-bit session token. Only its SHA-256 is
  stored, so a stolen database yields no usable tokens.
- Sessions expire (12 hours by default) and can be rotated or revoked.
- A long-lived API token is supported for scripts and compared in constant time.
- Failed attempts are counted per user and per address. Five failures locks
  sign-in for 15 minutes; the response carries `Retry-After`.
- All API requests are rate limited (120 per minute per address by default).

## Secrets

Secrets are read from environment variables only, via the `.env` file:
`MCSC_ADMIN_PASSWORD_HASH`, `MCSC_API_TOKEN`, `MCSC_DISCORD_WEBHOOK`,
`MCSC_SMTP_USERNAME`, `MCSC_SMTP_PASSWORD`.

They are never in `config.yaml`, never in source, never sent to the browser,
and `.env` is in `.gitignore`. The settings API reports only whether each
secret *is configured*, never its value.

## Command injection

- There is **no** endpoint that runs a shell command. None.
- Minecraft is launched with an argument **list** and no shell, from a fixed
  working directory, using values that only come from `config.yaml`.
- Console commands pass `agent/minecraft/commands.py`: single line, length
  capped, restricted character set, the first token must look like a Minecraft
  command, and shell metacharacters (`` ` ``, `;`, `&&`, `||`, `$(`, newlines,
  NUL) are rejected.
- `MinecraftServer.send_command` independently refuses anything containing a
  newline, so one call can never become two commands.

## Path traversal and arbitrary writes

`agent/security/paths.py` is the only way file names from outside reach the
disk. It enforces: single path component, no separators, no `..`, no Windows
reserved device names, an extension allow-list, and an explicit executable
extension blocklist. Every resolved path is then checked to be inside its base
directory, and symlinks and NTFS reparse points are refused rather than
followed.

Backup restore additionally validates **every member of the zip** before
extracting, so a crafted archive cannot write outside the server folder
(zip-slip).

## Downloads

Mod downloads are HTTPS-only, restricted to Modrinth's CDN hosts, verified
against the SHA-512 Modrinth published, size-checked, confirmed to be real zip
archives containing `fabric.mod.json`, and refused entirely if no checksum was
published. Nothing downloaded is ever executed by the agent.

## Web surface

- Bearer tokens, **not cookies** — so cross-site request forgery does not apply.
- CORS is off by default because the dashboard is served from the same origin.
- `Content-Security-Policy` blocks inline scripts and restricts connections to
  the same origin; `X-Frame-Options: DENY` blocks clickjacking;
  `X-Content-Type-Options: nosniff` and a strict referrer policy are set.
- The dashboard builds the DOM through `document.createElement` and text
  nodes, so console output and mod descriptions cannot inject markup.
- The WebSocket authenticates in its **first message**, not in the query
  string, so tokens do not end up in logs or browser history. It also checks
  the `Origin` header, and it is read-only: actions go through the audited
  REST API.

## Auditing

Every privileged action is written to `audit_log` with the time, user, source
address, action, target and result. The Security page shows it. Mod changes get
a second record in `mod_history` with checksums and source URLs.

## Transport

- **HTTPS is mandatory in practice.** The agent refuses to serve plain HTTP on
  any address other than `127.0.0.1`, and exits with an explanation rather than
  starting insecurely.
- **The certificate is real.** Either Let's Encrypt via Tailscale, or a local
  CA you trust once per device. No permanent click-through warnings.
- **Startup is gated on TLS validity.** A missing, unparseable, expired or
  mismatched certificate stops the agent rather than being worked around.
- **HSTS** is sent over HTTPS only, and never on loopback.
- **HTTP**, if enabled at all, is a redirect-only listener that refuses
  anything except `GET`/`HEAD` and serves no API or data.
- **WebSockets** inherit the page scheme, so an HTTPS dashboard always uses
  `wss://`, and the socket authenticates in its first message.
- **Certificate verification is never disabled.** The agent's own HTTPS
  self-check loads the CA bundle and verifies.
