# What's new

Each release lists what changed in plain words. The release workflow copies
the newest section onto the GitHub release, and the dashboard shows it as
"What's new" when an update is ready.

Changes a client (the dashboard, or the phone app) must know about are listed
under **API**, with the API version they arrived in. The API version is shown
at `/api/version` and only goes up for those changes.

## 1.4.0

- **Phone apps** for Android and iPhone, built natively for each (not the
  dashboard in a frame). Scan the code in the dashboard's App settings with
  the app's own camera view, sign in once, and the app stays signed in
  behind your phone's unlock. In this first version: every server's state
  and players, Start, Stop and Restart (Stop and Restart ask first), a
  Notifications tab with the PC's alerts, a home-screen widget, and Help &
  About in the app. The apps are being tested before they go into the
  stores.
- **Lock-screen alerts in the Android app**, through Google's Firebase
  Cloud Messaging, sent by the agent itself with your own free Firebase
  key (`docs/notifications.md`). Google only carries a nudge with an alert
  number in it; the phone reads the alert from your PC.
- The agent keeps its newest 200 alerts for the app's Notifications tab,
  whether or not Discord, email or phone alerts are turned on.
- PRIVACY.md says what the app and the phone apps contact, and when.
- "Report a problem" and "Suggest a feature" on GitHub are forms now, with
  a reminder never to paste a password.

### API (version 1)

- `GET /api/alerts` (the alerts since a given number, for the phone apps)
  and `GET|PUT|DELETE /api/app/phone` (this sign-in's push address for
  lock-screen alerts). Additive.
- `POST /api/auth/login`, `POST /api/auth/logout` and `GET /api/auth/me`
  now describe their answers in `/api/openapi.json`. Nothing changed in
  what they answer.

## 1.3.0

- Passwords are stored more strongly (600,000 rounds instead of 240,000).
  Nothing to do: each password is upgraded the next time that person signs
  in.
- When the app hits an unexpected error, the dashboard shows an error
  number. The same number is on the matching lines of the app's logs (and
  so in a Get help file).
- A short SECURITY.md says how to report a security problem
  privately.
- For whoever publishes releases: double-click `make-update-key.cmd` to make
  the update-signing key. It saves the private half as the GitHub secret
  and writes the public half into the app, and asks before replacing a key.
  It works with the newest Python too: it installs only the one library it
  needs.
- **Bedrock servers.** Pick Bedrock in the "+" tab to run Mojang's Bedrock
  Dedicated Server for friends on phones, tablets and consoles. It gets its
  own tab (marked "Bedrock"), and:
  - the download comes from Mojang. Mojang offers only the newest version
    and publishes no checksum, so it is marked unverified, its SHA-256 goes
    in the install log, and every version downloaded is kept so you can go
    back to it. Nothing is downloaded until you tick that you accept
    Mojang's EULA and Privacy Policy;
  - updates replace only the program: worlds, settings, the allowlist,
    permissions and your packs stay, and the change can be undone;
  - an Add-ons page for .mcpack, .mcaddon and .mctemplate files, each
    checked before it's installed and turned on per world;
  - .mcworld import (with a warning when the world is newer than the
    server) and download;
  - backups while it runs use Bedrock's own save hold, and always let it
    save again afterwards;
  - players are tracked by their Xbox ID; allowlist, operator and kick work.
    There is no ban list on Bedrock, and its console doesn't show chat, so
    the pages say so;
  - memory, game speed and crossplay say "not available for Bedrock
    servers", and a Bedrock server can't be turned into a Java one (or the
    other way round): create a new server instead;
  - ports are UDP (19132, and 19133 for IPv6), never clashing with Geyser on
    another server, and "is it reachable" uses Bedrock's own ping.
- For developers: dependencies are declared in `pyproject.toml` (the
  hash-pinned lock files are made from it and stay as strict); CI checks
  the locked versions for known security problems (`pip-audit`), runs
  GitHub's CodeQL scan, and prints test coverage.

### API (version 1)

- Every answer has an `X-Request-ID` header, and error answers repeat it as
  `request_id`. Additive; nothing a client relies on changed.
- Bedrock: `GET|POST /api/bedrock/terms`, `GET /api/bedrock/versions`, the
  per-server `/addons` routes, and `edition` and `capabilities` on each
  server row. Additive.

## 1.2.0

- A real Windows installer: one setup file that opens its own window, in
  the dashboard's colors (light or dark, following Windows), with a few
  short screens, a Start menu entry and an "Installed apps" entry. It finds an older copy by itself
  and offers to update it, keeping your settings, servers and backups.
- Copies made with `setup.ps1` are moved over with every file checked, and
  the old folder is left where it was until you choose to remove it.
- Every update makes a restore point first and puts things back by itself if
  the new version doesn't start.
- A new install that lets other devices in listens on the PC's Tailscale
  address, so the address on the last screen opens from your phone. Without
  Tailscale it stays on this PC only and shows `https://localhost:8765`.
- The installer can install Java (Eclipse Temurin) for you, checked against
  its published checksum, and point the servers you tick at it. When a
  server needs a newer Java, the dashboard says to open the setup from the
  Start menu.
- The app tells you when a new version is out (a dot on the gear) and can
  install it for you, after you confirm, from this app's own GitHub
  releases only. Every update is signed: the app refuses one whose signature
  doesn't match the key built into it, before it even checks the file.
- Setup now stops with a clear message if it can't make the password file
  private, instead of carrying on, and the health check says who can open
  that file.
- Each release says where it was built (GitHub artifact attestations).
- "Open on your phone": a code to scan that has the PC's address and its
  certificate fingerprint, ready for the phone app.
- The Security page lists the devices that are signed in, with a sign-out
  button for each, and the sign-in screen has "Keep me signed in on this
  device".
- Links name the server and page, like `#survival/console`, so reloading or
  going back stays on the same server. Phone alerts open the server and page
  they are about.

### API (version 1)

- `/api/version` gives the app version and the API version.
- `/api/pairing` gives the pairing code shown in the installer and the
  dashboard.
- `/api/sessions` lists signed-in devices; `DELETE /api/sessions/{id}` signs
  one out. Sign-in takes `remember` and `device`.
- `/api/updates` and its `check`, `preflight` and `install` actions.
- The main phone routes now describe their answers in `/api/openapi.json`.
  A route or field is only removed after it has been marked deprecated for a
  release.

## 1.1.0

- Several servers in one dashboard, each with its own tab and color.
- Server types (Vanilla, Fabric, Quilt, Forge, NeoForge, Paper, Purpur),
  version changes and crossplay with Bedrock players.
- Everyday tools: game settings, player buttons, duplicate a server,
  modpacks, join info.
- Quality of life: auto-sleep, world undo, chat, phone alerts.
- First-run checklist, helper accounts, world import, off-PC copies and
  password reset.
