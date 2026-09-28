# Remote access with Tailscale

The point of this setup: you can reach the dashboard from your phone anywhere
in the world, and nobody else can reach it at all. No port forwarding, no
dynamic DNS, no open ports on your router.

## How it works

Tailscale builds a private encrypted network (a "tailnet") between your own
devices. Each device gets a stable address in the `100.x.y.z` range that only
your devices can route to. The agent binds to that address, so the dashboard is
reachable from your tailnet and from literally nowhere else.

## 1. Install Tailscale on the Minecraft PC

1. Download from https://tailscale.com/download/windows
2. Install and sign in (Google, Microsoft or GitHub account is fine)
3. The tray icon shows your machine's address, e.g. `100.101.102.103`

Find it from PowerShell any time:

```powershell
tailscale ip -4
```

## 2. Install Tailscale on your phone and laptop

Install the app from the App Store or Play Store, sign in with **the same
account**. That is the whole pairing process.

## 3. Turn on MagicDNS and HTTPS certificates

Do this once in the admin console, because it gives you a stable hostname
**and** publicly trusted certificates with nothing to install on your devices:

1. <https://login.tailscale.com/admin/dns> -> enable **MagicDNS**
2. Same page -> enable **HTTPS Certificates**

Your Minecraft PC now has a stable name like `minecraft-pc.tail1234.ts.net`
that works from every device in your tailnet.

## 4. Find the address the agent should use

```powershell
tailscale ip -4          # the 100.x.y.z address
tailscale status --json  # everything, including the MagicDNS name
```

The agent asks the Tailscale daemon the same way, so what it reports on the
Security page and in `--check` comes from the daemon, not from a guess about
network interfaces. If the daemon cannot be asked, it says
**unknown** rather than "connected".

## 5. Point the agent at the Tailscale address

In `config/config.yaml`:

```yaml
network:
  host: 100.101.102.103   # your Tailscale address, not 0.0.0.0
  port: 8765

tls:
  enabled: true
  hostname: minecraft-pc.tail1234.ts.net   # what you type in the browser
```

Then issue the certificate and restart the agent:

```powershell
python -m installer.make_certs
python -m agent.main --check
```

From your phone, open:

```
https://minecraft-pc.tail1234.ts.net:8765
```

## 6. Prefer the MagicDNS name

Use the full MagicDNS name rather than the bare IP. It is stable, it is what
the certificate is issued for, and it survives the Tailscale address changing:

```
https://minecraft-pc.tail1234.ts.net:8765
```

## Rules worth keeping

- **Never set `host: 0.0.0.0`** unless you fully understand the consequences.
  That binds the dashboard to every network interface, including your home
  LAN and anything your router forwards.
- **Never port-forward 8765.** The whole design assumes it is unreachable from
  the internet.
- Minecraft's own port (25565) is separate. If your players connect over the
  internet, that port is forwarded and public — that is normal and unrelated to
  the dashboard.
- Tailscale's access controls can restrict which of your devices may reach the
  PC at all. Worth doing if you share your tailnet with anyone.

## Checking it works

```powershell
python -m agent.main --check
```

The Tailscale section reports what the daemon actually said:

```
Tailscale
  Tailscale:                     OK       Running
      Verified through tailscale status.
  Tailscale address:             OK       100.101.102.103
  MagicDNS name:                 OK       minecraft-pc.tail1234.ts.net
```

If the CLI is missing or cannot answer, you get `UNKNOWN` with the reason.
Having a `100.x` address assigned is reported as "interface detected" and
explicitly **not** as connected, because an address is not proof of
connectivity.

## Firewall

Allow the dashboard port to Tailscale peers only - see
[firewall.md](firewall.md). Do not port-forward it.
