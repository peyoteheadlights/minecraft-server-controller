import Foundation

/// What the live feed tells the app. Screens refetch what they show.
public enum LiveSignal: Equatable, Sendable {
    /// Connected and signed in.
    case ready
    /// Something happened on `serverId` (nil: the PC itself). `type` is the
    /// agent's event type ("state", "player_joined", ...).
    case changed(serverId: String?, type: String)
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
/// never in a log. Console lines are ignored; the app has no console yet.
public final class LiveFeed {
    private let client: AgentClient
    private let token: () -> String?

    public init(client: AgentClient, token: @escaping () -> String?) {
        self.client = client
        self.token = token
    }

    /// One message from the agent, as a signal; nil for anything the app
    /// doesn't act on (pings, console lines, other kinds).
    public static func signal(from text: String) -> LiveSignal? {
        guard let data = text.data(using: .utf8),
              let message = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              let type = message["type"] as? String
        else { return nil }
        switch type {
        case "ready":
            return .ready
        case "event":
            guard let event = message["event"] as? [String: Any],
                  let kind = event["type"] as? String
            else { return nil }
            if kind == "console" { return nil }
            return .changed(serverId: event["server_id"] as? String, type: kind)
        case "error":
            return .closed(message: message["message"] as? String)
        default:
            return nil
        }
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
                        if let text = text, let signal = LiveFeed.signal(from: text) {
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

            continuation.onTermination = { _ in
                task.cancel(with: .normalClosure, reason: nil)
            }
        }
    }
}
