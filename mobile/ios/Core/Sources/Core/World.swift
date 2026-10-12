import Foundation

// What Backups, Restore world, Schedules and Performance read, and their
// rules. Mirrors mobile/android/core's WorldModels.kt and World.kt. As in
// Pages.swift, a value the agent can leave out is nil and shown as Unknown.

/// Any JSON value, kept as it came: a schedule's settings are sent back
/// unchanged, and a health check's value is shown as the agent sent it.
public enum JSONValue: Codable, Equatable, Sendable {
    case null
    case bool(Bool)
    case number(Double)
    case string(String)
    case array([JSONValue])
    case object([String: JSONValue])

    public init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() {
            self = .null
        } else if let value = try? c.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? c.decode(Double.self) {
            self = .number(value)
        } else if let value = try? c.decode(String.self) {
            self = .string(value)
        } else if let value = try? c.decode([JSONValue].self) {
            self = .array(value)
        } else {
            self = .object(try c.decode([String: JSONValue].self))
        }
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .null: try c.encodeNil()
        case .bool(let value): try c.encode(value)
        case .number(let value):
            // A whole number goes back as one (25565, not 25565.0): the
            // agent reads a port or a count with int().
            if value.rounded() == value && abs(value) < 1e15 {
                try c.encode(Int64(value))
            } else {
                try c.encode(value)
            }
        case .string(let value): try c.encode(value)
        case .array(let value): try c.encode(value)
        case .object(let value): try c.encode(value)
        }
    }

    /// As the dashboard prints it: 90 rather than 90.0; nil for null.
    public var text: String? {
        switch self {
        case .null: return nil
        case .bool(let value): return value ? "true" : "false"
        case .number(let value):
            if value.rounded() == value && abs(value) < 1e15 { return String(Int64(value)) }
            return String(value)
        case .string(let value): return value
        case .array, .object:
            guard let data = try? AgentClient.encode(self) else { return nil }
            return String(data: data, encoding: .utf8)
        }
    }
}

extension KeyedDecodingContainer {
    /// Each entry that reads; one the app can't read is left out rather
    /// than emptying the whole list.
    func each<T: Decodable>(_ key: Key) -> [T] {
        guard var list = try? nestedUnkeyedContainer(forKey: key) else { return [] }
        var out: [T] = []
        while !list.isAtEnd {
            if let item = try? list.decode(T.self) {
                out.append(item)
            } else if (try? list.decode(Skipped.self)) == nil {
                break
            }
        }
        return out
    }
}

/// Reads any value and keeps nothing: steps over an entry the app can't read.
private struct Skipped: Decodable {
    init(from decoder: Decoder) throws {}
}

// MARK: - Backups

/// A backup's second copy off the PC, as the agent found it just now.
public struct BackupCopy: Decodable, Equatable, Sendable {
    public var state: String
    public var reason: String?

    enum CodingKeys: String, CodingKey { case state, reason }

    public init(state: String = "none", reason: String? = nil) {
        self.state = state
        self.reason = reason
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        state = c.value(.state, "none")
        reason = c.maybe(.reason)
    }
}

public struct Backup: Decodable, Equatable, Identifiable, Sendable {
    public var id: Int64
    public var name: String
    public var kind: String?
    public var createdAt: Double?
    public var sizeBytes: Int64?
    public var status: String?
    public var exists: Bool?
    public var copy: BackupCopy?

    enum CodingKeys: String, CodingKey {
        case id, name, kind, status, exists, copy
        case createdAt = "created_at"
        case sizeBytes = "size_bytes"
    }

    public init(
        id: Int64, name: String = "", kind: String? = nil, createdAt: Double? = nil, sizeBytes: Int64? = nil,
        status: String? = nil, exists: Bool? = nil, copy: BackupCopy? = nil
    ) {
        self.id = id
        self.name = name
        self.kind = kind
        self.createdAt = createdAt
        self.sizeBytes = sizeBytes
        self.status = status
        self.exists = exists
        self.copy = copy
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(Int64.self, forKey: .id)
        name = c.value(.name, "")
        kind = c.maybe(.kind)
        createdAt = c.maybe(.createdAt)
        sizeBytes = c.maybe(.sizeBytes)
        status = c.maybe(.status)
        exists = c.maybe(.exists)
        copy = c.maybe(.copy)
    }
}

public struct Retention: Decodable, Equatable, Sendable {
    public var daily: Int?
    public var weekly: Int?
    public var monthly: Int?

    public init(daily: Int?, weekly: Int?, monthly: Int?) {
        self.daily = daily
        self.weekly = weekly
        self.monthly = monthly
    }
}

public struct BackupList: Decodable, Equatable, Sendable {
    public var backups: [Backup]
    public var retention: Retention?

    enum CodingKeys: String, CodingKey { case backups, retention }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        backups = c.each(.backups)
        retention = c.maybe(.retention)
    }
}

/// Opening the archive and checking it. `reason` says why it failed.
public struct BackupCheck: Decodable, Equatable, Sendable {
    public var ok: Bool
    public var reason: String?
    public var entries: Int?

    enum CodingKeys: String, CodingKey { case ok, reason, entries }

    public init(ok: Bool, reason: String? = nil, entries: Int? = nil) {
        self.ok = ok
        self.reason = reason
        self.entries = entries
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ok = c.value(.ok, false)
        reason = c.maybe(.reason)
        entries = c.maybe(.entries)
    }
}

public struct BackupMade: Decodable, Equatable, Sendable {
    public var name: String
    public var verification: BackupCheck?

    enum CodingKeys: String, CodingKey { case name, verification }

    public init(name: String, verification: BackupCheck? = nil) {
        self.name = name
        self.verification = verification
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = c.value(.name, "")
        verification = c.maybe(.verification)
    }
}

public struct SafetyBackup: Decodable, Equatable, Sendable {
    public var name: String

    public init(name: String) {
        self.name = name
    }
}

/// How a change is undone: by restoring the backup made just before it.
public struct Undo: Decodable, Equatable, Sendable {
    public var backup: String

    public init(backup: String) {
        self.backup = backup
    }
}

/// A restore asked without confirm answers `willHappen`; a confirmed one
/// says what was put back and the backup made just before.
public struct Restored: Decodable, Equatable, Sendable {
    public var willHappen: [String]?
    public var restored: String?
    public var safetyBackup: SafetyBackup?

    enum CodingKeys: String, CodingKey {
        case restored
        case willHappen = "will_happen"
        case safetyBackup = "safety_backup"
    }

    public init(willHappen: [String]? = nil, restored: String? = nil, safetyBackup: SafetyBackup? = nil) {
        self.willHappen = willHappen
        self.restored = restored
        self.safetyBackup = safetyBackup
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        willHappen = c.maybe(.willHappen)
        restored = c.maybe(.restored)
        safetyBackup = c.maybe(.safetyBackup)
    }
}

/// Where second copies go; `directory` is empty when they are off.
public struct Offsite: Decodable, Equatable, Sendable {
    public var directory: String
    public var unavailable: String?
    public var subfolder: String?

    enum CodingKeys: String, CodingKey { case directory, unavailable, subfolder }

    public init(directory: String = "", unavailable: String? = nil, subfolder: String? = nil) {
        self.directory = directory
        self.unavailable = unavailable
        self.subfolder = subfolder
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        directory = c.value(.directory, "")
        unavailable = c.maybe(.unavailable)
        subfolder = c.maybe(.subfolder)
    }
}

public struct BackupCopied: Decodable, Equatable, Sendable {
    public var copy: BackupCopy?
}

public struct LastBackup: Decodable, Equatable, Sendable {
    public var name: String?
    public var createdAt: Double?

    enum CodingKeys: String, CodingKey {
        case name
        case createdAt = "created_at"
    }
}

public struct World: Decodable, Equatable, Identifiable, Sendable {
    public var key: String
    public var label: String
    public var exists: Bool
    public var sizeBytes: Int64?
    public var modified: Double?
    public var lastBackup: LastBackup?

    public var id: String { key }

    enum CodingKeys: String, CodingKey {
        case key, label, exists, modified
        case sizeBytes = "size_bytes"
        case lastBackup = "last_backup"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        key = try c.decode(String.self, forKey: .key)
        label = c.value(.label, "")
        exists = c.value(.exists, false)
        sizeBytes = c.maybe(.sizeBytes)
        modified = c.maybe(.modified)
        lastBackup = c.maybe(.lastBackup)
    }
}

public struct WorldList: Decodable, Equatable, Sendable {
    public var worlds: [World]

    enum CodingKeys: String, CodingKey { case worlds }

    public init(from decoder: Decoder) throws {
        worlds = try decoder.container(keyedBy: CodingKeys.self).each(.worlds)
    }
}

/// Written to the console; Minecraft gives no answer to check.
public struct Requested: Decodable, Equatable, Sendable {
    public var result: String?
}

/// A point Restore world can go back to: a backup that holds the world.
public struct WorldPoint: Decodable, Equatable, Identifiable, Sendable {
    public var backupId: Int64
    public var name: String
    public var createdAt: Double
    public var ageSeconds: Double
    public var sizeBytes: Int64?
    public var kind: String?
    public var checked: Bool
    /// Time with players online since; nil when sessions weren't recorded.
    public var playedSeconds: Double?

    public var id: Int64 { backupId }

    enum CodingKeys: String, CodingKey {
        case name, kind, checked
        case backupId = "backup_id"
        case createdAt = "created_at"
        case ageSeconds = "age_seconds"
        case sizeBytes = "size_bytes"
        case playedSeconds = "played_seconds"
    }

    public init(
        backupId: Int64, name: String = "", createdAt: Double = 0, ageSeconds: Double = 0, sizeBytes: Int64? = nil,
        kind: String? = nil, checked: Bool = false, playedSeconds: Double? = nil
    ) {
        self.backupId = backupId
        self.name = name
        self.createdAt = createdAt
        self.ageSeconds = ageSeconds
        self.sizeBytes = sizeBytes
        self.kind = kind
        self.checked = checked
        self.playedSeconds = playedSeconds
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        backupId = try c.decode(Int64.self, forKey: .backupId)
        name = c.value(.name, "")
        createdAt = c.value(.createdAt, 0)
        ageSeconds = c.value(.ageSeconds, 0)
        sizeBytes = c.maybe(.sizeBytes)
        kind = c.maybe(.kind)
        checked = c.value(.checked, false)
        playedSeconds = c.maybe(.playedSeconds)
    }
}

public struct WorldTimeline: Decodable, Equatable, Sendable {
    public var points: [WorldPoint]
    public var serverRunning: Bool
    public var canRestore: Bool
    public var blockedBy: String?

    enum CodingKeys: String, CodingKey {
        case points
        case serverRunning = "server_running"
        case canRestore = "can_restore"
        case blockedBy = "blocked_by"
    }

    public init(points: [WorldPoint] = [], serverRunning: Bool = false, canRestore: Bool = false, blockedBy: String? = nil) {
        self.points = points
        self.serverRunning = serverRunning
        self.canRestore = canRestore
        self.blockedBy = blockedBy
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        points = c.each(.points)
        serverRunning = c.value(.serverRunning, false)
        canRestore = c.value(.canRestore, false)
        blockedBy = c.maybe(.blockedBy)
    }
}

/// A task the agent ran (a backup, a restore, a mod install).
public struct Job: Decodable, Equatable, Identifiable, Sendable {
    public var id: String
    public var kind: String
    public var title: String
    public var state: String
    /// What it is doing now ("Updating Sodium (2 of 5)").
    public var step: String?
    public var serverId: String?
    public var finishedAt: Double?
    public var undo: Undo?

    enum CodingKeys: String, CodingKey {
        case id, kind, title, state, step, result
        case serverId = "server_id"
        case finishedAt = "finished_at"
    }

    enum ResultKeys: String, CodingKey { case undo }

    public init(
        id: String, kind: String = "", title: String = "", state: String = "", step: String? = nil,
        serverId: String? = nil, finishedAt: Double? = nil, undo: Undo? = nil
    ) {
        self.id = id
        self.kind = kind
        self.title = title
        self.state = state
        self.step = step
        self.serverId = serverId
        self.finishedAt = finishedAt
        self.undo = undo
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        kind = c.value(.kind, "")
        title = c.value(.title, "")
        state = c.value(.state, "")
        step = c.maybe(.step)
        serverId = c.maybe(.serverId)
        finishedAt = c.maybe(.finishedAt)
        let result = try? c.nestedContainer(keyedBy: ResultKeys.self, forKey: .result)
        undo = result?.maybe(.undo)
    }
}

public struct JobList: Decodable, Equatable, Sendable {
    public var jobs: [Job]

    enum CodingKeys: String, CodingKey { case jobs }

    public init(from decoder: Decoder) throws {
        jobs = try decoder.container(keyedBy: CodingKeys.self).each(.jobs)
    }
}

/// One change on a server's Undo or Redo list (agent/changes.py).
public struct Change: Decodable, Equatable, Identifiable, Sendable {
    public var id: Int64
    public var title: String
    public var user: String?
    public var madeAt: Double
    /// Set on the Redo list: when it was undone.
    public var undoneAt: Double?
    /// What Undo or Redo puts back; nil for everything the backup holds.
    public var scope: [String]?
    public var backup: String
    /// When the backup that would be put back was made.
    public var backupAt: Double
    /// Play since that backup; nil when no sessions were recorded.
    public var playedSeconds: Double?

    enum CodingKeys: String, CodingKey {
        case id, title, user, scope, backup
        case madeAt = "made_at"
        case undoneAt = "undone_at"
        case backupAt = "backup_at"
        case playedSeconds = "played_seconds"
    }

    public init(
        id: Int64, title: String, user: String? = nil, madeAt: Double = 0, undoneAt: Double? = nil,
        scope: [String]? = nil, backup: String = "", backupAt: Double = 0, playedSeconds: Double? = nil
    ) {
        self.id = id
        self.title = title
        self.user = user
        self.madeAt = madeAt
        self.undoneAt = undoneAt
        self.scope = scope
        self.backup = backup
        self.backupAt = backupAt
        self.playedSeconds = playedSeconds
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(Int64.self, forKey: .id)
        title = c.value(.title, "")
        user = c.maybe(.user)
        madeAt = c.value(.madeAt, 0.0)
        undoneAt = c.maybe(.undoneAt)
        scope = c.maybe(.scope)
        backup = c.value(.backup, "")
        backupAt = c.value(.backupAt, 0.0)
        playedSeconds = c.maybe(.playedSeconds)
    }
}

/// A server's two lists: Undo reverses `undo`'s first, Redo puts back `redo`'s first.
public struct UndoRedo: Decodable, Equatable, Sendable {
    public var undo: [Change]
    public var redo: [Change]
    public var serverRunning: Bool
    public var blockedBy: String?

    enum CodingKeys: String, CodingKey {
        case undo, redo
        case serverRunning = "server_running"
        case blockedBy = "blocked_by"
    }

    public init(undo: [Change] = [], redo: [Change] = [], serverRunning: Bool = false, blockedBy: String? = nil) {
        self.undo = undo
        self.redo = redo
        self.serverRunning = serverRunning
        self.blockedBy = blockedBy
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        undo = c.each(.undo)
        redo = c.each(.redo)
        serverRunning = c.value(.serverRunning, false)
        blockedBy = c.maybe(.blockedBy)
    }
}

/// What Undo or Redo did.
public struct ChangeMoved: Decodable, Equatable, Sendable {
    public var change: Change
    public var restored: String?
    public var safetyBackup: SafetyBackup?

    enum CodingKeys: String, CodingKey {
        case change, restored
        case safetyBackup = "safety_backup"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        change = try c.decode(Change.self, forKey: .change)
        restored = c.maybe(.restored)
        safetyBackup = c.maybe(.safetyBackup)
    }
}

// MARK: - Schedules

public struct Schedule: Decodable, Equatable, Identifiable, Sendable {
    public var id: Int64
    public var name: String
    public var task: String
    public var kind: String
    public var expr: String
    /// Sent back unchanged when the schedule is switched on or off.
    public var payload: [String: JSONValue]
    public var enabled: Bool
    public var nextRun: Double?
    public var lastResult: String?

    enum CodingKeys: String, CodingKey {
        case id, name, task, kind, expr, payload, enabled
        case nextRun = "next_run"
        case lastResult = "last_result"
    }

    public init(
        id: Int64, name: String = "", task: String = "", kind: String = "", expr: String = "",
        payload: [String: JSONValue] = [:], enabled: Bool = false, nextRun: Double? = nil, lastResult: String? = nil
    ) {
        self.id = id
        self.name = name
        self.task = task
        self.kind = kind
        self.expr = expr
        self.payload = payload
        self.enabled = enabled
        self.nextRun = nextRun
        self.lastResult = lastResult
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(Int64.self, forKey: .id)
        name = c.value(.name, "")
        task = c.value(.task, "")
        kind = c.value(.kind, "")
        expr = c.value(.expr, "")
        payload = c.value(.payload, [:])
        enabled = c.value(.enabled, false)
        nextRun = c.maybe(.nextRun)
        lastResult = c.maybe(.lastResult)
    }
}

public struct ScheduleList: Decodable, Equatable, Sendable {
    public var schedules: [Schedule]
    public var tasks: [String]

    enum CodingKeys: String, CodingKey { case schedules, tasks }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        schedules = c.each(.schedules)
        tasks = c.value(.tasks, [])
    }
}

public struct ScheduleSaved: Decodable, Equatable, Sendable {
    public var schedule: Schedule?
}

public struct ScheduleRan: Decodable, Equatable, Sendable {
    public var result: String?
}

/// What a schedule is sent as: the whole of it (PUT replaces it).
public struct ScheduleBody: Encodable, Equatable, Sendable {
    public var name: String
    public var task: String
    public var kind: String
    public var expr: String
    public var payload: [String: JSONValue]
    public var enabled: Bool
}

// MARK: - Performance

/// The values now. Each is nil when it couldn't be measured.
public struct Snapshot: Decodable, Equatable, Sendable {
    public var cpuPercent: Double?
    public var processCpuPercent: Double?
    public var ramPercent: Double?
    public var procRamMb: Double?
    public var diskFreeGb: Double?
    public var diskUnknownReason: String?
    public var netRecvMbS: Double?
    public var netSentMbS: Double?

    enum CodingKeys: String, CodingKey {
        case cpuPercent = "cpu_percent"
        case processCpuPercent = "process_cpu_percent"
        case ramPercent = "ram_percent"
        case procRamMb = "proc_ram_mb"
        case diskFreeGb = "disk_free_gb"
        case diskUnknownReason = "disk_unknown_reason"
        case netRecvMbS = "net_recv_mb_s"
        case netSentMbS = "net_sent_mb_s"
    }

    public init() {}
}

/// One time bucket's averages; nil where nothing was measured.
public struct SeriesPoint: Decodable, Equatable, Sendable {
    public var ts: Double
    public var cpuPercent: Double?
    public var ramUsedMb: Double?
    public var ramTotalMb: Double?
    public var procRamMb: Double?
    public var tps: Double?
    public var mspt: Double?
    public var players: Double?
    public var playersMax: Double?

    enum CodingKeys: String, CodingKey {
        case ts, tps, mspt, players
        case cpuPercent = "cpu_percent"
        case ramUsedMb = "ram_used_mb"
        case ramTotalMb = "ram_total_mb"
        case procRamMb = "proc_ram_mb"
        case playersMax = "players_max"
    }

    public init(
        ts: Double, cpuPercent: Double? = nil, ramUsedMb: Double? = nil, ramTotalMb: Double? = nil, procRamMb: Double? = nil,
        tps: Double? = nil, mspt: Double? = nil, players: Double? = nil, playersMax: Double? = nil
    ) {
        self.ts = ts
        self.cpuPercent = cpuPercent
        self.ramUsedMb = ramUsedMb
        self.ramTotalMb = ramTotalMb
        self.procRamMb = procRamMb
        self.tps = tps
        self.mspt = mspt
        self.players = players
        self.playersMax = playersMax
    }
}

public struct Series: Decodable, Equatable, Sendable {
    public var points: [SeriesPoint]
    public var hours: Double
    public var bucketSeconds: Double

    enum CodingKeys: String, CodingKey {
        case points, hours
        case bucketSeconds = "bucket_seconds"
    }

    public init(points: [SeriesPoint] = [], hours: Double = 6, bucketSeconds: Double = 60) {
        self.points = points
        self.hours = hours
        self.bucketSeconds = bucketSeconds
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        points = c.each(.points)
        hours = c.value(.hours, 6)
        bucketSeconds = c.value(.bucketSeconds, 60)
    }
}

public struct Storage: Decodable, Equatable, Sendable {
    public var worldsGb: Double?
    public var backupsGb: Double?
    public var modsGb: Double?
    public var logsGb: Double?
    public var otherGb: Double?
    public var freeGb: Double?
    public var freeUnknownReason: String?

    enum CodingKeys: String, CodingKey {
        case worldsGb = "worlds_gb"
        case backupsGb = "backups_gb"
        case modsGb = "mods_gb"
        case logsGb = "logs_gb"
        case otherGb = "other_gb"
        case freeGb = "free_gb"
        case freeUnknownReason = "free_unknown_reason"
    }
}

public struct Performance: Decodable, Equatable, Sendable {
    public var current: Snapshot
    public var series: Series
    public var sampleInterval: Double
    public var memoryLimitMb: Double?
    public var storage: Storage?

    enum CodingKeys: String, CodingKey {
        case current, series, storage
        case sampleInterval = "sample_interval"
        case memoryLimitMb = "memory_limit_mb"
    }

    public init(current: Snapshot = Snapshot(), series: Series = Series(), sampleInterval: Double = 30, memoryLimitMb: Double? = nil, storage: Storage? = nil) {
        self.current = current
        self.series = series
        self.sampleInterval = sampleInterval
        self.memoryLimitMb = memoryLimitMb
        self.storage = storage
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        current = c.value(.current, Snapshot())
        series = c.value(.series, Series())
        sampleInterval = c.value(.sampleInterval, 30)
        memoryLimitMb = c.maybe(.memoryLimitMb)
        storage = c.maybe(.storage)
    }
}

public struct HealthCheck: Decodable, Equatable, Identifiable, Sendable {
    public var name: String
    public var status: String
    public var value: JSONValue?
    public var threshold: JSONValue?
    public var detail: String?
    public var source: String?

    public var id: String { name }

    enum CodingKeys: String, CodingKey { case name, status, value, threshold, detail, source }

    public init(name: String, status: String, value: JSONValue? = nil, threshold: JSONValue? = nil, detail: String? = nil, source: String? = nil) {
        self.name = name
        self.status = status
        self.value = value
        self.threshold = threshold
        self.detail = detail
        self.source = source
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = c.value(.name, "")
        status = c.value(.status, "unknown")
        value = c.maybe(.value)
        threshold = c.maybe(.threshold)
        detail = c.maybe(.detail)
        source = c.maybe(.source)
    }
}

/// The health checks. An unknown one is never counted as passing.
public struct ServerHealth: Decodable, Equatable, Sendable {
    public var overall: String
    public var note: String?
    public var checks: [HealthCheck]

    enum CodingKeys: String, CodingKey { case overall, note, checks }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        overall = c.value(.overall, "")
        note = c.maybe(.note)
        checks = c.each(.checks)
    }
}

// MARK: - Rules

/// Backups' words, and which buttons each row offers (backups.js).
public enum Backups {
    private static let KINDS: [String: StateWords] = [
        "manual": StateWords(key: "backups.kind_manual", tone: .success),
        "scheduled": StateWords(key: "backups.kind_scheduled", tone: .neutral),
        "safety": StateWords(key: "backups.kind_safety", tone: .warning),
    ]

    /// Manual, Scheduled or the one made before a change; nil for a kind
    /// the app has no words for (then its own name is shown).
    public static func kind(_ kind: String?) -> StateWords? {
        kind.flatMap { KINDS[$0] }
    }

    private static let STATUS: [String: StateWords] = [
        "ok": StateWords(key: "backup.checked", tone: .success),
        "unverified": StateWords(key: "backup.unchecked", tone: .warning),
        "failed": StateWords(key: "backup.failed", tone: .danger),
    ]

    /// Whether the backup was checked when it was made; Unknown otherwise.
    public static func status(_ status: String?) -> StateWords {
        status.flatMap { STATUS[$0] } ?? StateWords(key: "value.unknown", tone: .neutral)
    }

    /// The second copy's state, as the agent found it just now.
    public static func copy(_ strings: Strings, _ copy: BackupCopy?) -> (text: String, tone: Tone) {
        let reason = copy?.reason ?? strings.t("value.unknown")
        switch copy?.state ?? "none" {
        case "ok": return (strings.t("offsite.copied"), .success)
        case "failed": return (strings.t("offsite.failed", ["reason": reason]), .danger)
        case "unreachable": return (strings.t("offsite.unreachable", ["reason": reason]), .warning)
        case "missing": return (strings.t("offsite.missing"), .warning)
        case "none": return (strings.t("offsite.not_copied"), .neutral)
        default: return (strings.t("value.unknown"), .neutral)
        }
    }

    /// "Copy" is offered for a checked backup without a good second copy,
    /// while second copies are on.
    public static func canCopyAgain(_ backup: Backup, offsite: Offsite?, canCreate: Bool) -> Bool {
        canCreate && !(offsite?.directory ?? "").isEmpty && backup.status == "ok" && backup.copy?.state != "ok"
    }

    /// A backup whose file is gone can't be downloaded or restored.
    public static func onDisk(_ backup: Backup) -> Bool {
        backup.exists != false
    }

    /// The newest finished change on this server that can be undone. The
    /// agent lists jobs newest first.
    /// A task's states once it is over.
    public static let FINISHED: Set<String> = ["succeeded", "failed", "interrupted"]

    /// "Kept: last 7 days, 4 weeks, 3 months"; nil when the agent didn't say.
    public static func keeping(_ strings: Strings, _ retention: Retention?) -> String? {
        guard let r = retention, let daily = r.daily, let weekly = r.weekly, let monthly = r.monthly else { return nil }
        return strings.t("backups.keeping", ["daily": daily, "weekly": weekly, "monthly": monthly])
    }

    /// What to say once Back up now finished.
    public static func made(_ strings: Strings, _ made: BackupMade) -> String {
        if let check = made.verification, check.ok, let entries = check.entries {
            return strings.t("backups.verified_toast", ["name": made.name, "entries": entries])
        }
        return strings.t("backup.done", ["name": made.name])
    }

    /// What Check found.
    public static func checked(_ strings: Strings, _ check: BackupCheck) -> String {
        check.ok
            ? strings.t("backups.verify_ok")
            : strings.t("backups.verify_failed", ["reason": check.reason ?? strings.t("value.unknown")])
    }

    /// What a restore did, with the backup made just before it.
    public static func restored(_ strings: Strings, _ result: Restored) -> String {
        let name = result.restored ?? ""
        guard let safety = result.safetyBackup?.name else {
            return strings.t("mobile.backups.restored", ["name": name])
        }
        return strings.t("mobile.backups.restored_backup", ["name": name, "safety": safety])
    }
}

/// Schedules' words and what is sent (schedules.js).
public enum Schedules {
    public static let KINDS = ["daily", "weekly", "interval"]
    /// The most the agent takes for a name and a time.
    public static let NAME_LENGTH = 80
    public static let EXPR_LENGTH = 32

    public static func kindKey(_ kind: String) -> String {
        "schedules.kind_\(kind)"
    }

    /// "Every day at 04:00"; the agent's own words for a kind the app doesn't know.
    public static func whenText(_ strings: Strings, _ schedule: Schedule) -> String {
        KINDS.contains(schedule.kind)
            ? strings.t("schedules.every_\(schedule.kind)", ["expr": schedule.expr])
            : "\(schedule.kind) \(schedule.expr)"
    }

    /// "Back up"; its own name in Technical words or when the app has none.
    public static func taskName(_ strings: Strings, _ task: String, tasks: [String]) -> String {
        !strings.technical && tasks.contains(task) && strings.has("task.\(task)") ? strings.t("task.\(task)") : task
    }

    /// The next run's time, or Off.
    public static func next(_ strings: Strings, _ schedule: Schedule) -> String {
        schedule.enabled ? Display.dateTime(strings, schedule.nextRun) : strings.t("schedules.off")
    }

    /// A new schedule; with no name it is called after its task.
    public static func newBody(_ strings: Strings, name: String, task: String, kind: String, expr: String, tasks: [String]) -> ScheduleBody {
        let trimmed = name.trimmingCharacters(in: .whitespaces)
        return ScheduleBody(
            name: trimmed.isEmpty ? taskName(strings, task, tasks: tasks) : trimmed,
            task: task, kind: kind, expr: expr.trimmingCharacters(in: .whitespaces), payload: [:], enabled: true
        )
    }

    /// The whole schedule again with only on or off changed (PUT replaces it).
    public static func toggled(_ schedule: Schedule) -> ScheduleBody {
        ScheduleBody(
            name: schedule.name, task: schedule.task, kind: schedule.kind, expr: schedule.expr,
            payload: schedule.payload, enabled: !schedule.enabled
        )
    }
}

/// Restore world's words (world.js).
public enum WorldRestore {
    /// "Yesterday, 9:00 PM": the words a person would use for a moment.
    public static func whenLabel(_ strings: Strings, _ ts: Double, now: Double, zone: TimeZone = .current, locale: Locale = .current) -> String {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = zone
        calendar.locale = locale
        let then = Date(timeIntervalSince1970: ts)
        let days = calendar.dateComponents([.day], from: calendar.startOfDay(for: then), to: calendar.startOfDay(for: Date(timeIntervalSince1970: now))).day ?? 0
        let clock = format(then, template: "jmm", zone: zone, locale: locale)
        if days <= 0 { return strings.t("world.today_at", ["time": clock]) }
        if days == 1 { return strings.t("world.yesterday_at", ["time": clock]) }
        if days < 7 {
            return strings.t("world.day_at", ["day": format(then, template: "EEEE", zone: zone, locale: locale), "time": clock])
        }
        return strings.t("world.date_at", ["date": format(then, template: "MMMd", zone: zone, locale: locale), "time": clock])
    }

    /// "2h 10m ago · about 1h 30m of play would be lost"; play not known
    /// when no sessions were recorded (never "no play").
    public static func lossLine(_ strings: Strings, _ point: WorldPoint) -> String {
        lossLine(strings, ageSeconds: point.ageSeconds, playedSeconds: point.playedSeconds)
    }

    /// The same line for a backup made `ageSeconds` ago (Undo and Redo use it too).
    public static func lossLine(_ strings: Strings, ageSeconds: Double, playedSeconds: Double?) -> String {
        let since = strings.t("world.since", ["duration": Display.duration(strings, ageSeconds)])
        let play: String
        if let played = playedSeconds {
            play = played < 60
                ? strings.t("world.no_play")
                : strings.t("world.play_lost", ["duration": Display.duration(strings, played)])
        } else {
            play = strings.t("world.play_unknown")
        }
        return "\(since) · \(play)"
    }

    /// Why nothing can be put back now, or nil when it can.
    public static func blocked(_ strings: Strings, _ timeline: WorldTimeline) -> String? {
        if timeline.serverRunning { return strings.t("world.stop_first") }
        if let job = timeline.blockedBy { return strings.t("world.busy", ["job": job]) }
        return nil
    }

    public static func done(_ strings: Strings, _ result: Restored) -> String {
        result.safetyBackup.map { strings.t("world.done_with_undo", ["name": $0.name]) } ?? strings.t("world.done")
    }

    static func format(_ date: Date, template: String, zone: TimeZone, locale: Locale) -> String {
        let formatter = DateFormatter()
        formatter.locale = locale
        formatter.timeZone = zone
        formatter.setLocalizedDateFormatFromTemplate(template)
        return formatter.string(from: date)
    }
}

/// The health checks' words (healthCard in performance.js).
public enum HealthChecks {
    private static let OVERALL: [String: StateWords] = [
        "ALL CHECKS VERIFIED": StateWords(key: "health.all_ok", tone: .success),
        "PARTIALLY VERIFIED": StateWords(key: "health.partial", tone: .neutral),
        "ATTENTION NEEDED": StateWords(key: "health.attention", tone: .danger),
    ]

    /// nil for a verdict the app has no words for (then it is shown as sent).
    public static func overall(_ overall: String) -> StateWords? {
        OVERALL[overall]
    }

    public static func tone(_ status: String) -> Tone {
        switch status {
        case "ok": return .success
        case "unknown": return .neutral
        default: return .warning
        }
    }

    /// The measured value as the agent sent it, or Unknown.
    public static func value(_ strings: Strings, _ check: HealthCheck) -> String {
        check.value?.text ?? strings.t("value.unknown")
    }

    /// "detail (limit 90) [source]".
    public static func detail(_ strings: Strings, _ check: HealthCheck) -> String {
        var out = check.detail ?? ""
        if let limit = check.threshold?.text {
            out += " (" + strings.t("health.limit", ["limit": limit]) + ")"
        }
        if let source = check.source, !source.isEmpty {
            out += " [" + source + "]"
        }
        return out.trimmingCharacters(in: .whitespaces)
    }
}

extension Display {
    /// "512 MB", "1.4 GB" (fmt.bytes); Unknown when it wasn't measured.
    public static func bytes(_ strings: Strings, _ n: Int64?) -> String {
        guard let n = n else { return strings.t("value.unknown") }
        let units = ["B", "KB", "MB", "GB", "TB"]
        var value = Double(n)
        var i = 0
        while value >= 1024 && i < units.count - 1 {
            value /= 1024
            i += 1
        }
        return "\(fixed(value, value >= 100 || i == 0 ? 0 : 1)) \(units[i])"
    }

    /// "12.3 GB", or Unknown.
    public static func gb(_ strings: Strings, _ n: Double?) -> String {
        n.map { "\(fixed($0, 1)) GB" } ?? strings.t("value.unknown")
    }

    /// "42%", or Unknown.
    public static func pct(_ strings: Strings, _ n: Double?) -> String {
        n.map { "\(fixed($0, 0))%" } ?? strings.t("value.unknown")
    }

    /// "800 MB" or "2.5 GB"; nil when it wasn't measured (fmt.memory).
    public static func memory(_ mb: Double?) -> String? {
        guard let mb = mb else { return nil }
        return mb >= 1024 ? "\(fixed(mb / 1024, 1)) GB" : "\(fixed(mb, 0)) MB"
    }

    /// A number with `places` decimals, the same in every language (the
    /// dashboard's toFixed).
    public static func fixed(_ value: Double, _ places: Int) -> String {
        String(format: "%.\(places)f", locale: Locale(identifier: "en_US_POSIX"), value)
    }

    /// "Oct 10, 2026 at 2:05 PM" in the phone's language and time zone
    /// (fmt.time); "Never" when there is no time.
    public static func dateTime(_ strings: Strings, _ ts: Double?, zone: TimeZone = .current, locale: Locale = .current) -> String {
        guard let ts = ts, ts > 0 else { return strings.t("time.never") }
        let formatter = DateFormatter()
        formatter.locale = locale
        formatter.timeZone = zone
        formatter.dateStyle = .medium
        formatter.timeStyle = .short
        return formatter.string(from: Date(timeIntervalSince1970: ts))
    }
}

/// Undo and Redo: the two lists of changes (changesCard and moveChange in backups.js).
public enum ChangeList {
    /// How many changes past the newest the screen lists ("Pressing Undo again goes on to").
    public static let LATER = 3

    /// Whether the Undo ("undo") or Redo ("redo") button works now: the
    /// person may restore, there is something to move and no task holds the server.
    public static func canMove(_ changes: UndoRedo, _ direction: String, canRestore: Bool) -> Bool {
        let list = direction == "undo" ? changes.undo : changes.redo
        return canRestore && !list.isEmpty && changes.blockedBy == nil
    }

    /// The first line: the newest change, or that nothing is left to undo.
    public static func next(_ strings: Strings, _ changes: UndoRedo, now: Double) -> String {
        guard let change = changes.undo.first else { return strings.t("changes.nothing_to_undo") }
        return strings.t("changes.next_undo", [
            "title": change.title,
            "when": Display.ago(strings, change.madeAt, now: now),
            "who": who(strings, change),
        ])
    }

    /// The change Redo would put back, or nil when nothing was undone.
    public static func nextRedo(_ strings: Strings, _ changes: UndoRedo, now: Double) -> String? {
        guard let change = changes.redo.first else { return nil }
        return strings.t("changes.next_redo", ["title": change.title, "when": Display.ago(strings, change.undoneAt, now: now)])
    }

    /// The changes after the newest, for "Pressing Undo again goes on to".
    public static func later(_ strings: Strings, _ changes: UndoRedo, now: Double) -> [String] {
        changes.undo.dropFirst().prefix(LATER).map {
            strings.t("mobile.changes.later_item", ["title": $0.title, "when": Display.ago(strings, $0.madeAt, now: now), "who": who(strings, $0)])
        }
    }

    /// The undone changes after the one Redo puts back, for "Pressing Redo again goes on to".
    public static func laterRedo(_ strings: Strings, _ changes: UndoRedo, now: Double) -> [String] {
        changes.redo.dropFirst().prefix(LATER).map {
            strings.t("mobile.changes.later_redo_item", ["title": $0.title, "when": Display.ago(strings, $0.undoneAt, now: now), "who": who(strings, $0)])
        }
    }

    private static func who(_ strings: Strings, _ change: Change) -> String { change.user ?? strings.t("value.unknown") }

    /// The question before Undo or Redo: its title, and what goes back and what would be lost.
    public static func ask(_ strings: Strings, _ direction: String, _ change: Change, now: Double) -> (title: String, body: String) {
        let what = change.scope?.joined(separator: ", ") ?? strings.t("changes.everything")
        let body = strings.t("changes.\(direction)_body", ["what": what, "when": Display.dateTime(change.backupAt)])
        let loss = WorldRestore.lossLine(strings, ageSeconds: Swift.max(0, now - change.backupAt), playedSeconds: change.playedSeconds)
        return (
            strings.t("changes.\(direction)_title", ["title": change.title]),
            [body, loss, strings.t("changes.server_stops")].joined(separator: "\n\n")
        )
    }

    public static func done(_ strings: Strings, _ direction: String, _ moved: ChangeMoved) -> String {
        strings.t("changes.\(direction)_done", ["title": moved.change.title])
    }
}
