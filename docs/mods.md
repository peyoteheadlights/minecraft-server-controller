# The mod manager

This is the part that can break a server badly, so it is the part with the most
safety rails.

## Mods or plugins, depending on the server

What a server takes comes from its type (`agent/servertypes/`), not from an
assumption that every server is Fabric:

| Type | Takes | Folder | What a file has to carry |
| --- | --- | --- | --- |
| Vanilla | nothing | — | the page isn't offered at all |
| Fabric | mods | `mods/` | `fabric.mod.json` |
| Quilt | mods | `mods/` | `quilt.mod.json`, or `fabric.mod.json` — Quilt loads most Fabric mods |
| Forge | mods | `mods/` | `META-INF/mods.toml` |
| NeoForge | mods | `mods/` | `META-INF/neoforge.mods.toml` |
| Paper, Purpur | plugins | `plugins/` | `plugin.yml` or `paper-plugin.yml` |
| Bedrock | packs (an **Add-ons** page of its own) | `behavior_packs/`, `resource_packs/` | `manifest.json` with a valid UUID and version |

A Bedrock server's Add-ons page takes `.mcpack`, `.mcaddon` and `.mctemplate`
files (Bedrock add-ons aren't on Modrinth, so there is no search). Each
pack's `manifest.json` is checked, every path in the file is checked to
stay inside the pack's folder, and the pack is turned on in the server's
world (`world_behavior_packs.json` / `world_resource_packs.json`). Mojang's
own packs aren't listed. Removing a pack turns it off and moves it into the
data folder's `removed-addons/`. See `agent/addons.py`.

The page names itself after the server it is showing — "Mods" or "Plugins" —
and a file that belongs to a different loader is flagged by what its own
metadata says, with the file it was read from named.

## The installed mods table

| Column | Meaning |
| --- | --- |
| Mod | Display name from `fabric.mod.json`, with the mod id underneath |
| Version | The version the mod declares |
| Minecraft | The Minecraft range the mod says it supports |
| Status | `ok`, `warn`, `error`, or `disabled` — errors are explained above the table |
| Update | The newer Modrinth version, if one exists for your Minecraft version |

All of it is read straight from the jar: the agent opens it as a zip file and
parses the metadata member that type uses (JSON for Fabric and Quilt, TOML for
Forge and NeoForge, YAML for Paper plugins). It never loads or runs mod code.

Forge and NeoForge declare their Minecraft support as a Maven range
(`[1.20.1,1.21)`), Fabric as its own (`>=1.21 <1.22`). Both are read in their
own syntax; a file that declares nothing is **Unknown**, never assumed to
fit.

## Installing from Modrinth

Search, pick a mod, and you get a confirmation panel before anything is
written. It shows the file name and size, the Minecraft versions, whether the
mod works server-side, the licence, and how many required dependencies it
declares.

What happens when you confirm:

1. Compatibility is checked against the Minecraft version the server reported
2. Required dependencies are listed — never installed behind your back
3. Conflicts with what you have are checked
4. The current mods folder state is archived
5. The file is downloaded to a temporary `.part` file
6. The **SHA-512 that Modrinth published is verified** against the bytes received
7. The file is confirmed to be a real zip carrying the metadata this server's
   type uses
8. Only then is it moved into the mods folder
9. The source URL and a SHA-256 are recorded in the audit trail

If any step fails the temporary file is deleted and your mods folder is
untouched.

### The rules the downloader enforces

Every download, here and elsewhere, goes through `agent/downloads.py` — the
rules are in `docs/security.md`. On top of them, for mods:

- HTTPS only, and only from `cdn.modrinth.com` / `cdn-raw.modrinth.com`
- `.jar` files only — `.exe`, `.bat`, `.ps1`, `.cmd`, `.dll` and friends are
  refused by name before anything is fetched
- No path separators in file names, so nothing can escape the mods folder
- A file with no published checksum is refused rather than trusted
- 300 MB ceiling per file

## Why the server must be stopped

Installing, removing, enabling, disabling and updating all require the server
to be OFFLINE or CRASHED. Windows locks jars that a running JVM has open, and
Fabric reads the mods folder exactly once at startup — changing it underneath a
running server produces confusing half-states. The dashboard disables those
buttons and says why. Paper and Purpur read `plugins/` the same way.

## Changing the kind of server

Changing a server's type (Server settings → Kind and version) checks every
installed add-on against the type you are moving to and lists the ones that
don't fit **before** anything happens. Those files are moved to the mod trash,
where the usual restore puts them back. Nothing is deleted.

## Removing a mod

Before it does anything, the dashboard shows which installed mods declare this
one as a required dependency. Removing Fabric API with twelve mods depending on
it is a decision, not an accident.

The jar is then **copied to `mod-backups/` and moved to `mod-trash/`**. It is
never deleted outright, so a mistake costs you one click to undo.

## Enable and disable

Disabling renames `sodium.jar` to `sodium.jar.disabled`. Fabric only loads
files ending in exactly `.jar`, so the mod stops loading but the file stays put.
This is the fastest way to bisect a crash: disable half your mods, start, repeat.

## Updates and rollback

Checking for updates asks Modrinth for the newest build matching your Minecraft
version. Updating archives the current jar first, then swaps it. If the download
or the swap fails, the old jar is put straight back.

Every version the manager has ever seen is kept in `mod-backups/<mod_id>/` with
its SHA-256 recorded. **History** on any mod lists them, and **Roll back**
restores one — after re-verifying the archived file's SHA-256, so a corrupted
archive is refused rather than installed.

## Dependency and conflict checks

Run on every page load, and reported at the top of the mods page:

- a required dependency that is missing or disabled
- a dependency present but at a version outside the required range
- two enabled jars providing the same mod id
- a mod that declares it `breaks` another mod you have installed
- a Forge mod sitting in a Fabric server's mods folder

### What it cannot see — stated plainly

The page says this too, because it matters:

- **Only declared metadata is checked.** Two mods can corrupt each other's
  world data with nothing in either `fabric.mod.json` to suggest it.
- **Minecraft and Fabric versions are learned from the console**, so before the
  first successful start those checks are skipped rather than guessed.
- Maven-style ranges like `[1.0,2.0)` are not modelled; those are reported as
  "could not be checked" instead of being silently treated as passing.

## Modpacks

A Modrinth modpack (`.mrpack`) can become a new server (the **+** tab,
**From a modpack**) or be imported into the open server (Mods page,
**Import a modpack**).

Choosing the file reads it and changes nothing. The panel shows the Minecraft
version, the loader and its version, and every file, marked as downloaded,
skipped or refused:

- **Skipped**: files the pack marks as not for servers (`env.server` is
  "unsupported"), and folders only the game uses (resource packs, shader
  packs, `options.txt`) in its extra files. Files with program extensions
  (`.exe`, `.bat`, …) in the extra files are skipped too. Optional server
  files are included.
- **Refused**: a mod with no SHA-512 in the pack, one that isn't on
  Modrinth's own download site (`cdn.modrinth.com`), or one whose file name
  or folder isn't safe to write. Any refused file blocks the import, and so
  does an extra file whose path would land outside the server folder or is
  a link.

Importing downloads every mod through the safe downloader and checks it
against the pack's SHA-512, then copies the pack's extra files (`overrides/`,
then `server-overrides/`). The server type and version are set up with the
same installer as **New server** and **Change the kind or version**.

Into an existing server, the import stops the server and takes a verified
backup first. If the server isn't already on the pack's type and versions
(as its console last reported them), the version is changed first. The mods
it had are moved to the mod trash in a `<date>-before-modpack` folder, never
deleted. If anything fails, the server is put back from the backup.

## The audit trail

Every mod action is recorded with the time, who did it, the action, the mod,
the old and new versions, the source URL, the SHA-256 and the result — including
failed attempts. It is at the bottom of the Mods page and in the database table
`mod_history`.
