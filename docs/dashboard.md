# Using the dashboard

Sign in with the username and password you created with
`python -m installer.make_secrets`. The session lasts 12 hours by default.

## Layout and appearance

Sections are grouped in the sidebar: **Servers** (All servers), **Server**
(Overview, Console, Players, Performance), **Manage** (Backups, Mods,
Schedules), **Activity** (Events, Crash history) and **System** (Settings,
Security). The server's state is always visible at the top of the sidebar.

With more than one server, the top of the sidebar is a picker. Every page acts
on the server picked there, and this browser remembers the choice. If another
server crashes, a message names it with a button to switch, and a red badge
stays next to the picker until you look at that server. **All servers** shows
each server's state, players, uptime and port. Running backups and restores
appear under the server state with their real progress.

At the bottom of the sidebar you can choose the appearance: match the system,
light, or dark. The choice is remembered in this browser. On narrow windows
the sidebar shrinks to icons, and on a phone it opens from the menu button.

## Overview

The page leads with the server's state in plain words: **Online**,
**Offline**, **Starting…**, **Stopping…**, **Restarting…** or **Crashed**.
Each has a coloured dot, but the word always says it too.

- **While starting**, it shows the stage the console has actually reached
  (launching Java, loading mods, starting the server, loading the world) and
  how long it has taken.
- **When crashed**, it says the server stopped unexpectedly, gives the exit
  code, and states the likely cause from the crash report with its
  confidence. *View Crash Details* opens the evidence.

The buttons change with the state. Start is the main action when the server
is stopped; Stop is shown as destructive when it is running, and asks for
confirmation. While an operation runs, the buttons show progress and cannot
be clicked again.

Below that: players, TPS, MSPT, the server's measured memory against its
limit, and CPU; then who is online, the detected versions, and the most
recent console lines. Anything the agent cannot measure says **Unknown**.

## Console

Live output from the server. Times are in their own column, warnings and
errors are coloured, and your own commands are marked.

- **Filter** narrows the lines as you type
- **Auto-scroll** follows new lines; scroll up to read and it stops following
  until you return to the bottom
- **Pause** stops new lines arriving
- **Copy** and **Download** take the visible lines
- **Clear** empties this view only; the server's log files are not touched

The box at the bottom sends one Minecraft command. It is not a Windows shell.
Commands such as `stop`, `op`, `ban` and `whitelist` ask for confirmation.

## Players

Who is online now with session length, and everyone ever seen with first seen,
last seen, session count and total playtime. IP addresses are deliberately not
recorded.

## Performance

Current CPU, RAM, disk and network, this server's own share of the PC's CPU
(with how many cores it runs on, read from its process), six hours of history
as sparklines, the health checks, and a storage breakdown by category. The
PC's CPU is one reading shared by every server, and shows Unknown until two
readings a second apart exist.

Each health check shows the measured value **and the threshold it was compared
against**, so a warning is never mysterious. Checks that cannot be measured —
TPS with no tick-reporting mod — say `unknown` and explain why, rather than
showing a made-up number.

## Backups

Worlds with sizes and last-backup times, the backup list, and buttons to create,
verify, download, restore and delete. Restore shows a full list of what it is
about to do before it does any of it. See [backups.md](backups.md).

**Last change** at the top shows the newest restore (or other safe change) on
this server with an **Undo this change** button. Undo restores the safety copy
taken just before that change; it is a change of its own, with its own safety
copy, so it can be undone too. The toast after a restore has the same Undo
button.

While a restore runs, the server cannot be started from anywhere (the button,
a schedule, another device), and mod changes wait: a server runs one change
like this at a time.

## Mods

The mod manager. See [mods.md](mods.md) — it has the most detail and the most
caveats.

## Schedules

Add a task, choose daily (`23:00`), weekly (`sun 04:00`) or interval (`6h`),
and enable or disable it. The next run time is shown for each. **Run now**
executes one immediately for testing.

Three schedules are created on first run: a nightly backup (on), a weekly
restart (off), and a weekly log cleanup (on).

## Events

Everything the agent has recorded, newest first: starts, stops, crashes,
backups, mod changes, threshold breaches, scheduled tasks.

## Crash history

One row per crash with the exit code, the category, and the confidence.
**Details** opens the evidence: the matched log lines, the Minecraft, Fabric and
Java versions, who was online, and where the saved crash report and log live on
disk. It ends with a reminder that this is a rule match on log text, not a
diagnosis.

## Settings

**Servers** lists every server. **Add a server** registers a folder that
already holds a Minecraft server (its name, the full folder path, and the jar
if it is not `fabric-server-launch.jar` or `server.jar`); nothing in the folder
is changed and the server is not started. **Remove** takes a server off the
list after you confirm; its folder, world, mods and backups stay where they are.

Below that: auto-restart behaviour (for the selected server when there are
several), **CPU cores** (tick the cores this server may use, or **Use every
core**; it shows which cores other servers are set to, and the cores the
running server really uses, read from its process), alert thresholds, notification channels and per-event checkboxes,
and maintenance mode. Changes are written to `config.yaml` when you press Save.

Only a safe subset of settings can be changed here. Things that would change
what the agent executes — the server directory, the launch command — are
rejected by the API even if the request is crafted by hand.

## Security

Agent and Tailscale status, whether authentication is configured, active
sessions with their addresses, failed sign-in count, and the audit log. You can
rotate your own token or revoke every session at once.
