import XCTest
@testable import Core

/// Collects what the client logs.
final class Lines: AgentLog {
    var all: [String] = []
    func line(_ text: String) { all.append(text) }
}

final class AgentClientTests: XCTestCase {
    private let token = "secret-session-token-1234567890"
    private let pairing = Pairing(host: "localhost", port: 8765, fingerprint: String(repeating: "ab", count: 32), apiVersion: 1)

    override func setUp() {
        super.setUp()
        StubAgent.reset()
    }

    private func client(
        token current: String?? = nil,
        onSignedOut: @escaping () -> Void = {},
        log: AgentLog = NoLog()
    ) -> AgentClient {
        let value: String? = current ?? token
        return AgentClient(
            pairing: pairing,
            token: { value },
            onSignedOut: onSignedOut,
            log: log,
            configuration: StubAgent.configuration()
        )
    }

    private func expectError<T>(_ body: () async throws -> T) async -> Error? {
        do {
            _ = try await body()
            return nil
        } catch {
            return error
        }
    }

    func testRequestsCarryTheTokenAndReadTheAnswer() async throws {
        StubAgent.json("{\"servers\": [{\"id\": \"survival\", \"name\": \"Survival\", \"state\": \"ONLINE\", \"players_online\": 2, \"max_players\": 20, \"new_field\": 1}], \"default\": \"survival\"}")
        let list = try await client().servers()
        XCTAssertEqual(list.servers.count, 1)
        XCTAssertEqual(list.servers.first?.name, "Survival")
        XCTAssertEqual(list.servers.first?.playersOnline, 2)
        XCTAssertEqual(list.defaultServer, "survival")
        XCTAssertEqual(StubAgent.requests.first?.request.value(forHTTPHeaderField: "Authorization"), "Bearer \(token)")
    }

    func testAValueTheAgentDidntMeasureStaysUnknown() async throws {
        StubAgent.json("{\"servers\": [{\"id\": \"s\", \"name\": \"S\", \"state\": \"ONLINE\", \"players_online\": null}]}")
        let row = try await client().servers().servers[0]
        XCTAssertNil(row.playersOnline)
        XCTAssertEqual(Display.players(Strings(Shared.strings), row.playersOnline, row.maxPlayers), "Unknown")
    }

    func testANullStateReadsUnknown() async throws {
        StubAgent.json("{\"servers\": [{\"id\": \"s\", \"name\": \"S\", \"state\": null}]}")
        let row = try await client().servers().servers[0]
        XCTAssertEqual(row.state, "UNKNOWN")
    }

    func testSigningThePhoneOutOnThePCSignsTheAppOut() async {
        StubAgent.json("{\"detail\": \"Not signed in\"}", status: 401)
        var signedOut = false
        let c = client(onSignedOut: { signedOut = true })
        let error = await expectError { try await c.servers() }
        XCTAssertEqual(error as? AgentError, .signedOut)
        XCTAssertTrue(signedOut)
    }

    func testWithoutATokenNothingIsSent() async {
        let c = client(token: .some(nil))
        let error = await expectError { try await c.me() }
        XCTAssertEqual(error as? AgentError, .signedOut)
        XCTAssertEqual(StubAgent.requests.count, 0)
    }

    func testRefusalsCarryTheAgentsOwnWords() async {
        let c = client()
        StubAgent.json("{\"detail\": \"Wrong username or password\"}", status: 401)
        let refused = await expectError { try await c.login(username: "admin", password: "hunter2-password", device: "Server Controller on iPhone") }
        XCTAssertEqual(refused as? AgentError, .signInRefused(reason: "Wrong username or password"))

        StubAgent.json("{\"detail\": \"Helpers can't do that\"}", status: 403)
        let no = await expectError { try await c.serverAction(serverId: "survival", action: "stop") }
        XCTAssertEqual(no as? AgentError, .notAllowed(reason: "Helpers can't do that"))

        StubAgent.json("{\"detail\": \"Busy\"}", status: 409, headers: ["X-Request-ID": "abc123"])
        let failed = await expectError { try await c.serverAction(serverId: "survival", action: "start") }
        XCTAssertEqual(failed as? AgentError, .failed(status: 409, reason: "Busy", requestId: "abc123"))
    }

    func testOnlyStartStopAndRestartCanBeSent() async {
        let c = client()
        let error = await expectError { try await c.serverAction(serverId: "survival", action: "command") }
        XCTAssertNotNil(error as? AgentClient.NotAnAction)
        XCTAssertEqual(StubAgent.requests.count, 0)
    }

    func testServerNamesAreSentSafelyInThePath() async throws {
        StubAgent.json("{\"state\": \"OFFLINE\"}")
        _ = try await client().status(serverId: "my world/../x")
        let url = StubAgent.requests.first?.request.url?.absoluteString ?? ""
        XCTAssertTrue(url.hasSuffix("/api/servers/my%20world%2F..%2Fx/status"), url)
    }

    func testTheLogNeverHasTheTokenOrThePassword() async throws {
        let log = RequestLog()
        StubAgent.json("{\"token\": \"\(token)\", \"user\": \"admin\"}")
        StubAgent.json("{\"alerts\": [], \"latest\": 3}")
        let c = client(log: log)
        _ = try await c.login(username: "admin", password: "hunter2-password", device: "Phone")
        _ = try await c.alerts(after: 1)
        let lines = log.recent().joined(separator: "\n")
        XCTAssertTrue(lines.contains("POST /api/auth/login -> 200"), lines)
        XCTAssertTrue(lines.contains("GET /api/alerts -> 200"), lines)
        XCTAssertFalse(lines.contains(token))
        XCTAssertFalse(lines.contains("hunter2"))
        XCTAssertFalse(lines.contains("Bearer"))
        XCTAssertTrue(StubAgent.requests[1].request.url?.absoluteString.hasSuffix("/api/alerts?limit=50&after=1") ?? false)
    }

    func testTheSignInAsksToBeRememberedWithThePhonesName() async throws {
        StubAgent.json("{\"token\": \"\(token)\"}")
        let result = try await client().login(username: "admin", password: "pw", device: "Server Controller on iPhone")
        XCTAssertEqual(result.token, token)
        let body = String(data: StubAgent.requests.first?.body ?? Data(), encoding: .utf8) ?? ""
        XCTAssertTrue(body.contains("\"remember\":true"), body)
        XCTAssertTrue(body.contains("\"device\":\"Server Controller on iPhone\""), body)
        XCTAssertNil(StubAgent.requests.first?.request.value(forHTTPHeaderField: "Authorization"))
    }

    func testAnAnswerThatIsntJsonIsNotTheAgent() async {
        StubAgent.enqueue(StubAgent.Answer(status: 200, headers: ["Content-Type": "text/html"], body: Data("<html></html>".utf8)))
        let error = await expectError { try await client().servers() }
        XCTAssertEqual(error as? AgentError, .notAnAgent)
    }

    func testNoAnswerIsUnreachable() async {
        let error = await expectError { try await client().servers() }
        XCTAssertEqual(error as? AgentError, .unreachable)
    }

    func testErrorsReadInTheAppsWords() {
        let s = Strings(Shared.strings)
        XCTAssertEqual(AgentError.unreachable.key, "mobile.error.unreachable")
        XCTAssertEqual(AgentError.signedOut.key, "error.session_ended")
        XCTAssertEqual(AgentError.signInRefused(reason: "Wrong username or password").message(s), "Wrong username or password")
        XCTAssertTrue(AgentError.failed(status: 500, reason: nil, requestId: nil).message(s).contains("500"))
    }
}
