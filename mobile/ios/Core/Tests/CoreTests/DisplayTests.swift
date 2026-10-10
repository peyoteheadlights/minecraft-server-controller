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

    func testValuesTheAgentDidntGiveReadUnknown() {
        XCTAssertEqual(Display.onlineNow(s, nil, 20), "Players not known")
        XCTAssertEqual(Display.onlineNow(s, 3, 20), "Online now (3 of 20)")
        XCTAssertEqual(Display.onlineNow(s, 3, nil), "Online now (3)")
        XCTAssertEqual(Display.exitCode(s, nil), "Unknown")
        XCTAssertEqual(Display.exitCode(s, 1), "1")
        XCTAssertEqual(Display.playingFor(s, OnlinePlayer(username: "Alex", sessionSeconds: 0)), "Unknown")
        XCTAssertEqual(Display.playingFor(s, OnlinePlayer(username: "Alex", sessionSeconds: 300, sessionStarted: 1)), "5m")
        XCTAssertEqual(s.t(Display.actionState("something_new").key), "Unknown")
        XCTAssertEqual(s.t(Display.confidence(nil).key), "Not sure")
    }

    func testCrashCausesAndConfidenceReadAsInTheDashboard() {
        XCTAssertEqual(Display.cause(s, nil), "Not known")
        XCTAssertEqual(Display.cause(s, "Unknown"), "Not known")
        XCTAssertEqual(Display.cause(s, "OutOfMemoryError"), "The server ran out of memory")
        XCTAssertEqual(Display.cause(s, "SomethingNew"), "SomethingNew")
        XCTAssertEqual(Display.confidence("confirmed").tone, .danger)
        XCTAssertEqual(s.t(Display.confidence("likely").key), "Likely")
        let technical = Strings(Shared.strings)
        technical.technical = true
        XCTAssertEqual(Display.cause(technical, "OutOfMemoryError"), "OutOfMemoryError")
    }

    func testActivityAndClock() {
        XCTAssertEqual(Display.eventTone("error"), .danger)
        XCTAssertEqual(Display.eventTone(nil), .neutral)
        XCTAssertTrue(Display.worthShowing("server_started", technical: false))
        XCTAssertFalse(Display.worthShowing("state", technical: false))
        XCTAssertTrue(Display.worthShowing("state", technical: true))
        let utc = TimeZone(identifier: "UTC")!
        XCTAssertEqual(Display.clock(1_700_000_000, zone: utc), "22:13:20")
        XCTAssertEqual(Display.dateTime(1_700_000_000, zone: utc), "2023-11-14 22:13:20")
    }
}
