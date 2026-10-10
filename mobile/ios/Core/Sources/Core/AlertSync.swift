import Foundation

/// The Notifications tab's list as the phone keeps it: the alerts read so
/// far (newest `KEPT`), where to carry on reading (`cursor`) and how far the
/// person has looked (`readUpTo`). Saved on the phone between launches.
public struct AlertState: Codable, Equatable, Sendable {
    /// The agent keeps its newest 200 (APP_ALERTS_KEPT); so does the phone.
    public static let KEPT = 200

    public var cursor: Int64?
    public var readUpTo: Int64
    public var alerts: [AppAlert]

    public init(cursor: Int64? = nil, readUpTo: Int64 = 0, alerts: [AppAlert] = []) {
        self.cursor = cursor
        self.readUpTo = readUpTo
        self.alerts = alerts
    }

    /// Newest first, for the list.
    public var newestFirst: [AppAlert] { alerts.sorted { $0.id > $1.id } }

    public var unread: Int { alerts.filter { $0.id > readUpTo }.count }

    public func markAllRead() -> AlertState {
        var copy = self
        let newest = alerts.map { $0.id }.max() ?? 0
        copy.readUpTo = Swift.max(readUpTo, newest)
        return copy
    }
}

/// Catches the list up with the agent's (GET /api/alerts). A newly paired
/// phone starts from "now": it learns where the list is and shows nothing
/// old. After that, every alert since the last read is fetched, page by
/// page. Called when the app opens, on a live-feed event and from the
/// widget's refresh.
public final class AlertSync {
    public typealias Fetch = (_ after: Int64?, _ limit: Int) async throws -> AppAlerts

    private let fetch: Fetch

    public init(fetch: @escaping Fetch) {
        self.fetch = fetch
    }

    public func catchUp(_ state: AlertState, pageSize: Int = 50, maxPages: Int = 10) async throws -> AlertState {
        guard let cursor = state.cursor else {
            let now = try await fetch(nil, pageSize)
            var started = state
            started.cursor = now.latest
            started.readUpTo = now.latest
            return started
        }
        var after = cursor
        var found: [AppAlert] = []
        for _ in 0..<maxPages {
            let answer = try await fetch(after, pageSize)
            if answer.latest < after {
                // The agent's list started again (a new data folder): its
                // numbers mean other alerts now, so start from where it is.
                return AlertState(cursor: answer.latest, readUpTo: answer.latest)
            }
            found.append(contentsOf: answer.alerts)
            after = answer.latest
            if !answer.more { break }
        }
        var byId: [Int64: AppAlert] = [:]
        for alert in state.alerts + found {
            byId[alert.id] = alert
        }
        let sorted = byId.values.sorted { $0.id < $1.id }
        let kept = Array(sorted.suffix(AlertState.KEPT))
        var next = state
        next.cursor = after
        next.alerts = kept
        return next
    }
}
