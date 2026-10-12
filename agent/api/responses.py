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


class BackupCopy(Open):
    """A backup's second copy off the PC, as found on the drive just now."""

    state: str = Field(description="ok, failed, unreachable, missing or none")
    reason: str | None = None
    path: str | None = None
    checked_at: float | None = None


class Backup(Open):
    id: int
    name: str
    kind: str | None = Field(None, description="manual, scheduled or safety")
    created_at: float | None = None
    size_bytes: int | None = None
    status: str | None = Field(None, description="ok (checked), unverified or failed")
    note: str | None = None
    includes: str | None = Field(None, description="Its top-level folders, comma-separated")
    exists: bool | None = Field(None, description="Whether its file is still on disk")
    copy_: BackupCopy | None = Field(None, alias="copy")


class Retention(Open):
    daily: int
    weekly: int
    monthly: int


class BackupList(Open):
    backups: list[Backup] = Field(description="Newest first")
    directory: str | None = None
    retention: Retention | None = None


class BackupMade(Open):
    ok: bool
    id: int | None = None
    name: str
    size_bytes: int | None = None
    verified: bool | None = None
    verification: dict[str, Any] | None = None
    job_id: str | None = None


class BackupCheck(Open):
    """Opening the archive and checking it now. ``reason`` says why it failed."""

    ok: bool
    reason: str | None = None
    entries: int | None = None
    size_bytes: int | None = None
    checks: list[str] = []


class SafetyBackup(Open):
    id: int | None = None
    name: str


class Undo(Open):
    kind: str
    backup_id: int
    backup: str


class Restored(Open):
    """A restore asked without ``confirm`` answers ``confirmation_required``
    and ``will_happen``; a confirmed one answers what was put back."""

    ok: bool | None = None
    confirmation_required: bool | None = None
    will_happen: list[str] | None = None
    backup: dict[str, Any] | None = None
    restored: str | None = None
    safety_backup: SafetyBackup | None = Field(
        None, description="The backup made just before; null when none was"
    )
    undo: Undo | None = None
    verified: bool | None = None
    job_id: str | None = None


class BackupDeleted(Open):
    ok: bool
    deleted: str


class Offsite(Open):
    directory: str = Field(description="Where second copies go; empty when they're off")
    unavailable: str | None = Field(None, description="Why that folder can't be reached now")
    subfolder: str | None = None


class OffsiteSaved(Open):
    ok: bool
    directory: str


class BackupCopied(Open):
    ok: bool
    copy_: BackupCopy = Field(alias="copy")


class World(Open):
    key: str
    label: str
    exists: bool
    size_bytes: int | None = None
    modified: float | None = None
    last_backup: dict[str, Any] | None = Field(None, description="name and created_at")


class WorldList(Open):
    worlds: list[World]


class Requested(Open):
    """Written to the server console; Minecraft gives no answer to check."""

    result: str = Field(description="REQUESTED")
    detail: str


class WorldPoint(Open):
    backup_id: int
    name: str
    created_at: float
    age_seconds: float
    size_bytes: int | None = None
    kind: str | None = None
    note: str | None = None
    checked: bool = Field(description="Only a checked backup is offered")
    status: str | None = None
    played_seconds: float | None = Field(
        None, description="Time with players online since; null when sessions weren't recorded"
    )


class WorldTimeline(Open):
    points: list[WorldPoint] = Field(description="Newest first")
    server_running: bool
    can_restore: bool
    blocked_by: str | None = Field(None, description="The task holding the server, if any")
    sessions_recorded: bool


# ------------------------------------------------------------ schedules
class Schedule(Open):
    id: int
    name: str
    task: str
    kind: str = Field(description="daily, weekly or interval")
    expr: str
    payload: dict[str, Any] = {}
    enabled: bool
    last_run: float | None = None
    next_run: float | None = None
    last_result: str | None = None


class ScheduleList(Open):
    schedules: list[Schedule]
    tasks: list[str] = Field(description="What a schedule can run")


class ScheduleSaved(Open):
    ok: bool
    schedule: Schedule


class ScheduleRan(Open):
    ok: bool
    result: str = Field(description="What the task said, in its own words")


# ------------------------------------------------------------ performance
class Snapshot(Open):
    """The values now. Each is null when it couldn't be measured."""

    ts: float
    cpu_percent: float | None = None
    process_cpu_percent: float | None = None
    ram_used_mb: float | None = None
    ram_total_mb: float | None = None
    ram_percent: float | None = None
    proc_ram_mb: float | None = Field(None, description="null while the server isn't running")
    disk_free_gb: float | None = None
    disk_unknown_reason: str | None = None
    net_sent_mb_s: float | None = None
    net_recv_mb_s: float | None = None
    tps: float | None = None
    mspt: float | None = None


class SeriesPoint(Open):
    """One time bucket's averages. A value nobody measured is null: a gap."""

    ts: float
    cpu_percent: float | None = None
    ram_used_mb: float | None = None
    ram_total_mb: float | None = None
    proc_ram_mb: float | None = None
    tps: float | None = None
    mspt: float | None = None
    players: float | None = None
    players_max: float | None = None


class Series(Open):
    points: list[SeriesPoint] = Field(description="Oldest first; empty buckets left out")
    hours: float
    bucket_seconds: float


class Storage(Open):
    worlds_gb: float
    backups_gb: float
    mods_gb: float
    logs_gb: float
    other_gb: float
    free_gb: float | None = None
    free_unknown_reason: str | None = None


class Performance(Open):
    current: Snapshot
    series: Series
    sample_interval: float
    memory_limit_mb: int | None = Field(None, description="The -Xmx setting; null when none")
    storage: Storage | None = Field(None, description="null when asked with storage=false")


class HealthCheck(Open):
    name: str
    status: str = Field(description="ok, warn or unknown (never counted as passing)")
    value: Any = None
    threshold: Any = None
    detail: str | None = None
    source: str | None = None


class ServerHealth(Open):
    overall: str = Field(description="ALL CHECKS VERIFIED, PARTIALLY VERIFIED or ATTENTION NEEDED")
    note: str = ""
    checks: list[HealthCheck]
    generated_at: float


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


class Change(Open):
    id: int
    title: str
    user: str | None = None
    made_at: float
    undone_at: float | None = Field(None, description="Set on the redo stack")
    scope: list[str] | None = Field(
        None, description="What Undo or Redo puts back; null for everything the backup holds"
    )
    backup_id: int
    backup: str
    backup_at: float = Field(description="When the backup that would be put back was made")
    played_seconds: float | None = Field(
        None,
        description="How long people played since that backup; null when no sessions were recorded",
    )


class Changes(Open):
    undo: list[Change] = Field(description="Newest first: Undo reverses the first one")
    redo: list[Change] = Field(description="Undone last first: Redo puts back the first one")
    server_running: bool
    blocked_by: str | None = None


class ChangeMoved(Open):
    ok: bool
    change: Change
    restored: str
    safety_backup: SafetyBackup | None = None
    job_id: str | None = None


class JobUndone(Open):
    ok: bool
    restored: str
    safety_backup: SafetyBackup | None = None
    undo: Undo | None = None
    job_id: str | None = None


class Recommendations(Open):
    recommendations: list[dict[str, Any]]
    hidden: list[dict[str, Any]] = []


# ------------------------------------------------------------ the agent itself
class LoginResult(Open):
    token: str = Field(description="Send as 'Authorization: Bearer <token>'")
    user: str
    expires_at: float | None = Field(
        description="null for a phone's sign-in: it lasts until signed out"
    )
    role: str = Field(description="owner or helper")
    remember: bool


class Me(Open):
    user: str
    kind: str
    expires_at: float | None = None
    role: str = Field(description="owner or helper (a moderator)")
    servers: list[str] | None = Field(
        None, description="A moderator's servers; null for every server"
    )
    permissions: list[str] = Field(
        description="Every permission held on at least one server, plus the account's own; "
        "the list apps released before per-server permissions read"
    )
    account_permissions: list[str] = Field(
        description="Permissions that don't belong to one server"
    )
    server_permissions: dict[str, list[str]] = Field(
        description="What this account may do on each server it can see, by server id"
    )
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


# ------------------------------------------------------------ moderators
class Described(Open):
    permissions: list[str]
    level: str = Field(description="start_and_stop, look_after_it, run_it, custom or none")


class ServerAccess(Described):
    id: str
    name: str


class OpenInvite(Open):
    created_at: float
    expires_at: float


class Moderator(Open):
    username: str
    role: str
    servers: list[str] | None = Field(None, description="null: every server, now and later")
    all_servers: bool
    new_server: Described = Field(description="What a new server gives an all-servers moderator")
    access: list[ServerAccess] = Field(description="What they may do on each server")
    invite_waiting: bool = Field(description="True until they choose a password with an invite")
    invite: OpenInvite | None = None
    created_at: float
    active_sessions: int
    last_used: float | None = None
    last_sign_in: float | None = None


class PermissionLevel(Open):
    id: str
    permissions: list[str]


class PermissionGroup(Open):
    id: str
    permissions: list[str]


class PermissionCatalogue(Open):
    levels: list[PermissionLevel] = Field(description="Smallest first")
    default_level: str
    groups: list[PermissionGroup] = Field(description="The switches, as the apps group them")
    technical: list[str] = Field(description="Switches shown only in Technical mode")
    warn: list[str] = Field(description="Switches that let someone do anything in the game")
    needs: dict[str, list[str]] = Field(description="A switch brings these along")


class ServerName(Open):
    id: str
    name: str


class ModeratorList(Open):
    owner: str
    helpers: list[Moderator]
    permissions: PermissionCatalogue
    servers: list[ServerName]


class InviteCode(Open):
    ok: bool = Field(description="False when the PC has no pairing code; reason says why")
    username: str
    expires_at: float
    url: str | None = Field(None, description="The pairing link with the one-time invite")
    qr: list[str] | None = Field(None, description="QR rows, 1 = dark square, no border")
    reason: str | None = None


class ModeratorAdded(Open):
    ok: bool
    username: str
    invite: InviteCode | None = Field(None, description="Present when no password was given")


class ModeratorChanged(Open):
    ok: bool
    username: str


class ModeratorRemoved(Open):
    ok: bool
    removed: str


class InviteCheck(Open):
    username: str
    expires_at: float


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


# ------------------------------------------------------------ mods and plugins
class ModIssue(Open):
    kind: str
    severity: str = Field(description="error, warn or info")
    detail: str


class ModUpdate(Open):
    """A newer version found on Modrinth at the last check."""

    mod_id: str
    latest_version: str
    version_id: str
    installed_version: str | None = None


class Mod(Open):
    filename: str
    mod_id: str
    name: str
    version: str
    enabled: bool
    description: str | None = None
    size_bytes: int | None = None
    minecraft_range: str | None = None
    loader: str | None = None
    environment: str | None = None
    status: str | None = Field(None, description="ok, warn, error or disabled")
    issues: list[ModIssue] = []
    has_history: bool | None = None
    update_available: ModUpdate | None = None


class ModProblem(ModIssue):
    mod: str | None = None
    filename: str | None = None


class ModList(Open):
    mods: list[Mod]
    problems: list[ModProblem] = []
    minecraft_version: str | None = Field(
        None, description="null until the server has started once"
    )
    server_state: str
    updates_checked_at: float | None = None


class ModChanged(Open):
    """Turning a mod or plugin on or off."""

    ok: bool
    mod: Mod
    changed: bool | None = None


class ModDependent(Open):
    name: str
    mod_id: str
    filename: str
    requires: str | None = None


class ModImpact(Open):
    """What else needs a mod, before it is removed."""

    dependents: list[ModDependent]
    warning: str | None = None


class ModRemoved(Open):
    ok: bool
    removed: dict[str, Any]
    trash: str | None = Field(None, description="Where the file was kept")


class ModUpdated(Open):
    ok: bool
    updated: dict[str, Any]
    previous_version: str | None = None


class ModVersion(Open):
    """A copy of a mod kept on this server, which it can roll back to."""

    version: str | None = None
    filename: str
    archive_path: str
    created_at: float
    is_current: bool
    exists: bool = Field(description="False when the kept file has gone")


class ModVersions(Open):
    versions: list[ModVersion]


class ModRolledBack(Open):
    ok: bool
    restored: dict[str, Any]
    previous_version: str | None = None


class ModHistoryRow(Open):
    ts: float
    user: str | None = None
    action: str
    mod_id: str | None = None
    mod_name: str | None = None
    old_version: str | None = None
    new_version: str | None = None
    result: str = Field(description="ok or failed")
    detail: str | None = None


class ModHistory(Open):
    history: list[ModHistoryRow] = Field(description="Newest first")


class ModrinthHit(Open):
    project_id: str | None = None
    slug: str | None = None
    title: str | None = None
    description: str | None = None
    downloads: int | None = None
    icon_url: str | None = Field(None, description="Loaded by the client straight from Modrinth")
    page: str | None = None
    server_side: str | None = None
    client_side: str | None = None


class ModSearch(Open):
    hits: list[ModrinthHit]
    total: int | None = None


class ModrinthFile(Open):
    filename: str | None = None
    size: int | None = None


class ModrinthDependency(Open):
    project_id: str | None = None
    type: str | None = Field(None, description="required, optional, incompatible or embedded")


class ModrinthVersion(Open):
    version_id: str | None = None
    version_number: str | None = None
    release_type: str | None = None
    game_versions: list[str] = []
    dependencies: list[ModrinthDependency] = []
    file: ModrinthFile | None = None


class ModrinthProject(Open):
    project_id: str | None = None
    slug: str | None = None
    title: str | None = None
    description: str | None = None
    license: str | None = None
    server_side: str | None = None
    client_side: str | None = None
    icon_url: str | None = None
    page: str | None = None


class ModProject(Open):
    """A Modrinth project and its versions that fit this server."""

    project: ModrinthProject
    versions: list[ModrinthVersion]
    installed: dict[str, Any] | None = None


class DependencyNeeded(Open):
    mod_id: str
    title: str | None = None
    installed: bool = False


class ModInstalled(Open):
    ok: bool
    installed: dict[str, Any]
    dependencies_required: list[DependencyNeeded] = []
    dependencies_installed: list[dict[str, Any]] = []


class DependencyItem(Open):
    mod_id: str
    name: str
    kind: str = Field(description="required or optional")
    platform: bool = Field(description="Minecraft, the loader or Java rather than a mod")
    status: str | None = None
    range_text: str | None = None
    reason: str | None = None
    modrinth: dict[str, Any] | None = Field(None, description="Its Modrinth page, when found")


class DependencyReport(Open):
    items: list[DependencyItem]
    missing_required: list[str] = []
    lookup_error: str | None = None


class PlannedDependency(Open):
    mod_id: str
    title: str | None = None
    version_number: str | None = None
    size: int | None = None
    page: str | None = None


class UnresolvableDependency(Open):
    mod_id: str
    name: str | None = None
    reason: str
    page: str | None = Field(None, description="A page to get it by hand, when known")


class DependencyPlan(Open):
    """What installing the missing ones would download. Nothing is yet."""

    items: list[PlannedDependency]
    unresolvable: list[UnresolvableDependency] = []


class DependencyResult(Open):
    title: str
    result: str = Field(description="installed, skipped or failed")
    detail: str | None = None
    version: str | None = None


class DependencyInstall(Open):
    results: list[DependencyResult]
    still_missing: list[dict[str, Any]] = []


class ModUploaded(Open):
    ok: bool
    installed: dict[str, Any]


class UpdateAllRow(Open):
    mod_id: str
    name: str
    filename: str
    enabled: bool = Field(description="Turned-off ones are listed but not ticked first")
    installed_version: str
    latest_version: str
    version_id: str


class UpdateAllUnchecked(Open):
    mod_id: str
    name: str
    filename: str
    reason: str


class UpdateAllPlan(Open):
    """What Update all would change, checked on Modrinth just now."""

    updates: list[UpdateAllRow]
    unchecked: list[UpdateAllUnchecked] = Field(
        description="Ones Modrinth couldn't be asked about, with the reason"
    )
    server_running: bool
    blocked_by: str | None = Field(None, description="The task holding the server, if any")
    checked_at: float


class UpdateAllDone(Open):
    mod_id: str
    name: str
    filename: str
    previous_version: str
    version: str


class UpdateAllResult(Open):
    ok: bool
    job_id: str
    updated: list[UpdateAllDone]
    safety_backup: SafetyBackup | None = Field(None, description="The one backup made first")
    undo: Undo | None = None


# ------------------------------------------------------------ modpacks
class ModpackFile(Open):
    name: str
    path: str | None = None
    size: int | None = None
    status: str = Field(description="download, client_only or refused")
    reason: str | None = None


class Modpack(Open):
    name: str
    version: str | None = None
    summary: str | None = None
    minecraft_version: str | None = None
    type: str | None = None
    type_name: str | None = None
    loader_version: str | None = None
    files: list[ModpackFile] = []
    download_count: int = 0
    download_bytes: int = 0
    client_only: list[str] = []
    skipped_overrides: list[str] = []
    problems: list[str] = []
    can_import: bool


class ModpackInto(Open):
    version_change: bool
    running: bool | None = None


class ModpackInspected(Open):
    token: str
    pack: Modpack
    into: ModpackInto | None = Field(None, description="What importing into server_id would do")


class ModpackImported(Open):
    ok: bool
    job_id: str | None = None
    modpack: dict[str, Any]
    version_change: bool | None = None
    undo: Undo | None = None


# ------------------------------------------------------------ game settings
class GameSetting(Open):
    key: str
    kind: str = Field(description="choice, bool, int, text, port or seed")
    value: Any = Field(None, description="What the file says, typed; null when unset or unreadable")
    set: bool
    problem: str | None = Field(None, description="Why the file's value couldn't be read")
    raw: str | None = Field(None, description="The file's own text for it; null when unset")
    minecraft_default: str
    choices: list[str] = []
    min: int | None = None
    max: int | None = None
    max_length: int | None = None
    read_only: str | None = Field(
        None, description='"world_exists" for the seed once there is a world'
    )


class GameSettings(Open):
    file: str
    exists: bool
    world_exists: bool
    fields: list[GameSetting]
    running: bool
    restart_needed: bool


class GameSettingsSaved(Open):
    ok: bool
    changed: dict[str, Any] = {}
    keys: list[str] = []
    nothing_changed: bool | None = None
    safety_backup: str | None = Field(None, description="The backup of the old file, by name")
    undo: Undo | None = None
    running: bool
    restart_needed: bool


# ------------------------------------------------------------ server settings
class PaletteColor(Open):
    id: str
    name: str
    hex: str


class CpuStatus(Open):
    configured: list[int] | None = Field(None, description="null: every core")
    applied: list[int] | None = Field(
        None, description="Read from the running server; null when unknown"
    )
    applied_reason: str | None = None
    problems: list[str] = []


class CpuOther(Open):
    id: str
    name: str
    cores: list[int] = []


class CpuOverview(Open):
    logical_cores: int | None = None
    supported: bool
    unsupported_reason: str | None = None
    others: list[CpuOther] = []
    status: CpuStatus


class SleepStatus(Open):
    enabled: bool
    minutes: int
    players_online: int | None = None
    stops_in: float | None = None
    list_answered: bool | None = None


class ServerSettings(Open):
    """One server's own settings: name and launch settings under "server",
    then its crash, backup and mod settings with its overrides applied."""

    server_id: str
    server: dict[str, Any]
    color: str | None = None
    palette: list[PaletteColor]
    monitor: dict[str, Any]
    backups: dict[str, Any]
    mods: dict[str, Any]
    overrides: dict[str, Any]
    editable: list[str]
    cpu: CpuOverview
    sleep: SleepStatus | None = None


class CpuApplied(Open):
    ok: bool
    applied: list[int] | None = Field(None, description="Read back from the running server")
    reason: str | None = None


class ServerSettingsSaved(Open):
    ok: bool
    applied: dict[str, Any]
    rejected: dict[str, str] = Field(
        description="Each refused key with the reason, said to the person"
    )
    cpu_cores: CpuApplied | None = Field(None, description="Only when the server is running")


class ColorSaved(Open):
    ok: bool
    color: str


class MemoryServer(Open):
    id: str
    name: str
    limit_mb: int | None = Field(None, description="null: no -Xmx set")
    running: bool
    this: bool


class MemoryOverview(Open):
    """The memory slider: bounded by the PC's measured memory."""

    total_mb: int | None = Field(None, description="null when it couldn't be measured")
    limit_mb: int | None = None
    jvm_args: list[str]
    takes_memory_limit: bool
    min_mb: int
    max_mb: int | None = None
    step_mb: int
    together_mb: int
    servers: list[MemoryServer]
    over: bool
    running: bool


class MemorySaved(MemoryOverview):
    ok: bool


# ------------------------------------------------------------ server types and versions
class ServerType(Open):
    id: str
    name: str
    edition: str = "java"
    content: str | None = None
    ease: str | None = None
    snapshots: bool = False
    picks_loader: bool = False
    loader_name: str | None = None
    latest_only: bool = False
    takes_memory_limit: bool = True
    crossplay: bool = False
    has_content: bool = False
    recommended: bool = False
    modrinth: bool = False
    metadata_files: list[str] = []
    version_source: str | None = None


class ServerTypes(Open):
    types: list[ServerType]
    recommended: str
    default: str


class OfferedVersion(Open):
    minecraft: str
    stable: bool = True
    loaders: list[str] = []
    java_required: int | None = Field(
        None, description="The oldest Java it runs on; null when unknown"
    )
    kept: bool = False
    latest: bool = False


class TypeVersions(Open):
    type: str
    type_name: str
    latest_only: bool = False
    snapshots: bool = False
    picks_loader: bool = False
    loader_name: str | None = None
    latest_stable: str | None = None
    versions: list[OfferedVersion]
    source_problem: str | None = None


class LastVersionChange(Open):
    at: float | None = None
    type: str | None = None
    previous_type: str | None = None
    minecraft_version: str | None = None
    can_roll_back: bool = False


class ServerVersion(Open):
    """One server's type and version as its console reported them; null
    means Unknown, never a guess from a file name."""

    type: str
    capabilities: ServerType
    minecraft_version: str | None = None
    minecraft_version_source: str | None = None
    loader_version: str | None = None
    loader_name: str | None = None
    detected_type: str | None = None
    pending_version: dict[str, Any] | None = None
    eula_required: bool = False
    eula_url: str
    last_change: LastVersionChange | None = None


class PreflightSide(Open):
    type: str
    type_name: str
    minecraft_version: str | None = None
    loader_version: str | None = None


class JavaCheck(Open):
    verdict: str = Field(description="ok, incompatible, unknown or not_needed")
    detail: str | None = None


class VersionPreflight(Open):
    """What a version or type change would do, before anything happens."""

    current: PreflightSide
    target: PreflightSide
    type_change: bool
    gentle_type_change: bool
    direction: str
    downgrade_warning: bool
    java: JavaCheck
    java_required: int | None = None
    moved_aside: list[str] = []
    unknown_support: list[str] = []
    not_supporting: list[str] = []
    crossplay: bool = False
    crossplay_available: bool = False


class VersionChanged(Open):
    ok: bool
    job_id: str
    verified: bool | None = None
    crossplay_turned_off: bool | None = None


class VersionRolledBack(Open):
    ok: bool
    job_id: str
    type: str


class EulaAccepted(Open):
    ok: bool
    url: str


# ------------------------------------------------------------ crossplay and duplicate
class Crossplay(Open):
    """Whether Bedrock players can join this Java server (Geyser)."""

    available: bool
    unavailable_reason: str | None = None
    enabled: bool
    port: int | None = None
    default_port: int
    suggested_port: int | None = None
    username_prefix: str = ""
    missing_mod: str | None = None
    ready: bool = False
    differences: list[str] = []
    address: str | None = Field(None, description="Only from a measured Tailscale address")
    address_unknown: str | None = None


class CrossplaySaved(Crossplay):
    ok: bool


class DuplicateOptions(Open):
    name: str
    directory: str
    running: bool
    crossplay: bool
    world_folders: list[str] = []


class DuplicateStarted(Open):
    ok: bool
    job: Job


class ServerRemoved(Open):
    """A server taken off the list. Nothing on disk was touched."""

    ok: bool
    removed: str
    name: str
    directory: str


# ------------------------------------------------------------ folder picker
class PcDrive(Open):
    name: str
    path: str


class PcShortcut(Open):
    key: str
    path: str


class PcFolder(Open):
    name: str
    path: str
    world: bool = Field(description="It holds a Minecraft world (a level.dat inside)")


class FolderListing(Open):
    """The folders inside one folder, names only. With no folder asked for:
    the PC's drives and the usual shortcuts, and path is null."""

    path: str | None
    parent: str | None = Field(description="null at a drive's root: going up shows the drives")
    folders: list[PcFolder]
    drives: list[PcDrive] = []
    shortcuts: list[PcShortcut] = []
    truncated: bool = False
    world: bool = False


# ------------------------------------------------------------ adding a server
class ServerAdded(Open):
    """A server folder already on the PC, now on the list. Nothing in it changed."""

    ok: bool
    server: ServerRow
    warnings: list[str] = Field(
        [], description="Said in the agent's own words: no port set, a shared port"
    )


class BedrockNewOptions(Open):
    port: int | None = Field(None, description="null when no free pair of UDP ports was found")
    port_v6: int | None = None
    eula_url: str
    privacy_url: str
    terms: dict[str, Any] | None = Field(
        None, description="Who accepted Mojang's terms and when; null before anyone did"
    )


class NewServerOptions(Open):
    types: list[ServerType]
    recommended: str
    memory_mb: int | None = Field(
        None, description="The suggested memory; null when the PC's memory couldn't be read"
    )
    memory_reason: str | None = None
    port: int
    color: str
    palette: list[PaletteColor]
    eula_url: str
    bedrock: BedrockNewOptions


class ServerCreated(Open):
    """A brand-new server, set up and not started."""

    ok: bool
    server_id: str
    name: str
    directory: str
    port: int | None = None
    memory_mb: int | None = None
    job_id: str
    server: ServerRow
    next: str | None = None
    modpack: dict[str, Any] | None = Field(
        None, description="Only for a server made from a modpack"
    )


# ------------------------------------------------------------ world import and download
class WorldInfo(Open):
    """A world read before it replaces anything."""

    source: str = Field(description="zip or folder")
    folder_name: str
    name: str | None = Field(None, description="LevelName from level.dat; null when unreadable")
    version: str | None = Field(
        None, description="The game version that last saved it; null when unknown"
    )
    last_played: float | None = None
    size_bytes: int
    files: int
    read_problem: str | None = None
    edition: str = "java"


class WorldRead(Open):
    """An uploaded or picked world and whether it fits this server. Nothing
    changes until the import is confirmed with the token."""

    token: str
    world: WorldInfo
    edition_matches: bool
    server_edition: str
    server_version: str | None = None
    newer_than_server: bool | None = Field(None, description="null when either version isn't known")
    level_name: str | None = None


class SavedWorld(Open):
    folder: str
    path: str
    modified: float


class SavedWorlds(Open):
    folder: str | None = Field(
        None, description="Single-player's saves folder; null when it isn't on this PC"
    )
    worlds: list[SavedWorld]


class WorldImported(Open):
    ok: bool
    job_id: str
    world: WorldInfo
    safety_backup: SafetyBackup | None = None
    undo: Undo | None = None


class WorldPacked(Open):
    """The world zipped for single-player; download it with the token."""

    ok: bool
    token: str
    files: int
    size_bytes: int
    filename: str
