import XCTest
@testable import Core

final class DisplayTests: XCTestCase {
    private let s = Strings(Shared.strings)

    func testStatesReadAsInTheDashboard() {
        XCTAssertEqual(s.t(Display.state("ONLINE").key), "Online")
        XCTAssertEqual(s.t(Display.state("RESTART_PENDING").key), "Crashed")
        XCTAssertEqual(s.t(Display.state("SOMETHING_NEW").key), "Unknown")
        XCTAssertEqual(s.t(Display.state(nil).key), "Unknown")
        XCTAssertTrue(Display.state("STARTING").busy)
    }

    func testDurationsAndPlayers() {
        XCTAssertEqual(Display.duration(s, 40.9), "40s")
        XCTAssertEqual(Display.duration(s, 300.0), "5m")
        XCTAssertEqual(Display.duration(s, 7800.0), "2h 10m")
        XCTAssertEqual(Display.duration(s, 3 * 86400.0 + 4 * 3600), "3d 4h")
        XCTAssertEqual(Display.ago(s, 1000.0, now: 1300.0), "5m ago")
        XCTAssertEqual(Display.ago(s, nil, now: 1300.0), "Never")
        XCTAssertEqual(Display.players(s, 3, 20), "3 of 20")
        XCTAssertEqual(Display.players(s, nil, 20), "Unknown")
        XCTAssertEqual(Display.uptime(s, "ONLINE", 300.0), "Up for 5m")
        XCTAssertNil(Display.uptime(s, "ONLINE", nil))
        XCTAssertNil(Display.uptime(s, "OFFLINE", 300.0))
    }

    func testStartingAsksNothingStoppingAndRestartingAskFirst() {
        XCTAssertEqual(Display.actions("OFFLINE", canControl: true).map { $0.action }, ["start"])
        XCTAssertEqual(Display.actions("CRASHED", canControl: true).first?.confirm, false)
        let online = Display.actions("ONLINE", canControl: true)
        XCTAssertEqual(online.map { $0.action }, ["restart", "stop"])
        XCTAssertTrue(online.allSatisfy { $0.confirm })
        for busy in ["STARTING", "STOPPING", "RESTARTING", "RESTART_PENDING", "UNKNOWN"] {
            XCTAssertEqual(Display.actions(busy, canControl: true), [], busy)
        }
        XCTAssertEqual(Display.actions("OFFLINE", canControl: false), [])
    }
}
