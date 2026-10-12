import Foundation

// What the Mods / Plugins / Packs and Game settings screens read. Mirrors
// mobile/android/core's ContentModels.kt. As in Pages.swift, only the fields
// the app uses are read, and a value the agent can leave out is nil here and
// shown as Unknown.

/// Something wrong with one mod, in the agent's words.
public struct ModIssue: Decodable, Equatable, Sendable {
    public var kind: String
    public var severity: String
    public var detail: String

    enum CodingKeys: String, CodingKey { case kind, severity, detail }

    public init(kind: String = "", severity: String = "info", detail: String = "") {
        self.kind = kind
        self.severity = severity
        self.detail = detail
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        kind = c.value(.kind, "")
        severity = c.value(.severity, "info")
        detail = c.value(.detail, "")
    }
}

/// A newer version found on Modrinth at the agent's last check.
public struct ModUpdate: Decodable, Equatable, Sendable {
    public var latestVersion: String
    public var versionId: String?

    enum CodingKeys: String, CodingKey {
        case latestVersion = "latest_version"
        case versionId = "version_id"
    }

    public init(latestVersion: String, versionId: String? = nil) {
        self.latestVersion = latestVersion
        self.versionId = versionId
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        latestVersion = c.value(.latestVersion, "")
        versionId = c.maybe(.versionId)
    }
}

/// One mod or plugin in the server's folder.
public struct Mod: Decodable, Equatable, Identifiable, Sendable {
    public var filename: String
    public var modId: String
    public var name: String
    public var version: String
    public var enabled: Bool
    public var description: String?
    public var minecraftRange: String?
    /// ok, warn or error while on; disabled while off.
    public var status: String?
    public var issues: [ModIssue]
    public var updateAvailable: ModUpdate?

    public var id: String { filename }

    enum CodingKeys: String, CodingKey {
        case filename, name, version, enabled, description, status, issues
        case modId = "mod_id"
        case minecraftRange = "minecraft_range"
        case updateAvailable = "update_available"
    }

    public init(
        filename: String, modId: String = "", name: String = "", version: String = "", enabled: Bool = true,
        description: String? = nil, minecraftRange: String? = nil, status: String? = nil, issues: [ModIssue] = [],
        updateAvailable: ModUpdate? = nil
    ) {
        self.filename = filename
        self.modId = modId
        self.name = name
        self.version = version
        self.enabled = enabled
        self.description = description
        self.minecraftRange = minecraftRange
        self.status = status
        self.issues = issues
        self.updateAvailable = updateAvailable
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        filename = try c.decode(String.self, forKey: .filename)
        modId = c.value(.modId, "")
        name = c.value(.name, "")
        version = c.value(.version, "")
        enabled = c.value(.enabled, true)
        description = c.maybe(.description)
        minecraftRange = c.maybe(.minecraftRange)
        status = c.maybe(.status)
        issues = c.each(.issues)
        updateAvailable = c.maybe(.updateAvailable)
    }
}

public struct ModList: Decodable, Equatable, Sendable {
    public var mods: [Mod]
    /// Nil until the server has started once.
    public var minecraftVersion: String?
    public var serverState: String

    enum CodingKeys: String, CodingKey {
        case mods
        case minecraftVersion = "minecraft_version"
        case serverState = "server_state"
    }

    public init(mods: [Mod] = [], minecraftVersion: String? = nil, serverState: String = States.UNKNOWN) {
        self.mods = mods
        self.minecraftVersion = minecraftVersion
        self.serverState = serverState
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        mods = c.each(.mods)
        minecraftVersion = c.maybe(.minecraftVersion)
        serverState = c.value(.serverState, States.UNKNOWN)
    }
}

public struct ModChanged: Decodable, Equatable, Sendable {
    public var mod: Mod?

    enum CodingKeys: String, CodingKey { case mod }

    public init(from decoder: Decoder) throws {
        mod = try decoder.container(keyedBy: CodingKeys.self).maybe(.mod)
    }
}

public struct ModDependent: Decodable, Equatable, Sendable {
    public var name: String
    public var requires: String?

    enum CodingKeys: String, CodingKey { case name, requires }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = c.value(.name, "")
        requires = c.maybe(.requires)
    }
}

/// What else needs a mod, asked before it is removed.
public struct ModImpact: Decodable, Equatable, Sendable {
    public var dependents: [ModDependent]
    public var warning: String?

    enum CodingKeys: String, CodingKey { case dependents, warning }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        dependents = c.each(.dependents)
        warning = c.maybe(.warning)
    }
}

public struct ModRef: Decodable, Equatable, Sendable {
    public var filename: String
    public var name: String
    public var version: String

    enum CodingKeys: String, CodingKey { case filename, name, version }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        filename = c.value(.filename, "")
        name = c.value(.name, "")
        version = c.value(.version, "")
    }
}

public struct ModRemoved: Decodable, Equatable, Sendable {
    public var removed: ModRef?
}

public struct ModUpdated: Decodable, Equatable, Sendable {
    public var updated: ModRef?
    public var previousVersion: String?

    enum CodingKeys: String, CodingKey {
        case updated
        case previousVersion = "previous_version"
    }
}

/// A copy of a mod kept on this server, which it can roll back to.
public struct ModVersion: Decodable, Equatable, Identifiable, Sendable {
    public var version: String?
    public var filename: String
    public var archivePath: String
    public var createdAt: Double
    public var isCurrent: Bool
    /// False when the kept file has gone.
    public var exists: Bool

    public var id: String { archivePath }

    enum CodingKeys: String, CodingKey {
        case version, filename, exists
        case archivePath = "archive_path"
        case createdAt = "created_at"
        case isCurrent = "is_current"
    }

    public init(version: String? = nil, filename: String = "", archivePath: String, createdAt: Double = 0, isCurrent: Bool = false, exists: Bool = false) {
        self.version = version
        self.filename = filename
        self.archivePath = archivePath
        self.createdAt = createdAt
        self.isCurrent = isCurrent
        self.exists = exists
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        version = c.maybe(.version)
        filename = c.value(.filename, "")
        archivePath = try c.decode(String.self, forKey: .archivePath)
        createdAt = c.value(.createdAt, 0)
        isCurrent = c.value(.isCurrent, false)
        exists = c.value(.exists, false)
    }
}

public struct ModVersions: Decodable, Equatable, Sendable {
    public var versions: [ModVersion]

    enum CodingKeys: String, CodingKey { case versions }

    public init(from decoder: Decoder) throws {
        versions = try decoder.container(keyedBy: CodingKeys.self).each(.versions)
    }
}

public struct ModRolledBack: Decodable, Equatable, Sendable {
    public var restored: ModRef?
    public var previousVersion: String?

    enum CodingKeys: String, CodingKey {
        case restored
        case previousVersion = "previous_version"
    }
}

/// One change in the history: what, when, who, and whether it worked.
public struct ModHistoryRow: Decodable, Equatable, Sendable {
    public var ts: Double
    public var user: String?
    public var action: String
    public var modId: String?
    public var modName: String?
    public var oldVersion: String?
    public var newVersion: String?
    public var result: String
    public var detail: String?

    enum CodingKeys: String, CodingKey {
        case ts, user, action, result, detail
        case modId = "mod_id"
        case modName = "mod_name"
        case oldVersion = "old_version"
        case newVersion = "new_version"
    }

    public init(
        ts: Double = 0, user: String? = nil, action: String = "", modId: String? = nil, modName: String? = nil,
        oldVersion: String? = nil, newVersion: String? = nil, result: String = "", detail: String? = nil
    ) {
        self.ts = ts
        self.user = user
        self.action = action
        self.modId = modId
        self.modName = modName
        self.oldVersion = oldVersion
        self.newVersion = newVersion
        self.result = result
        self.detail = detail
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ts = c.value(.ts, 0)
        user = c.maybe(.user)
        action = c.value(.action, "")
        modId = c.maybe(.modId)
        modName = c.maybe(.modName)
        oldVersion = c.maybe(.oldVersion)
        newVersion = c.maybe(.newVersion)
        result = c.value(.result, "")
        detail = c.maybe(.detail)
    }
}

public struct ModHistory: Decodable, Equatable, Sendable {
    public var history: [ModHistoryRow]

    enum CodingKeys: String, CodingKey { case history }

    public init(from decoder: Decoder) throws {
        history = try decoder.container(keyedBy: CodingKeys.self).each(.history)
    }
}

/// A Modrinth search result. `iconUrl` is loaded straight from Modrinth.
public struct ModrinthHit: Decodable, Equatable, Identifiable, Sendable {
    public var slug: String
    public var title: String
    public var description: String?
    public var downloads: Int64?
    public var iconUrl: String?
    public var page: String?

    public var id: String { slug }

    enum CodingKeys: String, CodingKey {
        case slug, title, description, downloads, page
        case iconUrl = "icon_url"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        slug = c.value(.slug, "")
        title = c.value(.title, "")
        description = c.maybe(.description)
        downloads = c.maybe(.downloads)
        iconUrl = c.maybe(.iconUrl)
        page = c.maybe(.page)
    }
}

public struct ModSearch: Decodable, Equatable, Sendable {
    public var hits: [ModrinthHit]
    public var total: Int?

    enum CodingKeys: String, CodingKey { case hits, total }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        hits = c.each(.hits)
        total = c.maybe(.total)
    }
}

public struct ModrinthFile: Decodable, Equatable, Sendable {
    public var filename: String?
    public var size: Int64?

    public init(filename: String? = nil, size: Int64? = nil) {
        self.filename = filename
        self.size = size
    }
}

public struct ModrinthDependency: Decodable, Equatable, Sendable {
    public var projectId: String?
    public var type: String?

    enum CodingKeys: String, CodingKey {
        case type
        case projectId = "project_id"
    }

    public init(projectId: String? = nil, type: String? = nil) {
        self.projectId = projectId
        self.type = type
    }
}

public struct ModrinthVersion: Decodable, Equatable, Sendable {
    public var versionId: String?
    public var versionNumber: String?
    public var gameVersions: [String]
    public var dependencies: [ModrinthDependency]
    public var file: ModrinthFile?

    enum CodingKeys: String, CodingKey {
        case dependencies, file
        case versionId = "version_id"
        case versionNumber = "version_number"
        case gameVersions = "game_versions"
    }

    public init(
        versionId: String? = nil, versionNumber: String? = nil, gameVersions: [String] = [],
        dependencies: [ModrinthDependency] = [], file: ModrinthFile? = nil
    ) {
        self.versionId = versionId
        self.versionNumber = versionNumber
        self.gameVersions = gameVersions
        self.dependencies = dependencies
        self.file = file
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        versionId = c.maybe(.versionId)
        versionNumber = c.maybe(.versionNumber)
        gameVersions = c.value(.gameVersions, [])
        dependencies = c.each(.dependencies)
        file = c.maybe(.file)
    }
}

public struct ModrinthProject: Decodable, Equatable, Sendable {
    public var slug: String
    public var title: String
    public var description: String?
    public var license: String?
    public var serverSide: String?
    public var clientSide: String?
    public var iconUrl: String?
    public var page: String?

    enum CodingKeys: String, CodingKey {
        case slug, title, description, license, page
        case serverSide = "server_side"
        case clientSide = "client_side"
        case iconUrl = "icon_url"
    }

    public init(
        slug: String = "", title: String = "", description: String? = nil, license: String? = nil,
        serverSide: String? = nil, clientSide: String? = nil, iconUrl: String? = nil, page: String? = nil
    ) {
        self.slug = slug
        self.title = title
        self.description = description
        self.license = license
        self.serverSide = serverSide
        self.clientSide = clientSide
        self.iconUrl = iconUrl
        self.page = page
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        slug = c.value(.slug, "")
        title = c.value(.title, "")
        description = c.maybe(.description)
        license = c.maybe(.license)
        serverSide = c.maybe(.serverSide)
        clientSide = c.maybe(.clientSide)
        iconUrl = c.maybe(.iconUrl)
        page = c.maybe(.page)
    }
}

/// A Modrinth project and its versions that fit this server, newest first.
public struct ModProject: Decodable, Equatable, Sendable {
    public var project: ModrinthProject
    public var versions: [ModrinthVersion]

    enum CodingKeys: String, CodingKey { case project, versions }

    public init(project: ModrinthProject, versions: [ModrinthVersion]) {
        self.project = project
        self.versions = versions
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        project = c.value(.project, ModrinthProject())
        versions = c.each(.versions)
    }
}

public struct DependencyNeeded: Decodable, Equatable, Sendable {
    public var modId: String
    public var title: String?
    public var installed: Bool

    enum CodingKeys: String, CodingKey {
        case title, installed
        case modId = "mod_id"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        modId = c.value(.modId, "")
        title = c.maybe(.title)
        installed = c.value(.installed, false)
    }
}

public struct ModInstalled: Decodable, Equatable, Sendable {
    public var installed: ModRef?
    public var dependenciesRequired: [DependencyNeeded]

    enum CodingKeys: String, CodingKey {
        case installed
        case dependenciesRequired = "dependencies_required"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        installed = c.maybe(.installed)
        dependenciesRequired = c.each(.dependenciesRequired)
    }
}

public struct DependencyItem: Decodable, Equatable, Sendable {
    public var modId: String
    public var name: String
    public var kind: String
    /// Minecraft, the loader or Java rather than a mod.
    public var platform: Bool
    public var status: String?
    public var rangeText: String?
    public var reason: String?

    enum CodingKeys: String, CodingKey {
        case name, kind, platform, status, reason
        case modId = "mod_id"
        case rangeText = "range_text"
    }

    public init(modId: String, name: String = "", kind: String = "", platform: Bool = false, status: String? = nil, rangeText: String? = nil, reason: String? = nil) {
        self.modId = modId
        self.name = name
        self.kind = kind
        self.platform = platform
        self.status = status
        self.rangeText = rangeText
        self.reason = reason
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        modId = try c.decode(String.self, forKey: .modId)
        name = c.value(.name, "")
        kind = c.value(.kind, "")
        platform = c.value(.platform, false)
        status = c.maybe(.status)
        rangeText = c.maybe(.rangeText)
        reason = c.maybe(.reason)
    }
}

public struct DependencyReport: Decodable, Equatable, Sendable {
    public var items: [DependencyItem]

    enum CodingKeys: String, CodingKey { case items }

    public init(items: [DependencyItem]) {
        self.items = items
    }

    public init(from decoder: Decoder) throws {
        items = try decoder.container(keyedBy: CodingKeys.self).each(.items)
    }
}

public struct PlannedDependency: Decodable, Equatable, Sendable {
    public var modId: String
    public var title: String?
    public var versionNumber: String?
    public var size: Int64?

    enum CodingKeys: String, CodingKey {
        case title, size
        case modId = "mod_id"
        case versionNumber = "version_number"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        modId = c.value(.modId, "")
        title = c.maybe(.title)
        versionNumber = c.maybe(.versionNumber)
        size = c.maybe(.size)
    }
}

/// One the app can't install by itself, with a page to get it by hand.
public struct UnresolvableDependency: Decodable, Equatable, Sendable {
    public var modId: String
    public var name: String?
    public var reason: String
    public var page: String?

    enum CodingKeys: String, CodingKey {
        case name, reason, page
        case modId = "mod_id"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        modId = c.value(.modId, "")
        name = c.maybe(.name)
        reason = c.value(.reason, "")
        page = c.maybe(.page)
    }
}

/// What "Install the missing ones" would download. Nothing is yet.
public struct DependencyPlan: Decodable, Equatable, Sendable {
    public var items: [PlannedDependency]
    public var unresolvable: [UnresolvableDependency]

    enum CodingKeys: String, CodingKey { case items, unresolvable }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        items = c.each(.items)
        unresolvable = c.each(.unresolvable)
    }
}

public struct DependencyResult: Decodable, Equatable, Sendable {
    public var title: String
    public var result: String
    public var detail: String?

    enum CodingKeys: String, CodingKey { case title, result, detail }

    public init(title: String, result: String, detail: String? = nil) {
        self.title = title
        self.result = result
        self.detail = detail
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        title = c.value(.title, "")
        result = c.value(.result, "")
        detail = c.maybe(.detail)
    }
}

public struct DependencyInstall: Decodable, Equatable, Sendable {
    public var results: [DependencyResult]

    enum CodingKeys: String, CodingKey { case results }

    public init(from decoder: Decoder) throws {
        results = try decoder.container(keyedBy: CodingKeys.self).each(.results)
    }
}

public struct ModUploaded: Decodable, Equatable, Sendable {
    public var installed: ModRef?
}

/// A mod Update all would change. Turned-off ones are listed, not ticked.
public struct UpdateAllRow: Decodable, Equatable, Identifiable, Sendable {
    public var modId: String
    public var name: String
    public var filename: String
    public var enabled: Bool
    public var installedVersion: String
    public var latestVersion: String
    public var versionId: String?

    public var id: String { filename }

    enum CodingKeys: String, CodingKey {
        case name, filename, enabled
        case modId = "mod_id"
        case installedVersion = "installed_version"
        case latestVersion = "latest_version"
        case versionId = "version_id"
    }

    public init(
        modId: String = "", name: String = "", filename: String, enabled: Bool = true,
        installedVersion: String = "", latestVersion: String = "", versionId: String? = nil
    ) {
        self.modId = modId
        self.name = name
        self.filename = filename
        self.enabled = enabled
        self.installedVersion = installedVersion
        self.latestVersion = latestVersion
        self.versionId = versionId
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        modId = c.value(.modId, "")
        name = c.value(.name, "")
        filename = try c.decode(String.self, forKey: .filename)
        enabled = c.value(.enabled, true)
        installedVersion = c.value(.installedVersion, "")
        latestVersion = c.value(.latestVersion, "")
        versionId = c.maybe(.versionId)
    }
}

/// One Modrinth couldn't be asked about, with the reason.
public struct UpdateAllUnchecked: Decodable, Equatable, Sendable {
    public var name: String
    public var reason: String

    enum CodingKeys: String, CodingKey { case name, reason }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = c.value(.name, "")
        reason = c.value(.reason, "")
    }
}

public struct UpdateAllPlan: Decodable, Equatable, Sendable {
    public var updates: [UpdateAllRow]
    public var unchecked: [UpdateAllUnchecked]
    public var serverRunning: Bool
    public var blockedBy: String?

    enum CodingKeys: String, CodingKey {
        case updates, unchecked
        case serverRunning = "server_running"
        case blockedBy = "blocked_by"
    }

    public init(updates: [UpdateAllRow] = [], unchecked: [UpdateAllUnchecked] = [], serverRunning: Bool = false, blockedBy: String? = nil) {
        self.updates = updates
        self.unchecked = unchecked
        self.serverRunning = serverRunning
        self.blockedBy = blockedBy
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        updates = c.each(.updates)
        unchecked = c.each(.unchecked)
        serverRunning = c.value(.serverRunning, false)
        blockedBy = c.maybe(.blockedBy)
    }
}

public struct UpdateAllDone: Decodable, Equatable, Sendable {
    public var name: String
    public var previousVersion: String
    public var version: String

    enum CodingKeys: String, CodingKey {
        case name, version
        case previousVersion = "previous_version"
    }

    public init(name: String, previousVersion: String, version: String) {
        self.name = name
        self.previousVersion = previousVersion
        self.version = version
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = c.value(.name, "")
        previousVersion = c.value(.previousVersion, "")
        version = c.value(.version, "")
    }
}

public struct UpdateAllResult: Decodable, Equatable, Sendable {
    public var updated: [UpdateAllDone]
    public var safetyBackup: SafetyBackup?
    public var undo: Undo?

    enum CodingKeys: String, CodingKey {
        case updated, undo
        case safetyBackup = "safety_backup"
    }

    public init(updated: [UpdateAllDone], safetyBackup: SafetyBackup? = nil, undo: Undo? = nil) {
        self.updated = updated
        self.safetyBackup = safetyBackup
        self.undo = undo
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        updated = c.each(.updated)
        safetyBackup = c.maybe(.safetyBackup)
        undo = c.maybe(.undo)
    }
}

public struct ModpackFile: Decodable, Equatable, Sendable {
    public var name: String
    public var size: Int64?
    /// download, client_only or refused.
    public var status: String
    public var reason: String?

    enum CodingKeys: String, CodingKey { case name, size, status, reason }

    public init(name: String = "", size: Int64? = nil, status: String = "", reason: String? = nil) {
        self.name = name
        self.size = size
        self.status = status
        self.reason = reason
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = c.value(.name, "")
        size = c.maybe(.size)
        status = c.value(.status, "")
        reason = c.maybe(.reason)
    }
}

/// What a modpack holds, read before anything changes.
public struct Modpack: Decodable, Equatable, Sendable {
    public var name: String
    public var minecraftVersion: String?
    public var typeName: String?
    public var loaderVersion: String?
    public var files: [ModpackFile]
    public var downloadCount: Int
    public var downloadBytes: Int64
    public var clientOnly: [String]
    public var skippedOverrides: [String]
    public var problems: [String]
    public var canImport: Bool

    enum CodingKeys: String, CodingKey {
        case name, files, problems
        case minecraftVersion = "minecraft_version"
        case typeName = "type_name"
        case loaderVersion = "loader_version"
        case downloadCount = "download_count"
        case downloadBytes = "download_bytes"
        case clientOnly = "client_only"
        case skippedOverrides = "skipped_overrides"
        case canImport = "can_import"
    }

    public init(
        name: String = "", minecraftVersion: String? = nil, typeName: String? = nil, loaderVersion: String? = nil,
        files: [ModpackFile] = [], downloadCount: Int = 0, downloadBytes: Int64 = 0, clientOnly: [String] = [],
        skippedOverrides: [String] = [], problems: [String] = [], canImport: Bool = false
    ) {
        self.name = name
        self.minecraftVersion = minecraftVersion
        self.typeName = typeName
        self.loaderVersion = loaderVersion
        self.files = files
        self.downloadCount = downloadCount
        self.downloadBytes = downloadBytes
        self.clientOnly = clientOnly
        self.skippedOverrides = skippedOverrides
        self.problems = problems
        self.canImport = canImport
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = c.value(.name, "")
        minecraftVersion = c.maybe(.minecraftVersion)
        typeName = c.maybe(.typeName)
        loaderVersion = c.maybe(.loaderVersion)
        files = c.each(.files)
        downloadCount = c.value(.downloadCount, 0)
        downloadBytes = c.value(.downloadBytes, 0)
        clientOnly = c.value(.clientOnly, [])
        skippedOverrides = c.value(.skippedOverrides, [])
        problems = c.value(.problems, [])
        canImport = c.value(.canImport, false)
    }
}

public struct ModpackInspected: Decodable, Equatable, Sendable {
    public var token: String
    public var pack: Modpack
    /// The server's software changes too (another type or Minecraft version).
    public var versionChange: Bool

    enum CodingKeys: String, CodingKey { case token, pack, into }
    enum IntoKeys: String, CodingKey { case versionChange = "version_change" }

    public init(token: String, pack: Modpack, versionChange: Bool = false) {
        self.token = token
        self.pack = pack
        self.versionChange = versionChange
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        token = try c.decode(String.self, forKey: .token)
        pack = c.value(.pack, Modpack())
        let into = try? c.nestedContainer(keyedBy: IntoKeys.self, forKey: .into)
        versionChange = into?.value(.versionChange, false) ?? false
    }
}

public struct ModpackImported: Decodable, Equatable, Sendable {
    public var name: String

    enum CodingKeys: String, CodingKey { case modpack }
    enum PackKeys: String, CodingKey { case name }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let pack = try? c.nestedContainer(keyedBy: PackKeys.self, forKey: .modpack)
        name = pack?.value(.name, "") ?? ""
    }
}

/// One Bedrock behavior or resource pack.
public struct Addon: Decodable, Equatable, Identifiable, Sendable {
    public var uuid: String
    public var name: String
    public var version: String
    public var description: String?
    /// behavior or resource.
    public var kind: String
    public var folder: String
    public var enabled: Bool

    public var id: String { uuid }

    enum CodingKeys: String, CodingKey { case uuid, name, version, description, kind, folder, enabled }

    public init(uuid: String, name: String = "", version: String = "", description: String? = nil, kind: String = "", folder: String = "", enabled: Bool = false) {
        self.uuid = uuid
        self.name = name
        self.version = version
        self.description = description
        self.kind = kind
        self.folder = folder
        self.enabled = enabled
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        uuid = try c.decode(String.self, forKey: .uuid)
        name = c.value(.name, "")
        version = c.value(.version, "")
        description = c.maybe(.description)
        kind = c.value(.kind, "")
        folder = c.value(.folder, "")
        enabled = c.value(.enabled, false)
    }
}

public struct AddonList: Decodable, Equatable, Sendable {
    public var addons: [Addon]
    /// The world the packs are on; nil before the server made one.
    public var world: String?
    public var running: Bool

    enum CodingKeys: String, CodingKey { case addons, world, running }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        addons = c.each(.addons)
        world = c.maybe(.world)
        running = c.value(.running, false)
    }
}

public struct AddonResult: Decodable, Equatable, Sendable {
    public var installed: [Addon]
    public var restartNeeded: Bool?

    enum CodingKeys: String, CodingKey {
        case installed
        case restartNeeded = "restart_needed"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        installed = c.each(.installed)
        restartNeeded = c.maybe(.restartNeeded)
    }
}

/// One setting from server.properties. `value` is typed (a word, a number,
/// true or false); nil when the file doesn't set it or can't be read.
public struct GameSetting: Decodable, Equatable, Identifiable, Sendable {
    public var key: String
    /// choice, bool, int, text, port or seed.
    public var kind: String
    public var value: JSONValue?
    public var set: Bool
    public var problem: String?
    /// The file's own text for it, as written (shown when it can't be read as a value).
    public var raw: String?
    public var minecraftDefault: String
    public var choices: [String]
    public var maxLength: Int?
    /// "world_exists" for the seed once the world is made.
    public var readOnly: String?

    public var id: String { key }

    enum CodingKeys: String, CodingKey {
        case key, kind, value, set, problem, raw, choices
        case minecraftDefault = "minecraft_default"
        case maxLength = "max_length"
        case readOnly = "read_only"
    }

    public init(
        key: String, kind: String = "text", value: JSONValue? = nil, set: Bool = false, problem: String? = nil,
        raw: String? = nil, minecraftDefault: String = "", choices: [String] = [], maxLength: Int? = nil,
        readOnly: String? = nil
    ) {
        self.key = key
        self.kind = kind
        self.value = value
        self.set = set
        self.problem = problem
        self.raw = raw
        self.minecraftDefault = minecraftDefault
        self.choices = choices
        self.maxLength = maxLength
        self.readOnly = readOnly
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        key = try c.decode(String.self, forKey: .key)
        kind = c.value(.kind, "text")
        value = c.maybe(.value)
        set = c.value(.set, false)
        problem = c.maybe(.problem)
        raw = c.maybe(.raw)
        minecraftDefault = c.value(.minecraftDefault, "")
        choices = c.value(.choices, [])
        maxLength = c.maybe(.maxLength)
        readOnly = c.maybe(.readOnly)
    }
}

public struct GameSettings: Decodable, Equatable, Sendable {
    public var file: String
    public var exists: Bool
    public var fields: [GameSetting]
    public var running: Bool
    public var restartNeeded: Bool
    /// The whole file as it is now, for the Technical mode editor.
    public var text: String

    enum CodingKeys: String, CodingKey {
        case file, exists, fields, running, text
        case restartNeeded = "restart_needed"
    }

    public init(file: String = "", exists: Bool = false, fields: [GameSetting] = [], running: Bool = false,
                restartNeeded: Bool = false, text: String = "") {
        self.file = file
        self.exists = exists
        self.fields = fields
        self.running = running
        self.restartNeeded = restartNeeded
        self.text = text
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        file = c.value(.file, "")
        exists = c.value(.exists, false)
        fields = c.each(.fields)
        running = c.value(.running, false)
        restartNeeded = c.value(.restartNeeded, false)
        text = c.value(.text, "")
    }
}

public struct GameSettingsSaved: Decodable, Equatable, Sendable {
    public var keys: [String]
    public var nothingChanged: Bool?
    public var running: Bool
    public var restartNeeded: Bool

    enum CodingKeys: String, CodingKey {
        case keys, running
        case nothingChanged = "nothing_changed"
        case restartNeeded = "restart_needed"
    }

    public init(keys: [String] = [], nothingChanged: Bool? = nil, running: Bool = false, restartNeeded: Bool = false) {
        self.keys = keys
        self.nothingChanged = nothingChanged
        self.running = running
        self.restartNeeded = restartNeeded
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        keys = c.value(.keys, [])
        nothingChanged = c.maybe(.nothingChanged)
        running = c.value(.running, false)
        restartNeeded = c.value(.restartNeeded, false)
    }
}
