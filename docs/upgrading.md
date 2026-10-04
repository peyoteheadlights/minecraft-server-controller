# Upgrading and uninstalling

## Upgrading

1. Stop the agent: Ctrl+C in its window, or, if it starts with Windows,
   `schtasks /End /TN "Minecraft Server Control"`
2. Back up `config/config.yaml` and `.env`
3. Replace the project files with the new version
4. `pip install -r requirements.txt`
5. Put `config.yaml` and `.env` back
6. `python -m agent.main --check`
7. Start the agent

Database migrations run automatically at startup and are forward-only. The
schema version is recorded, and only newer migrations are applied.

New settings appear with their defaults; your existing `config.yaml` does not
need rewriting. Compare it against `config/config.example.yaml` to see what is
new.

## Uninstalling

```powershell
# 1. Stop Minecraft from the dashboard if it is running
# 2. Remove the startup task (Administrator PowerShell if it runs at boot)
python -m installer.autostart disable
```

Then delete what you want gone:

| Path | Contents | Safe to delete? |
| --- | --- | --- |
| The project folder | Agent code, `config.yaml`, `.env` | Yes |
| `<server>\mcsc-data\` | Database, backups, mod archives, crash evidence, logs | Yes, but **your backups are in here** |
| `<server>\mcsc-data\mod-trash\` | Mods you removed via the dashboard | Check first |
| `<server>\world*`, `mods\`, jars | Your actual server | **No** — this is your server |

Nothing the agent installs lives outside the project folder and `mcsc-data`. It
adds no registry keys beyond the service registration, which `uninstall`
removes, and it writes nothing to `AppData`.

Your Minecraft server is exactly as it was: same jar, same worlds, same mods
folder. Run your original `java -Xmx6G -jar fabric-server-launch.jar nogui`
command and it starts as it always did.
