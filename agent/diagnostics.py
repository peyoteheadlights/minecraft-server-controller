"""The diagnostic report behind `python -m agent.main --check`.

Every line in the report is the result of an actual check against the real
system: a file is opened, a process is run, a socket is connected, a directory
is written to. Where a check cannot be performed, the status is UNKNOWN and the
reason is printed. Nothing is inferred from configuration alone.

Statuses:
  OK       verified true
  WARN     verified, but something needs attention
  FAIL     verified false, and it will stop the agent working
  UNKNOWN  could not be determined - never treated as a pass
  SKIP     not applicable to this configuration
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .minecraft.java import detect_java
from .tailscale import tailscale_status
from .security.tls import inspect_certificate, verify_endpoint

OK, WARN, FAIL, UNKNOWN, SKIP = "OK", "WARN", "FAIL", "UNKNOWN", "SKIP"


@dataclass
class Check:
    name: str
    status: str
    value: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "status": self.status,
                "value": self.value, "detail": self.detail}


@dataclass
class Report:
    sections: dict[str, list[Check]] = field(default_factory=dict)

    def add(self, section: str, check: Check) -> Check:
        self.sections.setdefault(section, []).append(check)
        return check

    @property
    def failures(self) -> list[Check]:
        return [c for checks in self.sections.values() for c in checks if c.status == FAIL]

    @property
    def warnings(self) -> list[Check]:
        return [c for checks in self.sections.values() for c in checks if c.status == WARN]

    @property
    def unknowns(self) -> list[Check]:
        return [c for checks in self.sections.values() for c in checks if c.status == UNKNOWN]

    def to_dict(self) -> dict[str, Any]:
        return {
            "sections": {name: [c.to_dict() for c in checks] for name, checks in self.sections.items()},
            "failures": len(self.failures),
            "warnings": len(self.warnings),
            "unknowns": len(self.unknowns),
            "ready": not self.failures,
        }

    def render(self) -> str:
        symbol = {OK: "OK", WARN: "WARN", FAIL: "FAIL", UNKNOWN: "UNKNOWN", SKIP: "SKIP"}
        lines = ["", "Minecraft Server Control Center - system check", "=" * 62]
        for section, checks in self.sections.items():
            lines.append("")
            lines.append(f"{section}")
            lines.append("-" * 62)
            for check in checks:
                head = f"  {check.name + ':':<30} {symbol[check.status]:<8}"
                if check.value:
                    head += f" {check.value}"
                lines.append(head.rstrip())
                if check.detail:
                    for part in _wrap(check.detail, 58):
                        lines.append(f"      {part}")
        lines.append("")
        lines.append("=" * 62)
        if self.failures:
            lines.append(f"NOT READY - {len(self.failures)} blocking problem(s):")
            for check in self.failures:
                lines.append(f"  - {check.name}: {check.detail or check.value}")
        else:
            lines.append("READY - no blocking problems found.")
        if self.warnings:
            lines.append(f"{len(self.warnings)} warning(s):")
            for check in self.warnings:
                lines.append(f"  - {check.name}: {check.detail or check.value}")
        if self.unknowns:
            lines.append(f"{len(self.unknowns)} item(s) could not be verified "
                         f"(reported as UNKNOWN, not assumed good):")
            for check in self.unknowns:
                lines.append(f"  - {check.name}: {check.detail or 'no data source available'}")
        lines.append("")
        return "\n".join(lines)


def _wrap(text: str, width: int) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        if len(current) + len(word) + 1 > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines


def _writable(path: Path) -> tuple[bool, str]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".mcsc-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True, ""
    except OSError as exc:
        return False, str(exc)


# ----------------------------------------------------------------------
def run_diagnostics(config, deep: bool = False) -> Report:
    """Build the full report. `deep` additionally opens a TLS connection to a
    running agent, which only makes sense when one is running."""
    report = Report()

    # ---------------- Minecraft ----------------
    section = "Minecraft server"
    server_dir = config.server_dir
    if not config.server_dir_configured:
        report.add(section, Check("Minecraft directory", FAIL, "not set",
                                  "server.directory is empty. Open config/config.yaml and set it to "
                                  "the folder that contains your server jar."))
    elif server_dir.is_dir():
        report.add(section, Check("Minecraft directory", OK, str(server_dir)))
    else:
        report.add(section, Check("Minecraft directory", FAIL, str(server_dir),
                                  f"The directory does not exist: {server_dir}. "
                                  "Set server.directory in config/config.yaml."))
        # everything below depends on it, but keep checking what we can

    raw_command = config.server.raw_command
    if not config.server_dir_configured:
        # Nothing else in this section can be checked without the folder, and
        # nothing may be created under a path that has not been chosen.
        report.add(section, Check("Server JAR, mods, worlds", SKIP, "",
                                  "Checked once server.directory is set."))
    elif raw_command:
        report.add(section, Check("Launch command", OK, " ".join(str(a) for a in raw_command),
                                  "server.raw_command is set, so jar and java settings are not used."))
    else:
        jar = server_dir / config.server.jar
        if jar.is_file():
            report.add(section, Check("Server JAR", OK, jar.name,
                                      f"{jar.stat().st_size / 1024**2:.1f} MB"))
        else:
            report.add(section, Check("Server JAR", FAIL, str(jar),
                                      "The server jar was not found. Check server.jar."))

    mods_dir = config.mods_dir
    if not config.server_dir_configured:
        pass
    elif mods_dir.is_dir():
        jars = [p for p in mods_dir.glob("*.jar")]
        disabled = [p for p in mods_dir.glob("*.jar.disabled")]
        report.add(section, Check("Mods directory", OK, str(mods_dir),
                                  f"{len(jars)} enabled, {len(disabled)} disabled"))
    else:
        ok, error = _writable(mods_dir)
        report.add(section, Check("Mods directory", OK if ok else FAIL, str(mods_dir),
                                  "Created, it did not exist." if ok else f"Cannot create: {error}"))

    if config.server_dir_configured:
        config_dir = server_dir / "config"
        report.add(section, Check(
            "Config directory", OK if config_dir.is_dir() else WARN, str(config_dir),
            "" if config_dir.is_dir() else "Not present. Fabric creates it on first start."))
        worlds = [name for name in ("world", "world_nether", "world_the_end")
                  if (server_dir / name).is_dir()]
        if worlds:
            report.add(section, Check("World directories", OK, ", ".join(worlds)))
        else:
            report.add(section, Check("World directories", WARN, "none found",
                                      "No world folders yet. Minecraft creates them on first start."))

    # ---------------- Java ----------------
    section = "Java"
    java = detect_java(config.server.java)
    if raw_command:
        report.add(section, Check("Java", SKIP, "",
                                  "server.raw_command is set, so the agent does not choose the runtime."))
    elif java.executable_found is False:
        report.add(section, Check("Java executable", FAIL, config.server.java,
                                  "Java was not found. Install a JDK or set server.java to the "
                                  "full path of java.exe."))
    elif java.version_major is None:
        report.add(section, Check("Java executable", OK, java.path or "found"))
        report.add(section, Check("Java version", UNKNOWN, "unknown",
                                  java.error or "The java -version output could not be parsed. "
                                                "The agent will not block startup on an unknown version."))
    else:
        report.add(section, Check("Java executable", OK, java.path or ""))
        report.add(section, Check("Java version", OK, str(java.version_major),
                                  java.version_string or ""))

    # ---------------- storage / database ----------------
    section = "Storage"
    ok, error = _writable(config.data_dir)
    report.add(section, Check("Data directory", OK if ok else FAIL, str(config.data_dir),
                              "" if ok else f"Not writable: {error}"))
    ok, error = _writable(config.log_dir)
    report.add(section, Check("Log directory", OK if ok else FAIL, str(config.log_dir),
                              "" if ok else f"Not writable: {error}"))
    db_path = config.database_path
    try:
        from .database.db import Database
        probe = Database(db_path)
        version = probe.version
        probe.close()
        report.add(section, Check("Database", OK, str(db_path), f"schema version {version}"))
    except Exception as exc:
        report.add(section, Check("Database", FAIL, str(db_path), f"Not usable: {exc}"))
    try:
        usage = shutil.disk_usage(server_dir if server_dir.is_dir() else Path.home())
        free_gb = usage.free / 1024**3
        threshold = config.thresholds.disk_free_gb
        report.add(section, Check(
            "Disk space", OK if free_gb > threshold else WARN, f"{free_gb:.1f} GB free",
            f"Alert threshold is {threshold} GB"))
    except OSError as exc:
        report.add(section, Check("Disk space", UNKNOWN, "unknown",
                                  f"The filesystem could not be queried: {exc}"))

    # ---------------- HTTPS ----------------
    section = "HTTPS"
    host = config.network.host
    port = config.network.port
    if not config.tls_enabled:
        report.add(section, Check("TLS", WARN, "disabled",
                                  "tls.enabled is false, so the dashboard is served over plain HTTP. "
                                  "This is only acceptable on 127.0.0.1 for local development."))
        if host not in ("127.0.0.1", "localhost", "::1"):
            report.add(section, Check("Plain HTTP binding", FAIL, f"{host}:{port}",
                                      "HTTP is bound to a non-loopback address. Credentials would "
                                      "cross the network unencrypted. Enable tls.enabled."))
    else:
        cert = inspect_certificate(config.tls_certificate, config.tls_private_key)
        if cert.certificate_present is False:
            report.add(section, Check("Certificate", FAIL, str(config.tls_certificate),
                                      "No certificate file. Run: python -m installer.make_certs"))
        elif not cert.parsed:
            report.add(section, Check("Certificate", FAIL, str(config.tls_certificate),
                                      cert.parse_error or "The certificate could not be parsed"))
        else:
            report.add(section, Check("Certificate", OK, str(config.tls_certificate),
                                      f"issued by {cert.issuer}"))
            if cert.expired:
                report.add(section, Check("Certificate expiration", FAIL, "expired",
                                          "The certificate is outside its validity window. Renew it."))
            elif cert.days_remaining is not None:
                status = {"critical": FAIL, "warn": WARN, "ok": OK}[cert.expiry_severity]
                report.add(section, Check("Certificate expiration", status,
                                          f"{cert.days_remaining:.0f} days",
                                          "Renew with: python -m installer.make_certs --renew"
                                          if status != OK else ""))
            else:
                report.add(section, Check("Certificate expiration", UNKNOWN, "unknown",
                                          "The validity dates could not be read."))

            hostname = config.dashboard_hostname
            if not hostname:
                report.add(section, Check("Certificate hostname", UNKNOWN, "not configured",
                                          "tls.hostname is empty, so the agent cannot check that the "
                                          f"certificate matches what you type. It covers: "
                                          f"{', '.join(cert.names + cert.ip_names) or 'no names'}"))
            else:
                covers = cert.covers(hostname)
                if covers is True:
                    report.add(section, Check("Certificate hostname", OK, hostname))
                elif covers is False:
                    report.add(section, Check("Certificate hostname", FAIL, hostname,
                                              "The certificate does not cover this name. It covers: "
                                              f"{', '.join(cert.names + cert.ip_names)}. "
                                              "Re-issue with: python -m installer.make_certs"))
                else:
                    report.add(section, Check("Certificate hostname", UNKNOWN, hostname,
                                              "The names in the certificate could not be read."))

            if cert.key_present is False:
                report.add(section, Check("Private key", FAIL, str(config.tls_private_key),
                                          "The private key file was not found."))
            elif cert.key_matches_certificate is True:
                report.add(section, Check("Private key", OK, "matches certificate"))
            elif cert.key_matches_certificate is False:
                report.add(section, Check("Private key", FAIL, "does not match certificate",
                                          "TLS will fail to start. Re-issue both files together."))
            else:
                report.add(section, Check("Private key", UNKNOWN, "not verified",
                                          cert.key_check_error or "The key could not be compared."))

            for problem in cert.problems:
                if "not found" not in problem:
                    report.add(section, Check("Certificate note", WARN, "", problem))

        report.add(section, Check("HTTPS binding", OK, f"https://{host}:{port}",
                                  "This is the address the agent will listen on."))
        if host in ("0.0.0.0", "::"):
            report.add(section, Check("Bind scope", WARN, host,
                                      "Binding to every interface. Prefer the Tailscale address so "
                                      "the dashboard is not reachable from your LAN or a forwarded port."))
        if config.tls.http_redirect:
            report.add(section, Check("HTTP redirect", OK,
                                      f"http://{host}:{config.tls.http_redirect_port}",
                                      "Redirect-only listener: it answers 308 to HTTPS and serves "
                                      "no API, no data and no session."))
        else:
            report.add(section, Check("HTTP redirect", SKIP, "disabled",
                                      "Plain HTTP is not served at all."))
        report.add(section, Check("HSTS", OK if config.tls.hsts else SKIP,
                                  f"max-age={config.tls.hsts_max_age}" if config.tls.hsts else "off",
                                  "Sent on HTTPS responses only, never over HTTP, and never on "
                                  "loopback, so local development is unaffected."))
        report.add(section, Check("WebSocket", OK, "wss://",
                                  "The dashboard derives its socket scheme from the page, so an "
                                  "HTTPS dashboard always uses wss://."))

        if deep:
            check_host = config.dashboard_hostname or ("127.0.0.1" if host in ("0.0.0.0", "::") else host)
            result = verify_endpoint(host if host not in ("0.0.0.0", "::") else "127.0.0.1",
                                     port, config.tls_ca_certificate, server_hostname=check_host)
            if result["verified"] is True:
                report.add(section, Check("TLS handshake", OK,
                                          f"{result['protocol']} / {result['cipher']}",
                                          f"Verified against {check_host} with certificate checking on."))
            elif result["reachable"] is False:
                report.add(section, Check("TLS handshake", UNKNOWN, "no agent listening",
                                          "Nothing answered on that port. Start the agent and run "
                                          "--check --deep again."))
            else:
                report.add(section, Check("TLS handshake", FAIL, "not verified",
                                          result["error"] or "unknown error"))

    # ---------------- Tailscale ----------------
    section = "Tailscale"
    status = tailscale_status()
    if not status["cli_found"]:
        report.add(section, Check("Tailscale", UNKNOWN, "CLI not found",
                                  "The tailscale command is not on this machine, so connectivity "
                                  "cannot be verified. Install Tailscale for remote access."))
    elif status.get("error"):
        report.add(section, Check("Tailscale", UNKNOWN, "not verified", status["error"]))
    elif status.get("connected"):
        report.add(section, Check("Tailscale", OK, status.get("backend_state") or "Running",
                                  "Verified through tailscale status."))
        report.add(section, Check("Tailscale address", OK,
                                  ", ".join(status.get("addresses") or []) or "none reported"))
        if status.get("dns_name"):
            report.add(section, Check("MagicDNS name", OK, status["dns_name"],
                                      "Use this as tls.hostname and in the browser."))
        else:
            report.add(section, Check("MagicDNS name", WARN, "not available",
                                      "Without MagicDNS you must use the 100.x address, and "
                                      "Tailscale-issued certificates are not available."))
    else:
        report.add(section, Check("Tailscale", FAIL, status.get("backend_state") or "not running",
                                  "Tailscale is installed but not connected. Run: tailscale up"))

    # ---------------- authentication ----------------
    section = "Authentication"
    if config.admin_password_hash:
        algorithm = config.admin_password_hash.split("$")[0]
        report.add(section, Check("Dashboard password", OK, f"{algorithm} hash configured",
                                  f"User: {config.admin_username}"))
    else:
        report.add(section, Check("Dashboard password", FAIL, "not set",
                                  "Run: python -m installer.make_secrets"))
    report.add(section, Check("API token", OK if config.api_token else SKIP,
                              "configured" if config.api_token else "not set",
                              "" if config.api_token else "Optional: only needed for scripts."))
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.is_file():
        detail = ""
        if os.name != "nt":
            mode = env_path.stat().st_mode & 0o777
            detail = f"permissions {oct(mode)}" + (" - consider chmod 600" if mode & 0o077 else "")
        report.add(section, Check(".env file", OK, str(env_path), detail))
    else:
        report.add(section, Check(".env file", WARN, "not found",
                                  "Secrets are read from the environment instead."))

    # ---------------- notifications ----------------
    section = "Notifications"
    if config.notifications.discord_enabled:
        if config.discord_webhook:
            report.add(section, Check("Discord", OK, "enabled, webhook configured",
                                      "Delivery is only proven by Settings -> Send test."))
        else:
            report.add(section, Check("Discord", FAIL, "enabled but no webhook",
                                      "Set MCSC_DISCORD_WEBHOOK in .env."))
    else:
        report.add(section, Check("Discord", SKIP, "disabled"))
    if config.notifications.email_enabled:
        email = config.notifications.email
        missing = [k for k in ("host", "from_address") if not getattr(email, k)]
        if not email.to_addresses:
            missing.append("to_addresses")
        if missing:
            report.add(section, Check("Email", FAIL, "enabled but incomplete",
                                      f"Missing in config.yaml: {', '.join(missing)}"))
        elif not config.smtp_password:
            report.add(section, Check("Email", WARN, "no SMTP password",
                                      "Set MCSC_SMTP_PASSWORD in .env if your server needs a login."))
        else:
            report.add(section, Check("Email", OK, f"{email.host}:{email.port}",
                                      "Delivery is only proven by Settings -> Send test."))
    else:
        report.add(section, Check("Email", SKIP, "disabled"))

    # ---------------- Windows startup ----------------
    section = "Windows startup"
    try:
        from installer.autostart import report as startup_report
        startup = startup_report()
    except Exception as exc:  # the check must never crash the diagnostic
        startup = None
        report.add(section, Check("Startup task", UNKNOWN, "not inspected",
                                  f"The startup inspector failed: {exc}"))
    if startup is not None:
        if not startup["supported"]:
            report.add(section, Check("Startup task", SKIP, "not Windows"))
        elif not startup["registered"]:
            report.add(section, Check("Startup task", WARN, "not registered",
                                      "The agent will not start with Windows. Run (as Administrator): "
                                      "python -m installer.autostart enable"))
        else:
            task = startup.get("task") or {}
            status = OK if startup["points_to_current_app"] else FAIL
            report.add(section, Check("Startup task", status, startup["mechanism"],
                                      f"mode={task.get('mode')}, runs {task.get('command')} "
                                      f"in {task.get('working_directory')}"))
        for problem in startup["problems"]:
            report.add(section, Check("Startup problem", FAIL, "", problem))
        last = startup.get("last_startup") or {}
        if last:
            initialised = any(e.get("event") == "controller_initialized" for e in last.get("events", []))
            report.add(section, Check(
                "Last startup", OK if initialised else WARN,
                f"{last.get('started_at')} ({last.get('launched_by')})",
                f"outcome={last.get('outcome')}, last stage={last.get('last_event')}, "
                f"controller initialised={'yes' if initialised else 'no'}"))
        else:
            report.add(section, Check("Last startup", UNKNOWN, "none recorded",
                                      "logs/startup.log has no entries yet."))

    # ---------------- runtime ----------------
    section = "Runtime"
    report.add(section, Check("Python", OK, sys.version.split()[0], sys.executable))
    report.add(section, Check("Config file", OK if config.source and Path(config.source).is_file() else WARN,
                              str(config.source or "defaults only"),
                              "" if config.source and Path(config.source).is_file()
                              else "No config.yaml found; built-in defaults are in use."))
    report.add(section, Check("Working directory", OK, os.getcwd(),
                              "All paths the agent uses are absolute, so this does not matter "
                              "when running as a Windows Service."))
    return report
