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
