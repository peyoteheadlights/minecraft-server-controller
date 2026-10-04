"""The Python half of setup.ps1.

    python -m installer.setup_tool setup   configure what is missing, reuse what exists
    python -m installer.setup_tool check   read-only: report, change nothing

setup.ps1 handles what only PowerShell can: finding Python, the virtual
environment, installing packages and elevation. Everything else is here,
where it can be tested.

Principles:
  * reuse before create: an existing config.yaml, .env, certificate,
    firewall rule or startup task is inspected and kept if it is correct
  * edits preserve the rest of the file: config.yaml comments survive, and
    only the specific .env line being set is changed
  * secrets are never printed, logged or placed on a command line
  * `check` writes nothing at all
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import secrets
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent import startup_diag  # noqa: E402

MIN_PYTHON = (3, 11)
FIREWALL_RULE = "Minecraft Server Control (HTTPS, Tailscale only)"
EXIT_OK, EXIT_FAILED, EXIT_NEEDS_ADMIN = 0, 1, 10
IS_WINDOWS = os.name == "nt"


# ======================================================================
# results
# ======================================================================
@dataclass
class Step:
    name: str
    status: str               # OK | WARN | FAIL | SKIP | ADMIN
    detail: str = ""
    fix: str = ""

    def line(self) -> str:
        return f"[{self.status}] {self.name}" + (f" - {self.detail}" if self.detail else "")


@dataclass
class Context:
    mode: str = "setup"                   # setup | check
    interactive: bool = True
    skip_firewall: bool = False
    skip_startup: bool = False
    skip_certs: bool = False
    startup_mode: str = "boot"
    admin_only: bool = False
    root: Path = PROJECT_ROOT
    ask: Callable[[str], str] = input
    ask_secret: Callable[[str], str] = getpass.getpass
    say: Callable[[str], None] = print
    steps: list[Step] = field(default_factory=list)

    @property
    def writing(self) -> bool:
        return self.mode == "setup"

    @property
    def config_path(self) -> Path:
        return self.root / "config" / "config.yaml"

    @property
    def env_path(self) -> Path:
        return self.root / ".env"

    def add(self, step: Step) -> Step:
        self.steps.append(step)
        return step


# ======================================================================
# small, testable file helpers
# ======================================================================
def set_yaml_value(text: str, dotted: str, value: str) -> tuple[str, bool]:
    """Replace `section: key: value` in place, keeping comments and layout.

    Returns (new_text, changed). Only handles the two-level form this
    project's config uses; returns changed=False when the key is absent so
    the caller can fall back to a full rewrite.
    """
    section, key = dotted.split(".", 1)
    lines = text.splitlines(keepends=True)
    in_section = False
    quoted = "'" + str(value).replace("'", "''") + "'"
    for index, line in enumerate(lines):
        if re.match(rf"^{re.escape(section)}:\s*(#.*)?$", line.rstrip("\n")):
            in_section = True
            continue
        if in_section and re.match(r"^\S", line):
            break  # next top-level section
        match = re.match(rf"^(\s+){re.escape(key)}:(\s*)([^#\n]*?)(\s*#.*)?(\r?\n)?$", line)
        if in_section and match:
            indent, space, _, comment, newline = match.groups()
            lines[index] = f"{indent}{key}:{space or ' '}{quoted}{comment or ''}{newline or ''}"
            return "".join(lines), True
    return text, False


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def write_env_value(path: Path, key: str, value: str) -> None:
    """Set one KEY=value line, leaving every other line untouched."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else [
        "# Created by setup. Holds secrets: never commit or share this file."]
    for index, line in enumerate(lines):
        if re.match(rf"^\s*{re.escape(key)}\s*=", line):
            lines[index] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _restrict(path)


def _restrict(path: Path) -> None:
    try:
        from agent.security.certs import _restrict_file
        _restrict_file(path)
    except Exception:
        pass


def _load_config(ctx: Context):
    from agent.config import Config
    return Config.load(ctx.config_path, ctx.env_path)


def _edit_config(ctx: Context, updates: dict[str, str]) -> None:
    text = ctx.config_path.read_text(encoding="utf-8")
    leftovers = {}
    for dotted, value in updates.items():
        text, changed = set_yaml_value(text, dotted, value)
        if not changed:
            leftovers[dotted] = value
    ctx.config_path.write_text(text, encoding="utf-8")
    if leftovers:  # key absent from the file: fall back to a structured save
        config = _load_config(ctx)
        for dotted, value in leftovers.items():
            config.set(dotted, value)
        config.save(ctx.config_path)


# ======================================================================
# steps
# ======================================================================
def step_python(ctx: Context) -> Step:
    version = ".".join(str(p) for p in sys.version_info[:3])
    if sys.version_info[:2] < MIN_PYTHON:
        return ctx.add(Step("Python", "FAIL", f"{version} is too old",
                            f"Install Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer from python.org."))
    return ctx.add(Step("Python", "OK", f"{version} ({sys.executable})"))


def step_venv(ctx: Context) -> Step:
    venv = ctx.root / ".venv"
    inside = Path(sys.prefix).resolve() == venv.resolve()
    if inside:
        return ctx.add(Step("Virtual environment", "OK", str(venv)))
    return ctx.add(Step("Virtual environment", "WARN", "not running inside the project's .venv",
                        "Run setup.ps1, which creates and uses it."))


def step_dependencies(ctx: Context) -> Step:
    from importlib import metadata
    missing, old = [], []
    for raw in (ctx.root / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if ";" in line:
            requirement, marker = line.split(";", 1)
            if "win32" in marker and not IS_WINDOWS:
                continue
            line = requirement.strip()
        match = re.match(r"^([A-Za-z0-9_.\-]+)(\[[^\]]*\])?\s*(>=\s*([0-9.]+))?", line)
        if not match:
            continue
        name, minimum = match.group(1), match.group(4)
        try:
            installed = metadata.version(name)
        except metadata.PackageNotFoundError:
            missing.append(name)
            continue
        if minimum and _vtuple(installed) < _vtuple(minimum):
            old.append(f"{name} {installed} (needs {minimum}+)")
    if missing or old:
        detail = "; ".join(filter(None, [f"missing: {', '.join(missing)}" if missing else "",
                                          f"too old: {', '.join(old)}" if old else ""]))
        return ctx.add(Step("Dependencies", "FAIL", detail,
                            "Run setup.ps1, or: .venv\\Scripts\\python -m pip install -r requirements.txt"))
    return ctx.add(Step("Dependencies", "OK", "all requirements installed"))


def _vtuple(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", version)[:3])


def _valid_server_dir(path: str) -> str | None:
    """Return an error message, or None if the folder looks like a server."""
    folder = Path(path.strip().strip('"')).expanduser()
    if not path.strip():
        return "No folder was given."
    if not folder.is_dir():
        return f"The folder does not exist: {folder}"
    if not any(folder.glob("*.jar")):
        return f"No .jar file was found in {folder}. Choose the folder that contains your server jar."
    return None


def step_config(ctx: Context) -> Step:
    example = ctx.root / "config" / "config.example.yaml"
    if not ctx.config_path.is_file():
        if not ctx.writing:
            return ctx.add(Step("Configuration", "FAIL", "config/config.yaml does not exist",
                                "Run setup.ps1 to create it."))
        shutil.copyfile(example, ctx.config_path)
        ctx.say(f"      Created {ctx.config_path} from the example.")

    try:
        config = _load_config(ctx)
    except Exception as exc:
        return ctx.add(Step("Configuration", "FAIL", f"config.yaml could not be read: {exc}",
                            "Fix the YAML syntax, or rename the file and run setup again."))

    directory = str(config.server.directory or "").strip()
    placeholder = "path\\to" in directory or "path/to" in directory
    problem = _valid_server_dir(directory) if directory and not placeholder else "not set"
    if problem and ctx.writing:
        directory = _ask_server_dir(ctx, problem)
        if directory is None:
            return ctx.add(Step("Configuration", "FAIL", "server.directory is not set",
                                "Set it in config/config.yaml, or run setup.ps1 interactively."))
        _edit_config(ctx, {"server.directory": directory})
        config = _load_config(ctx)
        problem = None
    if problem:
        return ctx.add(Step("Configuration", "FAIL", f"server.directory: {problem}",
                            "Set server.directory in config/config.yaml to your server folder."))

    jar = config.server_dir / config.server.jar
    if not config.server.raw_command and not jar.is_file():
        return ctx.add(Step("Configuration", "FAIL", f"server jar not found: {jar}",
                            "Set server.jar in config/config.yaml to the jar's file name."))

    java = config.server.java
    if not config.server.raw_command and not Path(java).is_absolute():
        resolved = shutil.which(java)
        if resolved and ctx.writing:
            # Pinned so the startup task does not depend on the PATH it gets.
            _edit_config(ctx, {"server.java": str(Path(resolved).resolve())})
            ctx.say(f"      Set server.java to {Path(resolved).resolve()}")
        elif not resolved:
            return ctx.add(Step("Configuration", "FAIL", f"Java was not found ('{java}')",
                                "Install the Java version your server needs, or set server.java "
                                "to the full path of java.exe."))
    return ctx.add(Step("Configuration", "OK", f"server folder {config.server_dir}"))


def _ask_server_dir(ctx: Context, problem: str) -> str | None:
    env_value = os.environ.get("MCSC_SETUP_SERVER_DIR", "")
    if env_value:
        error = _valid_server_dir(env_value)
        if error:
            ctx.say(f"      MCSC_SETUP_SERVER_DIR: {error}")
            return None
        return str(Path(env_value.strip('"')).expanduser().resolve())
    if not ctx.interactive:
        return None
    ctx.say(f"      The Minecraft server folder is {problem.lower() if problem == 'not set' else 'invalid: ' + problem}")
    for _ in range(3):
        answer = ctx.ask("      Folder that contains your server jar: ").strip().strip('"')
        error = _valid_server_dir(answer)
        if not error:
            return str(Path(answer).expanduser().resolve())
        ctx.say(f"      {error}")
    return None


def step_secrets(ctx: Context) -> Step:
    values = read_env(ctx.env_path)
    if values.get("MCSC_ADMIN_PASSWORD_HASH", "").startswith("pbkdf2_sha256$"):
        extra = ""
        if ctx.writing and not values.get("MCSC_API_TOKEN"):
            write_env_value(ctx.env_path, "MCSC_API_TOKEN", secrets.token_urlsafe(32))
            extra = "; generated an API token (stored in .env, not shown)"
        return ctx.add(Step("Dashboard password", "OK",
                            f"existing password kept (hash in {ctx.env_path}){extra}"))
    if not ctx.writing:
        return ctx.add(Step("Dashboard password", "FAIL", "no password is configured",
                            "Run setup.ps1 to choose one."))

    from agent.security.auth import hash_password
    password = None
    if not ctx.interactive:
        password = os.environ.get("MCSC_SETUP_PASSWORD") or None   # for automated installs only
        if not password:
            return ctx.add(Step("Dashboard password", "FAIL", "no password is configured",
                                "Run setup.ps1 interactively, or set MCSC_SETUP_PASSWORD for an "
                                "automated install."))
    else:
        ctx.say("      Choose a dashboard password (at least 10 characters). "
                "Nothing appears while you type - that is normal.")
        for _ in range(3):
            first = ctx.ask_secret("      Password: ")
            if len(first) < 10:
                ctx.say("      Too short: use at least 10 characters.")
                continue
            if ctx.ask_secret("      Repeat it: ") != first:
                ctx.say("      The two entries did not match.")
                continue
            password = first
            break
    if not password or len(password) < 10:
        return ctx.add(Step("Dashboard password", "FAIL", "no valid password was entered",
                            "Run setup.ps1 again."))
    username = values.get("MCSC_ADMIN_USERNAME") or "admin"
    write_env_value(ctx.env_path, "MCSC_ADMIN_USERNAME", username)
    write_env_value(ctx.env_path, "MCSC_ADMIN_PASSWORD_HASH", hash_password(password))
    if not values.get("MCSC_API_TOKEN"):
        write_env_value(ctx.env_path, "MCSC_API_TOKEN", secrets.token_urlsafe(32))
    del password
    return ctx.add(Step("Dashboard password", "OK",
                        f"stored as a hash in {ctx.env_path} (user '{username}'); the password itself "
                        "is not saved anywhere"))


def step_certificate(ctx: Context) -> Step:
    if ctx.skip_certs:
        return ctx.add(Step("Certificate", "SKIP", "skipped by request"))
    config = _load_config(ctx)
    if not config.tls_enabled:
        return ctx.add(Step("Certificate", "WARN", "HTTPS is disabled in config.yaml",
                            "Set tls.enabled: true for remote access."))
    from agent.security.tls import inspect_certificate
    info = inspect_certificate(config.tls_certificate, config.tls_private_key)
    hostname = config.dashboard_hostname
    healthy = (info.parsed and info.key_matches_certificate and info.expiry_severity == "ok"
               and (not hostname or info.covers(hostname) is not False))
    if healthy:
        return ctx.add(Step("Certificate", "OK",
                            f"existing certificate kept, {info.days_remaining:.0f} days left"))
    reason = (info.parse_error or ("private key does not match" if info.key_matches_certificate is False
              else f"expires in {info.days_remaining:.0f} days" if info.days_remaining is not None
              else "not found"))
    if hostname and info.parsed and info.covers(hostname) is False:
        reason = f"does not cover {hostname}"
    if not ctx.writing:
        return ctx.add(Step("Certificate", "FAIL", reason, "Run setup.ps1, or: python -m installer.make_certs"))
    from agent.security.certs import provision, secure_directory
    report = provision(secure_directory(config.cert_dir),
                       extra_hostnames=[hostname] if hostname else [])
    result = report["result"]
    updates = {"tls.certificate": result["cert_path"], "tls.private_key": result["key_path"],
               "tls.ca_certificate": result.get("ca_path") or ""}
    if not hostname and result.get("hostnames"):
        updates["tls.hostname"] = result["hostnames"][0]
    _edit_config(ctx, updates)
    kind = "Tailscale-issued (publicly trusted)" if result["strategy"] == "tailscale" else \
        f"local CA - trust {result['ca_path']} once on each device (see docs/https.md)"
    return ctx.add(Step("Certificate", "OK", f"created: {kind}"))


def _run_powershell(args: list[str], timeout: float = 60) -> tuple[int, str]:
    from installer.autostart import run_tool
    code, out, err = run_tool(["powershell.exe", "-NoProfile", "-NonInteractive", *args], timeout=timeout)
    return code, (out or err).strip()


def firewall_rule_scope() -> str | None:
    """The rule's remote-address scope, or None if the rule does not exist."""
    code, out = _run_powershell(["-Command",
        f"$r = Get-NetFirewallRule -DisplayName '{FIREWALL_RULE}' -ErrorAction SilentlyContinue; "
        "if ($r) { ($r | Get-NetFirewallAddressFilter).RemoteAddress -join ',' }"])
    return (out or None) if code == 0 else None


def step_firewall(ctx: Context) -> Step:
    if ctx.skip_firewall:
        return ctx.add(Step("Firewall", "SKIP", "skipped by request"))
    if not IS_WINDOWS:
        return ctx.add(Step("Firewall", "SKIP", "Windows only"))
    scope = firewall_rule_scope()
    if scope and "100.64.0.0" in scope:
        return ctx.add(Step("Firewall", "OK", "existing rule kept (Tailscale devices only)"))
    if scope:
        problem = f"a rule exists but allows {scope}, not only Tailscale"
    else:
        problem = "no rule for the dashboard port"
    if not ctx.writing:
        return ctx.add(Step("Firewall", "FAIL", problem, "Run setup.ps1 as Administrator."))
    from installer.autostart import is_admin
    if not is_admin():
        return ctx.add(Step("Firewall", "ADMIN", problem + " (needs Administrator)"))
    config = _load_config(ctx)
    code, out = _run_powershell(["-ExecutionPolicy", "Bypass", "-File",
                                 str(ctx.root / "installer" / "firewall.ps1"),
                                 "-Port", str(config.network.port),
                                 "-RedirectPort", str(config.tls.http_redirect_port)])
    if code != 0:
        return ctx.add(Step("Firewall", "FAIL", f"the rule could not be created: {out[:200]}",
                            "Run setup.ps1 as Administrator. The firewall itself is left enabled."))
    return ctx.add(Step("Firewall", "OK", "rule created: dashboard port, Tailscale devices only"))


def step_startup(ctx: Context) -> Step:
    if ctx.skip_startup:
        return ctx.add(Step("Windows startup task", "SKIP", "skipped by request"))
    if not IS_WINDOWS:
        return ctx.add(Step("Windows startup task", "SKIP", "Windows only"))
    from installer import autostart
    report = autostart.report()
    if report["verdict"] == "registered correctly":
        return ctx.add(Step("Windows startup task", "OK", "existing task kept"))
    problem = "; ".join(report["problems"]) or "not registered"
    if report.get("registered") and not report.get("points_to_current_app"):
        problem = "the task points at a different or older copy of the project: " + problem
    if not ctx.writing:
        return ctx.add(Step("Windows startup task", "FAIL", problem[:300], "Run setup.ps1 as Administrator."))
    if ctx.startup_mode == "boot" and not autostart.is_admin():
        return ctx.add(Step("Windows startup task", "ADMIN", "needs Administrator to run at boot"))
    try:
        autostart.enable(ctx.startup_mode, pin_java=False)   # java is pinned by step_config
    except autostart.AutostartError as exc:
        return ctx.add(Step("Windows startup task", "FAIL",
                            f"Could not register the Windows startup task. Reason: {exc}",
                            "Run setup.ps1 as Administrator, or use --logon to start at login."))
    return ctx.add(Step("Windows startup task", "OK", f"registered ({ctx.startup_mode} mode)"))


# ======================================================================
# driver
# ======================================================================
def pre_steps_from_env() -> list[Step]:
    """setup.ps1 checks Python, the venv and packages itself and passes the
    outcome here, so the summary covers every component."""
    steps = []
    for part in filter(None, os.environ.get("MCSC_SETUP_PRE", "").split(";")):
        name, _, status = part.partition("=")
        if name and status:
            steps.append(Step(name, status))
    return steps


def run(ctx: Context) -> int:
    startup_diag.append_event("setup.log", "setup_started" if ctx.writing else "setup_check",
                              mode=ctx.mode, admin_only=ctx.admin_only)
    ctx.steps.extend(pre_steps_from_env())
    names = {s.name for s in ctx.steps}
    if not ctx.admin_only:
        if "Python" not in names:
            step_python(ctx)
        if "Virtual environment" not in names:
            step_venv(ctx)
        if "Dependencies" not in names:
            step_dependencies(ctx)
        config_ok = step_config(ctx).status == "OK"
        step_secrets(ctx)
        if config_ok:
            step_certificate(ctx)
        else:
            ctx.add(Step("Certificate", "SKIP", "waiting for a valid configuration"))
    step_firewall(ctx)
    step_startup(ctx)

    ctx.say("")
    ctx.say("=" * 40)
    ctx.say(" Minecraft Server Controller " + ("Setup" if ctx.writing else "Health Check"))
    ctx.say("=" * 40)
    ctx.say("")
    for step in ctx.steps:
        ctx.say(step.line())
        if step.fix and step.status == "FAIL":
            ctx.say(f"       What to do: {step.fix}")
    failed = [s for s in ctx.steps if s.status == "FAIL"]
    needs_admin = [s for s in ctx.steps if s.status == "ADMIN"]
    ctx.say("")
    if failed:
        ctx.say(f"{len(failed)} item(s) need attention.")
        code = EXIT_FAILED
    elif needs_admin:
        ctx.say("Almost done: " + ", ".join(s.name for s in needs_admin) + " need Administrator rights.")
        code = EXIT_NEEDS_ADMIN
    else:
        ctx.say("Setup completed successfully." if ctx.writing else "Everything checked is working.")
        if ctx.writing:
            ctx.say("")
            ctx.say("Run:")
            ctx.say("    .\\setup.ps1 --check")
            ctx.say("")
            ctx.say("to verify the installation.")
        code = EXIT_OK
    startup_diag.append_event("setup.log", "setup_completed" if ctx.writing else "setup_check",
                              result={EXIT_OK: "ok", EXIT_FAILED: "failed",
                                      EXIT_NEEDS_ADMIN: "needs_admin"}[code],
                              steps={s.name: s.status for s in ctx.steps})
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Minecraft Server Controller setup")
    parser.add_argument("mode", choices=["setup", "check"])
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--skip-firewall", action="store_true")
    parser.add_argument("--skip-startup", action="store_true")
    parser.add_argument("--skip-certs", action="store_true")
    parser.add_argument("--logon", action="store_true", help="start with Windows at login instead of boot")
    parser.add_argument("--admin-only", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    ctx = Context(mode=args.mode, interactive=not args.non_interactive,
                  skip_firewall=args.skip_firewall, skip_startup=args.skip_startup,
                  skip_certs=args.skip_certs, startup_mode="logon" if args.logon else "boot",
                  admin_only=args.admin_only)
    try:
        return run(ctx)
    except KeyboardInterrupt:
        print("\nSetup was interrupted. Nothing half-finished was left: run it again to continue.")
        return EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
