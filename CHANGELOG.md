# What's new

Each release lists what changed in plain words. The release workflow copies
the newest section onto the GitHub release, and the dashboard shows it as
"What's new" when an update is ready.

Changes a client (the dashboard, or the phone app) must know about are listed
under **API**, with the API version they arrived in. The API version is shown
at `/api/version` and only goes up for those changes.

## 1.2.0

- A real Windows installer: one setup file that opens its own window, in
  the dashboard's colors (light or dark, following Windows), with a few
  short screens, a Start menu entry and an "Installed apps" entry. It finds an older copy by itself
  and offers to update it, keeping your settings, servers and backups.
- Copies made with `setup.ps1` are moved over with every file checked, and
  the old folder is left where it was until you choose to remove it.
- Every update makes a restore point first and puts things back by itself if
  the new version doesn't start.
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
