# Using the dashboard

Sign in with the username and password you created with
`python -m installer.make_secrets`. The session lasts 12 hours by default.

## Tabs, colors and layout

Each server has a tab across the top, like the dividers in a folder, with
**All servers** on the left and **+** (add a server) on the right. The whole
page under a tab takes that server's color: the header, the page itself and
its cards are all tinted with it, and its buttons are filled with it. The
server's own pages are listed down the left side of the page, under its
name, in three groups: **Live** (Overview, Players, Console, Performance),
**Manage** (Backups, Mods, Schedules, Server settings) and **History**
(Events, Crashes).

Each server has a badge: its initials on its color. It is on the server's
tab, with a dot on its corner for the server's state, before its name at the
top of the page, and on its card under **All servers**. The browser tab
shows the state too: its title names it (for example "Survival (Online) ·
Overview") and its icon, in the server's color, gets a green, amber or red
dot, so you can keep an eye on a server from another tab. Left/Right arrow keys move between tabs, Home and End
jump to the ends, and the dashboard remembers the last server you looked at.

Every server has one of twelve colors, or any color you pick, set in
**Server settings > Name and color**. A new server gets the next unused one.
All text, links and status colors are darkened or lightened against the
tinted page so they stay readable whatever the color, in every theme. High
contrast keeps the tint faint.

If another server crashes, its tab gets a red **!**, and a message names it
with a button to switch to it. **All servers** shows one card per server with
its state, players, uptime and port; a crashed server's card is outlined in
red.

On a phone, the tabs scroll sideways, and the page list becomes a row under
the server's name that scrolls sideways too, with thin lines between the
groups; nothing on a page is wider than
the screen.

## App settings (the gear)

The gear at the top right opens the settings that apply to the whole app,
next to **Security**:

- **Appearance**: Match my device (the default), Light, Dark, Graphite or
  High contrast. It applies at once and follows your account to other
  devices.
- **Detail level**: **Simple** (the default) uses short, everyday words
  ("Game speed", "CPU use") and folds away the extra options. **Technical** uses
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

Below that, four numbers: players, game speed (TPS), memory used against
its limit, and the PC's CPU use. Hover or tap one for a short summary of
the last hour. Then three cards: **Last backup** (with **Back up now**),
**Next task**, and **Players online**, and a **Details** list
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

A player who came in from Bedrock carries a **Bedrock** badge. That comes
from Floodgate's `.` prefix on the name the server printed, and the name is
always shown exactly as printed. With crossplay off, nobody is badged.

## Performance

Graphs of game speed (TPS), memory, CPU and players, over 1 hour, 6 hours,
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

**Back up now** and **Save world** at the top, then the backup list
with buttons to check, download, restore and delete each one, and the worlds
with their sizes and last backup. Each backup is labelled **Manual**,
**Scheduled** or **Safety copy** (taken automatically before a restore or
other change). Restore shows a full list of what it is about to do before it
does any of it. See [backups.md](backups.md).

**Last change** at the top shows the newest restore (or other safe change) on
this server with an **Undo change** button. Undo restores the safety copy
taken just before that change; it is a change of its own, with its own safety
copy, so it can be undone too. The toast after a restore has the same Undo
button.

While a restore runs, the server cannot be started from anywhere (the button,
a schedule, another device), and mod changes wait: a server runs one change
like this at a time.

## Mods, or Plugins

The add-on manager. The page calls itself what this server's type calls them:
**Mods** on Fabric, Quilt, Forge and NeoForge, **Plugins** on Paper and
Purpur. Vanilla takes neither, so it has no such page at all. See
[mods.md](mods.md) — it has the most detail and the most caveats.

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
  "More options".
- **Memory**: the memory limit (`-Xmx`), with the Java options in an
  advanced section.
- **CPU cores**: tick the cores this server may use, or **All cores**.
  It shows which cores other servers use, and the cores the running server
  really uses, read from its process.
- **Kind and version**: what this server is and which Minecraft version its
  own console reported — "Not seen yet" until it has started once, never
  guessed from a file name. Opening **Change the kind or version** fetches
  that type's version list from its own project. **Check first** says what
  would happen (older or newer, whether the installed Java can run it, which
  add-ons don't fit the new kind and would be moved aside, which declare
  nothing so can't be judged) before you commit. The change stops the server
  and takes a verified backup first, and **Go back a version** puts the
  previous software back in one step. The new version shows as pending until
  the server starts and its console confirms it.
- **Bedrock players**: let people on phones, tablets and Windows Bedrock join
  this Java server. It installs Geyser and Floodgate into the server's own
  add-on folder, so the server has to be stopped. The address Bedrock players
  type is built from this PC's real Tailscale address; if that can't be read
  the panel says so rather than showing one. The differences a Bedrock player
  will notice are listed before you turn anything on.
- **Backups**: how many daily, weekly and monthly backups to keep, and the
  start and stop timeouts.
- **Remove from list** takes the server off the dashboard after you
  confirm; its folder, world, mods and backups stay where they are.

Changes are written to `config.yaml` when you press Save. Only a safe subset
of settings can be changed here. Things that would change what the agent
executes, such as the server directory or the launch command, are rejected by
the API even if the request is crafted by hand.

## Adding a server

The **+** tab has two ways in.

**New server** makes one from scratch:

1. **Which Minecraft** — Java, or Bedrock. Bedrock servers come in a later
   update; the panel says so rather than offering something that isn't there,
   and points out that Bedrock players can already join a Java server.
2. **Which kind of server** — a table comparing Vanilla, Fabric, Quilt,
   Forge, NeoForge, Paper and Purpur: what each is best for, whether it takes
   mods or plugins, whether Modrinth can install to it, whether Bedrock
   players can join, and how fiddly it is to set up. Technical mode adds the
   loader, the add-on metadata file and where its versions come from. One row
   is marked **Recommended**, with a line saying why. Nothing is chosen for
   you. On a phone each row becomes a card. The table is generated from what
   each type says about itself in the code, so it cannot go stale.
3. **Which version** — the newest finished version is picked for you;
   unfinished ones (snapshots) are behind a switch, and the loader version is
   under Advanced.
4. **Name, folder, color and memory** — the folder has to be new or empty,
   the port is the next free one, and the memory default comes from this PC's
   real memory with the reason written next to it.
5. **Minecraft's rules** — a link to Mojang's EULA and a box you tick
   yourself. Nothing is created until you do, and `eula.txt` says `eula=false`
   until then. The agent never accepts them for you.

It downloads, checks the file against the checksum that project published,
sets it up and puts it on the list. It does **not** start it: you press Start,
and only then does its console say which version it really is.

**Server I already have** registers a folder that already holds a Minecraft
server: its name, the full folder path, which kind of server it is (Fabric
unless you pick another; the console warns once it starts if it says
otherwise), and a color (the next unused one is already picked). A Forge or
NeoForge folder needs the start file its installer wrote
(`libraries/.../win_args.txt`). Nothing in the folder is changed and the
server is not started; it opens on its own Overview.

With Bedrock players switched on, the Overview's Details also show the
address they type (this PC's Tailscale address and the Bedrock port), until
Phase 4's "How friends join" card takes it over.

## Security

Next to the gear's settings. The agent, HTTPS (and, when it is on, the
certificate's expiry, whether it covers the dashboard's address and whether
the key matches), Tailscale and sign-in status, failed sign-ins, who is
signed in now with their addresses, and the audit log ("Who did what"). You
can get a new sign-in key for this session or sign everyone out at once.
