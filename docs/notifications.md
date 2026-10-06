# Discord, email and phone alerts

All three channels are off until you configure them. Secrets go in `.env`, never in
`config.yaml` and never in the dashboard.

## Discord

1. In Discord: **Server Settings → Integrations → Webhooks → New Webhook**
2. Choose the channel, press **Copy Webhook URL**
3. Paste it into `.env` on the Minecraft PC:

```
MCSC_DISCORD_WEBHOOK=https://discord.com/api/webhooks/123456789/abcdef...
```

4. Restart the agent
5. Dashboard → **Settings** → tick **Send to Discord** → **Send test**

Crash alerts arrive as an embed with the exit code, the likely cause, the
evidence lines, who was online, and the machine's RAM/CPU/disk at the time.

## Email

The host and addresses are not secret, so they live in `config/config.yaml`:

```yaml
notifications:
  email_enabled: true
  email:
    host: smtp.gmail.com
    port: 587
    use_tls: true
    use_ssl: false
    from_address: your.address@gmail.com
    to_addresses:
      - your.address@gmail.com
    attach_crash_report: true
    attach_log_tail: true
```

The credentials go in `.env`:

```
MCSC_SMTP_USERNAME=your.address@gmail.com
MCSC_SMTP_PASSWORD=your-app-password
```

**Gmail:** you must use an App Password, not your account password. Turn on
2-Step Verification, then create one at
https://myaccount.google.com/apppasswords.

Crash emails attach the crash report and the console tail, so you can read them
on a phone without opening the dashboard.

## Phone alerts

The same alerts as a lock-screen notification on your phone, with no account
anywhere: the browser gives this app an address on its own push service, and
the agent posts encrypted messages to it. The message is encrypted for that one
phone, so the push service carries text it cannot read.

1. On the Minecraft PC, make the key pair once:

```
python -m installer.make_push_keys
```

That appends `MCSC_VAPID_PUBLIC_KEY`, `MCSC_VAPID_PRIVATE_KEY` and
`MCSC_PUSH_SUBJECT` to `.env`. It refuses to overwrite keys that are already
there, because replacing them signs every phone out.

2. Restart the agent.
3. On the phone, open the dashboard, then **Settings → Alerts → Phone**, tick
   the channel, and press **Turn on for this phone**. The browser asks for
   permission; that answer is per phone, so do this on each one.
4. Press **Send a test**.

**iPhone and iPad:** Safari only allows notifications for a site added to the
home screen. Press **Share → Add to Home Screen** first, open the dashboard
from that icon, and then turn phone alerts on. Android and desktop Chrome,
Edge and Firefox do not need that.

A phone that is signed out, reinstalled, or whose browser data was cleared is
dropped automatically the first time its push service says it is gone. Up to
20 phones can be signed up; removing one is done from the same page.

Phone alerts need the dashboard to be reachable over HTTPS, which it is over
Tailscale (see `docs/tailscale.md`). A browser will not register the service
worker over plain HTTP on anything but `localhost`.

## Choosing events

Settings has a checkbox per event: server started/stopped/crashed/restarted/
recovered, player joined/left, high RAM/CPU/MSPT, low disk/TPS, backup
completed/failed, mod installed/removed/updated, dependency problems, failed
sign-ins, maintenance mode, a server added, removed or duplicated, a CPU core
limit that could not be applied, a player button the server confirmed
(whitelist, operator, kick, ban, unban; on by default), game settings saved
(off by default), a modpack imported (on by default) and a server put to
sleep because nobody was playing (on by default).

Every alert names its server ("Survival crashed"), so with several servers you
know which one without opening the dashboard. CPU and RAM are measured for the
whole PC, so those alerts are sent once for the machine, not once per server.

Performance alerts are throttled by `notifications.min_interval_seconds`
(default 300), so a server at 95% RAM for an hour sends one message, not
hundreds. The throttle counts each server separately: a slow Creative does
not hold back an alert about Survival.

## When sending fails

A notification failure **never** affects the server. The failure is written to
the `notifications_log` table, shown in the notification history, and published
as a `notification_failed` event — the agent carries on regardless. A Discord
outage cannot take your Minecraft server down.
