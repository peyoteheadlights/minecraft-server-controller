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


# ------------------------------------------------------------ console and chat
class ConsoleLine(Open):
    seq: int = Field(description="Counts up per line; starts at 1 again when the agent restarts")
    ts: float
    raw: str = Field(description="The line exactly as the server printed it")
    level: str = Field(description="INFO, WARN, ERROR, DEBUG, FATAL or TRACE")
    thread: str = Field(description="The thread the line names; empty when it names none")
    message: str
    source: str = Field(description="stdout, agent, or command for a command sent from here")


class ConsoleLog(Open):
    lines: list[ConsoleLine]
    buffered: int = Field(description="How many lines the agent holds now")
    buffer_limit: int = Field(description="The most lines it keeps")


class CommandCheck(Open):
    valid: bool = Field(description="Whether the command may be sent at all")
    error: str | None = Field(None, description="Why it can't be sent; null when it can")
    danger_reason: str | None = Field(
        None, description="Why it needs confirming first; null when it doesn't"
    )


class CommandSent(Open):
    result: str = Field(description="SENT: written to the console, not yet answered")
    detail: str
    command: str
    name: str = Field(description="The command's first word")
    dangerous: bool
    danger_reason: str | None = None


class ChatMessage(Open):
    seq: int = Field(description="Counts up per message; separate from the console's")
    ts: float
    kind: str = Field(description="player, server or action")
    name: str | None = Field(None, description="Who said it; null for the server")
    text: str


class ChatLog(Open):
    messages: list[ChatMessage]
    running: bool = Field(description="Whether a message can be sent now")
    kept: int = Field(description="How many messages the agent holds")


class ChatSent(Open):
    result: str = Field(description="SENT: it appears in the chat once the server prints it")
    detail: str
    message: str = Field(description="The text that was sent, trimmed")


# ------------------------------------------------------------ players, backups, alerts, jobs
class PlayerAction(Open):
    """A whitelist, op, kick, ban or unban sent to the server, and whether
    its console has confirmed it."""

    id: str
    kind: str = Field(description="whitelist_add, whitelist_remove, op, deop, kick, ban or pardon")
    name: str
    command: str
    sent_at: float
    state: str = Field(description="sent, done, unchanged, failed or no_answer")
    message: str | None = Field(None, description="The console line that answered")
    answered_at: float | None = None


class PlayerActionResult(Open):
    result: str = Field(description="SENT; the action's state says when it is confirmed")
    action: PlayerAction


class PlayerActionStatus(Open):
    action: PlayerAction


class OnlinePlayer(Open):
    username: str
    uuid: str | None = None
    session_started: float | None = None
    total_seconds: float = Field(description="Time played before this session")
    sessions: int
    first_seen: float | None = None
    last_seen: float | None = None
    edition: str | None = Field(None, description="java or bedrock; null when it can't be told")
    session_seconds: float = Field(description="0 when the session's start isn't known")


class KnownPlayer(OnlinePlayer):
    server_id: str
    online: int = Field(description="1 while the agent counts them as online")
    total_seconds_live: float = Field(description="Total time played, this session included")


class PlayerList(Open):
    players: list[dict[str, Any]] | None = Field(
        None, description="null when the file isn't there or can't be read; reason says why"
    )
    file: str | None = None
    reason: str | None = None
    not_applicable: bool | None = Field(None, description="true for a list this edition lacks")


class PlayerLists(Open):
    whitelist: PlayerList
    ops: PlayerList
    banned: PlayerList


class Players(Open):
    online: list[OnlinePlayer]
    online_count: int | None = Field(None, description="null until the list has been read")
    verified: bool | None = None
    source: str | None = Field(None, description="How the online list was learned")
    known: list[KnownPlayer] = Field(description="Everyone seen, last seen first")
    max_players: int | None = None
    lists: PlayerLists = Field(description="From Minecraft's own files")
    bans: bool = Field(description="false where the server has no ban list")
    edition: str = Field(description="java or bedrock")
    running: bool | None = None
    actions: list[PlayerAction] = Field(description="The latest sent, newest first")


# ------------------------------------------------------------ history
class EventRow(Open):
    id: int
    server_id: str = Field(description="The server, or _agent for the agent's own events")
    ts: float
    type: str
    level: str = Field(description="info, success, warn or error")
    message: str
    data: str | None = Field(None, description="JSON text, not an object; null when none")


class EventList(Open):
    events: list[EventRow] = Field(description="Newest first")


class Crash(Open):
    id: int
    server_id: str
    ts: float
    exit_code: int | None = Field(None, description="null when it isn't known")
    category: str | None = None
    confidence: str | None = Field(None, description="confirmed, likely, possible or unknown")
    summary: str | None = None
    evidence: list[str] = Field(description="The log lines the cause was read from")
    report_path: str | None = None
    log_path: str | None = None
    context: dict[str, Any] = Field(description="What was known when it crashed")
    restarted: int = Field(description="1 once it was started again after the crash")


class CrashList(Open):
    crashes: list[Crash] = Field(description="Newest first")


class CrashDetail(Crash):
    log_tail: list[str] | None = Field(
        None, description="The saved log's last lines; null when the file is gone"
    )


# ------------------------------------------------------------ the Overview's cards
class ChecklistItem(Open):
    id: str
    done: bool = Field(description="Ticked from what was measured, never from a click")
    page: str = Field(description="The dashboard page that does it")
    evidence_key: str
    evidence: dict[str, Any]


class Checklist(Open):
    items: list[ChecklistItem]
    done: int
    total: int
    show: bool
    dismissed: bool
    finished: bool


class JoinAddress(Open):
    address: str
    adapter: str
    virtual: bool = Field(description="A virtual adapter, like a VPN or a virtual machine's")


class TailscaleAddress(Open):
    address: str | None = None
    dns_name: str | None = None
    connected: bool | None = Field(None, description="null when it couldn't be read")
    verified: bool
    source: str | None = None
    detail: str | None = None


class JavaJoin(Open):
    port: int
    port_source: str = Field(description="Where the port number was read, in words")
    default_port: bool
    local: list[JoinAddress]
    tailscale: TailscaleAddress


class BedrockJoin(Open):
    port: int | None = Field(None, description="null when it isn't set up yet")
    port_source: str | None = None
    protocol: str
    default_port: bool | None = None
    ready: bool | None = None
    address: str | None = Field(None, description="The Tailscale address; null when unknown")
    local: list[JoinAddress]
    tailscale: TailscaleAddress | None = None
    consoles_note: bool | None = None
    own_server: bool | None = Field(None, description="true for a Bedrock server of its own")


class InternetReach(Open):
    known: bool = Field(description="Always false: reaching it from the internet isn't tested")
    reason: str | None = None


class JoinInfo(Open):
    java: JavaJoin | None = Field(None, description="null for a Bedrock server")
    bedrock: BedrockJoin | None = Field(None, description="null when Bedrock players can't join")
    internet: InternetReach
    running: bool


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
class LoginResult(Open):
    token: str = Field(description="Send as 'Authorization: Bearer <token>'")
    user: str
    expires_at: float
    role: str = Field(description="owner or helper")
    remember: bool


class Me(Open):
    user: str
    kind: str
    expires_at: float | None = None
    role: str = Field(description="owner or helper")
    servers: list[str] | None = Field(None, description="A helper's servers; null for the owner")
    permissions: list[str]
    preferences: dict[str, Any]


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
    more: bool = Field(False, description="More alerts are waiting after latest")
    enabled: bool = Field(description="Whether Web Push phone alerts are also turned on")


class AppPhone(Open):
    configured: bool = Field(description="Whether this PC has a Firebase key to send with")
    registered: bool = Field(description="Whether this sign-in has a push address")
    phone: dict[str, Any] | None = None


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
