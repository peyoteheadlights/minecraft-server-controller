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

### Upgrading to multi-server (Phase 1)

- Your `server:` block keeps working as it is. It is your first server.
- The old API paths (`/api/status`, `/api/backups`, …) still work for one more
  release and act on the first server. They answer with a `Deprecation`
  header; the new paths are `/api/servers/<id>/…`.
- **The data folder moves**, once, unless `paths.data_dir` is set. On the first
  start, `<server directory>\mcsc-data` is copied to
  `C:\ProgramData\Minecraft Server Controller`, checked, and used from then on.
  The old folder is left exactly as it was. Before upgrading you can see the
  plan with `python -m agent.datafolder`; after the first start,
  `python -m agent.main --check` reports it under Storage. Details:
  [configuration.md](configuration.md#the-data-folder-pathsdata_dir).
- Once you have checked everything works from the new folder, you may delete
  the old `mcsc-data` folder yourself. The agent never does.
- When the dashboard saves `config.yaml` (Settings, adding or removing a
  server), it writes the whole file again, which drops comments. Your file as
  you wrote it is kept once as `config.yaml.original`, and the version before
  each save as `config.yaml.bak`.

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
| `C:\ProgramData\Minecraft Server Controller\` | Database, backups, mod archives, crash evidence, certificates, logs | Yes, but **your backups are in here** |
| `…\Minecraft Server Controller\mod-trash\` (and `servers\<id>\mod-trash\`) | Mods you removed via the dashboard | Check first |
| `<server>\mcsc-data\` | The data folder from before multi-server, left in place when it was copied | Yes, once the new folder works |
| `<server>\world*`, `mods\`, jars | Your actual server | **No** — this is your server |

Nothing the agent installs lives outside the project folder and its data
folder. It adds no registry keys beyond the startup task, which `autostart
disable` removes, and it writes nothing to `AppData`.

Your Minecraft server is exactly as it was: same jar, same worlds, same mods
folder. Run your original `java -Xmx6G -jar fabric-server-launch.jar nogui`
command and it starts as it always did.
