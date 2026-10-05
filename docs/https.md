# HTTPS and certificates

The dashboard, the API and the live event stream all run over HTTPS. The agent
refuses to serve plain HTTP on anything except `127.0.0.1`, so your password
and session token can never cross the network unencrypted.

```
Phone / main PC  --(Tailscale, encrypted)-->  Minecraft PC
                         |
                     HTTPS + WSS
                         |
                    Server Agent  -->  Minecraft
```

Tailscale already encrypts the link. HTTPS on top of it gives you two more
things: the browser treats the page as a secure context (so no mixed-content
or insecure-origin restrictions), and nothing on the Minecraft PC itself can
read your traffic on the loopback interface.

---

## Two certificate strategies

`python -m installer.make_certs` picks the better one automatically.

### 1. Tailscale-issued certificates — preferred

If your tailnet has MagicDNS and HTTPS certificates enabled, Tailscale runs a
real ACME client against **Let's Encrypt**, using a DNS-01 challenge against
your tailnet domain.

| | |
| --- | --- |
| Trusted by | every browser, phone and laptop already — **nothing to install** |
| Requires an open port | no |
| Exposes anything publicly | no — the DNS challenge is the only thing that touches the internet |
| Renewal | automatic, handled by Tailscale |
| Hostname | `minecraft-pc.tailXXXX.ts.net` |

This is the cleanest possible answer for a private network, which is why the
tool tries it first.

**Enable it once** in the Tailscale admin console:

1. <https://login.tailscale.com/admin/dns> → enable **MagicDNS**
2. Same page → enable **HTTPS Certificates**

Then on the Minecraft PC:

```powershell
python -m installer.make_certs
```

You should see `Strategy: Tailscale-issued certificate (publicly trusted)`.

### 2. Local certificate authority — the fallback

Used when Tailscale HTTPS is not available. The tool creates a CA once, and
signs a server certificate with it. You trust the **CA** once per device; after
that every renewal is trusted automatically, because the CA does not change.

| | |
| --- | --- |
| Trusted by | devices where you install `ca.crt` (a one-off, per device) |
| Requires an open port | no |
| Renewal | `python -m installer.make_certs --renew`, and **no re-trusting** |
| Certificate lifetime | 398 days (the maximum browsers accept) |
| CA lifetime | 10 years |

Plain self-signed certificates with no CA are deliberately not offered: they
force you to click through a browser warning on every device forever, which is
exactly what this setup is meant to avoid.

---

## What the certificate covers

The tool puts every name you might use into the Subject Alternative Name list —
modern browsers ignore the Common Name entirely and check SANs only:

- your tailnet MagicDNS name (`minecraft-pc.tailXXXX.ts.net`)
- the machine's own hostname
- `localhost`
- the Tailscale IP (`100.x.y.z`)
- `127.0.0.1`

Add more with `--host` and `--ip`:

```powershell
python -m installer.make_certs --host minecraft.home.example --ip 100.101.102.103
```

If you open the dashboard with a name that is **not** in the certificate, the
browser will refuse it. `python -m agent.main --check` tells you before it
happens:

```
  Certificate hostname:          FAIL     minecraft-pc
      The certificate does not cover this name. It covers:
      minecraft-pc.tail1234.ts.net, localhost, 127.0.0.1
```

---

## Trusting the local CA

Only needed for strategy 2. You install **`ca.crt`** — never `ca.key`, which
must stay on the server PC.

The file is at `C:\ProgramData\Minecraft Server Controller\certs\ca.crt` (before multi-server: `…\Minecraft Server\mcsc-data\certs\ca.crt`). Verify you are
trusting the right file by comparing fingerprints:

```powershell
python -m installer.make_certs --show
```

### Windows

Administrator PowerShell:

```powershell
Import-Certificate -FilePath "C:\ProgramData\Minecraft Server Controller\certs\ca.crt" `
  -CertStoreLocation Cert:\LocalMachine\Root
```

Check it landed:

```powershell
Get-ChildItem Cert:\LocalMachine\Root | Where-Object { $_.Subject -like "*Minecraft Server Control*" }
```

Firefox keeps its own store: **Settings → Privacy & Security → Certificates →
View Certificates → Authorities → Import**, and tick "Trust this CA to identify
websites".

### Android

1. Copy `ca.crt` to the phone (email, USB, or Tailscale Taildrop)
2. **Settings → Security → Encryption & credentials → Install a certificate →
   CA certificate**
3. Accept the warning, pick the file

Chrome on Android will then trust it. Some apps pin their own stores and will
not — that does not affect the dashboard.

### iOS and iPadOS

Two steps, and people usually miss the second:

1. AirDrop or email `ca.crt` to the device and open it
2. **Settings → Profile Downloaded → Install**
3. **Settings → General → About → Certificate Trust Settings** → switch on
   full trust for "Minecraft Server Control local CA"

Without step 3 Safari will still refuse the certificate.

---

## Renewal

| Strategy | What you do |
| --- | --- |
| Tailscale | Nothing. Tailscale renews it. Re-run `make_certs` afterwards, or let the scheduled task do it, so the agent picks up the new files. |
| Local CA | `python -m installer.make_certs --renew` once every 398 days. The CA is untouched, so **no device needs re-trusting**. |

The agent watches its own certificate. Every six hours it reads the file and
checks the expiry date:

| Days remaining | What happens |
| --- | --- |
| more than 14 | nothing |
| 14 or fewer | `certificate_expiring` warning event, Discord/email alert, banner on the Security page |
| 3 or fewer | the same, escalated to error level |
| expired | the agent **refuses to start** rather than serving a broken certificate |

If the expiry cannot be read, it is reported as **unknown** — never as valid.

### Renew automatically

Add a schedule in the dashboard, or a Windows scheduled task:

```powershell
schtasks /create /tn "MCSC certificate renewal" /sc monthly `
  /tr "python -m installer.make_certs --renew" `
  /rl highest /ru SYSTEM
```

---

## HTTP behaviour

By default a small listener runs on port 8080 that does exactly one thing:

- `GET`/`HEAD` → **308 redirect** to the HTTPS address
- everything else → **400** with a message saying to use HTTPS

It serves no API, no static files and no session. A `POST` is refused rather
than redirected on purpose: a client that followed a redirect would re-send
credentials over plain HTTP first.

Turn it off entirely with `tls.http_redirect: false`.

## HSTS

`Strict-Transport-Security: max-age=31536000` is sent on HTTPS responses, and:

- **never over HTTP** (it would be meaningless and ignored)
- **never on loopback** — `https://127.0.0.1` and `https://localhost` are
  exempt, so a year of forced HTTPS is never pinned onto your local
  development, which is a mistake you cannot easily undo in a browser

Disable with `tls.hsts: false`.

## WebSockets

The dashboard derives its socket URL from the page it was served from, so an
HTTPS dashboard always connects with `wss://`. There is no configuration for
this and no way to end up on `ws://` from an HTTPS page.

Authentication happens in the **first message**, not the query string, so the
token never lands in a proxy log or browser history. The socket is read-only:
it streams events, and control actions go through the audited REST API.

---

## Private key security

| Rule | How it is enforced |
| --- | --- |
| Never in Git | `*.key`, `*.pem`, `certs/` are in `.gitignore` |
| Never downloadable | no endpoint serves files from the certificate folder |
| Never in an API response | `CertificateInfo` carries no key bytes; the only thing reported is whether the key's **public** half matches the certificate |
| Never logged | the key is loaded, compared and dropped inside one function |
| Restricted on disk | the folder and key get an ACL for SYSTEM, Administrators and you only (`icacls`), or `0600` on POSIX |

There is a test asserting that certificate metadata never contains the strings
`PRIVATE KEY` or `BEGIN`.

### Backing certificates up

Back up `ca.crt`, `ca.key`, `agent.crt` and `agent.key` **to an encrypted
location** — a password manager's file attachment, an encrypted archive, or a
BitLocker volume. Anyone with `ca.key` can issue certificates your devices will
trust.

Do not put them in the Minecraft backup zips: those are not encrypted. The
certificate folder is deliberately outside `backups.include`.

If you lose them, nothing is broken permanently — run `make_certs` again and
re-trust the new CA on your devices.

---

## Diagnostics

```powershell
python -m agent.main --check          # certificate, key, hostname, expiry
python -m agent.main --check --deep   # also opens a real TLS connection
```

`--deep` performs an actual handshake with certificate verification enabled
and reports the negotiated protocol and cipher. It never disables verification
to make a check pass.

```
HTTPS
  Certificate:                   OK       ...\certs\agent.crt
      issued by CN=Minecraft Server Control local CA
  Certificate expiration:        OK       398 days
  Certificate hostname:          OK       minecraft-pc.tail1234.ts.net
  Private key:                   OK       matches certificate
  HTTPS binding:                 OK       https://100.101.102.103:8765
  HTTP redirect:                 OK       http://100.101.102.103:8080
  HSTS:                          OK       max-age=31536000
  WebSocket:                     OK       wss://
  TLS handshake:                 OK       TLSv1.3 / TLS_AES_256_GCM_SHA384
```

## Common problems

| Symptom | Cause and fix |
| --- | --- |
| `HTTPS cannot start: TLS certificate not found` | Run `python -m installer.make_certs` |
| `The TLS private key does not match the certificate` | The two files came from different runs. Re-issue both: `--renew` |
| Browser says "not private" on Windows | The CA is not in `Cert:\LocalMachine\Root`, or you are using Firefox, which needs its own import |
| Works on the PC, fails on iPhone | You missed **Certificate Trust Settings** on iOS |
| Works with the IP, fails with the hostname | The hostname is not in the certificate. Re-issue with `--host <name>` |
| `ERR_CERT_DATE_INVALID` | Expired. `python -m installer.make_certs --renew` |
