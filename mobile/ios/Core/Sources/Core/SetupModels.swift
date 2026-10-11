import Foundation

// What the Setup screens read (Phase 9 part 5): Server settings, version
// and type changes, the raw editors, new servers and the PC folder picker.
// As in ContentModels.swift, only the fields the app uses are listed.

public struct PaletteColor: Decodable, Equatable, Sendable {
    public var id: String
    public var name: String
    public var hex: String

    enum CodingKeys: String, CodingKey { case id, name, hex }

    public init(id: String, name: String = "", hex: String) {
        self.id = id
        self.name = name
        self.hex = hex
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = c.value(.name, "")
        hex = try c.decode(String.self, forKey: .hex)
    }
}

public struct CpuStatus: Decodable, Equatable, Sendable {
    /// nil: every core.
    public var configured: [Int]?
    /// Read from the running server; nil when it couldn't be.
    public var applied: [Int]?
    public var appliedReason: String?
    public var problems: [String]

    enum CodingKeys: String, CodingKey {
        case configured, applied, problems
        case appliedReason = "applied_reason"
    }

    public init(configured: [Int]? = nil, applied: [Int]? = nil, appliedReason: String? = nil, problems: [String] = []) {
        self.configured = configured
        self.applied = applied
        self.appliedReason = appliedReason
        self.problems = problems
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        configured = c.maybe(.configured)
        applied = c.maybe(.applied)
        appliedReason = c.maybe(.appliedReason)
        problems = c.value(.problems, [])
    }
}

public struct CpuOther: Decodable, Equatable, Sendable {
    public var id: String
    public var name: String
    public var cores: [Int]

    enum CodingKeys: String, CodingKey { case id, name, cores }

    public init(id: String, name: String = "", cores: [Int] = []) {
        self.id = id
        self.name = name
        self.cores = cores
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = c.value(.name, "")
        cores = c.value(.cores, [])
    }
}

public struct CpuOverview: Decodable, Equatable, Sendable {
    public var logicalCores: Int?
    public var supported: Bool
    public var unsupportedReason: String?
    public var others: [CpuOther]
    public var status: CpuStatus

    enum CodingKeys: String, CodingKey {
        case supported, others, status
        case logicalCores = "logical_cores"
        case unsupportedReason = "unsupported_reason"
    }

    public init(logicalCores: Int? = nil, supported: Bool = false, unsupportedReason: String? = nil, others: [CpuOther] = [], status: CpuStatus = CpuStatus()) {
        self.logicalCores = logicalCores
        self.supported = supported
        self.unsupportedReason = unsupportedReason
        self.others = others
        self.status = status
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        logicalCores = c.maybe(.logicalCores)
        supported = c.value(.supported, false)
        unsupportedReason = c.maybe(.unsupportedReason)
        others = c.each(.others)
        status = c.value(.status, CpuStatus())
    }
}

/// Sleep when empty, as measured now.
public struct SleepStatus: Decodable, Equatable, Sendable {
    public var enabled: Bool
    public var minutes: Int
    public var playersOnline: Int?
    public var stopsIn: Double?
    public var listAnswered: Bool?

    enum CodingKeys: String, CodingKey {
        case enabled, minutes
        case playersOnline = "players_online"
        case stopsIn = "stops_in"
        case listAnswered = "list_answered"
    }

    public init(enabled: Bool = false, minutes: Int = 0, playersOnline: Int? = nil, stopsIn: Double? = nil, listAnswered: Bool? = nil) {
        self.enabled = enabled
        self.minutes = minutes
        self.playersOnline = playersOnline
        self.stopsIn = stopsIn
        self.listAnswered = listAnswered
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        enabled = c.value(.enabled, false)
        minutes = c.value(.minutes, 0)
        playersOnline = c.maybe(.playersOnline)
        stopsIn = c.maybe(.stopsIn)
        listAnswered = c.maybe(.listAnswered)
    }
}

/// One server's own settings: "server" holds its name and launch settings,
/// then its crash, backup and mod settings with its own values applied.
public struct ServerSettings: Decodable, Equatable, Sendable {
    public var serverId: String
    public var server: [String: JSONValue]
    public var color: String?
    public var palette: [PaletteColor]
    public var monitor: [String: JSONValue]
    public var backups: [String: JSONValue]
    public var mods: [String: JSONValue]
    public var cpu: CpuOverview
    public var sleep: SleepStatus?

    enum CodingKeys: String, CodingKey {
        case server, color, palette, monitor, backups, mods, cpu, sleep
        case serverId = "server_id"
    }

    public init(serverId: String = "", server: [String: JSONValue] = [:], color: String? = nil, palette: [PaletteColor] = [],
                monitor: [String: JSONValue] = [:], backups: [String: JSONValue] = [:], mods: [String: JSONValue] = [:],
                cpu: CpuOverview = CpuOverview(), sleep: SleepStatus? = nil) {
        self.serverId = serverId
        self.server = server
        self.color = color
        self.palette = palette
        self.monitor = monitor
        self.backups = backups
        self.mods = mods
        self.cpu = cpu
        self.sleep = sleep
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        serverId = c.value(.serverId, "")
        server = c.value(.server, [:])
        color = c.maybe(.color)
        palette = c.each(.palette)
        monitor = c.value(.monitor, [:])
        backups = c.value(.backups, [:])
        mods = c.value(.mods, [:])
        cpu = c.value(.cpu, CpuOverview())
        sleep = c.maybe(.sleep)
    }
}

public struct ServerSettingsSaved: Decodable, Equatable, Sendable {
    public var applied: [String: JSONValue]
    /// Each refused key with the agent's reason.
    public var rejected: [String: String]
    public var cpuCores: [String: JSONValue]?

    enum CodingKeys: String, CodingKey {
        case applied, rejected
        case cpuCores = "cpu_cores"
    }

    public init(applied: [String: JSONValue] = [:], rejected: [String: String] = [:], cpuCores: [String: JSONValue]? = nil) {
        self.applied = applied
        self.rejected = rejected
        self.cpuCores = cpuCores
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        applied = c.value(.applied, [:])
        rejected = c.value(.rejected, [:])
        cpuCores = c.maybe(.cpuCores)
    }
}

public struct ColorSaved: Decodable, Equatable, Sendable {
    public var color: String

    enum CodingKeys: String, CodingKey { case color }

    public init(color: String) { self.color = color }
}
