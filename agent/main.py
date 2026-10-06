"""Agent entry point.

    python -m agent.main            serve (HTTPS by default)
    python -m agent.main --check    full diagnostic report, no serving
    python -m agent.main --check --deep   also performs a real TLS handshake

HTTPS is the production interface. The agent binds to one address - normally
this machine's Tailscale address - and is never intended to be reachable from
the public internet.

Path handling: every path the agent uses is resolved to an absolute path from
the project root or from the configured data directory. Nothing depends on the
current working directory, because a Windows Service starts with a different
one (usually C:\\Windows\\system32).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import mimetypes
import socket
import ssl
import sys
import threading
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, startup_diag
from .api.errors import register_error_handlers
from .api.routes import router
from .api.ws import ws_router
from .config import Config
from .core import AgentCore
from .datafolder import MoveResult, apply_at_startup, use_data_in_use
from .diagnostics import run_diagnostics
from .events import Event
from .logging_setup import setup_logging
from .security.tls import inspect_certificate

log = logging.getLogger("msc.main")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = Path(__file__).resolve().parent / "web"

LOOPBACK = {"127.0.0.1", "localhost", "::1", "0:0:0:0:0:0:0:1"}


def lock_down_data_folder(config: Config, startup_diag) -> None:
    """The fixed app-data folder holds the database (sign-in sessions) and
    the HTTPS private key. A folder made inside ProgramData lets every
    account on the PC read it, so make it private to the agent's account,
    SYSTEM and Administrators, and record what its access really is. A data
    folder set in config.yaml is the owner's choice and is left alone."""
    from .config import default_data_root
    from .security.certs import folder_access, secure_directory

    if config.data_dir_configured or config.data_dir != default_data_root():
        return
    if folder_access(config.data_dir)[0] != "private":
        secure_directory(config.data_dir)
    status, detail = folder_access(config.data_dir)
    startup_diag.record("data_folder_access", ok=status == "private", detail=detail, status=status)
    if status != "private":
        log.warning("data folder %s is not private: %s", config.data_dir, detail)


class TLSConfigError(RuntimeError):
    """Raised when HTTPS is requested but cannot be served honestly."""


def resolve_tls(config: Config) -> tuple[str, str] | None:
    """Verify the certificate and key before uvicorn is handed them.

    Failing here with a clear message is far better than a TLS handshake that
    breaks in a browser with no explanation.
    """
    if not config.tls_enabled:
        return None
    cert = config.tls_certificate
    key = config.tls_private_key
    if not cert or not key:
        raise TLSConfigError(
            "tls.enabled is true but tls.certificate or tls.private_key is empty. "
            "Run: python -m installer.make_certs"
        )
    info = inspect_certificate(cert, key)
    if info.certificate_present is False:
        raise TLSConfigError(
            f"TLS certificate not found: {cert}\nRun: python -m installer.make_certs"
        )
    if info.key_present is False:
        raise TLSConfigError(
            f"TLS private key not found: {key}\nRun: python -m installer.make_certs"
        )
    if not info.parsed:
        raise TLSConfigError(f"The TLS certificate could not be parsed: {info.parse_error}")
    if info.key_matches_certificate is False:
        raise TLSConfigError(
            "The TLS private key does not match the certificate. "
            "Re-issue both together: python -m installer.make_certs --renew"
        )
    if info.expired:
        raise TLSConfigError(
            "The TLS certificate is outside its validity window. "
            "Renew it: python -m installer.make_certs --renew"
        )
    return str(cert), str(key)


def create_app(config: Config, data_move: MoveResult | None = None) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        startup_diag.record("controller_initializing")
        try:
            core = AgentCore(config)
            app.state.core = core
            await core.start()
            if data_move is not None:
                # Shown in the dashboard's history, so the move (or why it
                # did not happen) is visible without reading log files.
                await core.bus.publish(
                    Event(
                        type="data_folder_moved" if data_move.ok else "data_folder_not_moved",
                        level="success" if data_move.ok else "warn",
                        message=data_move.message,
                        data=data_move.to_dict(),
                    )
                )
        except Exception as exc:
            startup_diag.record_exception("controller_initialization", exc)
            raise
        startup_diag.record(
            "controller_initialized",
            ok=True,
            detail=", ".join(
                f"{sid}: state={ctx.server.state.value}, java={ctx.server.java_version or 'unknown'}"
                for sid, ctx in core.servers.items()
            ),
            url=config.base_url,
        )
        log.info("agent ready on %s", config.base_url)
        try:
            yield
        finally:
            await core.stop()
            log.info("agent stopped")
            # Close the startup record here, inside the server's own graceful
            # shutdown. uvicorn re-raises the stop signal after this hook, which
            # ends the process before main() regains control, so this is the
            # last reliable point to record how the run ended.
            startup_diag.record("controller_stopped")
            startup_diag.finish("stopped", detail="graceful shutdown")

    app = FastAPI(
        title="Minecraft Server Control",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.config = config

    # CORS stays off: the dashboard is served by this same process, so every
    # request is same-origin. If you ever host the UI elsewhere, list its exact
    # origin - never "*", which would be an open door on authenticated routes.
    origins = [str(o) for o in config.network.allowed_origins]
    if origins:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,  # bearer tokens, never cookies
            allow_methods=["GET", "POST", "PUT", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
        )

    hsts_enabled = config.tls.hsts and config.tls_enabled
    hsts_value = f"max-age={config.tls.hsts_max_age}"
    if config.tls.hsts_include_subdomains:
        hsts_value += "; includeSubDomains"

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            # Added for the phone app: the service worker and the web app
            # manifest, both this app's own files. Nothing else was widened.
            "worker-src 'self'; "
            "manifest-src 'self'; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'; "
            "object-src 'none'"
        )
        # HSTS is only meaningful, and only safe, over a real HTTPS connection.
        # It is never sent on loopback, so http://127.0.0.1 development is not
        # poisoned into being permanently HTTPS-only in the browser.
        if hsts_enabled and request.url.scheme == "https" and request.url.hostname not in LOOPBACK:
            response.headers["Strict-Transport-Security"] = hsts_value
        return response

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):  # pragma: no cover
        # The stack trace goes to the log file, never to the browser.
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "detail": "The agent hit an unexpected error. "
                "Check mcsc-data/logs/agent-errors.log."
            },
        )

    register_error_handlers(app)
    app.include_router(router)
    app.include_router(ws_router)

    if WEB_DIR.is_dir():
        # Browsers refuse module scripts served as text/plain, which some
        # Windows registries map .js to.
        mimetypes.add_type("text/javascript", ".js")
        app.mount("/assets", StaticFiles(directory=WEB_DIR), name="assets")

        @app.get("/", include_in_schema=False)
        async def index():
            return FileResponse(WEB_DIR / "index.html")

        # Both are served from the site root on purpose: a service worker
        # only covers the folder it is served from, and the manifest's
        # start_url has to be the dashboard itself.
        @app.get("/sw.js", include_in_schema=False)
        async def service_worker():
            return FileResponse(
                WEB_DIR / "sw.js",
                media_type="text/javascript",
                headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
            )

        @app.get("/manifest.webmanifest", include_in_schema=False)
        async def web_manifest():
            return FileResponse(
                WEB_DIR / "manifest.webmanifest", media_type="application/manifest+json"
            )

        @app.get("/favicon.ico", include_in_schema=False)
        async def favicon():
            return JSONResponse(status_code=404, content={"detail": "no favicon"})

    return app


def create_redirect_app(https_port: int) -> FastAPI:
    """A listener that does nothing but send browsers to HTTPS.

    It serves no API, no static files and no session. Anything that is not a
    GET or HEAD gets 400 rather than a redirect, because silently redirecting a
    POST would invite a client to resend credentials over plain HTTP.
    """
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def to_https(request: Request, path: str = ""):
        host = request.url.hostname or "localhost"
        target = request.url.replace(scheme="https", netloc=f"{host}:{https_port}")
        return RedirectResponse(str(target), status_code=308)

    @app.api_route(
        "/{path:path}",
        methods=["POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        include_in_schema=False,
    )
    async def refuse(request: Request, path: str = ""):
        return JSONResponse(
            status_code=400,
            content={
                "detail": "This agent only accepts API requests over HTTPS. "
                f"Use https://<host>:{https_port}{request.url.path}"
            },
        )

    return app


def _run_redirect_listener(host: str, http_port: int, https_port: int) -> threading.Thread:
    def serve():
        try:
            config = uvicorn.Config(
                create_redirect_app(https_port),
                host=host,
                port=http_port,
                log_level="warning",
                access_log=False,
            )
            asyncio.run(uvicorn.Server(config).serve())
        except OSError as exc:
            log.warning(
                "HTTP redirect listener could not start on %s:%s (%s). HTTPS is unaffected.",
                host,
                http_port,
                exc,
            )
        except Exception:  # pragma: no cover
            log.exception("HTTP redirect listener stopped")

    thread = threading.Thread(target=serve, name="http-redirect", daemon=True)
    thread.start()
    return thread


def wait_for_bind_address(host: str, timeout: float, interval: float = 3.0) -> bool:
    """Wait until `host` is an address this machine can bind to.

    At boot the Tailscale adapter can take several seconds - sometimes a
    minute - to receive its 100.x address. Binding before then fails with
    WinError 10049, uvicorn exits, and a clean exit is not treated as a failure
    by Windows, so nothing restarts it. Waiting here removes that race.

    Loopback and wildcard addresses are always available and return at once.
    """
    if host in LOOPBACK or host in ("0.0.0.0", "::", ""):
        return True
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    deadline = time.monotonic() + max(timeout, 0)
    attempt = 0
    while True:
        attempt += 1
        try:
            with socket.socket(family, socket.SOCK_STREAM) as probe:
                probe.bind((host, 0))  # port 0: tests the address, not our port
            if attempt > 1:
                startup_diag.record("bind_address_available", host=host, attempts=attempt)
            return True
        except OSError as exc:
            if attempt == 1 or attempt % 5 == 0:
                startup_diag.record(
                    "bind_address_waiting",
                    host=host,
                    attempt=attempt,
                    error=f"{type(exc).__name__}: {exc}",
                )
            if time.monotonic() >= deadline:
                startup_diag.record(
                    "bind_address_gave_up",
                    host=host,
                    attempts=attempt,
                    error=f"{type(exc).__name__}: {exc}",
                )
                return False
            time.sleep(interval)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Minecraft Server Control agent")
    parser.add_argument("--config", help="Path to config.yaml (absolute path recommended)")
    parser.add_argument("--env", help="Path to the .env file holding secrets")
    parser.add_argument("--host", help="Override the bind address")
    parser.add_argument("--port", type=int, help="Override the bind port")
    parser.add_argument(
        "--check", action="store_true", help="Run diagnostics and exit without serving"
    )
    parser.add_argument(
        "--deep",
        action="store_true",
        help="With --check: also perform a real TLS handshake against a running agent",
    )
    parser.add_argument("--json", action="store_true", help="With --check: emit JSON")
    parser.add_argument(
        "--no-tls",
        action="store_true",
        help="Serve plain HTTP. Only permitted on a loopback address.",
    )
    parser.add_argument(
        "--launched-by",
        default="manual",
        help="Recorded in logs/startup.log. The Windows startup task passes 'task'.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Every stage is written to logs/startup.log, because when
    Windows starts the agent there is nobody watching a console."""
    raw_argv = list(sys.argv if argv is None else ["agent.main", *argv])
    startup_diag.attach_streams_if_missing()
    startup_diag.install_excepthook()
    launched_by = "manual"
    for index, value in enumerate(raw_argv):
        if value == "--launched-by" and index + 1 < len(raw_argv):
            launched_by = raw_argv[index + 1]
        elif value.startswith("--launched-by="):
            launched_by = value.split("=", 1)[1]
    is_check = "--check" in raw_argv
    if not is_check:
        startup_diag.begin(raw_argv, launched_by)
    try:
        code = _main(argv)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        if not is_check:
            startup_diag.finish("exited", exit_code=code)
        raise
    except BaseException as exc:
        if not is_check:
            startup_diag.record_exception("main", exc)
            startup_diag.finish("crashed", error=f"{type(exc).__name__}: {exc}")
        raise
    if not is_check:
        startup_diag.finish("stopped" if code == 0 else "failed", exit_code=code)
    return code


def _main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = Config.load(args.config, args.env)
    except Exception as exc:
        startup_diag.record_exception("config_load", exc)
        print(f"\nConfiguration could not be loaded: {exc}\n", file=sys.stderr)
        return 2
    if not args.check:
        startup_diag.record(
            "config_loaded",
            source=str(config.source),
            server_directory=str(config.server_dir),
            server_directory_exists=config.server_dir.is_dir(),
            data_directory=str(config.data_dir),
            java=config.server.java,
            host=config.network.host,
            port=config.network.port,
            tls=config.tls_enabled,
            password_configured=bool(config.admin_password_hash),
        )
    if args.host:
        config.set("network.host", args.host)
    if args.port:
        config.set("network.port", args.port)
    if args.no_tls:
        config.set("tls.enabled", False)

    data_move = None
    data_plan = None
    if args.check:
        # Read-only: report on the folder actually in use, create nothing in
        # the new one before the agent has copied the old one there.
        data_plan = use_data_in_use(config)
    else:
        # Before anything creates folders in the new data folder or reads the
        # certificate: an old <server>/mcsc-data is copied there once.
        data_move = apply_at_startup(config)
        if data_move is not None:
            startup_diag.record(
                "data_folder_moved" if data_move.ok else "data_folder_not_moved",
                ok=data_move.ok,
                detail=data_move.message,
                source=str(data_move.source),
                target=str(data_move.target),
                warnings=data_move.warnings,
            )
        lock_down_data_folder(config, startup_diag)
    config.ensure_dirs()

    host = config.network.host
    port = config.network.port

    if args.check:
        report = run_diagnostics(config, deep=args.deep, data_plan=data_plan)
        if args.json:
            import json

            print(json.dumps(report.to_dict(), indent=2))
        else:
            print(report.render())
        return 0 if not report.failures else 1

    setup_logging(config.log_dir, level=config.logging.level)
    if data_move is not None:
        (log.info if data_move.ok else log.warning)("%s", data_move.message)
        for warning in data_move.warnings:
            log.warning("%s", warning)

    if not config.admin_password_hash and not config.api_token:
        log.error(
            "No MCSC_ADMIN_PASSWORD_HASH or MCSC_API_TOKEN is set. Every API call will be "
            "refused. Run: python -m installer.make_secrets"
        )

    ssl_files = None
    if config.tls_enabled:
        try:
            ssl_files = resolve_tls(config)
        except TLSConfigError as exc:
            log.error("HTTPS cannot start: %s", exc)
            startup_diag.record("tls_failed", error=str(exc))
            print(f"\nHTTPS cannot start:\n{exc}\n", file=sys.stderr)
            return 2
        if ssl_files:
            startup_diag.record("tls_ready", certificate=ssl_files[0])
    else:
        if host not in LOOPBACK:
            log.error(
                "Refusing to serve plain HTTP on %s. Credentials would cross the network "
                "unencrypted. Enable tls.enabled, or bind to 127.0.0.1.",
                host,
            )
            print(
                f"\nRefusing to serve plain HTTP on {host}.\n"
                "HTTP is only allowed on 127.0.0.1. Enable TLS in config.yaml "
                "(tls.enabled: true) and run: python -m installer.make_certs\n",
                file=sys.stderr,
            )
            return 2
        log.warning("TLS is disabled. Serving plain HTTP on %s:%s (loopback only).", host, port)

    if host in ("0.0.0.0", "::"):
        log.warning(
            "Binding to %s exposes the dashboard on every interface, including your LAN. "
            "Prefer this machine's Tailscale address.",
            host,
        )

    bind_wait = config.network.bind_wait_seconds
    if not wait_for_bind_address(host, bind_wait):
        log.error(
            "The address %s never became available (waited %.0fs). Is Tailscale running?",
            host,
            bind_wait,
        )
        print(
            f"\nCannot bind to {host}: the address did not become available within "
            f"{bind_wait:.0f}s. If this is a Tailscale address, check Tailscale is running.\n",
            file=sys.stderr,
        )
        return 3

    if ssl_files and config.tls.http_redirect:
        _run_redirect_listener(host, config.tls.http_redirect_port, port)

    app = create_app(config, data_move=data_move)
    startup_diag.record("server_binding", host=host, port=port, tls=bool(ssl_files))
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=False,
        ws_ping_interval=20,
        ws_ping_timeout=20,
        ssl_certfile=ssl_files[0] if ssl_files else None,
        ssl_keyfile=ssl_files[1] if ssl_files else None,
        # TLS 1.2 is the floor; anything older is long broken.
        ssl_version=ssl.PROTOCOL_TLS_SERVER,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
