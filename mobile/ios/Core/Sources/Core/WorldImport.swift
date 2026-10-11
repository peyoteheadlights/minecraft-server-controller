import Foundation

/// Bringing a world in (a zip from the phone, a folder on the PC or one of
/// single-player's saves) and taking this server's world home as a zip
/// (world.js). A world is read and shown first; it replaces this one only
/// after a confirm, with a backup first that Undo puts back. Mirrors the
/// Android core.
public enum WorldImport {
    /// What the phone may send: a Java world's zip, a Bedrock .mcworld or .mctemplate.
    public static let SUFFIXES = [".zip", ".mcworld", ".mctemplate"]

    public static func canImport(_ me: Me?) -> Bool { me?.can(Permissions.WORLD_REPLACE) == true }

    public static func canDownload(_ me: Me?) -> Bool { me?.can(Permissions.BACKUPS_DOWNLOAD) == true }

    public static func accepts(_ fileName: String) -> Bool {
        let lower = fileName.lowercased()
        return SUFFIXES.contains { lower.hasSuffix($0) }
    }

    /// Why no world can be brought in now, or nil when it can.
    public static func blocked(_ strings: Strings, _ timeline: WorldTimeline) -> String? {
        if timeline.serverRunning { return strings.t("import.stop_first") }
        if let job = timeline.blockedBy { return strings.t("world.busy", ["job": job]) }
        return nil
    }

    public static func title(_ read: WorldRead) -> String { read.world.name ?? read.world.folderName }

    /// Name, version, size and last played, as label and value; Unknown when not read.
    public static func facts(_ strings: Strings, _ world: WorldInfo, zone: TimeZone = .current, locale: Locale = .current) -> [(String, String)] {
        let played = world.lastPlayed.flatMap { $0 > 0 ? Display.dateTime(strings, $0, zone: zone, locale: locale) : nil }
        return [
            (strings.t("import.name"), world.name ?? world.folderName),
            (strings.t("import.version"), world.version ?? strings.t("value.unknown")),
            (strings.t("import.size"), strings.t("import.size_value", ["size": Display.bytes(strings, world.sizeBytes), "files": String(world.files)])),
            (strings.t("import.last_played"), played ?? strings.t("value.unknown")),
        ]
    }

    /// What the person should know before replacing: a level.dat not fully
    /// read, the wrong edition, a newer game version, where a Bedrock world goes.
    public static func lines(_ strings: Strings, _ read: WorldRead) -> [VersionChange.Line] {
        var out: [VersionChange.Line] = []
        if let problem = read.world.readProblem {
            out.append(VersionChange.Line(text: strings.t("import.read_problem", ["problem": problem]), tone: .warning))
        }
        if !read.editionMatches {
            out.append(VersionChange.Line(text: strings.t(read.world.edition == "bedrock" ? "import.is_bedrock" : "import.is_java"), tone: .danger))
        }
        if read.newerThanServer == true {
            out.append(VersionChange.Line(
                text: strings.t("import.newer", ["world": read.world.version ?? "", "server": read.serverVersion ?? ""]), tone: .warning
            ))
        }
        if let level = read.levelName {
            out.append(VersionChange.Line(text: strings.t("import.bedrock_level", ["name": level]), tone: .neutral))
        }
        return out
    }

    /// The agent refuses a world of the other edition, so it isn't offered.
    public static func canUse(_ read: WorldRead) -> Bool { read.editionMatches }

    public static func done(_ strings: Strings, _ result: WorldImported) -> String {
        strings.t(result.undo != nil ? "import.done_with_undo" : "import.done")
    }
}

/// A world read before it replaces anything (bringing a world in).
public struct WorldInfo: Decodable, Equatable, Sendable {
    public var source: String
    public var folderName: String
    public var name: String?
    public var version: String?
    public var lastPlayed: Double?
    public var sizeBytes: Int64
    public var files: Int
    public var readProblem: String?
    public var edition: String

    enum CodingKeys: String, CodingKey {
        case source, name, version, files, edition
        case folderName = "folder_name"
        case lastPlayed = "last_played"
        case sizeBytes = "size_bytes"
        case readProblem = "read_problem"
    }

    public init(source: String = "", folderName: String = "", name: String? = nil, version: String? = nil, lastPlayed: Double? = nil, sizeBytes: Int64 = 0, files: Int = 0, readProblem: String? = nil, edition: String = "java") {
        self.source = source
        self.folderName = folderName
        self.name = name
        self.version = version
        self.lastPlayed = lastPlayed
        self.sizeBytes = sizeBytes
        self.files = files
        self.readProblem = readProblem
        self.edition = edition
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        source = c.value(.source, "")
        folderName = c.value(.folderName, "")
        name = c.maybe(.name)
        version = c.maybe(.version)
        lastPlayed = c.maybe(.lastPlayed)
        sizeBytes = c.value(.sizeBytes, 0)
        files = c.value(.files, 0)
        readProblem = c.maybe(.readProblem)
        edition = c.value(.edition, "java")
    }
}

/// An uploaded or picked world and whether it fits this server. Nothing
/// changes until it is imported with `token`.
public struct WorldRead: Decodable, Equatable, Sendable, Identifiable {
    public var token: String
    public var world: WorldInfo
    public var editionMatches: Bool
    public var serverEdition: String
    public var serverVersion: String?
    public var newerThanServer: Bool?
    public var levelName: String?

    public var id: String { token }

    enum CodingKeys: String, CodingKey {
        case token, world
        case editionMatches = "edition_matches"
        case serverEdition = "server_edition"
        case serverVersion = "server_version"
        case newerThanServer = "newer_than_server"
        case levelName = "level_name"
    }

    public init(token: String, world: WorldInfo, editionMatches: Bool = false, serverEdition: String = "java", serverVersion: String? = nil, newerThanServer: Bool? = nil, levelName: String? = nil) {
        self.token = token
        self.world = world
        self.editionMatches = editionMatches
        self.serverEdition = serverEdition
        self.serverVersion = serverVersion
        self.newerThanServer = newerThanServer
        self.levelName = levelName
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        token = try c.decode(String.self, forKey: .token)
        world = try c.decode(WorldInfo.self, forKey: .world)
        editionMatches = c.value(.editionMatches, false)
        serverEdition = c.value(.serverEdition, "java")
        serverVersion = c.maybe(.serverVersion)
        newerThanServer = c.maybe(.newerThanServer)
        levelName = c.maybe(.levelName)
    }
}

public struct SavedWorld: Decodable, Equatable, Sendable {
    public var folder: String
    public var path: String
    public var modified: Double

    enum CodingKeys: String, CodingKey {
        case folder, path, modified
    }

    public init(folder: String = "", path: String = "", modified: Double = 0) {
        self.folder = folder
        self.path = path
        self.modified = modified
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        folder = c.value(.folder, "")
        path = c.value(.path, "")
        modified = c.value(.modified, 0)
    }
}

/// Single-player's worlds on the PC; `folder` is nil when it has none.
public struct SavedWorlds: Decodable, Equatable, Sendable {
    public var folder: String?
    public var worlds: [SavedWorld]

    enum CodingKeys: String, CodingKey {
        case folder, worlds
    }

    public init(folder: String? = nil, worlds: [SavedWorld] = []) {
        self.folder = folder
        self.worlds = worlds
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        folder = c.maybe(.folder)
        worlds = c.each(.worlds)
    }
}

public struct WorldImported: Decodable, Equatable, Sendable {
    public var jobId: String?
    public var world: WorldInfo
    public var safetyBackup: SafetyBackup?
    public var undo: Undo?

    enum CodingKeys: String, CodingKey {
        case world, undo
        case jobId = "job_id"
        case safetyBackup = "safety_backup"
    }

    public init(jobId: String? = nil, world: WorldInfo, safetyBackup: SafetyBackup? = nil, undo: Undo? = nil) {
        self.jobId = jobId
        self.world = world
        self.safetyBackup = safetyBackup
        self.undo = undo
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        jobId = c.maybe(.jobId)
        world = try c.decode(WorldInfo.self, forKey: .world)
        safetyBackup = c.maybe(.safetyBackup)
        undo = c.maybe(.undo)
    }
}

/// The world zipped for single-player, downloaded with `token`.
public struct WorldPacked: Decodable, Equatable, Sendable {
    public var token: String
    public var files: Int
    public var sizeBytes: Int64?
    public var filename: String

    enum CodingKeys: String, CodingKey {
        case token, files, filename
        case sizeBytes = "size_bytes"
    }

    public init(token: String, files: Int = 0, sizeBytes: Int64? = nil, filename: String = "world.zip") {
        self.token = token
        self.files = files
        self.sizeBytes = sizeBytes
        self.filename = filename
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        token = try c.decode(String.self, forKey: .token)
        files = c.value(.files, 0)
        sizeBytes = c.maybe(.sizeBytes)
        filename = c.value(.filename, "world.zip")
    }
}
