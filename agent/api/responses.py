"""What the API answers, described for clients (the dashboard and the phone
app). FastAPI publishes these in ``/api/openapi.json``.

Every model is *open*: it lists the fields a client may rely on, with their
types, and lets through any others the route adds. So a new field never
needs a new model first, and nothing a route returned before is dropped.
A listed field is a promise: ``tests/test_api_contract.py`` compares the
schema with the copy saved at the last release and fails when a route or a
listed field disappears without having been marked deprecated first.

Routes added from Phase 7 on must declare a response model
(``tests/test_api_contract.py`` checks that too). The routes the phone app
uses come first; the rest of the older routes are listed in
``tests/api_untyped_routes.txt`` and get models as they are touched.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Open(BaseModel):
    model_config = ConfigDict(extra="allow")


# ------------------------------------------------------------ shared pieces
class Job(Open):
    id: str
    kind: str
    title: str
    server_id: str | None = None
    state: str = Field(description="running, succeeded, failed or interrupted")
    step: str | None = None
    progress: float | None = Field(None, description="0 to 1; null when it can't be measured")
    message: str | None = None
    result: dict[str, Any] | None = None
    created_at: float | None = None
    finished_at: float | None = None


class GamePort(Open):
    port: int | None = None


# ------------------------------------------------------------ servers
class ServerRow(Open):
    id: str
    name: str
    color: str | None = None
    state: str
    state_verified: bool | None = None
    uptime: float | None = None
    players_online: int | None = Field(None, description="null until it has been measured")
    players_verified: bool | None = None
    max_players: int | None = None
    minecraft_version: str | None = None
    type: str | None = None
    type_name: str | None = None
    default: bool | None = None
    edition: str | None = Field(None, description="java or bedrock")
    capabilities: dict[str, bool] | None = Field(
        None, description="What this server's type can do; false means not applicable"
    )


class ServerList(Open):
    servers: list[ServerRow]
    default: str | None = None


class ServerStatus(Open):
    """One server's state, as the Overview shows it."""

    server_id: str | None = None
    name: str | None = None
    state: str
    state_verified: bool | None = None
    uptime: float | None = None
    minecraft_version: str | None = None
    server_type: str | None = None
    server_type_name: str | None = None
    players_online: int | None = None
    players_verified: bool | None = None
    players: list[Any] = []
    max_players: int | None = None
    metrics: dict[str, Any] | None = None
    job: Job | None = None


class ServerAction(Open):
    """Start, stop and restart. ``result`` says how sure the agent is:
    REQUESTED, IN_PROGRESS or VERIFIED."""

    result: str
    detail: str | None = None
    state: str
    startup_confirmed: bool | None = None


# ------------------------------------------------------------ players, backups, alerts, jobs
class Players(Open):
    online: list[Any]
    online_count: int | None = None
    verified: bool | None = None
    max_players: int | None = None
    running: bool | None = None


class Backup(Open):
    id: int
    name: str
    kind: str | None = None
    created_at: float | None = None
    size_bytes: int | None = None
    status: str | None = None


class BackupList(Open):
    backups: list[Backup]
    directory: str | None = None


class AlertRow(Open):
    id: int
    ts: float
    channel: str
    event: str
    status: str
    detail: str | None = None


class AlertHistory(Open):
    history: list[AlertRow]


class JobList(Open):
    jobs: list[Job]


class Recommendations(Open):
    recommendations: list[dict[str, Any]]
    hidden: list[dict[str, Any]] = []


# ------------------------------------------------------------ the agent itself
class Health(Open):
    ok: bool
    auth_configured: bool | None = None
    api_version: int = Field(description="The API version; see /api/version and CHANGELOG.md")


class VersionInfo(Open):
    version: str = Field(description="The app's version, like 1.2.0")
    api_version: int = Field(description="Goes up only for a change a client must know about")


class PairingCode(Open):
    ok: bool
    address: str | None = None
    port: int | None = None
    fingerprint: str | None = Field(None, description="SHA-256 of the certificate, 64 hex digits")
    api_version: int | None = None
    url: str | None = Field(None, description="What the code holds; no password or token")
    qr: list[str] | None = Field(None, description="QR rows, 1 = dark square, no border")
    reason: str | None = None


class AppAlert(Open):
    id: int
    ts: float
    server_id: str | None = None
    event: str
    title: str
    body: str
    page: str = Field(description="The dashboard page the alert opens")
    url: str = Field(description="Its link, like /#survival/crashes")


class AppAlerts(Open):
    alerts: list[AppAlert]
    latest: int = Field(description="Ask with after=latest next time")
    enabled: bool = Field(description="Whether Web Push phone alerts are also turned on")


class Release(Open):
    version: str
    page: str | None = None
    notes: str | None = None
    published_at: str | None = None


class UpdateResult(Open):
    ok: bool | None = None
    version: str | None = None
    message: str | None = None
    rolled_back: bool | None = None


class UpdateStatus(Open):
    current: str
    latest: Release | None = None
    available: bool
    checked_at: float | None = None
    error: str | None = None
    checking: bool
    install_kind: str = Field(description="installer, or project for a setup.ps1 copy")
    can_install: bool
    cannot_install_reason: str | None = None
    last_result: UpdateResult | None = None


class UpdatePreflight(UpdateStatus):
    players_online: int | None = Field(None, description="null when it couldn't be measured")
    players: list[dict[str, Any]] = []


class UpdateStarted(Open):
    ok: bool
    job: Job


class OldCopy(Open):
    path: str
    version: str | None = None
    moved_at: str | None = None
    offer: bool
    problems: list[str] = []
    removes: list[str] = []


class OldCopyStatus(Open):
    old_copy: OldCopy | None = None


class OldCopyRemoveResult(Open):
    ok: bool
    path: str
    removed: list[str]
    kept: list[str]
    failed: list[str]
    folder_removed: bool


class Device(Open):
    id: str = Field(description="Use it to sign this device out")
    user: str
    label: str | None = None
    created_at: float | None = None
    last_used: float | None = None
    expires_at: float | None = None
    source_ip: str | None = None
    remember: bool = False
    current: bool = False


class DeviceList(Open):
    sessions: list[Device]
    remember_days: float | None = None


class Ok(Open):
    ok: bool


# ------------------------------------------------------------ Bedrock
class BedrockTerms(Open):
    """Whether Mojang's EULA and Privacy Policy were accepted (needed before
    the Bedrock server is downloaded), by whom and when."""

    accepted: bool
    user: str | None = None
    at: float | None = None
    eula_url: str
    privacy_url: str


class KeptBedrockVersion(Open):
    version: str
    sha256: str | None = None
    size: int | None = None
    downloaded_at: float | None = None


class BedrockVersions(Open):
    """The Bedrock versions this app kept. Mojang only offers the newest, so
    older ones can be installed only from these."""

    kept: list[KeptBedrockVersion]
    folder: str


class Addon(Open):
    uuid: str
    version: str
    name: str
    description: str | None = None
    kind: str = Field(description="behavior or resource")
    folder: str
    enabled: bool


class AddonList(Open):
    addons: list[Addon]
    world: str | None = Field(None, description="The world the packs are enabled in")
    running: bool
    restart_needed: bool | None = None


class AddonResult(Open):
    ok: bool
    installed: list[Addon] = []
    restart_needed: bool | None = None
