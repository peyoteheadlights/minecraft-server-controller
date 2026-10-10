import Foundation

public struct WidgetServer: Codable, Equatable, Identifiable, Sendable {
    public var id: String
    public var name: String
    public var color: String?
    public var state: String
    public var playersOnline: Int?
    public var maxPlayers: Int?

    public init(id: String, name: String, color: String? = nil, state: String = States.UNKNOWN, playersOnline: Int? = nil, maxPlayers: Int? = nil) {
        self.id = id
        self.name = name
        self.color = color
        self.state = state
        self.playersOnline = playersOnline
        self.maxPlayers = maxPlayers
    }

    /// The name and color only: what a server was doing isn't known.
    public var unknown: WidgetServer {
        var copy = self
        copy.state = States.UNKNOWN
        copy.playersOnline = nil
        return copy
    }
}

/// What the home-screen widget shows, saved by the app and the widget's own
/// refresh. Only what the last read actually saw is shown as current: a PC
/// that didn't answer leaves every server Unknown, with when it was last
/// checked, and a reading older than `FRESH_FOR` seconds turns Unknown too.
public struct WidgetSnapshot: Codable, Equatable, Sendable {
    /// The widget refreshes every 30 minutes at most; allow one miss.
    public static let FRESH_FOR: Double = 60.0 * 60

    public var checkedAt: Double
    public var reached: Bool
    public var problemKey: String?
    public var servers: [WidgetServer]

    public init(checkedAt: Double, reached: Bool, problemKey: String? = nil, servers: [WidgetServer] = []) {
        self.checkedAt = checkedAt
        self.reached = reached
        self.problemKey = problemKey
        self.servers = servers
    }

    /// The snapshot as it may be shown at `now`.
    public func shown(_ now: Double) -> WidgetSnapshot {
        if isFresh(now) { return self }
        var copy = self
        copy.servers = servers.map { $0.unknown }
        return copy
    }

    public func isFresh(_ now: Double) -> Bool {
        reached && now - checkedAt <= WidgetSnapshot.FRESH_FOR
    }

    public static func read(_ list: ServerList, now: Double) -> WidgetSnapshot {
        WidgetSnapshot(
            checkedAt: now,
            reached: true,
            servers: list.servers.map {
                WidgetServer(id: $0.id, name: $0.name, color: $0.color, state: $0.state, playersOnline: $0.playersOnline, maxPlayers: $0.maxPlayers)
            }
        )
    }

    /// The PC didn't answer: keep the names, not what they were doing.
    public static func failed(_ previous: WidgetSnapshot?, problem: AgentError, now: Double) -> WidgetSnapshot {
        WidgetSnapshot(
            checkedAt: now,
            reached: false,
            problemKey: problem.key,
            servers: (previous?.servers ?? []).map { $0.unknown }
        )
    }
}
