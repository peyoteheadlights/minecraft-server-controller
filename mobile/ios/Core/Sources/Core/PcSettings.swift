import Foundation

// PC settings, owner only (agent/api/routes/settings.py, system.py,
// updates.py, transfer.py, helpdesk.py; the dashboard's app-settings.js).
// Mirrors the Android core's PcSettings.kt.

public struct SettingsSecrets: Decodable, Equatable, Sendable {
    public var discord: Bool
    public var email: Bool

    enum CodingKeys: String, CodingKey {
        case discord = "discord_webhook_configured"
        case email = "smtp_configured"
    }

    public init(discord: Bool = false, email: Bool = false) {
        self.discord = discord
        self.email = email
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        discord = try c.decodeIfPresent(Bool.self, forKey: .discord) ?? false
        email = try c.decodeIfPresent(Bool.self, forKey: .email) ?? false
    }
}

public struct PcSettingsView: Decodable, Equatable, Sendable {
    public var config: [String: JSONValue]
    public var secrets: SettingsSecrets

    enum CodingKeys: String, CodingKey { case config, secrets }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        config = try c.decodeIfPresent([String: JSONValue].self, forKey: .config) ?? [:]
        secrets = try c.decodeIfPresent(SettingsSecrets.self, forKey: .secrets) ?? SettingsSecrets()
    }
}

public struct SettingsSaved: Decodable, Equatable, Sendable {
    public var applied: [String: JSONValue]
    public var rejected: [String: String]

    enum CodingKeys: String, CodingKey { case applied, rejected }

    public init(applied: [String: JSONValue] = [:], rejected: [String: String] = [:]) {
        self.applied = applied
        self.rejected = rejected
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        applied = try c.decodeIfPresent([String: JSONValue].self, forKey: .applied) ?? [:]
        rejected = try c.decodeIfPresent([String: String].self, forKey: .rejected) ?? [:]
    }
}

public struct MaintenanceSet: Decodable, Equatable, Sendable {
    public var maintenance: Bool
}

public struct TestAlert: Decodable, Equatable, Sendable {
    public var sent: Bool
}

public struct Battery: Decodable, Equatable, Sendable {
    public var present: Bool?
    public var percent: Int?
    public var pluggedIn: Bool?

    enum CodingKeys: String, CodingKey {
        case present, percent
        case pluggedIn = "plugged_in"
    }
}

public struct PowerStatus: Decodable, Equatable, Sendable {
    public var supported: Bool
    public var enabled: Bool
    public var active: Bool
    public var running: [String]
    public var problem: String?
    public var battery: Battery?
    public var stillSleeps: [String]

    enum CodingKeys: String, CodingKey {
        case supported, enabled, active, running, problem, battery
        case stillSleeps = "still_sleeps"
    }

    public init(supported: Bool = false, enabled: Bool = false, active: Bool = false, running: [String] = [], stillSleeps: [String] = []) {
        self.supported = supported
        self.enabled = enabled
        self.active = active
        self.running = running
        self.stillSleeps = stillSleeps
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        supported = try c.decodeIfPresent(Bool.self, forKey: .supported) ?? false
        enabled = try c.decodeIfPresent(Bool.self, forKey: .enabled) ?? false
        active = try c.decodeIfPresent(Bool.self, forKey: .active) ?? false
        running = try c.decodeIfPresent([String].self, forKey: .running) ?? []
        problem = try c.decodeIfPresent(String.self, forKey: .problem)
        battery = try? c.decodeIfPresent(Battery.self, forKey: .battery)
        stillSleeps = try c.decodeIfPresent([String].self, forKey: .stillSleeps) ?? []
    }
}

public struct StartupTask: Decodable, Equatable, Sendable {
    public var mode: String?
    public var command: String?
    public var folder: String?

    enum CodingKeys: String, CodingKey {
        case mode, command
        case folder = "working_directory"
    }
}

public struct StartupRuntime: Decodable, Equatable, Sendable {
    public var lastRun: String?
    public var lastResult: String?

    enum CodingKeys: String, CodingKey {
        case lastRun = "last_run_time"
        case lastResult = "last_result"
    }
}

public struct StartupStep: Decodable, Equatable, Sendable {
    public var event: String?
}

public struct LastStartup: Decodable, Equatable, Sendable {
    public var startedAt: String?
    public var launchedBy: String?
    public var events: [StartupStep]?

    enum CodingKeys: String, CodingKey {
        case events
        case startedAt = "started_at"
        case launchedBy = "launched_by"
    }
}

public struct StartupReport: Decodable, Equatable, Sendable {
    public var verdict: String
    public var registered: Bool?
    public var pointsHere: Bool?
    public var mechanism: String?
    public var problems: [String]?
    public var task: StartupTask?
    public var runtime: StartupRuntime?
    public var lastStartup: LastStartup?

    enum CodingKeys: String, CodingKey {
        case verdict, registered, mechanism, problems, task, runtime
        case pointsHere = "points_to_current_app"
        case lastStartup = "last_startup"
    }
}

public struct ExportServerSizes: Decodable, Equatable, Sendable {
    public var files: Int64
    public var worlds: Int64
    public var backups: Int64

    public init(files: Int64, worlds: Int64, backups: Int64) {
        self.files = files
        self.worlds = worlds
        self.backups = backups
    }
}

public struct ExportSizes: Decodable, Equatable, Sendable {
    public var servers: [ExportServerSizes]

    public init(servers: [ExportServerSizes]) {
        self.servers = servers
    }
}

public struct ExportStarted: Decodable, Equatable, Sendable {
    public var jobId: String

    enum CodingKeys: String, CodingKey { case jobId = "job_id" }
}

public struct ExportResult: Decodable, Equatable, Sendable {
    public var token: String?
    public var filename: String?
    public var sizeBytes: Int64?
    public var savedTo: String?

    enum CodingKeys: String, CodingKey {
        case token, filename
        case sizeBytes = "size_bytes"
        case savedTo = "saved_to"
    }
}

/// The export task as GET /api/jobs/{id} reports it.
public struct ExportJob: Decodable, Equatable, Sendable {
    public var id: String
    public var state: String
    public var step: String?
    public var progress: Double?
    public var message: String?
    public var result: ExportResult?
}

public struct HelpFile: Decodable, Equatable, Sendable, Identifiable {
    public var name: String
    public var size: Int64?
    public var id: String { name }
}

public struct HelpFiles: Decodable, Equatable, Sendable {
    public var files: [HelpFile]
}

public struct HelpFileMade: Decodable, Equatable, Sendable {
    public var token: String
    public var filename: String
}

public struct SessionsRevoked: Decodable, Equatable, Sendable {
    public var revoked: Int
}

public struct Release: Decodable, Equatable, Sendable {
    public var version: String
    public var page: String?
    public var notes: String?

    public init(version: String, page: String? = nil, notes: String? = nil) {
        self.version = version
        self.page = page
        self.notes = notes
    }
}

public struct UpdateResult: Decodable, Equatable, Sendable {
    public var ok: Bool?
    public var version: String?
    public var message: String?
    public var rolledBack: Bool?

    enum CodingKeys: String, CodingKey {
        case ok, version, message
        case rolledBack = "rolled_back"
    }

    public init(ok: Bool? = nil, version: String? = nil, rolledBack: Bool? = nil) {
        self.ok = ok
        self.version = version
        self.rolledBack = rolledBack
    }
}

public struct UpdateStatus: Decodable, Equatable, Sendable {
    public var current: String
    public var latest: Release?
    public var available: Bool
    public var checkedAt: Double?
    public var error: String?
    public var canInstall: Bool
    public var cannotInstallReason: String?
    public var lastResult: UpdateResult?
    /// Only in the checks before installing: nil when it couldn't tell.
    public var playersOnline: Int?

    enum CodingKeys: String, CodingKey {
        case current, latest, available, error
        case checkedAt = "checked_at"
        case canInstall = "can_install"
        case cannotInstallReason = "cannot_install_reason"
        case lastResult = "last_result"
        case playersOnline = "players_online"
    }

    public init(
        current: String, latest: Release? = nil, available: Bool = false, checkedAt: Double? = nil,
        canInstall: Bool = false, cannotInstallReason: String? = nil, lastResult: UpdateResult? = nil, playersOnline: Int? = nil
    ) {
        self.current = current
        self.latest = latest
        self.available = available
        self.checkedAt = checkedAt
        self.canInstall = canInstall
        self.cannotInstallReason = cannotInstallReason
        self.lastResult = lastResult
        self.playersOnline = playersOnline
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        current = try c.decode(String.self, forKey: .current)
        latest = try c.decodeIfPresent(Release.self, forKey: .latest)
        available = try c.decodeIfPresent(Bool.self, forKey: .available) ?? false
        checkedAt = try c.decodeIfPresent(Double.self, forKey: .checkedAt)
        error = try c.decodeIfPresent(String.self, forKey: .error)
        canInstall = try c.decodeIfPresent(Bool.self, forKey: .canInstall) ?? false
        cannotInstallReason = try c.decodeIfPresent(String.self, forKey: .cannotInstallReason)
        lastResult = try c.decodeIfPresent(UpdateResult.self, forKey: .lastResult)
        playersOnline = try c.decodeIfPresent(Int.self, forKey: .playersOnline)
    }
}

public struct UpdateStarted: Decodable, Equatable, Sendable {
    public var job: Job
}

public struct OldCopy: Decodable, Equatable, Sendable {
    public var path: String
    public var offer: Bool
    public var problems: [String]

    enum CodingKeys: String, CodingKey { case path, offer, problems }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        path = try c.decode(String.self, forKey: .path)
        offer = try c.decodeIfPresent(Bool.self, forKey: .offer) ?? false
        problems = try c.decodeIfPresent([String].self, forKey: .problems) ?? []
    }
}

public struct OldCopyStatus: Decodable, Equatable, Sendable {
    public var oldCopy: OldCopy?

    enum CodingKeys: String, CodingKey { case oldCopy = "old_copy" }
}

public struct OldCopyRemoved: Decodable, Equatable, Sendable {
    public var kept: [String]
    public var folderRemoved: Bool

    enum CodingKeys: String, CodingKey {
        case kept
        case folderRemoved = "folder_removed"
    }
}

/// One event the PC can alert about, and whether it does.
public struct AlertEvent: Equatable, Sendable, Identifiable {
    public var key: String
    public var on: Bool
    public var id: String { key }
}

/// One limit the PC alerts at, with the dashboard's words for it.
public struct Threshold: Equatable, Sendable, Identifiable {
    public var key: String
    public var label: String
    public var id: String { key }
}

/// One account's signed-in devices.
public struct DeviceGroup: Equatable, Sendable, Identifiable {
    public var user: String
    public var devices: [Device]
    public var id: String { user }
}

/// The alert settings as the owner edits them, with the agent's key for each.
public struct AlertSettings: Equatable, Sendable {
    public var discord = false
    public var email = false
    public var phone = false
    /// Every event the PC can alert about, in the order the phone shows them.
    public var events: [AlertEvent] = []
    public var thresholds: [String: Double] = [:]
    public var repeatSeconds = 300.0

    public init() {}

    public func event(_ key: String) -> Bool? { events.first { $0.key == key }?.on }

    public mutating func set(event key: String, _ on: Bool) {
        if let i = events.firstIndex(where: { $0.key == key }) { events[i].on = on }
    }
}

public enum PcSettings {
    /// Each limit the PC alerts at, with the dashboard's words for it.
    public static let thresholds = [
        Threshold(key: "cpu_percent", label: "appset.cpu_alert"),
        Threshold(key: "ram_percent", label: "appset.ram_alert"),
        Threshold(key: "disk_free_gb", label: "appset.disk_alert"),
        Threshold(key: "tps_min", label: "appset.tps_alert"),
        Threshold(key: "mspt_max", label: "appset.mspt_alert"),
    ]

    /// Every PC-wide setting the dashboard's App settings page changes. The
    /// phones have a screen for each (tests/test_phone_app.py checks this
    /// list against the dashboard).
    public static let keys = [
        "notifications.discord_enabled",
        "notifications.email_enabled",
        "notifications.push_enabled",
        "notifications.events.",
        "notifications.min_interval_seconds",
        "thresholds.",
        "power.keep_awake",
        "updates.check",
    ]

    private static func section(_ config: [String: JSONValue], _ name: String) -> [String: JSONValue] {
        if case .object(let value)? = config[name] { return value }
        return [:]
    }

    private static func bool(_ value: JSONValue?) -> Bool? {
        if case .bool(let on)? = value { return on }
        return nil
    }

    private static func number(_ value: JSONValue?) -> Double? {
        if case .number(let n)? = value { return n }
        return nil
    }

    public static func alerts(_ view: PcSettingsView) -> AlertSettings {
        let notifications = section(view.config, "notifications")
        let limits = section(view.config, "thresholds")
        var alerts = AlertSettings()
        alerts.discord = bool(notifications["discord_enabled"]) ?? false
        alerts.email = bool(notifications["email_enabled"]) ?? false
        alerts.phone = bool(notifications["push_enabled"]) ?? false
        // The agent's JSON object has no order the decoder keeps: by name.
        let events = section(notifications, "events").compactMapValues { bool($0) }
        alerts.events = events.keys.sorted().map { AlertEvent(key: $0, on: events[$0] ?? false) }
        for limit in thresholds {
            if let n = number(limits[limit.key]) { alerts.thresholds[limit.key] = n }
        }
        alerts.repeatSeconds = number(notifications["min_interval_seconds"]) ?? 300
        return alerts
    }

    public static func keepAwake(_ view: PcSettingsView) -> Bool { bool(section(view.config, "power")["keep_awake"]) ?? false }
    public static func dailyCheck(_ view: PcSettingsView) -> Bool { bool(section(view.config, "updates")["check"]) ?? false }
    public static func maintenance(_ view: PcSettingsView) -> Bool { bool(section(view.config, "maintenance")["enabled"]) ?? false }

    /// Who the email alerts go to, for Technical mode; addresses aren't secret.
    public static func emailTo(_ view: PcSettingsView) -> [String] {
        let email = section(section(view.config, "notifications"), "email")
        guard case .array(let list)? = email["to_addresses"] else { return [] }
        return list.compactMap { if case .string(let s) = $0 { return s } else { return nil } }
    }

    /// Only what changed, as PUT /api/settings takes it.
    public static func changes(_ before: AlertSettings, _ after: AlertSettings) -> [String: JSONValue] {
        var out: [String: JSONValue] = [:]
        if after.discord != before.discord { out["notifications.discord_enabled"] = .bool(after.discord) }
        if after.email != before.email { out["notifications.email_enabled"] = .bool(after.email) }
        if after.phone != before.phone { out["notifications.push_enabled"] = .bool(after.phone) }
        for event in after.events where before.event(event.key) != event.on { out["notifications.events." + event.key] = .bool(event.on) }
        for (key, value) in after.thresholds where before.thresholds[key] != value { out["thresholds." + key] = .number(value) }
        if after.repeatSeconds != before.repeatSeconds { out["notifications.min_interval_seconds"] = .number(after.repeatSeconds) }
        return out
    }

    /// A typed number, or nil when it isn't one (the field shows it as wrong).
    public static func number(_ text: String) -> Double? {
        guard let n = Double(text.trimmingCharacters(in: .whitespaces).replacingOccurrences(of: ",", with: ".")),
              n.isFinite, n >= 0 else { return nil }
        return n
    }

    /// What saving said: the PC's reason for each setting it refused, or saved.
    public static func saved(_ strings: Strings, _ result: SettingsSaved) -> (text: String, good: Bool) {
        if !result.rejected.isEmpty {
            return (result.rejected.keys.sorted().compactMap { result.rejected[$0] }.joined(separator: " "), false)
        }
        return (strings.t("settings.saved"), true)
    }

    /// The line under "Keep the PC awake": what Windows does now.
    public static func awake(_ strings: Strings, _ power: PowerStatus) -> String {
        if !power.supported { return strings.t("awake.unsupported") }
        if !power.enabled { return strings.t("awake.off_now") }
        if power.active { return strings.t("awake.active", ["names": power.running.joined(separator: ", ")]) }
        return strings.t("awake.idle")
    }

    /// Why Windows can still sleep, only for reasons the dashboard has words for.
    public static func stillSleeps(_ strings: Strings, _ power: PowerStatus) -> [String] {
        power.stillSleeps.map { "awake.still_" + $0 }.filter(strings.has).map { strings.t($0) }
    }

    // MARK: start with Windows

    public static func verdict(_ report: StartupReport) -> String {
        "startup." + report.verdict.replacingOccurrences(of: " ", with: "_")
    }

    public static func verdictGood(_ report: StartupReport) -> Bool? {
        switch report.verdict {
        case "registered correctly": return true
        case "unsupported": return nil
        default: return false
        }
    }

    /// The check's rows, as the dashboard shows them; nothing is guessed.
    public static func startupRows(_ strings: Strings, _ report: StartupReport, technical: Bool) -> [(name: String, value: String)] {
        func yesNo(_ v: Bool?) -> String { strings.t(v == true ? "value.yes" : v == false ? "value.no" : "value.unknown") }
        let last = report.lastStartup
        let started = (last?.events ?? []).contains { $0.event == "controller_initialized" }
        var rows: [(name: String, value: String)] = [
            (strings.t("startup.registered"), strings.t(report.registered == true ? "startup.found" : report.registered == false ? "startup.not_found" : "value.unknown")),
            (strings.t("startup.mode"), report.task?.mode == "boot" ? strings.t("startup.at_boot") : report.task?.mode == "logon" ? strings.t("startup.at_logon") : "—"),
            (strings.t("startup.points_here"), yesNo(report.pointsHere)),
            (strings.t("startup.last_run"), report.runtime?.lastRun ?? strings.t("value.unknown")),
            (strings.t("startup.last_start"), (last?.startedAt).map { strings.t("startup.last_start_value", ["when": $0, "by": last?.launchedBy ?? ""]) } ?? strings.t("startup.none")),
            (strings.t("startup.initialised"), last?.startedAt != nil ? yesNo(started) : "—"),
        ]
        if technical {
            rows.append((strings.t("startup.mechanism"), report.mechanism ?? "—"))
            rows.append((strings.t("startup.command"), report.task?.command ?? "—"))
            rows.append((strings.t("startup.folder"), report.task?.folder ?? "—"))
            rows.append((strings.t("startup.last_result"), report.runtime?.lastResult ?? strings.t("value.unknown")))
        }
        return rows
    }

    // MARK: export everything

    public struct Totals: Equatable, Sendable {
        public var files: Int64
        public var worlds: Int64
        public var backups: Int64

        public init(files: Int64, worlds: Int64, backups: Int64) {
            self.files = files
            self.worlds = worlds
            self.backups = backups
        }
    }

    public static func totals(_ sizes: ExportSizes) -> Totals {
        Totals(
            files: sizes.servers.reduce(0) { $0 + $1.files },
            worlds: sizes.servers.reduce(0) { $0 + $1.worlds },
            backups: sizes.servers.reduce(0) { $0 + $1.backups }
        )
    }

    public static let minPassphrase = 10

    /// Whether Export can start: a folder picked, and a long enough passphrase when passwords go too.
    public static func canExport(folder: String?, secrets: Bool, passphrase: String) -> Bool {
        guard let folder = folder, !folder.trimmingCharacters(in: .whitespaces).isEmpty else { return false }
        return !secrets || passphrase.count >= minPassphrase
    }

    public static func exportBody(worlds: Bool, backups: Bool, secrets: Bool, passphrase: String, folder: String) -> [String: JSONValue] {
        var body: [String: JSONValue] = [
            "worlds": .bool(worlds), "backups": .bool(backups), "secrets": .bool(secrets), "folder": .string(folder),
        ]
        if secrets { body["passphrase"] = .string(passphrase) }
        return body
    }

    /// Where an export is: still running, saved on the PC, or failed.
    public enum Exporting: Equatable, Sendable {
        case running(step: String?, progress: Double?)
        case saved(path: String, size: Int64?)
        case failed(String?)
    }

    public static func exporting(_ job: ExportJob) -> Exporting {
        switch job.state {
        case "running", "queued": return .running(step: job.step, progress: job.progress)
        case "succeeded":
            if let path = job.result?.savedTo { return .saved(path: path, size: job.result?.sizeBytes) }
            return .failed(job.message)
        default: return .failed(job.message)
        }
    }

    public static func exportSaid(_ strings: Strings, _ state: Exporting) -> String? {
        switch state {
        case .running: return nil
        case .saved(let path, let size): return strings.t("mobile.pc.export_saved", ["path": path, "size": Display.bytes(strings, size)])
        case .failed(let reason): return reason ?? strings.t("export.failed")
        }
    }

    // MARK: signed-in devices

    /// Every account's devices, this account first, then by name; this phone first in its list.
    public static func byAccount(_ devices: [Device], me: String?) -> [DeviceGroup] {
        Dictionary(grouping: devices, by: { $0.user })
            .map { DeviceGroup(user: $0.key, devices: $0.value.sorted { a, b in
                a.current != b.current ? a.current : (a.lastUsed ?? 0) > (b.lastUsed ?? 0)
            }) }
            .sorted { a, b in
                (a.user == me) != (b.user == me) ? a.user == me : a.user.lowercased() < b.user.lowercased()
            }
    }
}

/// The app update as PC settings shows it, from GET /api/updates, and
/// while the PC is updating itself.
public enum PcUpdate {
    public enum Shows: Equatable, Sendable { case upToDate, ready, cantInstall, updating, updated, failed }

    /// `updating` is the version asked for, while the phone waits for the PC to come back.
    public static func shows(_ status: UpdateStatus, updating: String? = nil) -> Shows {
        if updating != nil { return .updating }
        if status.lastResult?.ok == false && !status.available { return .failed }
        if status.available { return status.canInstall ? .ready : .cantInstall }
        if status.lastResult?.ok == true && status.lastResult?.version == status.current { return .updated }
        return .upToDate
    }

    /// Whether the PC is back after an update to `target`: on the new
    /// version, or saying how the update went. Before that it doesn't answer
    /// at all, or still says the old version.
    public static func back(before: UpdateStatus, now: UpdateStatus, target: String) -> Bool {
        if now.current != before.current { return true }
        guard let result = now.lastResult else { return false }
        return result != before.lastResult && result.version == target
    }

    /// How long the phone waits for the PC to come back before saying so.
    public static let waitSeconds: Double = 600

    /// The confirmation's words: who will be disconnected, if the PC could tell.
    public static func confirmBody(_ strings: Strings, _ check: UpdateStatus) -> String {
        var parts = [strings.t("update.confirm_body")]
        if let players = check.playersOnline {
            if players > 0 { parts.append(strings.t("update.confirm_players", ["count": players])) }
        } else {
            parts.append(strings.t("update.confirm_players_unknown"))
        }
        return parts.joined(separator: " ")
    }

    public static func confirmLabel(_ strings: Strings, _ check: UpdateStatus) -> String {
        strings.t((check.playersOnline ?? 0) > 0 ? "update.install_anyway" : "update.install")
    }

    /// "What's new", one line per change, at most 30.
    public static func notes(_ release: Release?) -> [String] {
        (release?.notes ?? "").split(separator: "\n", omittingEmptySubsequences: true)
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
            .prefix(30)
            .map { line in String(line.drop(while: { "-*# ".contains($0) })) }
    }

    public static func lastResult(_ strings: Strings, _ result: UpdateResult?) -> String? {
        guard let result = result, let ok = result.ok else { return nil }
        let version = result.version ?? ""
        if ok { return strings.t("update.last_ok", ["version": version]) }
        var text = strings.t("update.last_failed", ["version": version])
        if result.rolledBack == true { text += " " + strings.t("update.rolled_back") }
        if result.rolledBack == false { text += " " + strings.t("update.not_rolled_back") }
        return text
    }

    public static func oldCopyRemoved(_ strings: Strings, _ result: OldCopyRemoved) -> String {
        result.folderRemoved ? strings.t("oldcopy.removed") : strings.t("oldcopy.removed_kept", ["count": result.kept.count])
    }
}

extension AgentClient {
    /// Signs every device out, this phone too.
    public func signEveryoneOut() async throws -> SessionsRevoked {
        try await call("POST", "/api/security/revoke-sessions", body: Data("{}".utf8), as: SessionsRevoked.self)
    }

    public func pcSettings() async throws -> PcSettingsView {
        try await call("GET", "/api/settings", as: PcSettingsView.self)
    }

    /// Saves `updates` as built by `PcSettings.changes`; each refused one comes back with why.
    public func savePcSettings(_ updates: [String: JSONValue]) async throws -> SettingsSaved {
        let body = try AgentClient.encode(["updates": JSONValue.object(updates)])
        return try await call("PUT", "/api/settings", body: body, as: SettingsSaved.self)
    }

    public func maintenance(_ on: Bool) async throws -> MaintenanceSet {
        try await call("POST", "/api/maintenance", body: try AgentClient.encode(["enabled": on]), as: MaintenanceSet.self)
    }

    /// "discord" or "email".
    public func testAlert(_ channel: String) async throws -> TestAlert {
        try await call("POST", "/api/notifications/test?channel=" + AgentClient.pathSegment(channel), body: Data("{}".utf8), slow: true, as: TestAlert.self)
    }

    public func power() async throws -> PowerStatus {
        try await call("GET", "/api/power", as: PowerStatus.self)
    }

    /// Asks Windows whether this app starts with it. It only checks.
    public func startupCheck() async throws -> StartupReport {
        try await call("GET", "/api/system/startup", slow: true, as: StartupReport.self)
    }

    public func updates() async throws -> UpdateStatus {
        try await call("GET", "/api/updates", as: UpdateStatus.self)
    }

    public func checkForUpdate() async throws -> UpdateStatus {
        try await call("POST", "/api/updates/check", body: Data("{}".utf8), slow: true, as: UpdateStatus.self)
    }

    /// The checks before updating: the version, and who is playing.
    public func updateChecks() async throws -> UpdateStatus {
        try await call("GET", "/api/updates/preflight", as: UpdateStatus.self)
    }

    /// Starts the update; the PC restarts this app, so it stops answering for a while.
    public func installUpdate() async throws -> UpdateStarted {
        try await call("POST", "/api/updates/install", body: Data("{}".utf8), as: UpdateStarted.self)
    }

    public func oldCopy() async throws -> OldCopyStatus {
        try await call("GET", "/api/updates/old-copy", as: OldCopyStatus.self)
    }

    public func removeOldCopy() async throws -> OldCopyRemoved {
        try await call("POST", "/api/updates/old-copy/remove", body: Data("{}".utf8), as: OldCopyRemoved.self)
    }

    public func exportSizes() async throws -> ExportSizes {
        try await call("GET", "/api/export", as: ExportSizes.self)
    }

    /// Starts Export everything into a folder on the PC (body from `PcSettings.exportBody`).
    public func startExport(_ body: [String: JSONValue]) async throws -> ExportStarted {
        try await call("POST", "/api/export", body: try AgentClient.encode(body), as: ExportStarted.self)
    }

    public func exportJob(_ id: String) async throws -> ExportJob {
        try await call("GET", "/api/jobs/" + AgentClient.pathSegment(id), as: ExportJob.self)
    }

    /// The files a help file would hold, before it is made.
    public func helpFiles() async throws -> HelpFiles {
        try await call("GET", "/api/help-bundle", as: HelpFiles.self)
    }

    public func makeHelpFile() async throws -> HelpFileMade {
        try await call("POST", "/api/help-bundle", body: try AgentClient.encode(["confirm": true]), slow: true, as: HelpFileMade.self)
    }

    /// Downloads the help file to `destination`, as `downloadBackup` does, for the share sheet.
    public func downloadHelpFile(_ made: HelpFileMade, to destination: URL) async throws -> Int64 {
        let path = "/api/help-bundle/" + AgentClient.pathSegment(made.token) + "?filename=" + AgentClient.pathSegment(made.filename)
        return try await downloadZip(path, to: destination, progress: { _, _ in })
    }
}
