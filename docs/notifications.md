# Discord and email alerts

Both channels are off until you configure them. Secrets go in `.env`, never in
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

## Choosing events

Settings has a checkbox per event: server started/stopped/crashed/restarted/
recovered, player joined/left, high RAM/CPU/MSPT, low disk/TPS, backup
completed/failed, mod installed/removed/updated, dependency problems, failed
sign-ins, maintenance mode, a server added or removed, and a CPU core limit
that could not be applied.

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
