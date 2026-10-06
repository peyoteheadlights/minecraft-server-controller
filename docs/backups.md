# Backups and restoring

## What is backed up

From `config/config.yaml`:

```yaml
backups:
  include:
    - world
    - world_nether
    - world_the_end
    - server.properties
    - config
    - mods
```

Each backup is a single `.zip` in `backups/` in the data folder (`servers/<id>/backups/` for a second server), with a SHA-256 recorded
in the database.

## Creating one

Press **Back up now**, or let the nightly schedule do it (23:00 by default).

While the server is running the agent sends `save-all flush`, waits, then
`save-off` so nothing is written mid-copy, zips everything, and re-enables
saving with `save-on` — even if the zip fails. `session.lock`, which the JVM
holds open on Windows, is skipped. Symlinks are never followed.

Before starting, it checks there is enough free space and refuses with a clear
message rather than filling your disk.

## Verifying

**Verify** re-opens the archive, runs a zip integrity test over every member,
and re-computes the SHA-256 to compare against the value recorded at creation.
Worth doing occasionally — a backup you have never verified is a hope, not a
backup.

## Restoring

Restore is deliberately slow and loud. Pressing it shows exactly what will
happen, then on confirmation:

1. The archive is **verified first** — a damaged backup is refused before
   anything is touched
2. The Minecraft server is stopped if running
3. A **safety backup of the current state** is taken and named `safety-…`
4. Every path inside the archive is checked so nothing can write outside the
   server folder
5. Current `world/` etc. are **moved aside** as `world.replaced-20260920-1030`,
   not deleted
6. The archive is extracted
7. If anything fails, the moved-aside folders are put back
8. The server starts again only if you ticked that box

Your old world is still on disk afterwards, under its `.replaced-` name. Delete
it yourself once you are happy.

## Restore world

**Restore world** is the same restore, arranged as a timeline instead of a
list of files: every backup that holds a world, newest first, each with what
going back to it would lose in plain words ("3 hours ago · about 2 hours of
play lost"). The play figure comes from the sessions the player tracker
recorded. Where nothing was recorded, it says so rather than claiming nobody
played.

Two things are different from the Backups page:

- **The server must already be off.** This page does not stop Minecraft for
  you: stopping a server people are playing on is not part of choosing a
  point in time. Stop it from Overview first.
- **A backup that was not checked is not offered**, and the page says why.

Everything else is the ordinary restore above, safety backup and all, so
going back can itself be undone from the Backups page.

## Retention

```yaml
keep_daily: 7
keep_weekly: 4
keep_monthly: 3
```

Retention runs after each new backup. It keeps the newest backup of each day,
week and month up to those limits.

- **Manual backups are never auto-deleted.**
- Safety backups are kept for 14 days.
- Retention only ever deletes files inside the backup folder. It cannot touch a
  live world.

## Disaster recovery

If the PC dies completely: copy a `.zip` from the data folder's `backups/` onto the new
machine, install your Fabric server, and unzip the archive into the server
folder. The archive's layout is exactly the server folder's layout — no special
tool needed to read it.

That is why backups are plain zips and not a custom format.
