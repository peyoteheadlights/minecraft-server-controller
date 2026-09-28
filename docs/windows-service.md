# Windows Service (alternative)

**Use [windows-startup.md](windows-startup.md) instead.** The scheduled task is
the supported way to start the agent with Windows.

`installer/service.py` still exists for people who specifically need a Windows
Service. Its original registration bug (the class was registered as
`__main__.MinecraftControlService`, which can never load) is fixed, and
`start` now verifies the service reached RUNNING instead of assuming it.

```powershell
# Administrator PowerShell - only if you are NOT using the scheduled task
python -m installer.service install
python -m installer.service start
python -m installer.service status
python -m installer.service uninstall
```

The service and the scheduled task must not both be installed; `install`
refuses while the task exists, and `autostart enable` removes the service.
