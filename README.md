# Minecraft Server Controller

A self-hosted control panel for a Fabric Minecraft server on Windows. A small
agent runs on the server PC, supervises the Minecraft process, and serves a
dashboard you open from your computer or phone over a private
[Tailscale](https://tailscale.com) network, using HTTPS.

## Features

- **Start, stop and restart** the server, with a graceful `stop` and a forced
  stop only after a timeout
- **Live status**: running, starting, stopping, crashed, uptime, players,
  memory and CPU
- **TPS and MSPT** when a tick-rate source is available (Carpet, spark, or
  `tick query` on 1.20.3+); shown as *Unknown* otherwise, never guessed
- **Server console** streamed live, with filter, copy, download and command
  input. Commands go to Minecraft only, and risky ones ask first
- **Crash detection** that tells a crash from a normal stop, saves the
  evidence, and names a likely cause with its confidence
- **Automatic restart** after a crash, with crash-loop protection
- **Player tracking**: who is online, sessions and total playtime
- **Backups** of worlds, config and mods, verified before they are trusted,
  with safe restore and retention
- **Mod manager**: install from Modrinth with checksum verification,
  enable, disable, update, roll back, and dependency checks
- **Scheduled tasks**: backups, restarts, log cleanup, maintenance windows
- **Alerts** to Discord and email
- **Starts with Windows** through a scheduled task, without anyone logging in
- **Security**: HTTPS, hashed passwords, session tokens, rate limiting, audit
  log, Tailscale-only access
- Light and dark appearance, following your system by default

## Screenshots

![Overview in light mode](docs/screenshots/overview-light.png)

| Overview, dark | Console, dark |
| --- | --- |
| ![Overview in dark mode](docs/screenshots/overview-dark.png) | ![Console in dark mode](docs/screenshots/console-dark.png) |

## Requirements

- Windows 10 or 11 on the server PC
- Python 3.11 or newer, from [python.org](https://www.python.org)
- A working Fabric server and the Java version it needs
- [Tailscale](https://tailscale.com) on the server PC and on every device you
  want to connect from

## Installation

On the server PC, from the project folder:

```powershell
.\setup.ps1
```

Setup finds Python (3.11+), creates a virtual environment in `.venv`,
installs the dependencies, and then configures whatever is missing: your
server folder, a dashboard password, the HTTPS certificate, the firewall rule
and the Windows startup task. It works from any folder, and running it again
is safe - anything already configured is checked and kept.

Your password is stored only as a hash in `.env`; it is never shown, logged or
saved in plain text. The firewall and startup steps need Administrator rights,
and setup offers to open an elevated window for them.

If Windows says the script "is not digitally signed", use `setup.cmd` instead,
or run `powershell -ExecutionPolicy Bypass -File .\setup.ps1`. Both bypass the
policy for that one run only; your system setting is not changed.

### Health check

```powershell
.\setup.ps1 --check
```

Read-only: it verifies every component, changes nothing, and says what to do
about anything that fails. Options: `--logon` (start at login instead of at
boot), `--skip-firewall`, `--skip-startup`, `--non-interactive`.

Step-by-step detail: [docs/installation.md](docs/installation.md).

## Configuration

Settings live in `config/config.yaml`. Secrets live only in `.env`, which is
created by `make_secrets` and is never committed.

| Setting | What to set |
| --- | --- |
| `server.directory` | **Required.** The folder that contains your server jar. There is no default. |
| `server.jar` | Your server jar, e.g. `fabric-server-launch.jar` |
| `server.java` | `java`, or the full path to `java.exe` |
| `server.jvm_args` | Memory and JVM options, e.g. `["-Xmx6G"]` |
| `network.host` | This PC's Tailscale address, from `tailscale ip -4` |
| `tls.hostname` | The name you type in the browser, e.g. `server-pc.your-tailnet.ts.net` |
| `monitor.tps_command` | `auto` (default) detects it; or force `tick query`, `tps`, `spark tps`; `off` disables |

Every option is described in [docs/configuration.md](docs/configuration.md).
Discord and email alerts: [docs/notifications.md](docs/notifications.md).

## How it handles…

### Crashes and automatic restart

When Minecraft exits without being asked to, the agent records the crash,
names a likely cause from the log, and - if automatic restart is on - starts
a countdown (`monitor.restart_delay`, 10 seconds by default). The dashboard
shows **Restarting in 7s** with two choices:

- **Restart Now** skips the rest of the countdown
- **Cancel** stops it; the server stays stopped until you start it

During the countdown the normal Start button is not offered, and the agent
itself refuses a second start, so two server processes can never be launched.
After repeated crashes (`monitor.max_crashes` within
`monitor.crash_window_minutes`) automatic restart pauses until you allow it.

### TPS

With `monitor.tps_command: auto`, the agent tries `tick query` (vanilla
1.20.3+), `tps` (Carpet) and `spark tps` once when the server finishes
starting, uses the first that answers with real figures, and remembers it for
next time. It never probes on a timer. If none answers, TPS is shown as
unavailable with the reason - never estimated. On vanilla, TPS is calculated
from the measured tick time, not from the configured target rate. To force a
command, use **Performance -> TPS monitoring -> Change Command**, or set
`monitor.tps_command` in `config.yaml`.

### Mod dependencies

The Mods page lists every missing, disabled, or wrong-version dependency by
name, with the version required ("Any version", "1.2 or newer") and which mod
needs it. **Install Missing Dependencies** looks them up on Modrinth, picks a
version that satisfies the range, follows their own dependencies (A needs B
needs C), and shows the full list before downloading anything. Each download
is checksum-verified, nothing already installed is replaced, and a mod the
server is running with is never touched - stop the server first.

## Running

```powershell
python -m agent.main
```

Open `https://<tls.hostname>:8765` and sign in. Once `autostart enable` has
run, the agent starts by itself whenever Windows starts; check it with
`python -m installer.autostart test`.

## Project structure

```
agent/              the server agent
  api/              REST API and live WebSocket
  minecraft/        process control, console parsing, crash analysis
  mods/  backups/  monitoring/  notifications/  scheduler/  security/
  web/              the dashboard (plain HTML, CSS and JavaScript)
  main.py           entry point
installer/          secrets, certificates, firewall, Windows startup
config/             config.example.yaml
docs/               installation, HTTPS, Tailscale, mods, backups, API and more
scripts/            end-to-end and browser checks
tests/              automated tests, with a fake Minecraft server
```

## Tests

```powershell
pip install -r requirements-dev.txt
python -m pytest -q
```

See [docs/testing.md](docs/testing.md) for the browser and end-to-end checks.

### Windows CI

`.github/workflows/windows-startup-test.yml` runs on every push, on
GitHub's `windows-latest` runners:

- **Startup task:** registers a real scheduled task under a unique name,
  reads it back from Windows and checks its settings, launches it and
  confirms the agent started from the right folder, then removes it and
  confirms it is gone. The task is always deleted, even if a step fails.
- **Setup script:** runs `setup.ps1` on Windows PowerShell 5.1 - from another
  folder, twice (to prove repeat runs keep existing settings), with Python
  missing, with a dependency removed, through `setup.cmd`, and `--check` -
  and checks the password never appears in output or files.
- **Unit tests** on Linux.

## License

Released under the [MIT License](LICENSE). Copyright (c) 2026 Mark Ramy.
