import Foundation

// What the per-server screens read: Console, Chat, Players, Activity,
// Crashes and the Overview's cards. As in Models.swift, only the fields the
// app uses are listed, and a value the agent can leave out is nil here and
// shown as Unknown. The rules mirror mobile/android/core's Pages.kt.

extension KeyedDecodingContainer {
    /// The value, or `fallback` when it is missing, null or of another type.
    func value<T: Decodable>(_ key: Key, _ fallback: T) -> T {
        ((try? decodeIfPresent(T.self, forKey: key)) ?? nil) ?? fallback
    }

    /// The value, or nil when it is missing, null or of another type.
    func maybe<T: Decodable>(_ key: Key) -> T? {
        (try? decodeIfPresent(T.self, forKey: key)) ?? nil
    }
}

/// One console line (agent/minecraft/console.py).
public struct ConsoleLine: Decodable, Equatable, Sendable {
    public var seq: Int64
    public var ts: Double
    public var raw: String
    public var level: String
    public var source: String

    enum CodingKeys: String, CodingKey { case seq, ts, raw, level, source }

    public init(seq: Int64 = 0, ts: Double = 0, raw: String = "", level: String = "INFO", source: String = "stdout") {
        self.seq = seq
        self.ts = ts
        self.raw = raw
        self.level = level
        self.source = source
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        seq = c.value(.seq, 0)
        ts = c.value(.ts, 0)
        raw = c.value(.raw, "")
        level = c.value(.level, "INFO")
        source = c.value(.source, "stdout")
    }
}

public struct ConsoleLog: Decodable, Equatable, Sendable {
    public var lines: [ConsoleLine]

    enum CodingKeys: String, CodingKey { case lines }

    public init(from decoder: Decoder) throws {
        lines = try decoder.container(keyedBy: CodingKeys.self).value(.lines, [])
    }
}

public struct CommandCheck: Decodable, Equatable, Sendable {
    public var valid: Bool
    public var error: String?
    public var dangerReason: String?

    enum CodingKeys: String, CodingKey {
        case valid, error
        case dangerReason = "danger_reason"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        valid = c.value(.valid, false)
        error = c.maybe(.error)
        dangerReason = c.maybe(.dangerReason)
    }
}

public struct CommandSent: Decodable, Equatable, Sendable {
    public var result: String?
    public var detail: String?
    public var command: String?
}

/// One chat line (agent/minecraft/chat.py). `name` is nil for the server.
public struct ChatMessage: Decodable, Equatable, Sendable {
    public var seq: Int64
    public var ts: Double
    public var kind: String
    public var name: String?
    public var text: String

    enum CodingKeys: String, CodingKey { case seq, ts, kind, name, text }

    public init(seq: Int64 = 0, ts: Double = 0, kind: String = "player", name: String? = nil, text: String = "") {
        self.seq = seq
        self.ts = ts
        self.kind = kind
        self.name = name
        self.text = text
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        seq = c.value(.seq, 0)
        ts = c.value(.ts, 0)
        kind = c.value(.kind, "player")
        name = c.maybe(.name)
        text = c.value(.text, "")
    }
}

public struct ChatLog: Decodable, Equatable, Sendable {
    public var messages: [ChatMessage]
    public var running: Bool?

    enum CodingKeys: String, CodingKey { case messages, running }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        messages = c.value(.messages, [])
        running = c.maybe(.running)
    }
}

/// Someone the agent has seen join (the players table).
public struct KnownPlayer: Decodable, Equatable, Sendable {
    public var username: String
    public var lastSeen: Double?
    public var edition: String?

    enum CodingKeys: String, CodingKey {
        case username, edition
        case lastSeen = "last_seen"
    }
}

/// A name on one of Minecraft's own lists. On Bedrock an operator can have
/// no name, only the Xbox number in `uuid`.
public struct ListedPlayer: Decodable, Equatable, Sendable {
    public var name: String?
    public var uuid: String?
    public var reason: String?
}

/// whitelist.json, ops.json or banned-players.json. `players` is nil when
/// the file isn't there or can't be read; `reason` says why.
public struct PlayerList: Decodable, Equatable, Sendable {
    public var players: [ListedPlayer]?
    public var file: String?
    public var reason: String?
}

public struct PlayerLists: Decodable, Equatable, Sendable {
    public var whitelist: PlayerList?
    public var ops: PlayerList?
    public var banned: PlayerList?
}

/// A player button sent to the server, and what the console answered.
public struct PlayerAction: Decodable, Equatable, Sendable {
    public var id: String
    public var kind: String
    public var name: String
    public var state: String
    public var message: String?

    enum CodingKeys: String, CodingKey { case id, kind, name, state, message }

    public init(id: String, kind: String, name: String, state: String = PlayerActions.SENT, message: String? = nil) {
        self.id = id
        self.kind = kind
        self.name = name
        self.state = state
        self.message = message
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        kind = c.value(.kind, "")
        name = c.value(.name, "")
        state = c.value(.state, PlayerActions.SENT)
        message = c.maybe(.message)
    }
}

public struct PlayerActionResult: Decodable, Equatable, Sendable {
    public var action: PlayerAction
}

public struct PlayerActionStatus: Decodable, Equatable, Sendable {
    public var action: PlayerAction
}

/// GET /players. `onlineCount` is nil until the list is established.
public struct PlayersPage: Decodable, Equatable, Sendable {
    public var online: [OnlinePlayer]
    public var onlineCount: Int?
    public var known: [KnownPlayer]
    public var maxPlayers: Int?
    public var lists: PlayerLists?
    public var bans: Bool?
    public var edition: String?
    public var running: Bool?
    public var actions: [PlayerAction]

    enum CodingKeys: String, CodingKey {
        case online, known, lists, bans, edition, running, actions
        case onlineCount = "online_count"
        case maxPlayers = "max_players"
    }

    public init(
        online: [OnlinePlayer] = [], onlineCount: Int? = nil, known: [KnownPlayer] = [], maxPlayers: Int? = nil,
        lists: PlayerLists? = nil, bans: Bool? = nil, edition: String? = nil, running: Bool? = nil, actions: [PlayerAction] = []
    ) {
        self.online = online
        self.onlineCount = onlineCount
        self.known = known
        self.maxPlayers = maxPlayers
        self.lists = lists
        self.bans = bans
        self.edition = edition
        self.running = running
        self.actions = actions
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        online = c.value(.online, [])
        onlineCount = c.maybe(.onlineCount)
        known = c.value(.known, [])
        maxPlayers = c.maybe(.maxPlayers)
        lists = c.maybe(.lists)
        bans = c.maybe(.bans)
        edition = c.maybe(.edition)
        running = c.maybe(.running)
        actions = c.value(.actions, [])
    }
}

/// One row of the events table. Its data is never shown as it is (it can
/// hold sign-in names and addresses), so it isn't read at all.
public struct EventRow: Decodable, Equatable, Sendable {
    public var serverId: String?
    public var ts: Double?
    public var type: String
    public var level: String
    public var message: String

    enum CodingKeys: String, CodingKey {
        case ts, type, level, message
        case serverId = "server_id"
    }

    public init(serverId: String?, ts: Double?, type: String, level: String = "info", message: String = "") {
        self.serverId = serverId
        self.ts = ts
        self.type = type
        self.level = level
        self.message = message
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        serverId = c.maybe(.serverId)
        ts = c.maybe(.ts)
        type = c.value(.type, "")
        level = c.value(.level, "info")
        message = c.value(.message, "")
    }
}

public struct EventList: Decodable, Equatable, Sendable {
    public var events: [EventRow]
}

public struct CrashAnalysis: Decodable, Equatable, Sendable {
    public var advice: String?
    public var suspectMods: [String]?

    enum CodingKeys: String, CodingKey {
        case advice
        case suspectMods = "suspect_mods"
    }
}

public struct CrashContext: Decodable, Equatable, Sendable {
    public var analysis: CrashAnalysis?
    public var playersOnline: [String]?
    public var crashReport: String?
    public var logFile: String?
    public var minecraftVersion: String?
    public var fabricLoader: String?
    public var javaVersion: String?

    enum CodingKeys: String, CodingKey {
        case analysis
        case playersOnline = "players_online"
        case crashReport = "crash_report"
        case logFile = "log_file"
        case minecraftVersion = "minecraft_version"
        case fabricLoader = "fabric_loader"
        case javaVersion = "java_version"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        analysis = c.maybe(.analysis)
        playersOnline = c.maybe(.playersOnline)
        crashReport = c.maybe(.crashReport)
        logFile = c.maybe(.logFile)
        minecraftVersion = c.maybe(.minecraftVersion)
        fabricLoader = c.maybe(.fabricLoader)
        javaVersion = c.maybe(.javaVersion)
    }
}

/// A crash. `logTail` only comes with GET /crashes/{id}, and only while the
/// saved log is still there.
public struct Crash: Decodable, Equatable, Sendable {
    public var id: Int64
    public var ts: Double?
    public var exitCode: Int?
    public var category: String?
    public var confidence: String?
    public var summary: String?
    public var evidence: [String]
    public var context: CrashContext?
    public var logTail: [String]?

    enum CodingKeys: String, CodingKey {
        case id, ts, category, confidence, summary, evidence, context
        case exitCode = "exit_code"
        case logTail = "log_tail"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(Int64.self, forKey: .id)
        ts = c.maybe(.ts)
        exitCode = c.maybe(.exitCode)
        category = c.maybe(.category)
        confidence = c.maybe(.confidence)
        summary = c.maybe(.summary)
        evidence = c.value(.evidence, [])
        context = c.maybe(.context)
        logTail = c.maybe(.logTail)
    }
}

public struct CrashList: Decodable, Equatable, Sendable {
    public var crashes: [Crash]
}

/// A suggestion's fix: a dashboard page or an outside link.
public struct RecAction: Decodable, Equatable, Sendable {
    public var label: String?
    public var url: String?
}

/// A suggestion, in the agent's own (English) words.
public struct Recommendation: Decodable, Equatable, Sendable {
    public var id: String
    public var title: String
    public var reason: String?
    public var evidence: String?
    public var action: RecAction?

    enum CodingKeys: String, CodingKey { case id, title, reason, evidence, action }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        title = c.value(.title, "")
        reason = c.maybe(.reason)
        evidence = c.maybe(.evidence)
        action = c.maybe(.action)
    }
}

public struct Recommendations: Decodable, Equatable, Sendable {
    public var recommendations: [Recommendation]
    public var hidden: [Recommendation]

    enum CodingKeys: String, CodingKey { case recommendations, hidden }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        recommendations = c.value(.recommendations, [])
        hidden = c.value(.hidden, [])
    }
}

public struct ChecklistEvidence: Decodable, Equatable, Sendable {
    public var name: String?
    public var createdAt: Double?

    enum CodingKeys: String, CodingKey {
        case name
        case createdAt = "created_at"
    }
}

public struct ChecklistItem: Decodable, Equatable, Sendable {
    public var id: String
    public var done: Bool
    public var evidenceKey: String?
    public var evidence: ChecklistEvidence?

    enum CodingKeys: String, CodingKey {
        case id, done, evidence
        case evidenceKey = "evidence_key"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        done = c.value(.done, false)
        evidenceKey = c.maybe(.evidenceKey)
        evidence = c.maybe(.evidence)
    }
}

/// Getting started. Ticked from what the agent measured, never from a tap.
public struct Checklist: Decodable, Equatable, Sendable {
    public var items: [ChecklistItem]
    public var done: Int?
    public var total: Int?
    public var show: Bool

    enum CodingKeys: String, CodingKey { case items, done, total, show }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        items = c.value(.items, [])
        done = c.maybe(.done)
        total = c.maybe(.total)
        show = c.value(.show, false)
    }
}

public struct JoinAddress: Decodable, Equatable, Sendable {
    public var address: String
    public var adapter: String?
    public var virtual: Bool

    enum CodingKeys: String, CodingKey { case address, adapter, virtual }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        address = try c.decode(String.self, forKey: .address)
        adapter = c.maybe(.adapter)
        virtual = c.value(.virtual, false)
    }
}

public struct TailscaleInfo: Decodable, Equatable, Sendable {
    public var address: String?
    public var dnsName: String?
    public var connected: Bool?
    public var verified: Bool?

    enum CodingKeys: String, CodingKey {
        case address, connected, verified
        case dnsName = "dns_name"
    }
}

/// How to reach one edition: home addresses, Tailscale and the port.
public struct JoinWay: Decodable, Equatable, Sendable {
    public var port: Int?
    public var portSource: String?
    public var defaultPort: Bool?
    public var local: [JoinAddress]
    public var tailscale: TailscaleInfo?
    /// Bedrock crossplay only: the Tailscale address, nil when unknown.
    public var address: String?
    public var ready: Bool?

    enum CodingKeys: String, CodingKey {
        case port, local, tailscale, address, ready
        case portSource = "port_source"
        case defaultPort = "default_port"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        port = c.maybe(.port)
        portSource = c.maybe(.portSource)
        defaultPort = c.maybe(.defaultPort)
        local = c.value(.local, [])
        tailscale = c.maybe(.tailscale)
        address = c.maybe(.address)
        ready = c.maybe(.ready)
    }
}

/// GET /join. The internet is never tested, so it is never claimed.
public struct JoinInfo: Decodable, Equatable, Sendable {
    public var java: JoinWay?
    public var bedrock: JoinWay?
}

public struct Ok: Decodable, Equatable, Sendable {
    public var ok: Bool?
}

/// The player buttons (agent/minecraft/playeractions.py) and their states.
public enum PlayerActions {
    public static let WHITELIST_ADD = "whitelist_add"
    public static let WHITELIST_REMOVE = "whitelist_remove"
    public static let OP = "op"
    public static let DEOP = "deop"
    public static let KICK = "kick"
    public static let BAN = "ban"
    public static let PARDON = "pardon"
    public static let ALL = [WHITELIST_ADD, WHITELIST_REMOVE, OP, DEOP, KICK, BAN, PARDON]

    /// Only these two ask first, with an optional reason.
    public static let CONFIRM: Set<String> = [KICK, BAN]

    public static let SENT = "sent"
    public static let DONE = "done"
    public static let UNCHANGED = "unchanged"
    public static let FAILED = "failed"
    public static let NO_ANSWER = "no_answer"
}

// MARK: - The rules

/// The Console's level chips.
public enum LevelChip: String, CaseIterable, Sendable {
    case all, warnings, errors

    public var key: String {
        switch self {
        case .all: return "mobile.console.level_all"
        case .warnings: return "mobile.console.level_warnings"
        case .errors: return "mobile.console.level_errors"
        }
    }

    public func matches(_ level: String) -> Bool {
        switch self {
        case .all: return true
        case .warnings: return level == "WARN"
        case .errors: return level == "ERROR" || level == "FATAL"
        }
    }
}

/// How a console line is colored: warnings amber, errors red, and the
/// agent's echo of a sent command in the accent color.
public enum LineLook: Equatable, Sendable {
    case plain, warning, danger, command
}

/// The lines the Console keeps: the newest `LIMIT`, as the dashboard keeps.
/// The same line can arrive both from GET /logs and live, so a line already
/// here is not added twice.
public enum ConsoleBuffer {
    public static let LIMIT = 1000
    private static let RECENT = 50

    public static func add(_ lines: [ConsoleLine], _ line: ConsoleLine) -> [ConsoleLine] {
        if lines.suffix(RECENT).contains(where: { $0.seq == line.seq && $0.raw == line.raw }) { return lines }
        return Array((lines + [line]).suffix(LIMIT))
    }

    public static func replace(_ lines: [ConsoleLine]) -> [ConsoleLine] {
        Array(lines.suffix(LIMIT))
    }

    /// What the filter box and chips leave: a case-insensitive match on the
    /// line as printed, among the lines already loaded.
    public static func shown(_ lines: [ConsoleLine], filter: String, chip: LevelChip) -> [ConsoleLine] {
        let needle = filter.trimmingCharacters(in: .whitespaces)
        if needle.isEmpty && chip == .all { return lines }
        return lines.filter { line in
            chip.matches(line.level) && (needle.isEmpty || line.raw.range(of: needle, options: .caseInsensitive) != nil)
        }
    }

    public static func look(_ line: ConsoleLine) -> LineLook {
        if line.source == "command" { return .command }
        if line.level == "ERROR" || line.level == "FATAL" { return .danger }
        if line.level == "WARN" { return .warning }
        return .plain
    }
}

/// The chat the Chat screen keeps: the newest `LIMIT` messages.
public enum ChatBuffer {
    public static let LIMIT = 300
    /// The most a message can be (the agent's own limit).
    public static let MAX_LENGTH = 220
    private static let RECENT = 50

    public static func add(_ messages: [ChatMessage], _ message: ChatMessage) -> [ChatMessage] {
        if messages.suffix(RECENT).contains(where: { $0.seq == message.seq && $0.text == message.text }) { return messages }
        return Array((messages + [message]).suffix(LIMIT))
    }

    public static func replace(_ messages: [ChatMessage]) -> [ChatMessage] {
        Array(messages.suffix(LIMIT))
    }
}

/// What happened to a typed console command.
public enum CommandStep: Equatable, Sendable {
    /// Nothing typed: nothing sent.
    case empty
    /// The agent says it can't be sent; `reason` in its words, if it gave some.
    case invalid(reason: String?)
    /// Risky: ask first with the agent's `reason`, then `ConsoleCommands.confirmed`.
    case askFirst(command: String, reason: String)
    case sent(command: String)
}

/// Sending a console command as the dashboard does: check it first; a risky
/// one is only sent with confirm after the person said yes to the agent's
/// reason. Commands go to Minecraft's console only, never a shell.
public struct ConsoleCommands: Sendable {
    public static let MAX_LENGTH = 512
    public static let HISTORY = 20

    private let client: AgentClient
    private let serverId: String

    public init(client: AgentClient, serverId: String) {
        self.client = client
        self.serverId = serverId
    }

    public func submit(_ text: String) async throws -> CommandStep {
        let command = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if command.isEmpty { return .empty }
        if command.count > ConsoleCommands.MAX_LENGTH { return .invalid(reason: nil) }
        let check = try await client.checkCommand(serverId: serverId, command: command)
        if !check.valid { return .invalid(reason: check.error) }
        if let danger = check.dangerReason { return .askFirst(command: command, reason: danger) }
        _ = try await client.sendCommand(serverId: serverId, command: command, confirm: false)
        return .sent(command: command)
    }

    /// After the person said yes to `.askFirst`.
    public func confirmed(_ command: String) async throws -> CommandStep {
        _ = try await client.sendCommand(serverId: serverId, command: command, confirm: true)
        return .sent(command: command)
    }

    /// The commands sent this time, newest last, for the history button.
    /// Kept in memory only, never written down.
    public static func remember(_ history: [String], _ command: String) -> [String] {
        Array((history.filter { $0 != command } + [command]).suffix(HISTORY))
    }
}

/// Following a player button after it was sent: ask the agent every second,
/// for up to 22 seconds, until the console answered. The result is the last
/// thing the agent said; still "sent" when time ran out or the PC stopped
/// answering, so the app never claims it worked.
public struct PlayerActionWatch: Sendable {
    public typealias Poll = @Sendable (String) async throws -> PlayerAction

    private let poll: Poll
    private let every: Double
    private let upTo: Double
    private let clock: @Sendable () -> Double
    private let sleep: @Sendable (Double) async -> Void

    public init(
        every: Double = 1,
        upTo: Double = 22,
        clock: @escaping @Sendable () -> Double = { Date().timeIntervalSince1970 },
        sleep: @escaping @Sendable (Double) async -> Void = { seconds in _ = try? await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000)) },
        poll: @escaping Poll
    ) {
        self.poll = poll
        self.every = every
        self.upTo = upTo
        self.clock = clock
        self.sleep = sleep
    }

    public func follow(_ action: PlayerAction, onChange: (PlayerAction) -> Void = { _ in }) async -> PlayerAction {
        var current = action
        let start = clock()
        while current.state == PlayerActions.SENT && clock() - start < upTo {
            await sleep(every)
            if Task.isCancelled { return current }
            guard let next = try? await poll(current.id) else { return current }
            if next != current {
                current = next
                onChange(next)
            }
        }
        return current
    }
}

/// Which player buttons show, as the dashboard's Players page decides.
public enum PlayerButtons {
    /// The most a reason for kick or ban can be.
    public static let REASON_LENGTH = 100

    /// The buttons for `name`: whitelist add or remove, operator (only with
    /// players.op), kick (only while online) and ban or unban (not on
    /// Bedrock). None without players.manage.
    public static func forPlayer(_ name: String, online: Bool, page: PlayersPage, canManage: Bool, canOp: Bool) -> [String] {
        if !canManage { return [] }
        var buttons: [String] = []
        buttons.append(on(page.lists?.whitelist, name) ? PlayerActions.WHITELIST_REMOVE : PlayerActions.WHITELIST_ADD)
        if canOp { buttons.append(on(page.lists?.ops, name) ? PlayerActions.DEOP : PlayerActions.OP) }
        if online { buttons.append(PlayerActions.KICK) }
        if page.bans != false { buttons.append(on(page.lists?.banned, name) ? PlayerActions.PARDON : PlayerActions.BAN) }
        return buttons
    }

    /// "Whitelisted", "Operator", "Banned" tags for `name`.
    public static func tags(_ name: String, page: PlayersPage) -> [String] {
        var tags: [String] = []
        if on(page.lists?.whitelist, name) { tags.append("players.tag_whitelisted") }
        if on(page.lists?.ops, name) { tags.append("players.tag_op") }
        if on(page.lists?.banned, name) { tags.append("players.tag_banned") }
        return tags
    }

    /// The remove button on a list card.
    public static func removeFrom(_ list: String) -> String {
        switch list {
        case "ops": return PlayerActions.DEOP
        case "banned": return PlayerActions.PARDON
        default: return PlayerActions.WHITELIST_REMOVE
        }
    }

    /// A typed name the agent would take, checked first so the person gets
    /// the dashboard's own hint; the agent checks again.
    public static func validName(_ name: String, edition: String?) -> Bool {
        let pattern = edition == "bedrock"
            ? "^[A-Za-z0-9](?:[A-Za-z0-9]| (?! )){0,19}(?<! )$"
            : "^\\.?[A-Za-z0-9_]{1,16}$"
        return name.range(of: pattern, options: .regularExpression) != nil
    }

    private static func on(_ list: PlayerList?, _ name: String) -> Bool {
        list?.players?.contains(where: { $0.name?.lowercased() == name.lowercased() }) == true
    }
}
