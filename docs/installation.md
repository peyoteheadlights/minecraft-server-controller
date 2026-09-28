> **Quickest way:** run `.\setup.ps1` from the project folder. It does every step below,
> keeps anything already configured, and `.\setup.ps1 --check` verifies the result.
> The manual steps are kept here for reference.

# Installation

Everything here happens on the PC that runs Minecraft.

## 1. Requirements

- Windows 10 or 11
- Python 3.11 or newer — install from python.org and **tick "Add Python to PATH"**
- Your existing Fabric server (this tool does not install Minecraft or Fabric)
- About 200 MB of free space for the agent, plus room for backups

Check Python is available:

```powershell
python --version
```

## 2. Put the project somewhere sensible

Do **not** put it inside the Minecraft server folder — keeping them separate
makes uninstalling clean. Something like:

```
C:\Main\minecraft-server-control\
```

## 3. Install the Python packages

```powershell
cd C:\Main\minecraft-server-control
pip install -r requirements.txt
```

If `pip` is not recognised, use `python -m pip install -r requirements.txt`.

## 4. Configure

```powershell
copy config\config.example.yaml config\config.yaml
notepad config\config.yaml
```

The only section you must get right is `server`:

```yaml
server:
  directory: 'C:\path\to\Minecraft Server'
  jar: fabric-server-launch.jar
  java: java
  jvm_args: ["-Xmx6G"]
  server_args: ["nogui"]
  port: 25565
```

Notes:

- Use single quotes around Windows paths so backslashes are kept literally.
- `java: java` uses whatever Java is on your PATH. If you have several, give a
  full path: `java: 'C:\Program Files\Java\jdk-21\bin\java.exe'`.
- The agent builds `java` + `jvm_args` + `-jar` + `jar` + `server_args`. It
  never runs a shell, so there is no `start.bat` involved.
- If you currently start the server with a batch file that does something
  unusual, put the exact argument list in `raw_command` instead:
  `raw_command: ['C:\path\java.exe', '-Xmx6G', '-jar', 'fabric-server-launch.jar', 'nogui']`

## 5. Create your credentials

```powershell
python -m installer.make_secrets
```

This writes `.env` in the project folder containing a password **hash**, never
your password. It also prints an API token — copy it somewhere safe, it is not
shown again.

If you ever forget your password, run `make_secrets` again after deleting
`.env`, then restart the agent.

## 6. Set up HTTPS

HTTPS is required: the agent refuses to serve plain HTTP on anything but
127.0.0.1.

```powershell
python -m installer.make_certs
```

It tries Tailscale first (publicly trusted, nothing to install on your
devices) and falls back to a local CA, printing exactly what to trust where.
Full detail in [https.md](https.md).

## 7. Preflight

```powershell
python -m agent.main --check
```

Expected output:

```
Minecraft server
  Minecraft directory:           OK       C:\path\to\Minecraft Server
  Server JAR:                    OK       fabric-server-launch.jar
  Mods directory:                OK       12 enabled, 0 disabled
Java
  Java executable:               OK       C:\Program Files\Java\jdk-21\bin\java.exe
  Java version:                  OK       21
Storage
  Database:                      OK       schema version 2
HTTPS
  Certificate:                   OK       ...\certs\agent.crt
  Certificate expiration:        OK       398 days
  Certificate hostname:          OK       minecraft-pc.tail1234.ts.net
  Private key:                   OK       matches certificate
Tailscale
  Tailscale:                     OK       Running
Authentication
  Dashboard password:            OK       pbkdf2_sha256 hash configured

READY - no blocking problems found.
```

Statuses mean exactly what they say. **FAIL** blocks startup. **WARN** needs
attention. **UNKNOWN** means the agent could not verify it and is not
pretending otherwise - it is never treated as a pass.

## 8. First run

```powershell
python -m agent.main
```

Leave the window open and go to **https://localhost:8765** (note the s). Sign in, press
**Start server**, and watch the Console page. When you see
`Done (12.345s)! For help, type "help"` the state pill turns green.

Press Ctrl+C in the PowerShell window to stop the agent. **Stopping the agent
does not stop Minecraft** — that is deliberate, so an agent restart never
disconnects your players. Stop Minecraft from the dashboard first if you want
it down.

## 9. Firewall and service

```powershell
# Administrator PowerShell
.\installer\firewall.ps1          # opens 8765 to Tailscale peers only
python -m installer.autostart enable
python -m installer.autostart run
```

## 10. Next steps

- [HTTPS and certificates](https.md)
- [Remote access over Tailscale](tailscale.md)
- [Windows Firewall rules](firewall.md)
- [Run it as a Windows Service](windows-service.md)
- [Set up Discord or email alerts](notifications.md)
