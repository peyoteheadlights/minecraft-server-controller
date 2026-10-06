# Using the dashboard

Sign in with the username and password you created with
`python -m installer.make_secrets`. The session lasts 12 hours by default.

## Tabs, colors and layout

Each server has a tab across the top, like the dividers in a folder, with
**All servers** on the left and **+** (add a server) on the right. The whole
page under a tab takes that server's color: the header, the page itself and
its cards are all tinted with it, and its buttons are filled with it. The
server's own pages are listed down the left side of the page, under its
name, in three groups: **Live** (Overview, Players, Chat, Console, Performance),
**Manage** (Backups, Restore world, Mods, Game settings, Schedules, Server
settings) and **History** (Events, Crashes).

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
- **Alerts**: thresholds, Discord, email and **Phone**, and which events send
  one. Phone alerts need two things on: the channel itself, and this phone,
  which the browser asks about and which is answered once per phone. The card
  lists the phones signed up and when each last had an alert, and **Send a
  test** proves the whole path works.
- **Maintenance mode** and the **Windows startup** check.

Small **?** buttons sit next to the settings that are easy to misread
(auto-sleep, phone alerts, Restore world, memory, how many backups to keep).
Pressing one opens a sentence or two in place; where there is more to say it
links to the matching page in `docs/`. They work from the keyboard like any
other button.

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

**How friends join** gives the address and port to type into Minecraft,
each with a **Copy** button: the PC's address on the home network (read from
its network adapters; adapters of virtual machines show in Technical mode
only) and its Tailscale address and name. With Bedrock players on, it adds
the same addresses with the UDP port Bedrock players use. An address that can't be read is
said to be missing rather than filled in. Whether the server can be reached
from the internet is always shown as **not known**: the app doesn't test
it and doesn't open router ports.

**Getting started** appears on a new server until its four items are done:
the server is set up, a backup has run and checked out, somebody has joined,
and alerts are on. Each is ticked from something the app measured, never from
pressing the item — pressing it only takes you to the page where it is done.
**Hide** puts it away for that server, and once every item is done it does not
come back.

**What happened** is the recent activity in plain sentences, grouped by day
("Today", "Yesterday"): "Alex joined.", "The server came online.", "A backup
finished and was checked." The steps the app took on the way (requesting a
start, detecting the tick command) are left out in Simple mode; Technical mode
shows every event with its raw type and data. **See all** opens the Events
page, which is the same feed without a limit.

When a server was put to sleep because nobody was playing, the state says so,
and that starting it again is up to you.

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

## Chat

The in-game chat, read from the server's own console output, so every
message here was really printed by Minecraft: what players said, `/me`
actions, and what the server said. Nothing is reconstructed from what this
app sent — a message you send appears once the console prints it back.

The box at the bottom sends a message to everyone in the game as **Server**.
It becomes a `say` command and passes exactly the checks a console command
passes, so the chat box can no more reach Windows than the console can.
Letters, numbers and basic punctuation only, up to 220 characters; anything
else is refused with the reason. The box is disabled while the server is
off.

## Players

Who is online now with how long they have been playing (Technical adds their
UUID), and everyone ever seen with first seen, last seen, times joined and
total time played. IP addresses are deliberately not recorded.

A player who came in from Bedrock carries a **Bedrock** badge. That comes
from Floodgate's `.` prefix on the name the server printed, and the name is
always shown exactly as printed. With crossplay off, nobody is badged.

While the server is running, each player has buttons: **Add to whitelist**
or **Remove from whitelist**, **Make operator** or **Remove operator**,
**Kick** (online players) and **Ban** or **Unban**. **Add a player by name**
does the same for someone who hasn't joined yet. Kick and ban ask first and
take an optional reason. Each button sends Minecraft's own command and the
line at the top says **Sent** until the server's console confirms it, then
**Done** (or "Nothing changed", "Failed", or "No answer" if the console said
nothing). The **Whitelist**, **Operators** and **Banned players** cards read
Minecraft's own files, so they show what the server has, not what was sent.

## Game settings

The main settings in `server.properties`, as a form: game mode, difficulty,
PvP, the server description (MOTD), player limit, whitelist on or off, world
seed, view distance and port. A setting the file doesn't contain says so and
names Minecraft's default. The seed is read-only once the world exists. The
port is checked against the other servers and this PC.

**Save** rewrites only the settings you changed: comments, the order of the
file and every setting this page doesn't show are kept exactly. A copy of
the old file is kept as a safety backup (undo it from Backups). A running
server keeps the old settings until it restarts; the page says so and offers
**Restart now**. "Waiting for a restart" is measured from the file's time
and the moment the console said the server was ready, because Minecraft
rewrites `server.properties` itself early in every start (and in doing so
drops comments; this page never does). The console commands `whitelist on`
and `whitelist off` also rewrite the file from what the running server
loaded, so typed while changes are waiting they overwrite them: restart
first. Technical mode adds the whole
file as text to edit; the known settings are still checked when you save it.

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

## Restore world

A timeline of the points this server's world can be put back to, newest
first, each saying when it was and what going back would lose ("3 hours ago ·
about 2 hours of play lost"). Where no play was recorded it says so rather
than claiming nobody played.

Going back always takes a fresh backup of the world as it is now first, so
the undo can itself be undone from Backups. The server has to be off; while
it is running the page says so with a button to Overview. A backup that was
not checked is listed but not offered. See `docs/backups.md`.

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

Everything the agent has recorded for this server, newest first and grouped
by day, written as plain sentences: starts, stops, crashes, backups, mod
changes, threshold breaches, scheduled tasks. Problems and warnings are
marked with a colored dot. Simple mode leaves out the app's own intermediate
steps; Technical mode shows every event with its type and the data it
carried. An event type with no sentence of its own falls back to the message
the agent wrote, so nothing is ever hidden because it is new.

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
- **Sleep when empty**: stop this server once nobody has played for a set
  number of minutes (off by default, 30 minutes when you turn it on). A
  minute before the stop, everyone in the game is warned in chat. It is a
  planned stop, not a crash, so no crash alert goes out and no automatic
  restart follows — **the server does not start again by itself**, which the
  setting says plainly. While the player count is Unknown, nothing is
  stopped: "nobody is online" would be a guess. The card shows the measured
  count and how long is left.
- **Backups**: how many daily, weekly and monthly backups to keep, and the
  start and stop timeouts.
- **Duplicate this server** makes a new server with the same software, mods,
  config files and game settings. Choose a name, an empty or new folder, and
  whether to **copy the world** or **start a fresh world** (which also clears
  the seed, so Minecraft picks a new one). The copy gets the next free port
  and an unused color, and isn't started. A running server is told to save
  and pause saving while it is copied. Logs, crash reports and this app's
  own files stay with the original.
- **Remove from list** takes the server off the dashboard after you
  confirm; its folder, world, mods and backups stay where they are.

Changes are written to `config.yaml` when you press Save. Only a safe subset
of settings can be changed here. Things that would change what the agent
executes, such as the server directory or the launch command, are rejected by
the API even if the request is crafted by hand.

## Adding a server

The **+** tab has three ways in: **New server**, **From a modpack** and
**Server I already have**.

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

**From a modpack** makes a server from a Modrinth modpack (`.mrpack`).
Choosing the file only reads it: the panel shows the pack's Minecraft
version, loader and loader version, and every file in it, with what will be
skipped (files only the game itself uses) or refused and why. Then a name,
an empty or new folder and Minecraft's rules, as for a new server. See
[mods.md](mods.md#modpacks). The Mods page has the same panel to import a
pack into the server that is open.

The address Bedrock players type is on the Overview's **How friends join**
card.

## Install it on a phone

The dashboard can be added to a phone's home screen and opened like an app,
full screen with no browser bars.

- **iPhone or iPad:** open the dashboard in Safari, then **Share → Add to
  Home Screen**. This is also what Safari needs before phone alerts can be
  turned on.
- **Android:** Chrome offers **Install app** or **Add to Home screen** from
  its menu.
- **Windows or Mac:** Chrome and Edge show an install button in the address
  bar.

A small service worker makes that possible and delivers phone alerts. It
keeps a copy of the app's own files (the page, its stylesheet, its scripts
and its icons) so the dashboard opens instantly, and **never** keeps a copy
of anything from `/api`: no world data, no player name and no sign-in token
is written to the phone. It asks the network first every time, so what you
see is never a stale copy of itself.

## Security

Next to the gear's settings. The agent, HTTPS (and, when it is on, the
certificate's expiry, whether it covers the dashboard's address and whether
the key matches), Tailscale and sign-in status, failed sign-ins, who is
signed in now with their addresses, and the audit log ("Who did what"). You
can get a new sign-in key for this session or sign everyone out at once.
