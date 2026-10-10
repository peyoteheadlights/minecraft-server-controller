import Core
import Foundation
import Observation

/// A reading that can fail: what was read and what went wrong the last
/// time. Screens hide `value` while `problem` is set when it is a current
/// state (players, the cards), so nothing old is shown as current.
struct PageRead<T> {
    var value: T?
    var problem: AgentError?
    var loading = false
}

/// How many events the Activity screen keeps.
private let EVENTS_KEPT = 200

/// Where the Servers tab can go: a server, one of its screens, a crash.
enum ServerRoute: Hashable {
    case server(String)
    case page(String, ServerPage)
    case crash(String, Int64)
}

/// A server's own screens, with the dashboard's titles for them.
enum ServerPage: String, Hashable, CaseIterable {
    case console, chat, players, events, crashes

    var titleKey: String { "page.\(rawValue)" }
}

/// Everything the Console, Chat, Players, Activity, Crashes and Overview
/// cards show for one server. Reads go through the person's own sign-in, so
/// the agent decides what they may see and do.
@MainActor
@Observable
final class ServerPages {
    let serverId: String
    @ObservationIgnored private let client: () -> AgentClient?
    @ObservationIgnored private let noted: (AgentError) -> Void

    init(serverId: String, client: @escaping () -> AgentClient?, noted: @escaping (AgentError) -> Void) {
        self.serverId = serverId
        self.client = client
        self.noted = noted
    }

    // MARK: - Console

    var console = PageRead<[ConsoleLine]>()
    /// The commands sent this time, for the history menu: memory only.
    var history: [String] = []
    var asking: (command: String, reason: String)? = nil
    var commandProblem: String? = nil
    var sending = false

    func loadConsole() async {
        await load(\.console) { client, id in ConsoleBuffer.replace(try await client.consoleLog(serverId: id).lines) }
    }

    func onConsoleLine(_ line: ConsoleLine) {
        console.value = ConsoleBuffer.add(console.value ?? [], line)
    }

    func onConsoleTail(_ lines: [ConsoleLine]) {
        console = PageRead(value: ConsoleBuffer.replace(lines))
    }

    func clearConsole(_ strings: Strings) async {
        guard let client = client() else { return }
        do {
            try await client.clearConsole(serverId: serverId)
            console = PageRead(value: [])
        } catch let problem as AgentError {
            noted(problem)
            commandProblem = problem.message(strings)
        } catch {}
    }

    /// Sends `text` as the dashboard does; true once it went, to empty the
    /// box. A risky command waits in `asking`.
    func submitCommand(_ text: String, _ strings: Strings) async -> Bool {
        guard let client = client() else { return false }
        commandProblem = nil
        sending = true
        defer { sending = false }
        do {
            switch try await ConsoleCommands(client: client, serverId: serverId).submit(text) {
            case .empty:
                return false
            case .invalid(let reason):
                if let reason = reason, !reason.isEmpty {
                    commandProblem = strings.t("mobile.error.failed", ["reason": reason])
                } else {
                    commandProblem = strings.t("mobile.console.invalid")
                }
                return false
            case .askFirst(let command, let reason):
                asking = (command: command, reason: reason)
                return false
            case .sent(let command):
                history = ConsoleCommands.remember(history, command)
                return true
            }
        } catch let problem as AgentError {
            noted(problem)
            commandProblem = problem.message(strings)
            return false
        } catch {
            return false
        }
    }

    /// After the person said yes to the agent's reason for `command`.
    func confirmCommand(_ command: String, _ strings: Strings) async -> Bool {
        asking = nil
        guard let client = client() else { return false }
        sending = true
        defer { sending = false }
        do {
            _ = try await ConsoleCommands(client: client, serverId: serverId).confirmed(command)
            history = ConsoleCommands.remember(history, command)
            return true
        } catch let problem as AgentError {
            noted(problem)
            commandProblem = problem.message(strings)
            return false
        } catch {
            return false
        }
    }

    // MARK: - Chat

    var chat = PageRead<[ChatMessage]>()
    var chatRunning: Bool? = nil
    var chatProblem: String? = nil
    var chatSending = false

    func loadChat() async {
        await load(\.chat) { [weak self] client, id in
            let log = try await client.chat(serverId: id)
            self?.chatRunning = log.running
            return ChatBuffer.replace(log.messages)
        }
    }

    func onChat(_ message: ChatMessage) {
        chat.value = ChatBuffer.add(chat.value ?? [], message)
    }

    func sendChat(_ text: String, _ strings: Strings) async -> Bool {
        let message = String(text.trimmingCharacters(in: .whitespacesAndNewlines).prefix(ChatBuffer.MAX_LENGTH))
        guard !message.isEmpty, let client = client() else { return false }
        chatProblem = nil
        chatSending = true
        defer { chatSending = false }
        do {
            try await client.sendChat(serverId: serverId, message: message)
            return true
        } catch let problem as AgentError {
            noted(problem)
            chatProblem = problem.message(strings)
            return false
        } catch {
            return false
        }
    }

    // MARK: - Players

    var players = PageRead<PlayersPage>()
    /// "kick:Steve" while that button is being sent.
    var playerBusy: String? = nil
    var playerProblem: String? = nil
    /// The buttons pressed here, newest first, as the agent last described them.
    var pressed: [PlayerAction] = []

    func loadPlayers() async {
        await load(\.players) { client, id in try await client.players(serverId: id) }
    }

    /// What was sent to the server: this phone's own presses first, then
    /// the agent's list, each once.
    var recentActions: [PlayerAction] {
        let mine = Set(pressed.map(\.id))
        return Array((pressed + (players.value?.actions ?? []).filter { !mine.contains($0.id) }).prefix(10))
    }

    func playerAction(_ action: String, name: String, reason: String?, _ strings: Strings) async {
        guard let client = client() else { return }
        playerBusy = "\(action):\(name)"
        playerProblem = nil
        let confirm = PlayerActions.CONFIRM.contains(action)
        do {
            let result = try await client.playerAction(
                serverId: serverId, action: action, name: name,
                reason: confirm ? reason : nil, confirm: confirm
            )
            track(result.action)
            playerBusy = nil
            let id = serverId
            let watch = PlayerActionWatch { actionId in
                try await client.playerActionStatus(serverId: id, actionId: actionId).action
            }
            let last = await watch.follow(result.action)
            track(last)
        } catch let problem as AgentError {
            noted(problem)
            playerProblem = problem.message(strings)
        } catch {}
        playerBusy = nil
        await loadPlayers()
    }

    private func track(_ action: PlayerAction) {
        pressed = Array(([action] + pressed.filter { $0.id != action.id }).prefix(10))
    }

    // MARK: - Activity

    var events = PageRead<[EventRow]>()

    func loadEvents() async {
        await load(\.events) { client, id in try await client.events(serverId: id, limit: EVENTS_KEPT).events }
    }

    /// A live event for this server (or the PC itself), newest first.
    func onEvent(_ row: EventRow) {
        guard let list = events.value else { return }
        if let server = row.serverId, server != serverId { return }
        events.value = Array(([row] + list).prefix(EVENTS_KEPT))
    }

    // MARK: - Crashes

    var crashes = PageRead<[Crash]>()
    var crash = PageRead<Crash>()

    func loadCrashes() async {
        await load(\.crashes) { client, id in try await client.crashes(serverId: id).crashes }
    }

    func openCrash(_ crashId: Int64) async {
        if crash.value?.id != crashId { crash = PageRead() }
        await load(\.crash) { client, id in try await client.crash(serverId: id, crashId: crashId) }
    }

    // MARK: - Overview cards

    var join = PageRead<JoinInfo>()
    var suggestions = PageRead<Recommendations>()
    var checklist = PageRead<Checklist>()
    var cardProblem: String? = nil

    func loadCards() async {
        await load(\.suggestions) { client, id in try await client.recommendations(serverId: id) }
        await load(\.checklist) { client, id in try await client.gettingStarted(serverId: id) }
        // Last: it can take a few seconds while the PC asks Tailscale.
        await load(\.join) { client, id in try await client.join(serverId: id) }
    }

    func suggestion(_ recId: String, _ action: String, _ strings: Strings) async {
        guard let client = client() else { return }
        cardProblem = nil
        do {
            suggestions = PageRead(value: try await client.recommendationAction(serverId: serverId, recId: recId, action: action))
        } catch let problem as AgentError {
            noted(problem)
            cardProblem = problem.message(strings)
        } catch {}
    }

    func hideChecklist(_ strings: Strings) async {
        guard let client = client() else { return }
        cardProblem = nil
        do {
            checklist = PageRead(value: try await client.hideGettingStarted(serverId: serverId))
        } catch let problem as AgentError {
            noted(problem)
            cardProblem = problem.message(strings)
        } catch {}
    }

    // MARK: - Reading

    /// Reads with `call` into the `PageRead` at `path`: loading, then the
    /// value, or the problem (keeping what was there, so each screen
    /// decides whether it may still show it).
    private func load<T>(
        _ path: ReferenceWritableKeyPath<ServerPages, PageRead<T>>,
        _ call: (AgentClient, String) async throws -> T
    ) async {
        guard let client = client() else { return }
        self[keyPath: path].loading = true
        do {
            let value = try await call(client, serverId)
            self[keyPath: path] = PageRead(value: value)
        } catch let problem as AgentError {
            noted(problem)
            self[keyPath: path].problem = problem
            self[keyPath: path].loading = false
        } catch {
            self[keyPath: path].loading = false
        }
    }
}
