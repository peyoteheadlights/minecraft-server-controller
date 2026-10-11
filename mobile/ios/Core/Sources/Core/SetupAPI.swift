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

    private func setup(_ id: String) -> String {
        "/api/servers/" + AgentClient.pathSegment(id)
    }
}
