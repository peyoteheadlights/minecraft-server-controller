import Foundation

// Moderators and their permissions on each server (agent/api/routes/accounts.py,
// agent/security/permissions.py). "helper" in the agent's names until Phase 12.
// Mirrors the Android core's Moderators.kt.

public enum Levels {
    public static let START_AND_STOP = "start_and_stop"
    public static let LOOK_AFTER_IT = "look_after_it"
    public static let RUN_IT = "run_it"
    public static let CUSTOM = "custom"
    public static let NONE = "none"
}

public struct Described: Codable, Equatable, Sendable {
    public var permissions: [String]
    public var level: String

    public init(permissions: [String] = [], level: String = Levels.NONE) {
        self.permissions = permissions
        self.level = level
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        permissions = try c.decodeIfPresent([String].self, forKey: .permissions) ?? []
        level = try c.decodeIfPresent(String.self, forKey: .level) ?? Levels.NONE
    }
}

public struct ServerAccess: Codable, Equatable, Sendable, Identifiable {
    public var id: String
    public var name: String
    public var permissions: [String]
    public var level: String

    public init(id: String, name: String, permissions: [String] = [], level: String = Levels.NONE) {
        self.id = id
        self.name = name
        self.permissions = permissions
        self.level = level
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = try c.decodeIfPresent(String.self, forKey: .name) ?? id
        permissions = try c.decodeIfPresent([String].self, forKey: .permissions) ?? []
        level = try c.decodeIfPresent(String.self, forKey: .level) ?? Levels.NONE
    }
}

public struct OpenInvite: Codable, Equatable, Sendable {
    public var createdAt: Double
    public var expiresAt: Double

    enum CodingKeys: String, CodingKey {
        case createdAt = "created_at"
        case expiresAt = "expires_at"
    }
}

public struct Moderator: Codable, Equatable, Sendable, Identifiable {
    public var username: String
    public var allServers: Bool
    public var newServer: Described
    public var access: [ServerAccess]
    public var inviteWaiting: Bool
    public var invite: OpenInvite?
    public var lastUsed: Double?

    public var id: String { username }

    /// The servers they can see, with what they may do on each.
    public var seen: [ServerAccess] { access.filter { !$0.permissions.isEmpty } }

    enum CodingKeys: String, CodingKey {
        case username, access, invite
        case allServers = "all_servers"
        case newServer = "new_server"
        case inviteWaiting = "invite_waiting"
        case lastUsed = "last_used"
    }

    public init(
        username: String, allServers: Bool = false, newServer: Described = Described(), access: [ServerAccess] = [],
        inviteWaiting: Bool = false, invite: OpenInvite? = nil, lastUsed: Double? = nil
    ) {
        self.username = username
        self.allServers = allServers
        self.newServer = newServer
        self.access = access
        self.inviteWaiting = inviteWaiting
        self.invite = invite
        self.lastUsed = lastUsed
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        username = try c.decode(String.self, forKey: .username)
        allServers = try c.decodeIfPresent(Bool.self, forKey: .allServers) ?? false
        newServer = try c.decodeIfPresent(Described.self, forKey: .newServer) ?? Described()
        access = try c.decodeIfPresent([ServerAccess].self, forKey: .access) ?? []
        inviteWaiting = try c.decodeIfPresent(Bool.self, forKey: .inviteWaiting) ?? false
        invite = try c.decodeIfPresent(OpenInvite.self, forKey: .invite)
        lastUsed = try c.decodeIfPresent(Double.self, forKey: .lastUsed)
    }
}

public struct PermissionLevel: Codable, Equatable, Sendable {
    public var id: String
    public var permissions: [String]
}

public struct PermissionGroup: Codable, Equatable, Sendable {
    public var id: String
    public var permissions: [String]
}

public struct PermissionCatalogue: Codable, Equatable, Sendable {
    public var levels: [PermissionLevel]
    public var defaultLevel: String
    public var groups: [PermissionGroup]
    public var technical: [String]
    public var warn: [String]
    public var needs: [String: [String]]

    enum CodingKeys: String, CodingKey {
        case levels, groups, technical, warn, needs
        case defaultLevel = "default_level"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        levels = try c.decodeIfPresent([PermissionLevel].self, forKey: .levels) ?? []
        defaultLevel = try c.decodeIfPresent(String.self, forKey: .defaultLevel) ?? Levels.LOOK_AFTER_IT
        groups = try c.decodeIfPresent([PermissionGroup].self, forKey: .groups) ?? []
        technical = try c.decodeIfPresent([String].self, forKey: .technical) ?? []
        warn = try c.decodeIfPresent([String].self, forKey: .warn) ?? []
        needs = try c.decodeIfPresent([String: [String]].self, forKey: .needs) ?? [:]
    }
}

public struct ServerName: Codable, Equatable, Sendable, Identifiable {
    public var id: String
    public var name: String
}

public struct ModeratorList: Codable, Equatable, Sendable {
    public var owner: String
    public var helpers: [Moderator]
    public var permissions: PermissionCatalogue
    public var servers: [ServerName]
}

public struct InviteCode: Codable, Equatable, Sendable {
    public var ok: Bool
    public var username: String
    public var expiresAt: Double
    public var url: String?
    public var qr: [String]?
    public var reason: String?

    enum CodingKeys: String, CodingKey {
        case ok, username, url, qr, reason
        case expiresAt = "expires_at"
    }
}

public struct ModeratorAdded: Codable, Equatable, Sendable {
    public var ok: Bool
    public var username: String
    public var invite: InviteCode?
}

public struct ModeratorChanged: Codable, Equatable, Sendable {
    public var ok: Bool
    public var username: String
}

public struct ModeratorRemoved: Codable, Equatable, Sendable {
    public var ok: Bool
    public var removed: String
}

public struct InviteCheck: Codable, Equatable, Sendable {
    public var username: String
    public var expiresAt: Double

    enum CodingKeys: String, CodingKey {
        case username
        case expiresAt = "expires_at"
    }
}

public struct Device: Codable, Equatable, Sendable, Identifiable {
    public var id: String
    public var user: String
    public var label: String?
    public var lastUsed: Double?
    public var current: Bool

    enum CodingKeys: String, CodingKey {
        case id, user, label, current
        case lastUsed = "last_used"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        user = try c.decode(String.self, forKey: .user)
        label = try c.decodeIfPresent(String.self, forKey: .label)
        lastUsed = try c.decodeIfPresent(Double.self, forKey: .lastUsed)
        current = try c.decodeIfPresent(Bool.self, forKey: .current) ?? false
    }
}

public struct DeviceList: Codable, Equatable, Sendable {
    public var sessions: [Device]
}

/// The owner's moderator screens: levels, switches and what gets saved.
public enum Moderators {
    /// The shortest password the agent takes (agent/security/auth.py).
    public static let minPassword = 10

    /// The level a set matches, `Levels.CUSTOM` if none, `Levels.NONE` when empty.
    public static func levelOf(_ permissions: Set<String>, _ catalogue: PermissionCatalogue) -> String {
        if permissions.isEmpty { return Levels.NONE }
        return catalogue.levels.first { Set($0.permissions) == permissions }?.id ?? Levels.CUSTOM
    }

    public static func level(_ id: String, _ catalogue: PermissionCatalogue) -> Set<String> {
        Set(catalogue.levels.first { $0.id == id }?.permissions ?? [])
    }

    /// Ticking a switch brings what it needs (Make ops needs Players);
    /// unticking one takes away what needs it. Anything ticked brings seeing
    /// the server; nothing left ticked hides the server.
    public static func toggle(_ permissions: Set<String>, _ permission: String, on: Bool, _ catalogue: PermissionCatalogue) -> Set<String> {
        var next = permissions
        if on {
            next.insert(permission)
            next.formUnion(catalogue.needs[permission] ?? [])
        } else {
            next.remove(permission)
            for (dependent, needed) in catalogue.needs where needed.contains(permission) {
                next.remove(dependent)
            }
        }
        next.remove(Permissions.SERVER_VIEW)
        return next.isEmpty ? [] : next.union([Permissions.SERVER_VIEW])
    }

    /// The switches a group shows: the Technical-only ones only in Technical mode.
    public static func shown(_ group: PermissionGroup, technical: Bool, _ catalogue: PermissionCatalogue) -> [String] {
        group.permissions.filter { technical || !catalogue.technical.contains($0) }
    }

    /// "N more permissions in Technical mode": ticked switches Simple mode doesn't show.
    public static func hiddenTicked(_ permissions: Set<String>, technical: Bool, _ catalogue: PermissionCatalogue) -> Int {
        technical ? 0 : permissions.filter { catalogue.technical.contains($0) }.count
    }

    /// Console commands or Make ops: they let someone do anything in the game.
    public static func warns(_ permissions: Set<String>, _ catalogue: PermissionCatalogue) -> Bool {
        permissions.contains { catalogue.warn.contains($0) }
    }

    /// The short line under a server: the level's name, or the ticked
    /// switches' names ("Start and stop, Players, Chat") for a custom set.
    public static func summary(_ permissions: Set<String>, _ catalogue: PermissionCatalogue, _ strings: Strings) -> String {
        let level = levelOf(permissions, catalogue)
        if level != Levels.CUSTOM { return strings.t("mobile.mod.level_\(level)") }
        let names = catalogue.groups.flatMap(\.permissions).filter { permissions.contains($0) }.map { strings.t(switchKey($0)) }
        let shown = names.prefix(3).joined(separator: ", ")
        return names.count > 3 ? strings.t("mobile.mod.summary_more", ["list": shown, "count": names.count - 3]) : shown
    }

    public static func switchKey(_ permission: String) -> String {
        "mobile.mod.switch_\(permission.replacingOccurrences(of: ".", with: "_"))"
    }

    /// "Save for this server" and "Save for…": the same set on each server named.
    public static func saveFor(_ servers: [String], _ permissions: Set<String>) -> [String: JSONValue] {
        ["grants": .object(Dictionary(uniqueKeysWithValues: servers.map { ($0, list(permissions)) }))]
    }

    /// "Apply to all": every server now, and each new one for an "All servers" moderator.
    public static func applyToAll(_ servers: [String], _ permissions: Set<String>, allServers: Bool) -> [String: JSONValue] {
        var body = saveFor(servers, permissions)
        if allServers { body["new_server"] = list(permissions) }
        return body
    }

    /// The "New servers" set of an "All servers" moderator.
    public static func newServers(_ permissions: Set<String>) -> [String: JSONValue] {
        ["new_server": list(permissions)]
    }

    /// "All servers" on: each new server gives what most of their servers
    /// have now (the default level if none). Off: they keep the servers
    /// they have, and new ones aren't theirs.
    public static func allServers(_ on: Bool, _ moderator: Moderator, _ catalogue: PermissionCatalogue) -> [String: JSONValue] {
        var body: [String: JSONValue] = ["all_servers": .bool(on)]
        if on {
            var counts: [Set<String>: Int] = [:]
            var order: [Set<String>] = []
            for access in moderator.seen {
                let set = Set(access.permissions)
                if counts[set] == nil { order.append(set) }
                counts[set, default: 0] += 1
            }
            // The first of the most common, as Kotlin's maxByOrNull picks.
            var usual: Set<String>? = nil
            for set in order where usual == nil || counts[set]! > counts[usual!]! {
                usual = set
            }
            body["new_server"] = list(usual ?? level(catalogue.defaultLevel, catalogue))
        }
        return body
    }

    private static func list(_ permissions: Set<String>) -> JSONValue {
        .array(permissions.sorted().map { .string($0) })
    }

    /// A name the agent accepts (USERNAME_RE in agent/security/auth.py).
    public static func nameOk(_ name: String) -> Bool {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.range(of: "^[A-Za-z0-9][A-Za-z0-9_.-]{1,31}$", options: .regularExpression) != nil
    }
}

/// A moderator's invite: the pairing link plus a one-time token and their name (agent/pairing.py).
public struct Invite: Equatable, Sendable {
    public var token: String
    public var username: String

    public init(token: String, username: String) {
        self.token = token
        self.username = username
    }
}

public enum InviteLink {
    /// The invite link in a scanned code or pasted text (a whole message
    /// with words around it), or nil when there is none.
    public static func url(_ input: String) -> String? {
        let text = input.trimmingCharacters(in: .whitespacesAndNewlines)
        let words = text.components(separatedBy: .whitespacesAndNewlines)
        if let found = words.first(where: { $0.lowercased().hasPrefix("https://") && $0.contains("invite=") }) {
            return found
        }
        return text.contains("invite=") && text.rangeOfCharacter(from: .whitespacesAndNewlines) == nil ? text : nil
    }

    /// The invite in `input`, or nil when it has none or it is broken.
    public static func parse(_ input: String) -> Invite? {
        guard let link = url(input), let start = link.firstIndex(of: "?") else { return nil }
        let query = link[link.index(after: start)...].split(separator: "#", maxSplits: 1, omittingEmptySubsequences: false).first ?? ""
        var values: [String: String] = [:]
        for part in query.split(separator: "&") {
            guard let eq = part.firstIndex(of: "="), eq != part.startIndex else { continue }
            let raw = String(part[part.index(after: eq)...]).replacingOccurrences(of: "+", with: " ")
            values[String(part[..<eq])] = raw.removingPercentEncoding
        }
        guard let token = values["invite"], let user = values["user"],
              token.range(of: "^[A-Za-z0-9_-]{20,128}$", options: .regularExpression) != nil,
              Moderators.nameOk(user)
        else { return nil }
        return Invite(token: token, username: user)
    }
}

// MARK: - The agent's API for moderators and accounts (mobile/api-routes.txt)

extension AgentClient {
    public func moderators() async throws -> ModeratorList {
        try await call("GET", "/api/accounts", as: ModeratorList.self)
    }

    /// A new moderator with no password: the answer carries their invite.
    public func addModerator(username: String, servers: [String]?, permissions: Set<String>) async throws -> ModeratorAdded {
        var body: [String: JSONValue] = [
            "username": .string(username),
            "permissions": .array(permissions.sorted().map { .string($0) }),
        ]
        if let servers = servers { body["servers"] = .array(servers.map { .string($0) }) }
        return try await call("POST", "/api/accounts", body: try AgentClient.encode(body), as: ModeratorAdded.self)
    }

    /// "Save for this server", "Save for…", "Apply to all": built by `Moderators`.
    public func saveModerator(username: String, body: [String: JSONValue]) async throws -> ModeratorChanged {
        try await call("PUT", "/api/accounts/" + AgentClient.pathSegment(username), body: try AgentClient.encode(body), as: ModeratorChanged.self)
    }

    /// A new invite; with `forgetPassword` the owner's Reset password, which signs them out.
    public func inviteModerator(username: String, forgetPassword: Bool) async throws -> InviteCode {
        let body = try AgentClient.encode(["forget_password": forgetPassword])
        return try await call("POST", "/api/accounts/" + AgentClient.pathSegment(username) + "/invite", body: body, as: InviteCode.self)
    }

    public func cancelInvite(username: String) async throws {
        _ = try await call("DELETE", "/api/accounts/" + AgentClient.pathSegment(username) + "/invite", as: Empty.self)
    }

    public func removeModerator(username: String) async throws -> ModeratorRemoved {
        try await call("DELETE", "/api/accounts/" + AgentClient.pathSegment(username), as: ModeratorRemoved.self)
    }

    /// Who an invite is for. No sign-in: the invite is what lets them in.
    public func checkInvite(token: String) async throws -> InviteCheck {
        try await call("POST", "/api/invite/check", body: try AgentClient.encode(["token": token]), signedIn: false, as: InviteCheck.self)
    }

    /// Chooses the password an invite is for and signs this phone in.
    public func acceptInvite(token: String, password: String, device: String) async throws -> LoginResult {
        let body = try AgentClient.encode(["token": token, "password": password, "device": device])
        return try await call("POST", "/api/invite/accept", body: body, signedIn: false, as: LoginResult.self)
    }

    /// A moderator's own password; their other devices are signed out.
    public func changePassword(current: String, new: String) async throws {
        _ = try await call("POST", "/api/account/password", body: try AgentClient.encode(["current": current, "new": new]), as: Empty.self)
    }

    /// Signed-in devices: the owner's list has everyone's, a moderator's their own.
    public func devices() async throws -> DeviceList {
        try await call("GET", "/api/sessions", as: DeviceList.self)
    }

    public func signOutDevice(id: String) async throws {
        _ = try await call("DELETE", "/api/sessions/" + AgentClient.pathSegment(id), as: Empty.self)
    }
}
