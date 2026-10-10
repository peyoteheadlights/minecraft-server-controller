import Foundation

// What the agent answers, as agent/api/responses.py describes it. Only the
// fields the app uses are listed; anything else the agent adds is ignored
// (Decodable skips keys it doesn't know). A value the agent hasn't measured
// is nil here and shown as Unknown, never as 0 or a guess (house rule 1).
// A null where a default exists reads as the default.

public struct Health: Codable, Equatable, Sendable {
    public var ok: Bool
    public var agentUptime: Double?
    public var authConfigured: Bool?
    public var apiVersion: Int?

    enum CodingKeys: String, CodingKey {
        case ok
        case agentUptime = "agent_uptime"
        case authConfigured = "auth_configured"
        case apiVersion = "api_version"
    }

    public init(ok: Bool = false, agentUptime: Double? = nil, authConfigured: Bool? = nil, apiVersion: Int? = nil) {
        self.ok = ok
        self.agentUptime = agentUptime
        self.authConfigured = authConfigured
        self.apiVersion = apiVersion
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ok = try c.decodeIfPresent(Bool.self, forKey: .ok) ?? false
        agentUptime = try c.decodeIfPresent(Double.self, forKey: .agentUptime)
        authConfigured = try c.decodeIfPresent(Bool.self, forKey: .authConfigured)
        apiVersion = try c.decodeIfPresent(Int.self, forKey: .apiVersion)
    }
}

public struct LoginResult: Codable, Equatable, Sendable {
    public var token: String
    public var user: String?
    public var expiresAt: Double?

    enum CodingKeys: String, CodingKey {
        case token
        case user
        case expiresAt = "expires_at"
    }

    public init(token: String, user: String? = nil, expiresAt: Double? = nil) {
        self.token = token
        self.user = user
        self.expiresAt = expiresAt
    }
}

public struct Me: Codable, Equatable, Sendable {
    public var user: String
    public var role: String
    public var servers: [String]?
    public var permissions: [String]
    public var preferences: [String: String]

    enum CodingKeys: String, CodingKey {
        case user, role, servers, permissions, preferences
    }

    public init(user: String, role: String = "owner", servers: [String]? = nil, permissions: [String] = [], preferences: [String: String] = [:]) {
        self.user = user
        self.role = role
        self.servers = servers
        self.permissions = permissions
        self.preferences = preferences
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        user = try c.decode(String.self, forKey: .user)
        role = try c.decodeIfPresent(String.self, forKey: .role) ?? "owner"
        servers = try c.decodeIfPresent([String].self, forKey: .servers)
        permissions = try c.decodeIfPresent([String].self, forKey: .permissions) ?? []
        // The dashboard keeps other kinds of values here too; the app only
        // reads text ones and never fails over the rest.
        preferences = (try? c.decodeIfPresent([String: String].self, forKey: .preferences)) ?? [:]
    }

    public var isOwner: Bool { role == "owner" }

    public func can(_ permission: String) -> Bool { permissions.contains(permission) }
}

public struct Capabilities: Codable, Equatable, Sendable {
    public var addons: Bool?
    public var mods: Bool?
    public var bans: Bool?
    public var crossplay: Bool?

    public init(addons: Bool? = nil, mods: Bool? = nil, bans: Bool? = nil, crossplay: Bool? = nil) {
        self.addons = addons
        self.mods = mods
        self.bans = bans
        self.crossplay = crossplay
    }
}

public struct ServerRow: Codable, Equatable, Identifiable, Sendable {
    public var id: String
    public var name: String
    public var color: String?
    public var state: String
    public var stateVerified: Bool?
    public var uptime: Double?
    public var playersOnline: Int?
    public var playersVerified: Bool?
    public var maxPlayers: Int?
    public var minecraftVersion: String?
    public var typeName: String?
    public var edition: String?
    public var capabilities: Capabilities?

    enum CodingKeys: String, CodingKey {
        case id, name, color, state, uptime, edition, capabilities
        case stateVerified = "state_verified"
        case playersOnline = "players_online"
        case playersVerified = "players_verified"
        case maxPlayers = "max_players"
        case minecraftVersion = "minecraft_version"
        case typeName = "type_name"
    }

    public init(
        id: String,
        name: String,
        color: String? = nil,
        state: String = States.UNKNOWN,
        stateVerified: Bool? = nil,
        uptime: Double? = nil,
        playersOnline: Int? = nil,
        playersVerified: Bool? = nil,
        maxPlayers: Int? = nil,
        minecraftVersion: String? = nil,
        typeName: String? = nil,
        edition: String? = nil,
        capabilities: Capabilities? = nil
    ) {
        self.id = id
        self.name = name
        self.color = color
        self.state = state
        self.stateVerified = stateVerified
        self.uptime = uptime
        self.playersOnline = playersOnline
        self.playersVerified = playersVerified
        self.maxPlayers = maxPlayers
        self.minecraftVersion = minecraftVersion
        self.typeName = typeName
        self.edition = edition
        self.capabilities = capabilities
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = try c.decode(String.self, forKey: .name)
        color = try c.decodeIfPresent(String.self, forKey: .color)
        state = try c.decodeIfPresent(String.self, forKey: .state) ?? States.UNKNOWN
        stateVerified = try c.decodeIfPresent(Bool.self, forKey: .stateVerified)
        uptime = try c.decodeIfPresent(Double.self, forKey: .uptime)
        playersOnline = try c.decodeIfPresent(Int.self, forKey: .playersOnline)
        playersVerified = try c.decodeIfPresent(Bool.self, forKey: .playersVerified)
        maxPlayers = try c.decodeIfPresent(Int.self, forKey: .maxPlayers)
        minecraftVersion = try c.decodeIfPresent(String.self, forKey: .minecraftVersion)
        typeName = try c.decodeIfPresent(String.self, forKey: .typeName)
        edition = try c.decodeIfPresent(String.self, forKey: .edition)
        capabilities = try c.decodeIfPresent(Capabilities.self, forKey: .capabilities)
    }
}

public struct ServerList: Codable, Equatable, Sendable {
    public var servers: [ServerRow]
    public var defaultServer: String?

    enum CodingKeys: String, CodingKey {
        case servers
        case defaultServer = "default"
    }

    public init(servers: [ServerRow] = [], defaultServer: String? = nil) {
        self.servers = servers
        self.defaultServer = defaultServer
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        servers = try c.decodeIfPresent([ServerRow].self, forKey: .servers) ?? []
        defaultServer = try c.decodeIfPresent(String.self, forKey: .defaultServer)
    }
}

public struct OnlinePlayer: Codable, Equatable, Sendable {
    public var username: String
    public var edition: String?
    public var sessionSeconds: Double?
    /// Nil when the join wasn't seen: then `sessionSeconds` is 0, not measured.
    public var sessionStarted: Double?

    enum CodingKeys: String, CodingKey {
        case username, edition
        case sessionSeconds = "session_seconds"
        case sessionStarted = "session_started"
    }

    public init(username: String, edition: String? = nil, sessionSeconds: Double? = nil, sessionStarted: Double? = nil) {
        self.username = username
        self.edition = edition
        self.sessionSeconds = sessionSeconds
        self.sessionStarted = sessionStarted
    }
}

public struct ServerStatus: Codable, Equatable, Sendable {
    public var serverId: String?
    public var name: String?
    public var state: String
    public var stateVerified: Bool?
    public var uptime: Double?
    public var minecraftVersion: String?
    public var serverTypeName: String?
    public var playersOnline: Int?
    public var playersVerified: Bool?
    public var players: [OnlinePlayer]
    public var maxPlayers: Int?

    enum CodingKeys: String, CodingKey {
        case name, state, uptime, players
        case serverId = "server_id"
        case stateVerified = "state_verified"
        case minecraftVersion = "minecraft_version"
        case serverTypeName = "server_type_name"
        case playersOnline = "players_online"
        case playersVerified = "players_verified"
        case maxPlayers = "max_players"
    }

    public init(
        serverId: String? = nil,
        name: String? = nil,
        state: String = States.UNKNOWN,
        stateVerified: Bool? = nil,
        uptime: Double? = nil,
        minecraftVersion: String? = nil,
        serverTypeName: String? = nil,
        playersOnline: Int? = nil,
        playersVerified: Bool? = nil,
        players: [OnlinePlayer] = [],
        maxPlayers: Int? = nil
    ) {
        self.serverId = serverId
        self.name = name
        self.state = state
        self.stateVerified = stateVerified
        self.uptime = uptime
        self.minecraftVersion = minecraftVersion
        self.serverTypeName = serverTypeName
        self.playersOnline = playersOnline
        self.playersVerified = playersVerified
        self.players = players
        self.maxPlayers = maxPlayers
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        serverId = try c.decodeIfPresent(String.self, forKey: .serverId)
        name = try c.decodeIfPresent(String.self, forKey: .name)
        state = try c.decodeIfPresent(String.self, forKey: .state) ?? States.UNKNOWN
        stateVerified = try c.decodeIfPresent(Bool.self, forKey: .stateVerified)
        uptime = try c.decodeIfPresent(Double.self, forKey: .uptime)
        minecraftVersion = try c.decodeIfPresent(String.self, forKey: .minecraftVersion)
        serverTypeName = try c.decodeIfPresent(String.self, forKey: .serverTypeName)
        playersOnline = try c.decodeIfPresent(Int.self, forKey: .playersOnline)
        playersVerified = try c.decodeIfPresent(Bool.self, forKey: .playersVerified)
        players = try c.decodeIfPresent([OnlinePlayer].self, forKey: .players) ?? []
        maxPlayers = try c.decodeIfPresent(Int.self, forKey: .maxPlayers)
    }
}

public struct ServerAction: Codable, Equatable, Sendable {
    public var result: String
    public var detail: String?
    public var state: String?

    public init(result: String, detail: String? = nil, state: String? = nil) {
        self.result = result
        self.detail = detail
        self.state = state
    }
}

public struct AppAlert: Codable, Equatable, Identifiable, Sendable {
    public var id: Int64
    public var ts: Double
    public var serverId: String?
    public var event: String
    public var title: String
    public var body: String
    public var page: String
    public var url: String

    enum CodingKeys: String, CodingKey {
        case id, ts, event, title, body, page, url
        case serverId = "server_id"
    }

    public init(id: Int64, ts: Double, serverId: String?, event: String, title: String, body: String, page: String, url: String) {
        self.id = id
        self.ts = ts
        self.serverId = serverId
        self.event = event
        self.title = title
        self.body = body
        self.page = page
        self.url = url
    }
}

public struct AppAlerts: Codable, Equatable, Sendable {
    public var alerts: [AppAlert]
    public var latest: Int64
    public var more: Bool
    public var enabled: Bool

    enum CodingKeys: String, CodingKey {
        case alerts, latest, more, enabled
    }

    public init(alerts: [AppAlert] = [], latest: Int64 = 0, more: Bool = false, enabled: Bool = false) {
        self.alerts = alerts
        self.latest = latest
        self.more = more
        self.enabled = enabled
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        alerts = try c.decodeIfPresent([AppAlert].self, forKey: .alerts) ?? []
        latest = try c.decodeIfPresent(Int64.self, forKey: .latest) ?? 0
        more = try c.decodeIfPresent(Bool.self, forKey: .more) ?? false
        enabled = try c.decodeIfPresent(Bool.self, forKey: .enabled) ?? false
    }
}

public struct AppPhone: Codable, Equatable, Sendable {
    public var configured: Bool
    public var registered: Bool

    enum CodingKeys: String, CodingKey {
        case configured, registered
    }

    public init(configured: Bool = false, registered: Bool = false) {
        self.configured = configured
        self.registered = registered
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        configured = try c.decodeIfPresent(Bool.self, forKey: .configured) ?? false
        registered = try c.decodeIfPresent(Bool.self, forKey: .registered) ?? false
    }
}

/// One line of the agent's live feed (/ws): {"type": "event", "event": {...}}.
public struct LiveEvent: Codable, Equatable, Sendable {
    public var type: String
    public var ts: Double?
    public var serverId: String?

    enum CodingKeys: String, CodingKey {
        case type, ts
        case serverId = "server_id"
    }

    public init(type: String, ts: Double? = nil, serverId: String? = nil) {
        self.type = type
        self.ts = ts
        self.serverId = serverId
    }
}

public struct VersionInfo: Codable, Equatable, Sendable {
    public var version: String?
    public var apiVersion: Int?

    enum CodingKeys: String, CodingKey {
        case version
        case apiVersion = "api_version"
    }

    public init(version: String? = nil, apiVersion: Int? = nil) {
        self.version = version
        self.apiVersion = apiVersion
    }
}

/// The states the agent reports (agent/minecraft/process.py).
public enum States {
    public static let ONLINE = "ONLINE"
    public static let OFFLINE = "OFFLINE"
    public static let STARTING = "STARTING"
    public static let STOPPING = "STOPPING"
    public static let RESTARTING = "RESTARTING"
    public static let RESTART_PENDING = "RESTART_PENDING"
    public static let CRASHED = "CRASHED"
    public static let UNKNOWN = "UNKNOWN"
}

/// Permission names (agent/security/permissions.py).
public enum Permissions {
    public static let SERVER_VIEW = "server.view"
    public static let SERVER_CONTROL = "server.control"
    public static let CONSOLE_SEND = "console.send"
    public static let PLAYERS_MANAGE = "players.manage"
    public static let PLAYERS_OP = "players.op"
    public static let CHAT_SEND = "chat.send"
    public static let SETTINGS_EDIT = "settings.edit"
}
