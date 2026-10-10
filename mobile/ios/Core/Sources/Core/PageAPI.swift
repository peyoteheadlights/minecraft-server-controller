import Foundation

/// One server's screens. Every route is the dashboard's own, with its
/// permissions; the agent refuses whatever the account may not do.
extension AgentClient {
    public static let REC_ACTIONS = ["snooze", "dismiss", "restore"]

    /// Thrown for a player button or suggestion action the agent doesn't
    /// have: a programming error.
    public struct NotAPageAction: Error, Equatable {
        public let action: String
    }

    /// The newest `lines` console lines (the agent keeps up to 500 here).
    public func consoleLog(serverId: String, lines: Int = 500) async throws -> ConsoleLog {
        try await call("GET", server(serverId) + "/logs?lines=\(Swift.min(Swift.max(lines, 1), 500))", as: ConsoleLog.self)
    }

    /// Empties the agent's console view; Minecraft's log files stay.
    public func clearConsole(serverId: String) async throws {
        _ = try await call("POST", server(serverId) + "/logs/clear", body: Data("{}".utf8), as: Ok.self)
    }

    /// Whether a command can be sent, and why it would need asking first.
    public func checkCommand(serverId: String, command: String) async throws -> CommandCheck {
        try await call("GET", server(serverId) + "/server/command/check?command=" + AgentClient.pathSegment(command), as: CommandCheck.self)
    }

    /// Writes one line to Minecraft's console (never a shell). `confirm`
    /// only after the person said yes to the danger the check named.
    public func sendCommand(serverId: String, command: String, confirm: Bool) async throws -> CommandSent {
        let body = try AgentClient.encode(CommandBody(command: command, confirm: confirm))
        return try await call("POST", server(serverId) + "/server/command", body: body, as: CommandSent.self)
    }

    public func chat(serverId: String, lines: Int = 200) async throws -> ChatLog {
        try await call("GET", server(serverId) + "/chat?lines=\(Swift.min(Swift.max(lines, 1), 400))", as: ChatLog.self)
    }

    /// Says `message` in the game as Server. It shows in the chat when the
    /// console prints it back, so the app never adds it itself.
    public func sendChat(serverId: String, message: String) async throws {
        let body = try AgentClient.encode(ChatBody(message: message))
        _ = try await call("POST", server(serverId) + "/chat", body: body, as: Ok.self)
    }

    public func players(serverId: String) async throws -> PlayersPage {
        try await call("GET", server(serverId) + "/players", as: PlayersPage.self)
    }

    /// One of the player buttons. `confirm` is for kick and ban, after asking.
    public func playerAction(serverId: String, action: String, name: String, reason: String?, confirm: Bool) async throws -> PlayerActionResult {
        guard PlayerActions.ALL.contains(action) else { throw NotAPageAction(action: action) }
        let trimmed = reason?.trimmingCharacters(in: .whitespaces)
        let body = try AgentClient.encode(
            PlayerActionBody(action: action, name: name, reason: trimmed?.isEmpty == false ? trimmed : nil, confirm: confirm)
        )
        return try await call("POST", server(serverId) + "/players/actions", body: body, as: PlayerActionResult.self)
    }

    public func playerActionStatus(serverId: String, actionId: String) async throws -> PlayerActionStatus {
        try await call("GET", server(serverId) + "/players/actions/" + AgentClient.pathSegment(actionId), as: PlayerActionStatus.self)
    }

    /// This server's events and the PC's own, newest first.
    public func events(serverId: String, limit: Int = 200) async throws -> EventList {
        try await call("GET", server(serverId) + "/events?limit=\(Swift.min(Swift.max(limit, 1), 500))", as: EventList.self)
    }

    public func crashes(serverId: String, limit: Int = 50) async throws -> CrashList {
        try await call("GET", server(serverId) + "/crashes?limit=\(Swift.min(Swift.max(limit, 1), 200))", as: CrashList.self)
    }

    public func crash(serverId: String, crashId: Int64) async throws -> Crash {
        try await call("GET", server(serverId) + "/crashes/\(crashId)", as: Crash.self)
    }

    public func recommendations(serverId: String) async throws -> Recommendations {
        try await call("GET", server(serverId) + "/recommendations", as: Recommendations.self)
    }

    /// snooze, dismiss or restore; the answer is the new list.
    public func recommendationAction(serverId: String, recId: String, action: String) async throws -> Recommendations {
        guard AgentClient.REC_ACTIONS.contains(action) else { throw NotAPageAction(action: action) }
        let body = try AgentClient.encode(ActionBody(action: action))
        return try await call("POST", server(serverId) + "/recommendations/" + AgentClient.pathSegment(recId), body: body, as: Recommendations.self)
    }

    public func gettingStarted(serverId: String) async throws -> Checklist {
        try await call("GET", server(serverId) + "/getting-started", as: Checklist.self)
    }

    public func hideGettingStarted(serverId: String) async throws -> Checklist {
        try await call("POST", server(serverId) + "/getting-started/dismiss", body: Data("{}".utf8), as: Checklist.self)
    }

    /// How friends join. Can take a few seconds: the PC asks Tailscale.
    public func join(serverId: String) async throws -> JoinInfo {
        try await call("GET", server(serverId) + "/join", as: JoinInfo.self)
    }

    private func server(_ id: String) -> String {
        "/api/servers/" + AgentClient.pathSegment(id)
    }

    private struct CommandBody: Encodable {
        let command: String
        let confirm: Bool
    }

    private struct ChatBody: Encodable {
        let message: String
    }

    private struct PlayerActionBody: Encodable {
        let action: String
        let name: String
        let reason: String?
        let confirm: Bool
    }

    private struct ActionBody: Encodable {
        let action: String
    }
}
