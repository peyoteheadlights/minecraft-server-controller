# Windows Firewall

The firewall stays **on**. Nothing in this project asks you to disable it.

## What the agent needs

One inbound TCP port — the dashboard port, 8765 by default — reachable from
your Tailscale peers and from nowhere else.

Tailscale's own traffic does not need a rule: it makes an outbound connection
and the Tailscale installer already handles its adapter.

## Create the rule

Administrator PowerShell, from the project folder:

```powershell
.\installer\firewall.ps1
```

That creates exactly two rules:

| Rule | Port | Remote address | Effect |
| --- | --- | --- | --- |
| Minecraft Server Control (HTTPS, Tailscale only) | TCP 8765 | `100.64.0.0/10` | dashboard reachable from tailnet peers |
| Minecraft Server Control (HTTP redirect, Tailscale only) | TCP 8080 | `100.64.0.0/10` | redirect listener, tailnet peers only |

`100.64.0.0/10` is the CGNAT range Tailscale assigns addresses from. It is not
routable on the public internet and it is not your LAN, so a device on your
home Wi-Fi that is not in your tailnet cannot reach the dashboard either.

Custom ports:

```powershell
.\installer\firewall.ps1 -Port 9000 -RedirectPort 9001
```

## Verify it

```powershell
Get-NetFirewallRule -DisplayName "Minecraft Server Control (HTTPS, Tailscale only)" |
  Get-NetFirewallAddressFilter
```

`RemoteAddress` must read `100.64.0.0/10`. If it says `Any`, the rule is wider
than intended — delete it and re-run the script.

## Remove it

```powershell
.\installer\firewall.ps1 -Remove
```

## What you must not do

- **Do not port-forward 8765** on your router. The dashboard is not designed to
  face the internet, and forwarding it defeats every assumption in the security
  model.
- **Do not disable Windows Firewall** to "make it work". If the dashboard is
  unreachable, the cause is almost always `network.host` pointing at the wrong
  address, not the firewall.
- **Do not bind to `0.0.0.0`.** That puts the dashboard on every interface,
  including any that is forwarded.

## Minecraft's own port

Port 25565 is separate. If players connect over the internet, that port is
forwarded and public — normal, and unrelated to the agent. The agent never
touches it, and the dashboard rule above does not affect it.
