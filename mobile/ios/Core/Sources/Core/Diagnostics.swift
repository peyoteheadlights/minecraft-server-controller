import Foundation

/// The app's own request log for "Copy diagnostics": method, path and the
/// answer's status, newest `size` lines. `AgentClient` only ever writes
/// those, never headers, bodies, the sign-in token or a password.
public final class RequestLog: AgentLog, @unchecked Sendable {
    private let size: Int
    private let clock: () -> Date
    private let lock = NSLock()
    private var lines: [String] = []

    public init(size: Int = 50, clock: @escaping () -> Date = { Date() }) {
        self.size = size
        self.clock = clock
    }

    public func line(_ text: String) {
        let formatter = ISO8601DateFormatter()
        let stamp = formatter.string(from: clock())
        lock.lock()
        lines.append("\(stamp) \(text)")
        if lines.count > size {
            lines.removeFirst(lines.count - size)
        }
        lock.unlock()
    }

    public func recent() -> [String] {
        lock.lock()
        defer { lock.unlock() }
        return lines
    }
}

/// What "Copy diagnostics" puts on the clipboard, to paste into "Report a
/// problem". Enough to tell versions and what failed; nothing that signs in
/// or finds the PC: no token, no password, no address, no fingerprint.
public enum Diagnostics {
    public struct Facts: Equatable {
        public var appVersion: String
        public var platform: String
        public var osVersion: String
        public var device: String
        public var agentVersion: String?
        public var agentApi: Int?
        public var paired: Bool
        public var pinned: Bool
        public var signedIn: Bool
        public var lockScreenAlerts: Bool?
        public var lastProblem: String?

        public init(
            appVersion: String,
            platform: String,
            osVersion: String,
            device: String,
            agentVersion: String?,
            agentApi: Int?,
            paired: Bool,
            pinned: Bool,
            signedIn: Bool,
            lockScreenAlerts: Bool?,
            lastProblem: String?
        ) {
            self.appVersion = appVersion
            self.platform = platform
            self.osVersion = osVersion
            self.device = device
            self.agentVersion = agentVersion
            self.agentApi = agentApi
            self.paired = paired
            self.pinned = pinned
            self.signedIn = signedIn
            self.lockScreenAlerts = lockScreenAlerts
            self.lastProblem = lastProblem
        }
    }

    public static func text(_ facts: Facts, log: [String]) -> String {
        var lines: [String] = []
        lines.append("App: \(facts.appVersion) (\(facts.platform) \(facts.osVersion), \(facts.device))")
        let api = facts.agentApi.map { String($0) } ?? "Unknown"
        lines.append("Agent: \(facts.agentVersion ?? "Unknown"), API \(api)")
        lines.append("Paired: \(yes(facts.paired)), certificate pinned: \(yes(facts.pinned)), signed in: \(yes(facts.signedIn))")
        lines.append("Lock-screen alerts: \(facts.lockScreenAlerts.map { yes($0) } ?? "Unknown")")
        lines.append("Last problem: \(facts.lastProblem ?? "None")")
        if !log.isEmpty {
            lines.append("")
            lines.append("Recent requests:")
            lines.append(contentsOf: log)
        }
        return lines.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func yes(_ value: Bool) -> String { value ? "yes" : "no" }
}
