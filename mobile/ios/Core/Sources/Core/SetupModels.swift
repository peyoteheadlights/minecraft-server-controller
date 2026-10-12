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

/// The cores a running server got, read back from it.
public struct CpuApplied: Decodable, Equatable, Sendable {
    public var ok: Bool
    public var applied: [Int]?
    public var reason: String?

    enum CodingKeys: String, CodingKey { case ok, applied, reason }

    public init(ok: Bool = false, applied: [Int]? = nil, reason: String? = nil) {
        self.ok = ok
        self.applied = applied
        self.reason = reason
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ok = c.value(.ok, false)
        applied = c.maybe(.applied)
        reason = c.maybe(.reason)
    }
}

public struct ServerSettingsSaved: Decodable, Equatable, Sendable {
    public var applied: [String: JSONValue]
    /// Each refused key with the agent's reason.
    public var rejected: [String: String]
    /// Only when the server is running.
    public var cpuCores: CpuApplied?

    enum CodingKeys: String, CodingKey {
        case applied, rejected
        case cpuCores = "cpu_cores"
    }

    public init(applied: [String: JSONValue] = [:], rejected: [String: String] = [:], cpuCores: CpuApplied? = nil) {
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

public struct MemoryServer: Decodable, Equatable, Sendable {
    public var id: String
    public var name: String
    public var limitMb: Int?
    public var running: Bool
    public var isThis: Bool

    enum CodingKeys: String, CodingKey {
        case id, name, running
        case limitMb = "limit_mb"
        case isThis = "this"
    }

    public init(id: String, name: String = "", limitMb: Int? = nil, running: Bool = false, isThis: Bool = false) {
        self.id = id
        self.name = name
        self.limitMb = limitMb
        self.running = running
        self.isThis = isThis
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = c.value(.name, "")
        limitMb = c.maybe(.limitMb)
        running = c.value(.running, false)
        isThis = c.value(.isThis, false)
    }
}

/// The memory slider: bounded by the PC's measured memory.
public struct MemoryOverview: Decodable, Equatable, Sendable {
    /// nil when it couldn't be measured: the slider is off then.
    public var totalMb: Int?
    public var limitMb: Int?
    public var jvmArgs: [String]
    public var takesMemoryLimit: Bool
    public var minMb: Int
    public var stepMb: Int
    public var servers: [MemoryServer]
    public var running: Bool

    enum CodingKeys: String, CodingKey {
        case servers, running
        case totalMb = "total_mb"
        case limitMb = "limit_mb"
        case jvmArgs = "jvm_args"
        case takesMemoryLimit = "takes_memory_limit"
        case minMb = "min_mb"
        case stepMb = "step_mb"
    }

    public init(totalMb: Int? = nil, limitMb: Int? = nil, jvmArgs: [String] = [], takesMemoryLimit: Bool = false,
                minMb: Int = 1024, stepMb: Int = 512, servers: [MemoryServer] = [], running: Bool = false) {
        self.totalMb = totalMb
        self.limitMb = limitMb
        self.jvmArgs = jvmArgs
        self.takesMemoryLimit = takesMemoryLimit
        self.minMb = minMb
        self.stepMb = stepMb
        self.servers = servers
        self.running = running
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        totalMb = c.maybe(.totalMb)
        limitMb = c.maybe(.limitMb)
        jvmArgs = c.value(.jvmArgs, [])
        takesMemoryLimit = c.value(.takesMemoryLimit, false)
        minMb = c.value(.minMb, 1024)
        stepMb = c.value(.stepMb, 512)
        servers = c.each(.servers)
        running = c.value(.running, false)
    }
}

/// One kind of server, with what it can do (agent/servertypes).
public struct ServerTypeInfo: Decodable, Equatable, Sendable {
    public var id: String
    public var name: String
    public var edition: String
    public var content: String?
    public var ease: String?
    public var snapshots: Bool
    public var picksLoader: Bool
    public var loaderName: String?
    public var latestOnly: Bool
    public var takesMemoryLimit: Bool
    public var crossplay: Bool
    public var recommended: Bool
    public var modrinth: Bool
    public var metadataFiles: [String]
    public var versionSource: String?

    enum CodingKeys: String, CodingKey {
        case id, name, edition, content, ease, snapshots, crossplay, recommended, modrinth
        case picksLoader = "picks_loader"
        case loaderName = "loader_name"
        case latestOnly = "latest_only"
        case takesMemoryLimit = "takes_memory_limit"
        case metadataFiles = "metadata_files"
        case versionSource = "version_source"
    }

    public init(id: String, name: String = "", edition: String = "java", content: String? = nil, ease: String? = nil, snapshots: Bool = false, picksLoader: Bool = false, loaderName: String? = nil, latestOnly: Bool = false, takesMemoryLimit: Bool = true, crossplay: Bool = false, recommended: Bool = false, modrinth: Bool = false, metadataFiles: [String] = [], versionSource: String? = nil) {
        self.id = id
        self.name = name
        self.edition = edition
        self.content = content
        self.ease = ease
        self.snapshots = snapshots
        self.picksLoader = picksLoader
        self.loaderName = loaderName
        self.latestOnly = latestOnly
        self.takesMemoryLimit = takesMemoryLimit
        self.crossplay = crossplay
        self.recommended = recommended
        self.modrinth = modrinth
        self.metadataFiles = metadataFiles
        self.versionSource = versionSource
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = c.value(.name, "")
        edition = c.value(.edition, "java")
        content = c.maybe(.content)
        ease = c.maybe(.ease)
        snapshots = c.value(.snapshots, false)
        picksLoader = c.value(.picksLoader, false)
        loaderName = c.maybe(.loaderName)
        latestOnly = c.value(.latestOnly, false)
        takesMemoryLimit = c.value(.takesMemoryLimit, true)
        crossplay = c.value(.crossplay, false)
        recommended = c.value(.recommended, false)
        modrinth = c.value(.modrinth, false)
        metadataFiles = c.value(.metadataFiles, [])
        versionSource = c.maybe(.versionSource)
    }
}

public struct ServerTypes: Decodable, Equatable, Sendable {
    public var types: [ServerTypeInfo]
    public var recommended: String
    public var defaultType: String

    enum CodingKeys: String, CodingKey {
        case types, recommended
        case defaultType = "default"
    }

    public init(types: [ServerTypeInfo] = [], recommended: String = "", defaultType: String = "") {
        self.types = types
        self.recommended = recommended
        self.defaultType = defaultType
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        types = c.each(.types)
        recommended = c.value(.recommended, "")
        defaultType = c.value(.defaultType, "")
    }
}

/// One Minecraft version a type offers.
public struct OfferedVersion: Decodable, Equatable, Sendable {
    public var minecraft: String
    public var stable: Bool
    public var loaders: [String]
    public var javaRequired: Int?
    public var kept: Bool
    public var latest: Bool

    enum CodingKeys: String, CodingKey {
        case minecraft, stable, loaders, kept, latest
        case javaRequired = "java_required"
    }

    public init(minecraft: String, stable: Bool = true, loaders: [String] = [], javaRequired: Int? = nil, kept: Bool = false, latest: Bool = false) {
        self.minecraft = minecraft
        self.stable = stable
        self.loaders = loaders
        self.javaRequired = javaRequired
        self.kept = kept
        self.latest = latest
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        minecraft = try c.decode(String.self, forKey: .minecraft)
        stable = c.value(.stable, true)
        loaders = c.value(.loaders, [])
        javaRequired = c.maybe(.javaRequired)
        kept = c.value(.kept, false)
        latest = c.value(.latest, false)
    }
}

public struct TypeVersions: Decodable, Equatable, Sendable {
    public var type: String
    public var typeName: String
    public var latestOnly: Bool
    public var snapshots: Bool
    public var picksLoader: Bool
    public var loaderName: String?
    public var latestStable: String?
    public var source: String?
    public var versions: [OfferedVersion]
    public var sourceProblem: String?

    enum CodingKeys: String, CodingKey {
        case type, snapshots, source, versions
        case typeName = "type_name"
        case latestOnly = "latest_only"
        case picksLoader = "picks_loader"
        case loaderName = "loader_name"
        case latestStable = "latest_stable"
        case sourceProblem = "source_problem"
    }

    public init(type: String = "", typeName: String = "", latestOnly: Bool = false, snapshots: Bool = false, picksLoader: Bool = false, loaderName: String? = nil, latestStable: String? = nil, source: String? = nil, versions: [OfferedVersion] = [], sourceProblem: String? = nil) {
        self.type = type
        self.typeName = typeName
        self.latestOnly = latestOnly
        self.snapshots = snapshots
        self.picksLoader = picksLoader
        self.loaderName = loaderName
        self.latestStable = latestStable
        self.source = source
        self.versions = versions
        self.sourceProblem = sourceProblem
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        type = c.value(.type, "")
        typeName = c.value(.typeName, "")
        latestOnly = c.value(.latestOnly, false)
        snapshots = c.value(.snapshots, false)
        picksLoader = c.value(.picksLoader, false)
        loaderName = c.maybe(.loaderName)
        latestStable = c.maybe(.latestStable)
        source = c.maybe(.source)
        versions = c.each(.versions)
        sourceProblem = c.maybe(.sourceProblem)
    }
}

public struct LastVersionChange: Decodable, Equatable, Sendable {
    public var at: Double?
    public var type: String?
    public var minecraftVersion: String?
    public var canRollBack: Bool

    enum CodingKeys: String, CodingKey {
        case at, type
        case minecraftVersion = "minecraft_version"
        case canRollBack = "can_roll_back"
    }

    public init(at: Double? = nil, type: String? = nil, minecraftVersion: String? = nil, canRollBack: Bool = false) {
        self.at = at
        self.type = type
        self.minecraftVersion = minecraftVersion
        self.canRollBack = canRollBack
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        at = c.maybe(.at)
        type = c.maybe(.type)
        minecraftVersion = c.maybe(.minecraftVersion)
        canRollBack = c.value(.canRollBack, false)
    }
}

/// A server's type and version as its console reported them; nil is Unknown.
public struct ServerVersion: Decodable, Equatable, Sendable {
    public var type: String
    public var capabilities: ServerTypeInfo
    public var minecraftVersion: String?
    public var minecraftVersionSource: String?
    public var loaderVersion: String?
    public var loaderName: String?
    public var detectedType: String?
    public var pendingVersion: [String: JSONValue]?
    public var eulaRequired: Bool
    public var eulaUrl: String
    public var lastChange: LastVersionChange?

    enum CodingKeys: String, CodingKey {
        case type, capabilities
        case minecraftVersion = "minecraft_version"
        case minecraftVersionSource = "minecraft_version_source"
        case loaderVersion = "loader_version"
        case loaderName = "loader_name"
        case detectedType = "detected_type"
        case pendingVersion = "pending_version"
        case eulaRequired = "eula_required"
        case eulaUrl = "eula_url"
        case lastChange = "last_change"
    }

    public init(type: String = "", capabilities: ServerTypeInfo = ServerTypeInfo(id: ""), minecraftVersion: String? = nil, minecraftVersionSource: String? = nil, loaderVersion: String? = nil, loaderName: String? = nil, detectedType: String? = nil, pendingVersion: [String: JSONValue]? = nil, eulaRequired: Bool = false, eulaUrl: String = "", lastChange: LastVersionChange? = nil) {
        self.type = type
        self.capabilities = capabilities
        self.minecraftVersion = minecraftVersion
        self.minecraftVersionSource = minecraftVersionSource
        self.loaderVersion = loaderVersion
        self.loaderName = loaderName
        self.detectedType = detectedType
        self.pendingVersion = pendingVersion
        self.eulaRequired = eulaRequired
        self.eulaUrl = eulaUrl
        self.lastChange = lastChange
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        type = c.value(.type, "")
        capabilities = c.value(.capabilities, ServerTypeInfo(id: ""))
        minecraftVersion = c.maybe(.minecraftVersion)
        minecraftVersionSource = c.maybe(.minecraftVersionSource)
        loaderVersion = c.maybe(.loaderVersion)
        loaderName = c.maybe(.loaderName)
        detectedType = c.maybe(.detectedType)
        pendingVersion = c.maybe(.pendingVersion)
        eulaRequired = c.value(.eulaRequired, false)
        eulaUrl = c.value(.eulaUrl, "")
        lastChange = c.maybe(.lastChange)
    }
}

public struct PreflightSide: Decodable, Equatable, Sendable {
    public var type: String
    public var typeName: String
    public var minecraftVersion: String?
    public var loaderVersion: String?

    enum CodingKeys: String, CodingKey {
        case type
        case typeName = "type_name"
        case minecraftVersion = "minecraft_version"
        case loaderVersion = "loader_version"
    }

    public init(type: String = "", typeName: String = "", minecraftVersion: String? = nil, loaderVersion: String? = nil) {
        self.type = type
        self.typeName = typeName
        self.minecraftVersion = minecraftVersion
        self.loaderVersion = loaderVersion
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        type = c.value(.type, "")
        typeName = c.value(.typeName, "")
        minecraftVersion = c.maybe(.minecraftVersion)
        loaderVersion = c.maybe(.loaderVersion)
    }
}

public struct JavaCheck: Decodable, Equatable, Sendable {
    public var verdict: String
    public var detail: String?

    enum CodingKeys: String, CodingKey {
        case verdict, detail
    }

    public init(verdict: String = "unknown", detail: String? = nil) {
        self.verdict = verdict
        self.detail = detail
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        verdict = c.value(.verdict, "unknown")
        detail = c.maybe(.detail)
    }
}

/// What a version or type change would do, before anything happens.
public struct VersionPreflight: Decodable, Equatable, Sendable {
    public var current: PreflightSide
    public var target: PreflightSide
    public var typeChange: Bool
    public var gentleTypeChange: Bool
    public var downgradeWarning: Bool
    public var java: JavaCheck
    public var javaRequired: Int?
    public var movedAside: [String]
    public var unknownSupport: [String]
    public var notSupporting: [String]
    public var crossplay: Bool
    public var crossplayAvailable: Bool

    enum CodingKeys: String, CodingKey {
        case current, target, java, crossplay
        case typeChange = "type_change"
        case gentleTypeChange = "gentle_type_change"
        case downgradeWarning = "downgrade_warning"
        case javaRequired = "java_required"
        case movedAside = "moved_aside"
        case unknownSupport = "unknown_support"
        case notSupporting = "not_supporting"
        case crossplayAvailable = "crossplay_available"
    }

    public init(current: PreflightSide = PreflightSide(), target: PreflightSide = PreflightSide(), typeChange: Bool = false, gentleTypeChange: Bool = false, downgradeWarning: Bool = false, java: JavaCheck = JavaCheck(), javaRequired: Int? = nil, movedAside: [String] = [], unknownSupport: [String] = [], notSupporting: [String] = [], crossplay: Bool = false, crossplayAvailable: Bool = false) {
        self.current = current
        self.target = target
        self.typeChange = typeChange
        self.gentleTypeChange = gentleTypeChange
        self.downgradeWarning = downgradeWarning
        self.java = java
        self.javaRequired = javaRequired
        self.movedAside = movedAside
        self.unknownSupport = unknownSupport
        self.notSupporting = notSupporting
        self.crossplay = crossplay
        self.crossplayAvailable = crossplayAvailable
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        current = c.value(.current, PreflightSide())
        target = c.value(.target, PreflightSide())
        typeChange = c.value(.typeChange, false)
        gentleTypeChange = c.value(.gentleTypeChange, false)
        downgradeWarning = c.value(.downgradeWarning, false)
        java = c.value(.java, JavaCheck())
        javaRequired = c.maybe(.javaRequired)
        movedAside = c.value(.movedAside, [])
        unknownSupport = c.value(.unknownSupport, [])
        notSupporting = c.value(.notSupporting, [])
        crossplay = c.value(.crossplay, false)
        crossplayAvailable = c.value(.crossplayAvailable, false)
    }
}

public struct VersionChanged: Decodable, Equatable, Sendable {
    public var jobId: String
    public var verified: Bool?
    public var crossplayTurnedOff: Bool?

    enum CodingKeys: String, CodingKey {
        case verified
        case jobId = "job_id"
        case crossplayTurnedOff = "crossplay_turned_off"
    }

    public init(jobId: String = "", verified: Bool? = nil, crossplayTurnedOff: Bool? = nil) {
        self.jobId = jobId
        self.verified = verified
        self.crossplayTurnedOff = crossplayTurnedOff
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        jobId = c.value(.jobId, "")
        verified = c.maybe(.verified)
        crossplayTurnedOff = c.maybe(.crossplayTurnedOff)
    }
}

public struct VersionRolledBack: Decodable, Equatable, Sendable {
    public var jobId: String
    public var type: String

    enum CodingKeys: String, CodingKey {
        case type
        case jobId = "job_id"
    }

    public init(jobId: String = "", type: String = "") {
        self.jobId = jobId
        self.type = type
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        jobId = c.value(.jobId, "")
        type = c.value(.type, "")
    }
}

public struct EulaAccepted: Decodable, Equatable, Sendable {
    public var url: String

    enum CodingKeys: String, CodingKey {
        case url
    }

    public init(url: String = "") {
        self.url = url
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        url = c.value(.url, "")
    }
}

/// Whether Bedrock players can join this Java server (Geyser).
public struct CrossplayInfo: Decodable, Equatable, Sendable {
    public var available: Bool
    public var unavailableReason: String?
    public var enabled: Bool
    public var port: Int?
    public var defaultPort: Int
    public var suggestedPort: Int?
    public var usernamePrefix: String
    public var missingMod: String?
    public var ready: Bool
    public var differences: [String]
    public var address: String?
    public var addressUnknown: String?

    enum CodingKeys: String, CodingKey {
        case available, enabled, port, ready, differences, address
        case unavailableReason = "unavailable_reason"
        case defaultPort = "default_port"
        case suggestedPort = "suggested_port"
        case usernamePrefix = "username_prefix"
        case missingMod = "missing_mod"
        case addressUnknown = "address_unknown"
    }

    public init(available: Bool = false, unavailableReason: String? = nil, enabled: Bool = false, port: Int? = nil, defaultPort: Int = 19132, suggestedPort: Int? = nil, usernamePrefix: String = "", missingMod: String? = nil, ready: Bool = false, differences: [String] = [], address: String? = nil, addressUnknown: String? = nil) {
        self.available = available
        self.unavailableReason = unavailableReason
        self.enabled = enabled
        self.port = port
        self.defaultPort = defaultPort
        self.suggestedPort = suggestedPort
        self.usernamePrefix = usernamePrefix
        self.missingMod = missingMod
        self.ready = ready
        self.differences = differences
        self.address = address
        self.addressUnknown = addressUnknown
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        available = c.value(.available, false)
        unavailableReason = c.maybe(.unavailableReason)
        enabled = c.value(.enabled, false)
        port = c.maybe(.port)
        defaultPort = c.value(.defaultPort, 19132)
        suggestedPort = c.maybe(.suggestedPort)
        usernamePrefix = c.value(.usernamePrefix, "")
        missingMod = c.maybe(.missingMod)
        ready = c.value(.ready, false)
        differences = c.value(.differences, [])
        address = c.maybe(.address)
        addressUnknown = c.maybe(.addressUnknown)
    }
}

/// A suggested name and folder for a copy of this server.
public struct DuplicateOptions: Decodable, Equatable, Sendable {
    public var name: String
    public var directory: String
    public var running: Bool
    public var crossplay: Bool
    public var worldFolders: [String]

    enum CodingKeys: String, CodingKey {
        case name, directory, running, crossplay
        case worldFolders = "world_folders"
    }

    public init(name: String = "", directory: String = "", running: Bool = false, crossplay: Bool = false, worldFolders: [String] = []) {
        self.name = name
        self.directory = directory
        self.running = running
        self.crossplay = crossplay
        self.worldFolders = worldFolders
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = c.value(.name, "")
        directory = c.value(.directory, "")
        running = c.value(.running, false)
        crossplay = c.value(.crossplay, false)
        worldFolders = c.value(.worldFolders, [])
    }
}

public struct DuplicateStarted: Decodable, Equatable, Sendable {
    public var job: Job

    enum CodingKeys: String, CodingKey {
        case job
    }

    public init(job: Job) {
        self.job = job
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        job = try c.decode(Job.self, forKey: .job)
    }
}

/// A server taken off the list; its folder stays where it is.
public struct ServerRemoved: Decodable, Equatable, Sendable {
    public var removed: String
    public var name: String
    public var directory: String

    enum CodingKeys: String, CodingKey {
        case removed, name, directory
    }

    public init(removed: String, name: String = "", directory: String = "") {
        self.removed = removed
        self.name = name
        self.directory = directory
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        removed = try c.decode(String.self, forKey: .removed)
        name = c.value(.name, "")
        directory = c.value(.directory, "")
    }
}

public struct PcDrive: Decodable, Equatable, Sendable {
    public var name: String
    public var path: String

    enum CodingKeys: String, CodingKey {
        case name, path
    }

    public init(name: String, path: String) {
        self.name = name
        self.path = path
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = try c.decode(String.self, forKey: .name)
        path = try c.decode(String.self, forKey: .path)
    }
}

public struct PcShortcut: Decodable, Equatable, Sendable {
    public var key: String
    public var path: String

    enum CodingKeys: String, CodingKey {
        case key, path
    }

    public init(key: String, path: String) {
        self.key = key
        self.path = path
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        key = try c.decode(String.self, forKey: .key)
        path = try c.decode(String.self, forKey: .path)
    }
}

public struct PcFolder: Decodable, Equatable, Sendable {
    public var name: String
    public var path: String
    public var world: Bool

    enum CodingKeys: String, CodingKey {
        case name, path, world
    }

    public init(name: String, path: String, world: Bool = false) {
        self.name = name
        self.path = path
        self.world = world
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = try c.decode(String.self, forKey: .name)
        path = try c.decode(String.self, forKey: .path)
        world = c.value(.world, false)
    }
}

/// The folders inside one folder on the PC, names only. `path` is nil for the top: the drives and the usual shortcuts.
public struct FolderListing: Decodable, Equatable, Sendable {
    public var path: String?
    public var parent: String?
    public var folders: [PcFolder]
    public var drives: [PcDrive]
    public var shortcuts: [PcShortcut]
    public var truncated: Bool
    public var world: Bool

    enum CodingKeys: String, CodingKey {
        case path, parent, folders, drives, shortcuts, truncated, world
    }

    public init(path: String? = nil, parent: String? = nil, folders: [PcFolder] = [], drives: [PcDrive] = [], shortcuts: [PcShortcut] = [], truncated: Bool = false, world: Bool = false) {
        self.path = path
        self.parent = parent
        self.folders = folders
        self.drives = drives
        self.shortcuts = shortcuts
        self.truncated = truncated
        self.world = world
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        path = c.maybe(.path)
        parent = c.maybe(.parent)
        folders = c.each(.folders)
        drives = c.each(.drives)
        shortcuts = c.each(.shortcuts)
        truncated = c.value(.truncated, false)
        world = c.value(.world, false)
    }
}

public struct OffsiteSaved: Decodable, Equatable, Sendable {
    public var directory: String

    enum CodingKeys: String, CodingKey {
        case directory
    }

    public init(directory: String = "") {
        self.directory = directory
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        directory = c.value(.directory, "")
    }
}

/// A server folder already on the PC, now on the list.
public struct ServerAdded: Decodable, Equatable, Sendable {
    public var server: ServerRow
    public var warnings: [String]

    enum CodingKeys: String, CodingKey {
        case server, warnings
    }

    public init(server: ServerRow, warnings: [String] = []) {
        self.server = server
        self.warnings = warnings
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        server = try c.decode(ServerRow.self, forKey: .server)
        warnings = c.value(.warnings, [])
    }
}

public struct BedrockNewOptions: Decodable, Equatable, Sendable {
    public var port: Int?
    public var eulaUrl: String
    public var privacyUrl: String

    enum CodingKeys: String, CodingKey {
        case port
        case eulaUrl = "eula_url"
        case privacyUrl = "privacy_url"
    }

    public init(port: Int? = nil, eulaUrl: String = "", privacyUrl: String = "") {
        self.port = port
        self.eulaUrl = eulaUrl
        self.privacyUrl = privacyUrl
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        port = c.maybe(.port)
        eulaUrl = c.value(.eulaUrl, "")
        privacyUrl = c.value(.privacyUrl, "")
    }
}

/// What the New server steps need before anything is chosen.
public struct NewServerOptions: Decodable, Equatable, Sendable {
    public var types: [ServerTypeInfo]
    public var recommended: String
    public var memoryMb: Int?
    public var color: String?
    public var palette: [PaletteColor]
    public var eulaUrl: String
    public var bedrock: BedrockNewOptions

    enum CodingKeys: String, CodingKey {
        case types, recommended, color, palette, bedrock
        case memoryMb = "memory_mb"
        case eulaUrl = "eula_url"
    }

    public init(types: [ServerTypeInfo] = [], recommended: String = "", memoryMb: Int? = nil, color: String? = nil, palette: [PaletteColor] = [], eulaUrl: String = "", bedrock: BedrockNewOptions = BedrockNewOptions()) {
        self.types = types
        self.recommended = recommended
        self.memoryMb = memoryMb
        self.color = color
        self.palette = palette
        self.eulaUrl = eulaUrl
        self.bedrock = bedrock
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        types = c.each(.types)
        recommended = c.value(.recommended, "")
        memoryMb = c.maybe(.memoryMb)
        color = c.maybe(.color)
        palette = c.each(.palette)
        eulaUrl = c.value(.eulaUrl, "")
        bedrock = c.value(.bedrock, BedrockNewOptions())
    }
}

/// A brand-new server, set up and not started.
public struct ServerCreated: Decodable, Equatable, Sendable {
    public var serverId: String
    public var name: String
    public var jobId: String?

    enum CodingKeys: String, CodingKey {
        case name
        case serverId = "server_id"
        case jobId = "job_id"
    }

    public init(serverId: String, name: String = "", jobId: String? = nil) {
        self.serverId = serverId
        self.name = name
        self.jobId = jobId
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        serverId = try c.decode(String.self, forKey: .serverId)
        name = c.value(.name, "")
        jobId = c.maybe(.jobId)
    }
}

/// What "Create server" sends; only the person's own tick accepts the rules.
public struct NewServerRequest: Equatable, Sendable {
    public var name: String
    public var directory: String
    public var type: String
    public var minecraft: String
    public var loader: String?
    public var memoryMb: Int?
    public var color: String?
    public var eulaAccepted: Bool

    public init(name: String, directory: String, type: String, minecraft: String, loader: String?, memoryMb: Int?, color: String?, eulaAccepted: Bool) {
        self.name = name
        self.directory = directory
        self.type = type
        self.minecraft = minecraft
        self.loader = loader
        self.memoryMb = memoryMb
        self.color = color
        self.eulaAccepted = eulaAccepted
    }
}
