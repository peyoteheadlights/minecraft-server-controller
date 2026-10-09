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

The world is always included as `server.properties` names it: with
`level-name=survival`, the folders `survival`, `survival_nether` and
`survival_the_end` are backed up even though the list says `world`.

Each backup is a single `.zip` in `backups/` in the data folder (`servers/<id>/backups/` for a second server), with a SHA-256 recorded
in the database.

## Creating one

Press **Back up now**, or let the nightly schedule do it (23:00 by default).

While the server is running the agent sends `save-all flush`, waits, then
`save-off` so nothing is written mid-copy, zips everything, and re-enables
saving with `save-on` — even if the zip fails. `session.lock`, which the JVM
holds open on Windows, is skipped. Symlinks are never followed.

A running **Bedrock** server can't pause saving that way. Instead the agent
sends `save hold`, asks `save query` until the server answers "Data saved.
Files are now ready to be copied." with its list of files and lengths, copies
each listed file cut to its listed length (a path outside `worlds/` stops the
copy), and then always sends `save resume`, even when the copy failed. A
stopped Bedrock server's files are copied directly. Both are verified like
any other backup.

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
play would be lost"). The play figure is how long anybody was on, from the
sessions the player tracker recorded; friends playing together for an hour
count as one hour, not one per player. Where nothing was recorded, it says so rather than claiming nobody
played.

Three things are different from the Backups page:

- **Only the world goes back.** The world folders (the one `level-name` in
  `server.properties` names, plus its `_nether` and `_the_end`) are put back;
  mods, config and `server.properties` stay as they are now, so a mod added
  since the backup is still there. The Backups page restores everything the
  backup holds.

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
