import Foundation

/// A file picked on the phone (a .jar, a pack or a modpack). `url` is a
/// local copy the app made; it is read only while it is sent, so a big one
/// is never held in memory whole.
public struct PickedFile: Equatable, Sendable {
    public let name: String
    public let url: URL

    public init(name: String, url: URL) {
        self.name = name
        self.url = url
    }
}

/// Mods / Plugins / Packs and Game settings (mobile/api-routes.txt). Mods
/// change only while the server is stopped; the agent refuses otherwise, in
/// its own words. Installs, updates and imports answer once done, so they
/// use the slow session. Mirrors the Android client.
extension AgentClient {
    public static let SEARCH_PAGE = 20

    public func mods(serverId: String) async throws -> ModList {
        try await call("GET", content(serverId) + "/mods", as: ModList.self)
    }

    /// Turns a mod or plugin on or off without removing it.
    public func setModEnabled(serverId: String, filename: String, enabled: Bool) async throws -> ModChanged {
        try await call("POST", content(serverId) + "/mods/" + (enabled ? "enable" : "disable"), body: try fileBody(filename), as: ModChanged.self)
    }

    /// What else needs a mod, asked before removing it.
    public func modImpact(serverId: String, filename: String) async throws -> ModImpact {
        try await call("GET", content(serverId) + "/mods/impact?filename=" + AgentClient.pathSegment(filename), as: ModImpact.self)
    }

    /// Removes a mod; its file is kept so it can be put back.
    public func removeMod(serverId: String, filename: String) async throws -> ModRemoved {
        try await call("POST", content(serverId) + "/mods/remove", body: try fileBody(filename), as: ModRemoved.self)
    }

    public func updateMod(serverId: String, filename: String, versionId: String?) async throws -> ModUpdated {
        let body = try AgentClient.encode(UpdateBody(filename: filename, versionId: versionId))
        return try await call("POST", content(serverId) + "/mods/update", body: body, slow: true, as: ModUpdated.self)
    }

    /// The copies of a mod kept on this server, newest first.
    public func modVersions(serverId: String, modId: String) async throws -> ModVersions {
        try await call("GET", content(serverId) + "/mods/versions/" + AgentClient.pathSegment(modId), as: ModVersions.self)
    }

    public func rollBackMod(serverId: String, modId: String, archivePath: String) async throws -> ModRolledBack {
        let body = try AgentClient.encode(RollBackBody(modId: modId, archivePath: archivePath))
        return try await call("POST", content(serverId) + "/mods/rollback", body: body, as: ModRolledBack.self)
    }

    public func modHistory(serverId: String, limit: Int = 100) async throws -> ModHistory {
        let count = Swift.min(Swift.max(limit, 1), 500)
        return try await call("GET", content(serverId) + "/mods/history?limit=\(count)", as: ModHistory.self)
    }

    /// What Update all would change, checked on Modrinth now (a mod at a
    /// time on the PC, so it can take a while with many).
    public func updateAllPlan(serverId: String) async throws -> UpdateAllPlan {
        try await call("GET", content(serverId) + "/mods/update-all", slow: true, as: UpdateAllPlan.self)
    }

    /// Updates the ticked ones as one change (one backup, all or nothing).
    public func updateAll(serverId: String, _ body: UpdateAllBody) async throws -> UpdateAllResult {
        try await call("POST", content(serverId) + "/mods/update-all", body: try AgentClient.encode(body), slow: true, as: UpdateAllResult.self)
    }

    /// Modrinth results that fit this server's type and Minecraft version.
    public func searchMods(serverId: String, query: String, offset: Int = 0) async throws -> ModSearch {
        let path = content(serverId) + "/mods/search?q=" + AgentClient.pathSegment(query)
            + "&limit=\(AgentClient.SEARCH_PAGE)&offset=\(Swift.max(offset, 0))"
        return try await call("GET", path, as: ModSearch.self)
    }

    public func modProject(serverId: String, slug: String) async throws -> ModProject {
        try await call("GET", content(serverId) + "/mods/project/" + AgentClient.pathSegment(slug), as: ModProject.self)
    }

    public func installMod(serverId: String, slug: String, versionId: String?, withDependencies: Bool) async throws -> ModInstalled {
        let body = try AgentClient.encode(InstallBody(project: slug, versionId: versionId, installDependencies: withDependencies))
        return try await call("POST", content(serverId) + "/mods/install", body: body, slow: true, as: ModInstalled.self)
    }

    public func dependencies(serverId: String) async throws -> DependencyReport {
        try await call("GET", content(serverId) + "/mods/dependencies", as: DependencyReport.self)
    }

    /// What installing the missing ones would download. Nothing is yet.
    public func planDependencies(serverId: String) async throws -> DependencyPlan {
        try await call("POST", content(serverId) + "/mods/dependencies/plan", body: Data("{}".utf8), as: DependencyPlan.self)
    }

    public func installDependencies(serverId: String) async throws -> DependencyInstall {
        try await call("POST", content(serverId) + "/mods/dependencies/install", body: Data("{}".utf8), slow: true, as: DependencyInstall.self)
    }

    /// Adds a mod or plugin file (.jar) picked on the phone.
    public func uploadMod(serverId: String, file: PickedFile) async throws -> ModUploaded {
        try await upload(content(serverId) + "/mods/upload", file, as: ModUploaded.self)
    }

    /// Reads a modpack (.mrpack) and says what importing it here would do.
    /// Reads a pack; with `serverId`, also what importing it there would do.
    public func inspectModpack(serverId: String?, file: PickedFile) async throws -> ModpackInspected {
        let path = serverId.map { "/api/modpacks/inspect?server_id=" + AgentClient.pathSegment($0) } ?? "/api/modpacks/inspect"
        return try await upload(path, file, as: ModpackInspected.self)
    }

    /// Throws away a modpack read but not imported.
    public func forgetModpack(token: String) async throws {
        _ = try await call("DELETE", "/api/modpacks/" + AgentClient.pathSegment(token), as: Ok.self)
    }

    public func importModpack(serverId: String, token: String) async throws -> ModpackImported {
        let body = try AgentClient.encode(ImportBody(token: token, confirm: true))
        return try await call("POST", content(serverId) + "/modpack", body: body, slow: true, as: ModpackImported.self)
    }

    /// A Bedrock server's behavior and resource packs.
    public func addons(serverId: String) async throws -> AddonList {
        try await call("GET", content(serverId) + "/addons", as: AddonList.self)
    }

    public func uploadAddon(serverId: String, file: PickedFile) async throws -> AddonResult {
        try await upload(content(serverId) + "/addons/upload", file, as: AddonResult.self)
    }

    public func setAddonEnabled(serverId: String, uuid: String, enabled: Bool) async throws -> AddonResult {
        let body = try AgentClient.encode(["enabled": enabled])
        return try await call("PUT", content(serverId) + "/addons/" + AgentClient.pathSegment(uuid), body: body, as: AddonResult.self)
    }

    public func removeAddon(serverId: String, uuid: String) async throws -> AddonResult {
        try await call("DELETE", content(serverId) + "/addons/" + AgentClient.pathSegment(uuid), as: AddonResult.self)
    }

    public func gameSettings(serverId: String) async throws -> GameSettings {
        try await call("GET", content(serverId) + "/game-settings", as: GameSettings.self)
    }

    /// Saves only `values`, the ones changed. A refused one comes back as
    /// `AgentError.failed` with each value's reason in its problems.
    public func saveGameSettings(serverId: String, values: [String: JSONValue]) async throws -> GameSettingsSaved {
        let body = try AgentClient.encode(["values": JSONValue.object(values)])
        return try await call("PUT", content(serverId) + "/game-settings", body: body, as: GameSettingsSaved.self)
    }

    /// Saves the whole server.properties as typed in Technical mode. The
    /// agent still checks the known keys, and writes nothing when one fails.
    public func saveGameSettingsText(serverId: String, text: String) async throws -> GameSettingsSaved {
        let body = try AgentClient.encode(["text": JSONValue.string(text)])
        return try await call("PUT", content(serverId) + "/game-settings/raw", body: body, as: GameSettingsSaved.self)
    }

    // MARK: - Plumbing

    private func content(_ id: String) -> String {
        "/api/servers/" + AgentClient.pathSegment(id)
    }

    private func fileBody(_ filename: String) throws -> Data {
        try AgentClient.encode(["filename": filename])
    }

    /// Sends a picked file as the dashboard's upload form does (field
    /// "file"). The form is written to a file next to it and sent from
    /// there, so the phone never holds the whole file in memory.
    /// `sent` gets the bytes sent so far and the form's size.
    func upload<T: Decodable>(
        _ path: String,
        _ file: PickedFile,
        sent: (@Sendable (Int64, Int64?) -> Void)? = nil,
        as type: T.Type
    ) async throws -> T {
        let boundary = "mcsc-" + UUID().uuidString
        let form = FileManager.default.temporaryDirectory.appendingPathComponent(boundary + ".form")
        defer { try? FileManager.default.removeItem(at: form) }
        try AgentClient.writeForm(file, boundary: boundary, to: form)
        return try await call(
            "POST", path, slow: true, upload: (form, "multipart/form-data; boundary=" + boundary), sent: sent, as: type
        )
    }

    /// The multipart form for one file, written to `destination`.
    static func writeForm(_ file: PickedFile, boundary: String, to destination: URL) throws {
        let safeName = file.name.replacingOccurrences(of: "\"", with: "_").replacingOccurrences(of: "\r", with: "").replacingOccurrences(of: "\n", with: "")
        FileManager.default.createFile(atPath: destination.path, contents: nil)
        let out = try FileHandle(forWritingTo: destination)
        defer { try? out.close() }
        let head = "--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"\(safeName)\"\r\nContent-Type: application/octet-stream\r\n\r\n"
        try out.write(contentsOf: Data(head.utf8))
        let input = try FileHandle(forReadingFrom: file.url)
        defer { try? input.close() }
        while let chunk = try input.read(upToCount: 1 << 20), !chunk.isEmpty {
            try out.write(contentsOf: chunk)
        }
        try out.write(contentsOf: Data("\r\n--\(boundary)--\r\n".utf8))
    }

    private struct UpdateBody: Encodable {
        let filename: String
        let versionId: String?

        enum CodingKeys: String, CodingKey {
            case filename
            case versionId = "version_id"
        }

        func encode(to encoder: Encoder) throws {
            var c = encoder.container(keyedBy: CodingKeys.self)
            try c.encode(filename, forKey: .filename)
            try c.encode(versionId, forKey: .versionId)
        }
    }

    private struct RollBackBody: Encodable {
        let modId: String
        let archivePath: String

        enum CodingKeys: String, CodingKey {
            case modId = "mod_id"
            case archivePath = "archive_path"
        }
    }

    private struct InstallBody: Encodable {
        let project: String
        let versionId: String?
        let installDependencies: Bool

        enum CodingKeys: String, CodingKey {
            case project
            case versionId = "version_id"
            case installDependencies = "install_dependencies"
        }

        func encode(to encoder: Encoder) throws {
            var c = encoder.container(keyedBy: CodingKeys.self)
            try c.encode(project, forKey: .project)
            try c.encode(versionId, forKey: .versionId)
            try c.encode(installDependencies, forKey: .installDependencies)
        }
    }

    private struct ImportBody: Encodable {
        let token: String
        let confirm: Bool
    }
}

/// What Update all sends: the ticked ones, in the plan's order, each with
/// the version the plan showed (null: the newest that fits).
public struct UpdateAllBody: Encodable, Equatable, Sendable {
    public struct Item: Encodable, Equatable, Sendable {
        public let filename: String
        public let versionId: String?

        enum CodingKeys: String, CodingKey {
            case filename
            case versionId = "version_id"
        }

        public func encode(to encoder: Encoder) throws {
            var c = encoder.container(keyedBy: CodingKeys.self)
            try c.encode(filename, forKey: .filename)
            try c.encode(versionId, forKey: .versionId)
        }
    }

    public let mods: [Item]
}
