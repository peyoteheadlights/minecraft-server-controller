# Troubleshooting

## The dashboard will not load

| Check | How |
| --- | --- |
| Is the agent running? | `python -m installer.autostart status`, or look for the PowerShell window |
| Right address? | `network.host` in `config.yaml` must match what you type |
| Firewall? | Windows Firewall may prompt the first time; allow it on private networks |
| Tailscale up on both devices? | `tailscale status` on the PC, and the phone app |

`curl http://127.0.0.1:8765/api/health` on the PC itself separates "agent is
down" from "cannot reach the agent".

## "No password is configured"

You have not run `python -m installer.make_secrets`, or the agent is not
reading your `.env`. The file must be in the project folder (next to
`agent/`), and the agent must be restarted after it is created.

## The server will not start

Run `python -m agent.main --check`. It prints the exact command it will run and
any blocking problems. Common ones:

- **Server jar not found** — `jar` or `directory` is wrong in `config.yaml`
- **Java not found** — set `java` to the full path of `java.exe`
- **FAILED TO BIND TO PORT** — a previous `java.exe` is still running. Check
  Task Manager.
- **EULA** — set `eula=true` in `eula.txt` in the server folder

## It starts then immediately crashes

Open **Crash history** and read the evidence. The most common causes:

| Category | Usual fix |
| --- | --- |
| `OutOfMemoryError` | Raise `-Xmx`, or reduce view distance and heavy mods |
| `JavaVersionIncompatible` | 1.20.5+ needs Java 21; 1.17–1.20.4 needs Java 17 |
| `ModDependencyError` | Install the named dependency at the version shown |
| `MixinError` | A mod does not match this Minecraft version — update or disable it |
| `PortInUse` | A stray `java.exe` is holding 25565 |

Bisect with the mod manager: disable half the mods, start, repeat.

## Auto-restart stopped working

You hit the crash-loop guard: N crashes inside the window disables automatic
restarts on purpose, so a bad mod cannot restart-loop all night. The dashboard
shows a banner with a **Clear and allow restarts** button. Fix the cause first.

## TPS shows "unknown"

Nothing is answering the tick-rate command. Vanilla Fabric has none. Options:

- Minecraft 1.20.3+: set `monitor.tps_command: tick query`
- Install Carpet (`tps`) or spark (`spark tps`) and set it accordingly

The dashboard reports unknown rather than guessing a number.

## Mod buttons are greyed out

The server must be stopped to change mods. Windows locks jars held by a running
JVM, and Fabric reads the folder once at startup.

## A mod will not install

- *"already in the mods folder"* — use Update, or confirm replacement
- *"supports 1.20.1, not 1.21.1"* — no build for your version yet
- *"SHA-512 checksum did not match"* — the download was corrupted and discarded;
  try again
- *"targets forge, not Fabric"* — wrong loader

## I removed the wrong mod

It is in `mcsc-data/mod-trash/`, and an archived copy is in
`mcsc-data/mod-backups/<mod_id>/`. Nothing was deleted. Use **History** on the
mod, or copy the jar back by hand.

## Restore failed halfway

The restore puts the moved-aside folders back automatically and reports the
error. Your pre-restore safety backup is in the backup list, named `safety-…`.
Nothing is deleted during a restore — the old folders are still on disk as
`world.replaced-<timestamp>`.

## Backups are huge or slow

Set `backups.compression: store` for speed at the cost of size, or trim
`backups.include` — mods and config are small, worlds are not. Retention
settings control how many are kept.

## No Discord or email alerts

Settings → **Send test**. Then check the notification history. Typical causes:
a missing `MCSC_DISCORD_WEBHOOK`, a Gmail account password used instead of an
App Password, the event's checkbox turned off, or throttling because the same
alert fired minutes ago.

## Where the logs are

```
mcsc-data\logs\agent.log          everything the agent did
mcsc-data\logs\agent-errors.log   warnings and errors only
mcsc-data\crashes\<timestamp>\    per-crash evidence
<server folder>\logs\latest.log   Minecraft's own log
```
