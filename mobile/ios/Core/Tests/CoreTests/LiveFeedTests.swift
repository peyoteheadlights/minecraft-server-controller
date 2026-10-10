import XCTest
@testable import Core

/// The live feed's messages, as agent/api/ws.py sends them. The socket
/// itself can't be faked without a network, so the reading is tested on its
/// own and the sign-in rule (no token, no connection) end to end.
final class LiveFeedTests: XCTestCase {
    private let token = "secret-session-token-1234567890"

    override func setUp() {
        super.setUp()
        StubAgent.reset()
    }

    func testEventsComeThroughAndConsoleLinesDont() {
        let messages = [
            "{\"type\": \"ready\", \"servers\": []}",
            "{\"type\": \"event\", \"event\": {\"type\": \"console\", \"server_id\": \"survival\", \"line\": \"x\"}}",
            "{\"type\": \"ping\", \"ts\": 1}",
            "{\"type\": \"event\", \"event\": {\"type\": \"state\", \"server_id\": \"survival\", \"state\": \"ONLINE\"}}",
            "{\"type\": \"event\", \"event\": {\"type\": \"agent_started\"}}",
            "{\"type\": \"error\", \"message\": \"Your session ended\"}",
            "not json",
        ]
        let signals = messages.compactMap { LiveFeed.signal(from: $0) }
        XCTAssertEqual(signals, [
            .ready,
            .changed(serverId: "survival", type: "state"),
            .changed(serverId: nil, type: "agent_started"),
            .closed(message: "Your session ended"),
        ])
    }

    func testConsoleLinesChatAndTheTailComeThroughForTheWatchedServer() {
        let line = "{\"seq\": 7, \"ts\": 1700000000.5, \"raw\": \"[10:00:00] [Server thread/WARN]: Can't keep up!\", \"level\": \"WARN\", \"thread\": \"Server thread\", \"message\": \"Can't keep up!\", \"source\": \"stdout\"}"
        let warn = ConsoleLine(seq: 7, ts: 1_700_000_000.5, raw: "[10:00:00] [Server thread/WARN]: Can't keep up!", level: "WARN", source: "stdout")
        XCTAssertEqual(
            LiveFeed.signals(from: "{\"type\": \"ready\", \"server_id\": \"survival\", \"servers\": [], \"console\": [\(line)]}"),
            [.ready, .consoleTail(serverId: "survival", lines: [warn])]
        )
        XCTAssertEqual(
            LiveFeed.signals(from: "{\"type\": \"event\", \"event\": {\"type\": \"console\", \"message\": \"x\", \"level\": \"info\", \"data\": \(line), \"ts\": 1, \"server_id\": \"survival\"}}"),
            [.console(serverId: "survival", line: warn)]
        )
        XCTAssertEqual(
            LiveFeed.signals(from: "{\"type\": \"event\", \"event\": {\"type\": \"chat\", \"message\": \"hi\", \"level\": \"info\", \"data\": {\"seq\": 3, \"ts\": 2.0, \"kind\": \"player\", \"name\": \"Alex\", \"text\": \"hi\"}, \"ts\": 2, \"server_id\": \"survival\"}}"),
            [.chat(serverId: "survival", message: ChatMessage(seq: 3, ts: 2, kind: "player", name: "Alex", text: "hi"))]
        )
        // An event's data (names, addresses) is never kept, only its words.
        XCTAssertEqual(
            LiveFeed.signals(from: "{\"type\": \"event\", \"event\": {\"type\": \"player_joined\", \"message\": \"Alex joined\", \"level\": \"success\", \"data\": {\"username\": \"Alex\"}, \"ts\": 3.5, \"server_id\": \"survival\"}}"),
            [
                .changed(serverId: "survival", type: "player_joined"),
                .activity(EventRow(serverId: "survival", ts: 3.5, type: "player_joined", level: "success", message: "Alex joined")),
            ]
        )
        XCTAssertEqual(
            LiveFeed.signals(from: "{\"type\": \"console_tail\", \"server_id\": \"creative\", \"lines\": []}"),
            [.consoleTail(serverId: "creative", lines: [])]
        )
    }

    func testTailNeedsAnOpenFeed() {
        let client = AgentClient(
            pairing: Pairing(host: "localhost", port: 8765, fingerprint: nil),
            token: { nil },
            configuration: StubAgent.configuration()
        )
        XCTAssertFalse(LiveFeed(client: client, token: { nil }).tail(serverId: "creative"))
    }

    func testTheTokenGoesInTheFirstMessage() {
        let auth = LiveFeed.authMessage(token: token, serverId: "survival")
        XCTAssertTrue(auth.contains("\"token\":\"\(token)\""), auth)
        XCTAssertTrue(auth.contains("\"server_id\":\"survival\""), auth)
        XCTAssertTrue(auth.contains("\"type\":\"auth\""), auth)
        XCTAssertFalse(LiveFeed.authMessage(token: token, serverId: nil).contains("server_id"))
    }

    func testWithoutASignInItDoesntConnect() async {
        let client = AgentClient(
            pairing: Pairing(host: "localhost", port: 8765, fingerprint: nil),
            token: { nil },
            configuration: StubAgent.configuration()
        )
        var signals: [LiveSignal] = []
        for await signal in LiveFeed(client: client, token: { nil }).connect(serverId: nil) {
            signals.append(signal)
        }
        XCTAssertEqual(signals, [.signedOut])
        XCTAssertEqual(StubAgent.requests.count, 0)
    }
}
