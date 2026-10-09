# For developers

The README is written for people running the app. This page has the
technical side: the settings file, how the trickier parts behave, the code
layout, and the tests. More detail:

- [architecture.md](architecture.md): how the agent is put together
- [api.md](api.md): every REST route and the live WebSocket
- [configuration.md](configuration.md): every setting in `config.yaml`
- [security.md](security.md): the threat model, roles and what is checked where
- [testing.md](testing.md): browser and end-to-end checks, lock files
- [translating.md](translating.md): adding a language to the dashboard

## Configuration

Settings live in `config/config.yaml`. Secrets live only in `.env`, created
by `make_secrets` and never committed.

| Setting | What to set |
| --- | --- |
| `server.directory` | **Required.** The folder that contains your server jar. There is no default. Several servers go in a `servers:` list instead ([how](configuration.md#server-or-servers)). |
| `server.type` | `vanilla`, `fabric`, `quilt`, `forge`, `neoforge`, `paper` or `purpur`. Left out, it is read as `fabric`, as before |
| `server.jar` | Your server jar, e.g. `fabric-server-launch.jar`. Forge and NeoForge use `server.args_file` instead, written by their installer |
| `server.java` | `java`, or the full path to `java.exe` |
| `server.jvm_args` | Memory and JVM options, e.g. `["-Xmx6G"]`. The Game settings memory slider changes only `-Xmx` |
| `network.host` | This PC's Tailscale address, from `tailscale ip -4` |
| `tls.hostname` | The name you type in the browser, e.g. `server-pc.your-tailnet.ts.net` |
| `backups.offsite_directory` | A folder on another drive or a cloud folder for a second copy of each backup. Empty is off |
| `power.keep_awake` | `true` (default) keeps Windows awake while a server runs |
| `monitor.tps_command` | `auto` (default) detects it; or force `tick query`, `tps`, `spark tps`; `off` disables |

The agent keeps its database, backups and certificates in
`C:\ProgramData\Minecraft Server Controller` (an older install's
`<server>\mcsc-data` is copied there once, and the original left in place:
[details](configuration.md#the-data-folder-pathsdata_dir)).

Every option is described in [docs/configuration.md](configuration.md).
Discord and email alerts: [docs/notifications.md](notifications.md).

## How it handles…

### Crashes and automatic restart

When Minecraft exits without being asked to, the agent records the crash,
names a likely cause from the log, and starts a countdown if automatic
restart is on (`monitor.restart_delay`, 10 seconds by default). The
dashboard shows **Restarting in 7s** with two choices: **Restart Now**
skips the countdown, **Cancel** stops it and the server stays down.

During the countdown the Start button is hidden, and the agent refuses a
second start, so two server processes can't run at once. After repeated
crashes (`monitor.max_crashes` within `monitor.crash_window_minutes`)
automatic restart pauses until you allow it again.

### TPS

With `monitor.tps_command: auto`, the agent tries `tick query` (vanilla
1.20.3+), `tps` (Carpet) and `spark tps` once when the server finishes
starting, uses the first that answers with real figures, and remembers it
for next time. It never polls on a timer. If none answers, TPS shows as
unavailable with the reason — never estimated. On vanilla, TPS is
calculated from the measured tick time, not the configured target rate. To
force a command, use **Performance → TPS monitoring → Change Command**, or
set `monitor.tps_command` in `config.yaml`.

### Mod dependencies

The Mods page lists every missing, disabled, or wrong-version dependency by
name, with the version required ("Any version," "1.2 or newer") and which
mod needs it. **Install Missing Dependencies** looks them up on Modrinth,
picks a version that satisfies the range, follows their own dependencies (A
needs B needs C), and shows the full list before downloading anything. Each
download is checksum-verified, nothing already installed is replaced, and a
mod the server is running with isn't touched — stop the server first.

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
  servertypes/      what each kind of server is, its versions and installs
  mods/  backups/  monitoring/  notifications/  scheduler/  security/
  downloads.py      the one safe downloader
  crossplay.py      Geyser and Floodgate for Bedrock players
  modpack.py        Modrinth modpack import
  duplicate.py      copying a server
  worldimport.py    bringing a world in, and the world as a .zip
  transfer.py       Export everything, and importing it on a new PC
  helpbundle.py     the Get help file
  keepawake.py      keeping Windows awake while a server runs
  memory.py         the memory slider's limits against the PC's RAM
  filebrowse.py     the folder picker (folder names only)
  web/              the dashboard (plain HTML, CSS and JavaScript)
  main.py           entry point
installer/          secrets, certificates, firewall, Windows startup,
                    reset_password.py (on the PC only), import_from_pc.py
config/             config.example.yaml
docs/               installation, HTTPS, Tailscale, mods, backups, API and more
scripts/            end-to-end and browser checks
tests/              automated tests, with a fake Minecraft server
```

## Tests

```powershell
pip install -r requirements-dev.lock
python -m pytest -q
python -m ruff check . ; python -m ruff format --check . ; python -m mypy
```

See [docs/testing.md](testing.md) for the browser and end-to-end checks,
the lock files and pre-commit.

### CI

`.github/workflows/ci.yml` runs on every push and pull request:

- **Lint and type check**: `ruff check`, `ruff format --check` and `mypy`,
  with the settings in `pyproject.toml`.
- **Unit tests** on both Linux and Windows.
- **Dashboard in a real browser**: `scripts/ui_check.py --quick` signs in and
  visits every page in headless Chromium in both Simple and Technical mode,
  and fails on any JavaScript or console error, failed request, sideways
  scrolling, code text such as `undefined` on the page, or text without
  enough contrast. The screenshots are kept as a build artifact.

### Windows CI

`.github/workflows/windows-startup-test.yml` runs on every push, on
GitHub's `windows-latest` runners:

- **Startup task**: registers a real scheduled task under a unique name,
  reads it back from Windows and checks its settings, launches it and
  confirms the agent started from the right folder, then removes it and
  confirms it's gone. The task is always deleted, even if a step fails.
- **Setup script**: runs `setup.ps1` on Windows PowerShell 5.1 — from
  another folder, twice (to prove repeat runs keep existing settings), with
  Python missing, with a dependency removed, through `setup.cmd`, and
  `--check` — and checks the password never appears in output or files.
