# Starting automatically with Windows

The agent starts with Windows through a **scheduled task**. It runs at boot,
before anyone logs in, as your own Windows account, with no console window.

## Enable

Open PowerShell **as Administrator** (right-click -> Run as administrator):

```powershell
cd C:\path\to\minecraft-server-control
python -m installer.autostart enable
```

That:

1. removes the old `MinecraftServerControl` Windows Service if it exists (it
   could never start - see "What was wrong" below - and would fight the task
   for the port)
2. replaces a bare `java` in `config.yaml` with the full path it resolves to,
   so a different PATH at boot cannot break Minecraft
3. registers the task, then **reads it back from Windows** and checks every
   field matches this installation
4. prints the Test Windows Startup report

Start it now without rebooting:

```powershell
python -m installer.autostart run
```

## Disable

```powershell
python -m installer.autostart disable
```

## Prefer starting at login instead of boot?

```powershell
python -m installer.autostart enable --logon
```

No administrator rights needed, but it only starts once you log in.

## Test it

```powershell
python -m installer.autostart test
```

or **Settings -> Windows startup -> Test Windows Startup** in the dashboard, or
the "Windows startup" section of `python -m agent.main --check`.

It reports: whether the task exists, the mechanism, the registered executable
and working directory, whether they point at *this* installation, Windows' own
last-run time and result, the old service if still present, duplicate startup
entries (Run keys, Startup folder), and the agent's own record of its last
startup - including whether the controller finished initialising.

## What the task does

| Setting | Value | Why |
| --- | --- | --- |
| Program | `<your Python>\pythonw.exe` | absolute path; `pythonw` has no console window |
| Arguments | `-m agent.main --launched-by task` | the same command you run manually |
| Start in | the project folder | `-m agent.main` needs it; recorded as an absolute path |
| Runs as | your account, "S4U" | boots without login, no stored password, same Python and files as a manual run |
| Privileges | least privilege | the agent does not run as Administrator |
| Triggers | at boot (+30 s), and every 5 minutes | the repeat does nothing while running and restarts it if it stopped |
| If already running | do not start another | the repeat can never create a duplicate |
| Time limit | none | Windows' default kills tasks after 72 hours |
| On battery | keep running | |

## The startup log

Every launch writes timestamped events to `logs\startup.log` in the project
folder - before configuration is even loaded, so a broken `config.yaml` is
still recorded. A healthy boot looks like:

```
process_started            launched_by=task, cwd=C:\path\to\minecraft-server-control
config_loaded              host=100.101.102.103, port=8765, tls=True
tls_ready
bind_address_waiting       host=100.101.102.103, error=[WinError 10049] ...
bind_address_available     attempts=3
server_binding
controller_initializing
controller_initialized     state=OFFLINE, java=openjdk version "21..."
```

`bind_address_waiting` at boot is normal: Tailscale takes a few seconds to
assign its address, and the agent now waits up to
`network.bind_wait_seconds` (300) instead of exiting.

Anything printed goes to `logs\console.log`.

## The old Windows Service

Earlier versions also offered a pywin32 Windows Service. It has been removed;
the scheduled task is the only supported way to start with Windows. If an old
`MinecraftServerControl` service is still registered, `autostart enable`
removes it once, because it would fight the task for the same port, and
`autostart test` reports it if it is still there.

## Permissions

| Action | Needs Administrator |
| --- | --- |
| `autostart enable` (boot mode) | yes - a task that runs without login needs it |
| `autostart enable --logon` | no |
| `autostart disable` | yes, if it was registered in boot mode |
| `autostart test`, `status` | no |
| Running the agent itself | **no** - it runs with least privilege |

S4U requires your account to have "Log on as a batch job", which
Administrators have by default. If `enable` says the right is missing, use
`--logon` or ask for the right to be granted.
