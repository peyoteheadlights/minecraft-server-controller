# Minecraft Server Controller

Run your Minecraft server on your own Windows PC, and look after it from
your phone or any computer. Start and stop it, see who's playing, keep
backups, add mods, and get told when something goes wrong.

It works with Vanilla, Fabric, Quilt, Forge, NeoForge, Paper and Purpur.
Only your own devices can reach it: it uses [Tailscale](https://tailscale.com),
a free private network, and HTTPS.

![Overview in the light theme](docs/screenshots/overview-light.png)

## What you can do

- **Start, stop and restart** from anywhere. If the server crashes, it
  says why in plain words and can start again by itself.
- **See who's playing**, chat with them, and whitelist, kick or ban.
- **Back up** the world on a schedule. Each backup is checked before it
  counts, and a second copy can go to a USB drive or a cloud folder.
- **Go back in time**: put the world back to how it was yesterday. What
  it's like now is saved first, so that can be undone too.
- **Bring a world in** from single-player, or take the server's world home
  as a .zip to play offline.
- **Add mods** from Modrinth, with the mods they need, checked before
  they're installed.
- **Make new servers** of any kind and version, change versions, and let
  Bedrock players join.
- **Give friends their own sign-in** as helpers: they can start the server
  and look after players, but can't change how it's set up.
- **Get alerts** on your phone, Discord or email.
- **Keep the PC awake** while someone is playing.
- **Move to a new PC** with one file.

Every number you see was measured. When something can't be measured, it
says *Unknown* and why, rather than guessing.

| Overview, dark theme | All servers |
| --- | --- |
| ![Overview in the dark theme](docs/screenshots/overview-dark.png) | ![All servers](docs/screenshots/all-servers-light.png) |

## What you need

- A Windows 10 or 11 PC to run the server
- [Python](https://www.python.org) 3.11 or newer
- Java, the version your Minecraft needs (the app tells you which)
- [Tailscale](https://tailscale.com) on that PC and on each phone or
  computer you want to use the dashboard from

## Install

1. Download this project to the PC (Code → Download ZIP, then unzip it).
2. In the folder, right-click `setup.cmd` and choose **Run**. Or, in
   PowerShell in that folder: `.\setup.ps1`
3. Answer its questions: where your server is (or where a new one should
   go), and a password for the dashboard.
4. Open the address it shows, on the PC or your phone, and sign in.

Setup is safe to run again: it keeps what's already set up and fixes what
isn't. `.\setup.ps1 --check` only checks, and changes nothing.

More detail, step by step: [docs/installation.md](docs/installation.md).

## First steps

After signing in, open **Getting started** (under the gear, or from the
checklist on a new server's Overview). It walks through starting the
server, letting friends join, backups and alerts, with a button to each.

## Forgot the password?

On the PC, open PowerShell in the app's folder and run:

```powershell
python -m installer.reset_password
```

It asks for a new password twice and signs everyone out. This only works on
the PC itself, never over the network.

## Moving to a new PC

1. On the old PC: **App settings → Move to a new PC → Export everything**.
   Tick worlds and backups if you want them. Tick passwords and keys only if
   you want them moved too; they are locked with a passphrase you choose.
2. Install the app on the new PC with `setup.ps1`.
3. On the new PC, with the app stopped:

   ```powershell
   python -m installer.import_from_pc "D:\the-export-file.zip" --to "C:\Minecraft Servers"
   ```

4. Run `setup.ps1` once more. It makes the new PC's certificate and start
   with Windows task.

## When something goes wrong

- **Crashes** shows what happened and the likely cause.
- **Get help** (on the Crashes page and in App settings) saves one file of
  logs and checks to send to whoever is helping you. It never contains
  passwords, keys or worlds, and shows its file list before saving.
- [docs/troubleshooting.md](docs/troubleshooting.md) covers the common
  problems.

## For developers

How it's built, the settings file, the API, security and the tests:
[docs/developers.md](docs/developers.md). The rest of the technical guides
are in [docs/](docs/).

## License

Released under the [MIT License](LICENSE). Copyright (c) 2026 Mark Ramy.
