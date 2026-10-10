import Foundation

/// How a state reads: the same words and tones as the dashboard's STATES
/// (agent/web/js/state.js).
public enum Tone: Equatable, Sendable {
    case success
    case warning
    case danger
    case neutral
}

public struct StateWords: Equatable, Sendable {
    public let key: String
    public let tone: Tone
    public let busy: Bool

    public init(key: String, tone: Tone, busy: Bool = false) {
        self.key = key
        self.tone = tone
        self.busy = busy
    }
}

/// What the server screen offers, and which need a second tap.
public struct QuickAction: Equatable, Hashable, Sendable {
    public let action: String
    public let labelKey: String
    public let confirm: Bool
    public let danger: Bool

    public init(action: String, labelKey: String, confirm: Bool, danger: Bool = false) {
        self.action = action
        self.labelKey = labelKey
        self.confirm = confirm
        self.danger = danger
    }
}

/// Turning what the agent said into words, with the dashboard's own rules:
/// a value the agent didn't measure reads "Unknown", never 0 or a guess, and
/// nothing is shown as current when it came from an earlier read.
public enum Display {
    private static let STATES: [String: StateWords] = [
        States.ONLINE: StateWords(key: "state.online", tone: .success),
        States.OFFLINE: StateWords(key: "state.offline", tone: .neutral),
        States.STARTING: StateWords(key: "state.starting", tone: .warning, busy: true),
        States.STOPPING: StateWords(key: "state.stopping", tone: .warning, busy: true),
        States.RESTARTING: StateWords(key: "state.restarting", tone: .warning, busy: true),
        // Crashed, with an automatic restart counting down.
        States.RESTART_PENDING: StateWords(key: "state.crashed", tone: .danger),
        States.CRASHED: StateWords(key: "state.crashed", tone: .danger),
        States.UNKNOWN: StateWords(key: "state.unknown", tone: .neutral),
    ]

    public static func state(_ name: String?) -> StateWords {
        if let name = name, let words = STATES[name] {
            return words
        }
        return StateWords(key: "state.unknown", tone: .neutral)
    }

    /// "3d 4h", "2h 10m", "5m", "40s": fmt.duration in agent/web/js/ui.js.
    public static func duration(_ strings: Strings, _ seconds: Double) -> String {
        let whole = seconds.isFinite ? seconds.rounded(.down) : 0
        let s = Swift.max(Int64(0), Int64(Swift.max(0, Swift.min(whole, 9.0e15))))
        let d = s / 86400
        let h = (s % 86400) / 3600
        let m = (s % 3600) / 60
        if d > 0 { return strings.t("time.days_hours", ["d": d, "h": h]) }
        if h > 0 { return strings.t("time.hours_minutes", ["h": h, "m": m]) }
        if m > 0 { return strings.t("time.minutes", ["m": m]) }
        return strings.t("time.seconds", ["s": s])
    }

    /// "5m ago", or "Never" when there is no time.
    public static func ago(_ strings: Strings, _ ts: Double?, now: Double) -> String {
        guard let ts = ts, ts > 0 else { return strings.t("time.never") }
        return strings.t("time.ago", ["duration": duration(strings, now - ts)])
    }

    /// "3 of 20", "3", or Unknown when the player list wasn't read.
    public static func players(_ strings: Strings, _ online: Int?, _ max: Int?) -> String {
        guard let online = online else { return strings.t("value.unknown") }
        if let max = max {
            return strings.t("servers.players_of", ["n": online, "max": max])
        }
        return String(online)
    }

    /// "Up for 2h 10m" while online; nothing for other states.
    public static func uptime(_ strings: Strings, _ state: String?, _ uptime: Double?) -> String? {
        guard state == States.ONLINE, let uptime = uptime else { return nil }
        return strings.t("hero.up_for", ["duration": duration(strings, uptime)])
    }

    /// The buttons the dashboard's server page shows for this state
    /// (heroActions in overview.js). Starting asks nothing; stopping and
    /// restarting ask first, because players are thrown off. Nothing is
    /// offered while the agent is busy, or to an account that may not
    /// control the server. A crash with a restart counting down offers no
    /// Start: the agent starts it itself.
    public static func actions(_ state: String?, canControl: Bool) -> [QuickAction] {
        if !canControl { return [] }
        switch state ?? "" {
        case States.ONLINE:
            return [
                QuickAction(action: "restart", labelKey: "action.restart", confirm: true),
                QuickAction(action: "stop", labelKey: "action.stop", confirm: true, danger: true),
            ]
        case States.OFFLINE, States.CRASHED:
            return [QuickAction(action: "start", labelKey: "action.start", confirm: false)]
        default:
            return []
        }
    }
}
