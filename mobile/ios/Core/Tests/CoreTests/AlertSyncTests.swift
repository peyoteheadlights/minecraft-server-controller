import XCTest
@testable import Core

final class AlertSyncTests: XCTestCase {
    /// A pretend agent holding alerts 1...last, answering like phoneapp.py.
    private final class Agent {
        var last: Int64
        var asked: [Int64?] = []

        init(last: Int64) {
            self.last = last
        }

        func answer(_ after: Int64?, _ limit: Int) -> AppAlerts {
            asked.append(after)
            guard let after = after else { return AppAlerts(latest: last) }
            var ids: [Int64] = []
            var next = after + 1
            while next <= last && ids.count < limit {
                ids.append(next)
                next += 1
            }
            let more = ids.count == limit && (ids.last ?? 0) < last
            let alerts = ids.map { AppAlert(id: $0, ts: Double($0), serverId: nil, event: "e", title: "t\($0)", body: "", page: "p", url: "/") }
            return AppAlerts(alerts: alerts, latest: more ? (ids.last ?? last) : last, more: more)
        }

        var sync: AlertSync {
            AlertSync { after, limit in self.answer(after, limit) }
        }
    }

    func testANewlyPairedPhoneStartsFromNow() async throws {
        let agent = Agent(last: 40)
        let state = try await agent.sync.catchUp(AlertState())
        XCTAssertEqual(state.cursor, 40)
        XCTAssertEqual(state.alerts.count, 0)
        XCTAssertEqual(state.unread, 0)
    }

    func testNewAlertsArrivePageByPageAndCountAsUnread() async throws {
        let agent = Agent(last: 40)
        let sync = agent.sync
        var state = try await sync.catchUp(AlertState())
        agent.last = 165
        state = try await sync.catchUp(state, pageSize: 50)
        XCTAssertEqual(state.alerts.map { $0.id }, Array(Int64(41)...Int64(165)))
        XCTAssertEqual(agent.asked, [nil, 40, 90, 140])
        XCTAssertEqual(state.unread, 125)
        XCTAssertEqual(state.newestFirst.first?.id, 165)
        state = state.markAllRead()
        XCTAssertEqual(state.unread, 0)
        agent.last = 166
        let later = try await sync.catchUp(state)
        XCTAssertEqual(later.unread, 1)
    }

    func testThePhoneKeepsTheNewest200() async throws {
        let agent = Agent(last: 0)
        let sync = agent.sync
        var state = try await sync.catchUp(AlertState())
        agent.last = 450
        state = try await sync.catchUp(state, pageSize: 200)
        XCTAssertEqual(state.alerts.count, AlertState.KEPT)
        XCTAssertEqual(state.alerts.first?.id, 251)
    }

    func testAFreshListOnThePCStartsThePhonesListAgain() async throws {
        let agent = Agent(last: 0)
        let sync = agent.sync
        var state = try await sync.catchUp(AlertState())
        agent.last = 30
        state = try await sync.catchUp(state)
        agent.last = 2
        state = try await sync.catchUp(state)
        XCTAssertEqual(state.cursor, 2)
        XCTAssertEqual(state.alerts.count, 0)
        XCTAssertNil(AlertState().cursor)
    }

    func testTheListIsSavedAndReadBack() throws {
        let alert = AppAlert(id: 7, ts: 7, serverId: "survival", event: "server_crashed", title: "Crashed", body: "", page: "overview", url: "/#overview")
        let state = AlertState(cursor: 7, readUpTo: 3, alerts: [alert])
        let data = try JSONEncoder().encode(state)
        XCTAssertEqual(try JSONDecoder().decode(AlertState.self, from: data), state)
    }
}
