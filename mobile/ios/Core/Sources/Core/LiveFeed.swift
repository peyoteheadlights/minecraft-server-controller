import Foundation

/// What the live feed tells the app. Screens refetch what they show.
public enum LiveSignal: Equatable, Sendable {
    /// Connected and signed in.
    case ready
    /// Something happened on `serverId` (nil: the PC itself). `type` is the
    /// agent's event type ("state", "player_joined", ...).
    case changed(serverId: String?, type: String)
    /// The same event as a line for the Activity screen (its data is never kept).
    case activity(EventRow)
    /// A new console line of the watched server.
    case console(serverId: String?, line: ConsoleLine)
    /// Someone said something in the watched server's game.
    case chat(serverId: String?, message: ChatMessage)
    /// The watched server's latest console lines, which replace what the
    /// Console shows: on connecting, and after `LiveFeed.tail`.
    case consoleTail(serverId: String, lines: [ConsoleLine])
    /// No sign-in to connect with.
    case signedOut
    /// The agent closed the feed: the sign-in ended, or the account may no
    /// longer use any server. The app asks /api/auth/me which (a 401 there
    /// signs the app out). `message` is the agent's own words.
    case closed(message: String?)
    /// The connection dropped; the app reconnects when it is next shown.
    case lost(AgentError)
}

/// The agent's live stream (/ws, agent/api/ws.py), as the dashboard uses it:
/// the token goes in the first message, never in the address, so it is
/// never in a log. One feed watches one server's console and chat at a
/// time: the one named on connecting, until `tail` names another.
public final class LiveFeed: @unchecked Sendable {
    private let client: AgentClient
    private let token: () -> String?
    private let lock = NSLock()
    private var socket: URLSessionWebSocketTask?

    public init(client: AgentClient, token: @escaping () -> String?) {
        self.client = client
        self.token = token
    }

    /// Watch `serverId`'s console and chat from now on; the agent answers
    /// with its latest `lines` lines (`.consoleTail`). False when the feed
    /// isn't connected: the next connect names the server instead.
    @discardableResult
    public func tail(serverId: String, lines: Int = 200) -> Bool {
        lock.lock()
        let open = socket
        lock.unlock()
        guard let open = open, open.state == .running else { return false }
        let object: [String: Any] = ["type": "tail", "server_id": serverId, "lines": Swift.min(Swift.max(lines, 1), 500)]
        guard let data = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]),
              let text = String(data: data, encoding: .utf8)
        else { return false }
        open.send(.string(text)) { _ in }
        return true
    }

    /// One message from the agent, as a signal; nil for anything the app
    /// doesn't act on (pings, other kinds).
    public static func signal(from text: String) -> LiveSignal? {
        signals(from: text).first
    }

    /// One message from the agent, as the signals it carries: "ready" also
    /// brings the watched server's console, and an event also its line for
    /// the Activity screen.
    public static func signals(from text: String) -> [LiveSignal] {
        guard let data = text.data(using: .utf8),
              let message = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              let type = message["type"] as? String
        else { return [] }
        switch type {
        case "ready":
            guard let watched = message["server_id"] as? String else { return [.ready] }
            return [.ready, .consoleTail(serverId: watched, lines: lines(message["console"]))]
        case "console_tail":
            guard let watched = message["server_id"] as? String else { return [] }
            return [.consoleTail(serverId: watched, lines: lines(message["lines"]))]
        case "event":
            guard let event = message["event"] as? [String: Any],
                  let kind = event["type"] as? String
            else { return [] }
            let server = event["server_id"] as? String
            switch kind {
            case "console":
                guard let line = decode(ConsoleLine.self, event["data"]) else { return [] }
                return [.console(serverId: server, line: line)]
            case "chat":
                guard let said = decode(ChatMessage.self, event["data"]) else { return [] }
                return [.chat(serverId: server, message: said)]
            default:
                let row = EventRow(
                    serverId: server,
                    ts: (event["ts"] as? NSNumber)?.doubleValue,
                    type: kind,
                    level: event["level"] as? String ?? "info",
                    message: event["message"] as? String ?? ""
                )
                return [.changed(serverId: server, type: kind), .activity(row)]
            }
        case "error":
            return [.closed(message: message["message"] as? String)]
        default:
            return []
        }
    }

    private static func decode<T: Decodable>(_ type: T.Type, _ object: Any?) -> T? {
        guard let object = object as? [String: Any],
              let data = try? JSONSerialization.data(withJSONObject: object)
        else { return nil }
        return try? JSONDecoder().decode(type, from: data)
    }

    private static func lines(_ object: Any?) -> [ConsoleLine] {
        guard let list = object as? [Any] else { return [] }
        return list.compactMap { decode(ConsoleLine.self, $0) }
    }

    /// The first message: the sign-in, and which server's details to follow.
    public static func authMessage(token: String, serverId: String?) -> String {
        var object: [String: String] = ["type": "auth", "token": token]
        if let serverId = serverId {
            object["server_id"] = serverId
        }
        guard let data = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]),
              let text = String(data: data, encoding: .utf8)
        else { return "{}" }
        return text
    }

    private func remember(_ task: URLSessionWebSocketTask?) {
        lock.lock()
        socket = task
        lock.unlock()
    }

    public func connect(serverId: String?) -> AsyncStream<LiveSignal> {
        let client = self.client
        let current = token()
        return AsyncStream { continuation in
            guard let current = current else {
                continuation.yield(.signedOut)
                continuation.finish()
                return
            }
            var origin = client.pairing.origin
            if origin.hasPrefix("https://") {
                origin = "wss://" + String(origin.dropFirst("https://".count))
            }
            guard let url = URL(string: origin + "/ws") else {
                continuation.yield(.lost(.notAnAgent))
                continuation.finish()
                return
            }
            let task = client.session.webSocketTask(with: url)
            self.remember(task)
            task.resume()
            task.send(.string(LiveFeed.authMessage(token: current, serverId: serverId))) { _ in
                // A failed send shows up as a failed receive below.
            }

            func receive() {
                task.receive { result in
                    switch result {
                    case .success(let message):
                        var text: String? = nil
                        switch message {
                        case .string(let value):
                            text = value
                        case .data(let value):
                            text = String(data: value, encoding: .utf8)
                        @unknown default:
                            text = nil
                        }
                        for signal in text.map(LiveFeed.signals(from:)) ?? [] {
                            continuation.yield(signal)
                            if case .closed = signal {
                                task.cancel(with: .normalClosure, reason: nil)
                                continuation.finish()
                                return
                            }
                        }
                        receive()
                    case .failure(let error):
                        if task.closeCode != .invalid {
                            // The agent closed the feed in the usual way.
                            continuation.finish()
                        } else {
                            continuation.yield(.lost(client.translateFailure(error)))
                            continuation.finish()
                        }
                    }
                }
            }
            receive()

            continuation.onTermination = { [weak self] _ in
                self?.remember(nil)
                task.cancel(with: .normalClosure, reason: nil)
            }
        }
    }
}
