# Privacy

Minecraft Server Controller runs on your own PC. It has no accounts, no
analytics and no tracking, and the person who made it receives nothing
from it.

It doesn't send information to other computers unless you, or whoever
installed or runs it, asked it to. Everything it does contact is listed
here.

## What it contacts, and when

| What | When | What is sent |
|---|---|---|
| **GitHub** (`api.github.com`, this repository's releases) | Once a day to see if a new version is out (on by default; `updates.check: false` in `config.yaml` turns it off), when you select **Check now**, and when you install an update | An ordinary web request. Nothing about you or your servers |
| **Mojang / Microsoft**, **Fabric**, **Quilt**, **Forge**, **NeoForge**, **PaperMC**, **Purpur**, **GeyserMC** | When you make a server, change its version or add crossplay | Which version to download |
| **Modrinth** | When you search for, add or update mods, and every 12 hours to see if your mods have updates (on by default; `mods.update_check_hours: 0` in `config.yaml` turns it off) | Your search words, or which mods you have, and the Minecraft version |
| **Adoptium** (Java) | When you ask the setup or the dashboard to get Java | Which Java version to download |
| **Discord** | Only if you set up Discord alerts | The alert text (for example "Server crashed") to the webhook you entered |
| **Your email server** | Only if you set up email alerts | The alert text to the addresses you entered |
| **Your browser's push service** (Google, Apple or Mozilla, chosen by the browser) | Only for browsers you turned phone alerts on in | The alert, encrypted so the push service can't read it |
| **Google Firebase Cloud Messaging** | Only if the owner set up lock-screen alerts for the phone app, and only to phones that turned them on | A wake-up with an alert number and no words in it. The phone then reads the alert from your PC |

Each of these services has its own privacy policy, and sees your PC's
internet address like any website you visit.

## What stays on your PC

Your worlds, backups, settings, passwords (stored only as salted hashes),
logs and players' names stay on your PC. The dashboard is reached through
your own Tailscale network; this app never sends it anywhere else.

**Get help** saves a file of logs and checks on your PC. It is never sent
by itself: you choose who to give it to. It never contains passwords, keys
or worlds.

## The phone apps

The Android and iPhone apps talk only to your PC, over your Tailscale
network. They have no accounts, no ads, no analytics and no tracking, and
send nothing to the person who made them.

- Your sign-in is kept in the phone's secure storage (the Android keystore
  or the iPhone keychain), behind the phone's own unlock. It is never sent
  anywhere but your PC, and is not included in phone backups.
- The camera is used only to read the pairing code from your PC's screen.
  The picture is read on the phone and never stored or sent.
- **Lock-screen alerts** (Android, if turned on) give Google a push address
  for the phone, and Google delivers wake-ups from your PC to it. A wake-up
  holds only an alert number. Turning the setting off, signing out, or the
  PC signing the phone out removes the address from your PC.
- **Copy details for a problem report** puts versions and recent request
  results on the clipboard, never a password, sign-in code or address. You
  choose where to paste it.
- The apps open other websites (Tailscale, GitHub's forms, this policy) in
  the phone's browser. Nothing of your sign-in goes with them.

## Questions

Open an issue on
[GitHub](https://github.com/peyoteheadlights/minecraft-server-controller/issues),
or see [SECURITY.md](SECURITY.md) to report a security problem privately.
