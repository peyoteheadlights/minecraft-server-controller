import Foundation

/// Setup: Server settings, version and type changes, the raw editors, new
/// servers and the PC folder picker (mobile/api-routes.txt). Mirrors the
/// Android client.
extension AgentClient {
    public func serverSettings(serverId: String) async throws -> ServerSettings {
        try await call("GET", setup(serverId) + "/settings", as: ServerSettings.self)
    }

    /// Saves `updates` (only what changed). Refused keys come back in
    /// `rejected` with the agent's reason.
    public func saveServerSettings(serverId: String, updates: [String: JSONValue]) async throws -> ServerSettingsSaved {
        let body = try AgentClient.encode(["updates": JSONValue.object(updates)])
        return try await call("PUT", setup(serverId) + "/settings", body: body, as: ServerSettingsSaved.self)
    }

    public func memory(serverId: String) async throws -> MemoryOverview {
        try await call("GET", setup(serverId) + "/memory", as: MemoryOverview.self)
    }

    /// Sets only the -Xmx limit; used from the next start.
    public func setMemory(serverId: String, mb: Int) async throws -> MemoryOverview {
        let body = try AgentClient.encode(["memory_mb": mb])
        return try await call("PUT", setup(serverId) + "/memory", body: body, as: MemoryOverview.self)
    }

    public func setColor(serverId: String, color: String) async throws -> ColorSaved {
        let body = try AgentClient.encode(["color": color])
        return try await call("PUT", setup(serverId) + "/color", body: body, as: ColorSaved.self)
    }

    public func serverTypes() async throws -> ServerTypes {
        try await call("GET", "/api/server-types", as: ServerTypes.self)
    }

    /// The versions a type offers, from its official source (read through the PC).
    public func typeVersions(typeId: String) async throws -> TypeVersions {
        try await call("GET", "/api/server-types/" + AgentClient.pathSegment(typeId) + "/versions", slow: true, as: TypeVersions.self)
    }

    public func serverVersion(serverId: String) async throws -> ServerVersion {
        try await call("GET", setup(serverId) + "/version", as: ServerVersion.self)
    }

    /// What a change would do, before anything happens.
    public func versionPreflight(serverId: String, type: String, minecraft: String, loader: String?) async throws -> VersionPreflight {
        let body = try versionBody(type: type, minecraft: minecraft, loader: loader, confirm: false)
        return try await call("POST", setup(serverId) + "/version/preflight", body: body, slow: true, as: VersionPreflight.self)
    }

    /// Stops the server, takes a backup, installs and checks; answers once done.
    public func changeVersion(serverId: String, type: String, minecraft: String, loader: String?) async throws -> VersionChanged {
        let body = try versionBody(type: type, minecraft: minecraft, loader: loader, confirm: true)
        return try await call("POST", setup(serverId) + "/version", body: body, slow: true, as: VersionChanged.self)
    }

    public func rollBackVersion(serverId: String) async throws -> VersionRolledBack {
        try await call("POST", setup(serverId) + "/version/roll-back", body: Data("{}".utf8), slow: true, as: VersionRolledBack.self)
    }

    /// Only ever sent from the person's own tick.
    public func acceptEula(serverId: String) async throws -> EulaAccepted {
        try await call("POST", setup(serverId) + "/eula", body: Data("{}".utf8), as: EulaAccepted.self)
    }

    public func crossplay(serverId: String) async throws -> CrossplayInfo {
        try await call("GET", setup(serverId) + "/crossplay", as: CrossplayInfo.self)
    }

    /// Installs or moves aside Geyser and Floodgate; the server must be stopped.
    public func setCrossplay(serverId: String, enabled: Bool, port: Int?) async throws -> CrossplayInfo {
        var body: [String: JSONValue] = ["enabled": .bool(enabled)]
        if let port { body["port"] = .number(Double(port)) }
        return try await call("PUT", setup(serverId) + "/crossplay", body: try AgentClient.encode(body), slow: true, as: CrossplayInfo.self)
    }

    public func duplicateOptions(serverId: String) async throws -> DuplicateOptions {
        try await call("GET", setup(serverId) + "/duplicate", as: DuplicateOptions.self)
    }

    /// Starts the copy as a task; the new server appears once it is checked.
    public func duplicate(serverId: String, name: String, directory: String, world: String) async throws -> DuplicateStarted {
        let body = try AgentClient.encode(["name": name, "directory": directory, "world": world])
        return try await call("POST", setup(serverId) + "/duplicate", body: body, as: DuplicateStarted.self)
    }

    /// Takes a server off the list. Nothing on the PC is deleted.
    public func removeServer(serverId: String) async throws -> ServerRemoved {
        try await call("DELETE", setup(serverId), as: ServerRemoved.self)
    }

    private func versionBody(type: String, minecraft: String, loader: String?, confirm: Bool) throws -> Data {
        var body: [String: JSONValue] = ["type": .string(type), "minecraft_version": .string(minecraft), "confirm": .bool(confirm)]
        if let loader { body["loader_version"] = .string(loader) }
        return try AgentClient.encode(body)
    }

    private func setup(_ id: String) -> String {
        "/api/servers/" + AgentClient.pathSegment(id)
    }
}
