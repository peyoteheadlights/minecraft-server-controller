# Using the dashboard

Sign in with the username and password you created with
`python -m installer.make_secrets`. The session lasts 12 hours by default.

## Tabs, colors and layout

Each server has a tab across the top, like the dividers in a folder, with
**All servers** on the left and **+** (add a server) on the right. The whole
page under a tab takes that server's color: the header, the page itself and
its cards are all tinted with it, and its buttons are filled with it. The
server's own pages (Overview, Players, Backups, Mods, Schedules,
Performance, Console, Events, Crashes, Server settings) are listed down the
left side of the page, under its name. The browser tab's icon takes the
server's color too. Left/Right arrow keys move between tabs, Home and End
jump to the ends, and the dashboard remembers the last server you looked at.

Every server has one of twelve colors, or any color you pick, set in
**Server settings > Name and color**. A new server gets the next unused one.
All text, links and status colors are darkened or lightened against the
tinted page so they stay readable whatever the color, in every theme. High
contrast keeps the tint faint.

If another server crashes, its tab gets a red **!**, and a message names it
with a button to switch to it. **All servers** shows one card per server with
its state, players, uptime and port.

On a phone, the tabs scroll sideways, and the page list becomes a row under
the server's name that scrolls sideways too; nothing on a page is wider than
the screen.

## Settings for this app (the gear)

The gear at the top right opens the settings that apply to the whole app,
next to **Security**:

- **Appearance**: Match my device (the default), Light, Dark, Graphite or
  High contrast. It applies at once and follows your account to other
  devices.
- **How much detail**: **Simple** (the default) uses everyday words ("Server
  speed", "Memory used") and folds away the extra options. **Technical** uses
  the exact terms (TPS, MSPT, RSS, `-Xmx`), shows extra columns and graphs,
  and opens the "Advanced" sections. Every label in the dashboard has both
  versions.
- **Alerts**: thresholds, Discord and email, and which events send one.
- **Maintenance mode** and the **Windows startup** check.

## Overview

The page leads with the server's state in plain words: **Online**,
**Offline**, **Starting…**, **Stopping…**, **Restarting…** or **Crashed**.
Each has a colored dot, but the word always says it too.

- **While starting**, it shows the stage the console has actually reached
  (launching Java, loading mods, starting the server, loading the world) and
  how long it has taken.
- **When crashed**, it says the server stopped unexpectedly and states the
  likely cause from the crash report with its confidence (Technical adds the
  exit code). *What happened?* opens the evidence.

The buttons change with the state. Start is the main action when the server
is stopped; Stop asks for confirmation. While an operation runs, the buttons
show progress and cannot be clicked again.

Below that, four numbers: players, server speed (TPS), memory used against
its limit, and how busy the PC is. Hover or tap one for a short summary of
the last hour. Then three cards: **Last backup** (with **Back up now**),
**Next scheduled task**, and **Players online**, and a **Details** list
(Minecraft version, port, mods, free disk space). Technical mode also shows
the most recent console lines. Anything the agent cannot measure says
**Unknown**.

**Suggestions** appear when there is a reason for one, such as no backup
schedule or no backup in a week. Each says why and what it is based on.
**Not now** hides it until the evidence changes; **Don't show again** hides it
for good, and **Show again** brings hidden ones back.

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

Who is online now with how long they have been playing (Technical adds their
UUID), and everyone ever seen with first seen, last seen, times joined and
total time played. IP addresses are deliberately not recorded.

## Performance

Graphs of server speed (TPS), memory, CPU and players, over 1 hour, 6 hours,
24 hours or 7 days (the choice is remembered). Times run along the bottom and
units up the side. While the server was off the line has a gap rather than
dropping to zero, and the memory graph has a dashed line at the server's
limit. Hover a graph, or focus it and use the arrow keys, to read exact
values.

Technical mode adds the MSPT and PC memory graphs and a network card. Below
the graphs: storage by category, and (folded away in Simple) the speed
reading source and the health checks.

The PC's CPU is one reading shared by every server, and shows Unknown until
two readings a second apart exist. Each health check shows the measured value
**and the threshold it was compared against**, so a warning is never
mysterious. Checks that cannot be measured, such as TPS with no tick-reporting
mod, say Unknown and explain why rather than showing a made-up number.

## Backups

**Back up now** and **Save the world now** at the top, then the backup list
with buttons to check, download, restore and delete each one, and the worlds
with their sizes and last backup. Each backup is labelled **Made by you**,
**Scheduled** or **Safety copy** (taken automatically before a restore or
other change). Restore shows a full list of what it is about to do before it
does any of it. See [backups.md](backups.md).

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

The list of schedules with what each does, when, the next time it runs and
how the last run went, with **Turn off**/**Turn on**, **Run now** and
**Delete** (which asks first). Below it, add one: pick what to do, then every
day (`23:00`), every week (`sun 04:00`) or every few hours (`6h`).

Three schedules are created on first run: a nightly backup (on), a weekly
restart (off), and a weekly log cleanup (on).

## Events

Everything the agent has recorded for this server, newest first: starts,
stops, crashes, backups, mod changes, threshold breaches, scheduled tasks.
Problems and warnings are marked. Technical mode adds the event type.

## Crashes

One row per crash with the likely cause and how sure it is (Technical adds
the exit code). **Details** opens the explanation and advice, then (folded
away in Simple) the matched log lines and the Minecraft, Fabric and Java
versions, who was online, and where the saved crash report and log live on
disk. It ends with a reminder that this is a best guess from log text, not a
diagnosis.

## Server settings

Each server's own settings, on its tab:

- **Name and color**.
- **When it crashes**: restart by itself, with crash-loop protection under
  "More crash options".
- **Memory**: the memory limit (`-Xmx`), with the Java options in an
  advanced section.
- **CPU cores**: tick the cores this server may use, or **Use every core**.
  It shows which cores other servers use, and the cores the running server
  really uses, read from its process.
- **Backups**: how many daily, weekly and monthly backups to keep, and the
  start and stop timeouts.
- **Remove from this list** takes the server off the dashboard after you
  confirm; its folder, world, mods and backups stay where they are.

Changes are written to `config.yaml` when you press Save. Only a safe subset
of settings can be changed here. Things that would change what the agent
executes, such as the server directory or the launch command, are rejected by
the API even if the request is crafted by hand.

## Adding a server

The **+** tab registers a folder that already holds a Minecraft server: its
name, the full folder path, and a color (the next unused one is already
picked). Nothing in the folder is changed and the server is not started; it
opens on its own Overview.

## Security

Next to the gear's settings. The agent, HTTPS (and, when it is on, the
certificate's expiry, whether it covers the dashboard's address and whether
the key matches), Tailscale and sign-in status, failed sign-ins, who is
signed in now with their addresses, and the audit log ("Who did what"). You
can get a new sign-in key for this session or sign everyone out at once.
