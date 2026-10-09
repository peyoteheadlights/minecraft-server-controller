# Installation

Everything here happens on the PC that runs Minecraft.

## The easy way: the setup file

1. Download `MinecraftServerController-Setup-<version>.exe` from the
   [latest release](https://github.com/peyoteheadlights/minecraft-server-controller/releases/latest).
2. Run it. Windows asks for permission to make changes: say Yes.
3. Answer a few short screens: where your server is (or "I don't have one
   yet"), a password, and Java if your PC needs it. Everything else has a
   good default; the install folder is under **Advanced**.
4. When it's done, open the dashboard from the last screen or the Start
   menu, and scan **Open on your phone** with your phone.

It installs to `C:\Program Files\Minecraft Server Controller`; your settings,
database, backups and logs live in `C:\ProgramData\Minecraft Server Controller`,
so updating or removing the program never touches them. It finds a copy
made with `setup.ps1` by itself and moves it over (see
[upgrading](upgrading.md)).

Afterwards, **"Minecraft Server Controller setup"** in the Start menu
repairs, updates or removes the app, and can install Java for your servers.
The app tells you when a new version is out (gear, top right) and can
install it after you confirm.

For automated installs: `setup.exe --quiet --password-env NAME` reads the
password from the environment variable `NAME` (never from the command
line), plus `--server-folder <folder>` (repeatable), `--java <java.exe>`,
`--no-startup`, `--no-firewall` and `--result-file <file.json>`.
`setup.exe --uninstall --quiet [--remove-data]` removes it.

### "Windows protected your PC" / "Unknown publisher"

The setup file isn't **code-signed** yet, so Windows SmartScreen doesn't know
who made it and warns before it runs, and some antivirus programs may be
cautious about it. If you downloaded it from this repo's release page,
select **More info**, then **Run anyway**. To check the file is the one the
release built, compare `Get-FileHash .\MinecraftServerController-Setup-<version>.exe`
with the `.sha256` file next to it, or run
`gh attestation verify <file> --repo peyoteheadlights/minecraft-server-controller`.

Updates the app installs by itself don't depend on this: they are checked
against a signature made with the app's own key before anything runs
([security](security.md#updating-the-app-itself)).

### Code signing: the way to remove the warning (not set up yet)

Signing the setup file with an Authenticode certificate makes Windows show a
named publisher. Nothing has been bought or set up; this is the path when
you want it. Prices were checked in October 2026.

| Option | Cost | Who can get it | Notes |
|---|---|---|---|
| **Azure Artifact Signing** (was "Trusted Signing") | $9.99 a month (Basic, 5,000 signatures) | Organizations in the US, Canada, EU and UK; **individuals only in the US and Canada** | Quickest: no hardware, signs from GitHub Actions with Microsoft's own action. Needs an Azure account and an identity check. |
| **OV code-signing certificate** (Sectigo, Comodo, DigiCert…) | About $219 to $400 a year | Anyone, after the certificate authority checks your identity | Since June 2023 the key must live on a hardware token or a cloud HSM, so signing from GitHub Actions needs the CA's cloud signing service (often extra). |
| **SignPath Foundation** | Free for qualifying open-source projects | Open-source projects they accept | Worth checking first; it signs in their name for your project. |

Either way, SmartScreen builds reputation per certificate, so the first
signed releases may still warn a little until enough people have run them.
Steps once one is chosen:

1. Get the certificate or Azure account (identity checks take days).
2. Add the signing step to `.github/workflows/release.yml`, after "Build the
   setup file" and before "Sign the update file" (the update file records
   the signed file's checksum). Sign both `.exe` files inside the payload too
   (`MinecraftServerController.exe`, `mcsc.exe`) by signing in
   `scripts/build_installer.py` before the payload is zipped.
3. Store the credentials as GitHub secrets, never in the repo.
4. Remove the "Unknown publisher" paragraph from the release notes
   (`scripts/release_check.py`) and from this page.

## From the project folder (setup.ps1, for developers)

> **Quickest way:** run `.\setup.ps1` from the project folder. It does every step below,
> keeps anything already configured, and `.\setup.ps1 --check` verifies the result.
> The manual steps are kept here for reference.

### 1. Requirements

- Windows 10 or 11
- Python 3.11 or newer — install from python.org and **tick "Add Python to PATH"**
- Your existing Fabric server (this tool does not install Minecraft or Fabric)
- About 200 MB of free space for the agent, plus room for backups

Check Python is available:

```powershell
python --version
```

### 2. Put the project somewhere sensible

Do **not** put it inside the Minecraft server folder — keeping them separate
makes uninstalling clean. Something like:

```
C:\Main\minecraft-server-control\
```

### 3. Install the Python packages

```powershell
cd C:\Main\minecraft-server-control
pip install -r requirements.lock
```

If `pip` is not recognised, use `python -m pip install -r requirements.lock`.
`requirements.lock` pins the exact versions the automated tests use;
`setup.ps1` installs from it too.

### 4. Configure

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

### 5. Create your credentials

```powershell
python -m installer.make_secrets
```

This writes `.env` in the project folder containing a password **hash**, never
your password. It also prints an API token — copy it somewhere safe, it is not
shown again.

If you ever forget your password, run `make_secrets` again after deleting
`.env`, then restart the agent.

#### Phone alert keys

```powershell
python -m installer.make_push_keys
```

Makes the key pair phone alerts are signed with and adds it to `.env`, with an
optional email address the push services can contact you at. `setup.ps1` does
this for you. Keys that already work are kept, because replacing them signs
every phone out.

### 6. Set up HTTPS

HTTPS is required: the agent refuses to serve plain HTTP on anything but
127.0.0.1.

```powershell
python -m installer.make_certs
```

It tries Tailscale first (publicly trusted, nothing to install on your
devices) and falls back to a local CA, printing exactly what to trust where.
Full detail in [https.md](https.md).

### 7. Preflight

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

### 8. First run

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

### 9. Firewall and service

```powershell
# Administrator PowerShell
.\installer\firewall.ps1          # opens 8765 to Tailscale peers only
python -m installer.autostart enable
python -m installer.autostart run
```

### 10. Next steps

- [HTTPS and certificates](https.md)
- [Remote access over Tailscale](tailscale.md)
- [Windows Firewall rules](firewall.md)
- [Set up Discord or email alerts](notifications.md)
