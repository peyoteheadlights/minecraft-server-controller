import XCTest
@testable import Core

/// One server's screens: the console and chat buffers, sending commands,
/// player buttons, and reading the agent's answers (mirrors PagesTest.kt).
final class PagesTests: XCTestCase {
    private let token = "secret-session-token-1234567890"
    private let s = Strings(Shared.strings)

    override func setUp() {
        super.setUp()
        StubAgent.reset()
    }

    private func client() -> AgentClient {
        let value = token
        return AgentClient(
            pairing: Pairing(host: "localhost", port: 8765, fingerprint: String(repeating: "ab", count: 32), apiVersion: 1),
            token: { value },
            configuration: StubAgent.configuration()
        )
    }

    private func line(_ seq: Int64, _ raw: String? = nil, level: String = "INFO", source: String = "stdout") -> ConsoleLine {
        ConsoleLine(seq: seq, ts: 1000 + Double(seq), raw: raw ?? "line \(seq)", level: level, source: source)
    }

    private func body(_ index: Int) -> String {
        String(data: StubAgent.requests[index].body, encoding: .utf8) ?? ""
    }

    // MARK: - Console and chat

    func testTheConsoleKeepsTheNewestThousandLinesOnceEach() {
        var lines = ConsoleBuffer.replace((1...1200).map { line(Int64($0)) })
        XCTAssertEqual(lines.count, 1000)
        XCTAssertEqual(lines.first?.seq, 201)
        lines = ConsoleBuffer.add(lines, line(1201))
        XCTAssertEqual(lines.count, 1000)
        XCTAssertEqual(lines.first?.seq, 202)
        XCTAssertEqual(lines.last?.seq, 1201)
        // The same line from GET /logs and from the feed shows once.
        XCTAssertEqual(ConsoleBuffer.add(lines, line(1201)), lines)
    }

    func testTheFilterAndChipsWorkOnTheLoadedLines() {
        let lines = [
            line(1, "[10:00:00] [Server thread/INFO]: Done (3.2s)!"),
            line(2, "[10:00:01] [Server thread/WARN]: Can't keep up!", level: "WARN"),
            line(3, "[10:00:02] [Server thread/ERROR]: Exception ticking world", level: "ERROR"),
            line(4, "[10:00:03] [Server thread/FATAL]: Stopping", level: "FATAL"),
            line(5, "> say hi", source: "command"),
        ]
        XCTAssertEqual(ConsoleBuffer.shown(lines, filter: "  ", chip: .all), lines)
        XCTAssertEqual(ConsoleBuffer.shown(lines, filter: "done", chip: .all).map(\.seq), [1])
        XCTAssertEqual(ConsoleBuffer.shown(lines, filter: "", chip: .warnings).map(\.seq), [2])
        XCTAssertEqual(ConsoleBuffer.shown(lines, filter: "", chip: .errors).map(\.seq), [3, 4])
        XCTAssertEqual(ConsoleBuffer.shown(lines, filter: "STOPPING", chip: .errors).map(\.seq), [4])
        XCTAssertEqual(lines.map(ConsoleBuffer.look), [.plain, .warning, .danger, .danger, .command])
    }

    func testChatKeepsThreeHundredAndNeverAddsAMessageTwice() {
        let messages = (1...320).map { ChatMessage(seq: Int64($0), ts: Double($0), name: "Alex", text: "hi \($0)") }
        var kept = ChatBuffer.replace(messages)
        XCTAssertEqual(kept.count, 300)
        XCTAssertEqual(kept.first?.seq, 21)
        kept = ChatBuffer.add(kept, ChatMessage(seq: 320, ts: 320, name: "Alex", text: "hi 320"))
        XCTAssertEqual(kept.count, 300)
        kept = ChatBuffer.add(kept, ChatMessage(seq: 321, ts: 321, kind: "server", text: "hello"))
        XCTAssertEqual(kept.last?.seq, 321)
        XCTAssertEqual(kept.first?.seq, 22)
    }

    // MARK: - Commands

    func testACommandIsCheckedRiskyOnesAskFirstThenItIsSent() async throws {
        let commands = ConsoleCommands(client: client(), serverId: "survival")
        let empty = try await commands.submit("   ")
        XCTAssertEqual(empty, .empty)
        XCTAssertEqual(StubAgent.requests.count, 0)

        StubAgent.json("{\"valid\": false, \"error\": \"Unknown characters\", \"danger_reason\": null}")
        let invalid = try await commands.submit("say $HOME")
        XCTAssertEqual(invalid, .invalid(reason: "Unknown characters"))
        let check = try XCTUnwrap(StubAgent.requests.first?.request.url)
        XCTAssertEqual(check.path, "/api/servers/survival/server/command/check")
        let query = URLComponents(url: check, resolvingAgainstBaseURL: false)?.queryItems
        XCTAssertEqual(query?.first(where: { $0.name == "command" })?.value, "say $HOME")

        StubAgent.json("{\"valid\": true, \"error\": null, \"danger_reason\": \"Stops the server for everyone.\"}")
        let ask = try await commands.submit(" stop ")
        XCTAssertEqual(ask, .askFirst(command: "stop", reason: "Stops the server for everyone."))
        // Nothing sent until the person says yes.
        XCTAssertEqual(StubAgent.requests.count, 2)
        StubAgent.json("{\"result\": \"SENT\", \"detail\": \"Sent\", \"command\": \"stop\", \"dangerous\": true}")
        let sent = try await commands.confirmed("stop")
        XCTAssertEqual(sent, .sent(command: "stop"))
        XCTAssertEqual(StubAgent.requests[2].request.url?.path, "/api/servers/survival/server/command")
        XCTAssertTrue(body(2).contains("\"confirm\":true"), body(2))

        StubAgent.json("{\"valid\": true, \"error\": null, \"danger_reason\": null}")
        StubAgent.json("{\"result\": \"SENT\", \"command\": \"list\"}")
        let list = try await commands.submit("list")
        XCTAssertEqual(list, .sent(command: "list"))
        XCTAssertTrue(body(4).contains("\"confirm\":false"), body(4))
    }

    func testTheServerNotRunningComesBackInTheAgentsWords() async {
        StubAgent.json("{\"valid\": true, \"danger_reason\": null}")
        StubAgent.json("{\"detail\": \"The server isn't running.\", \"request_id\": \"r1\"}", status: 409)
        do {
            _ = try await ConsoleCommands(client: client(), serverId: "survival").submit("list")
            XCTFail("expected a failure")
        } catch AgentError.failed(let status, let reason, _) {
            XCTAssertEqual(status, 409)
            XCTAssertEqual(reason, "The server isn't running.")
        } catch {
            XCTFail("unexpected \(error)")
        }
    }

    func testOnlyTheLastTwentyCommandsAreKeptNewestLast() {
        var history: [String] = []
        for i in 1...25 { history = ConsoleCommands.remember(history, "say \(i)") }
        XCTAssertEqual(history.count, 20)
        XCTAssertEqual(history.last, "say 25")
        history = ConsoleCommands.remember(history, "say 10")
        XCTAssertEqual(history.last, "say 10")
        XCTAssertEqual(history.filter { $0 == "say 10" }.count, 1)
    }

    // MARK: - Player buttons

    private func action(_ state: String) -> PlayerAction {
        PlayerAction(id: "abc123def456", kind: "kick", name: "Alex", state: state)
    }

    /// A clock that only moves when the watch waits.
    private final class FakeTime: @unchecked Sendable {
        var now = 0.0
        var waits: [Double] = []
        func clock() -> Double { now }
        func sleep(_ seconds: Double) {
            waits.append(seconds)
            now += seconds
        }
    }

    /// Answers in turn, the last one again once they run out.
    private final class Answers: @unchecked Sendable {
        var list: [PlayerAction]
        init(_ list: [PlayerAction]) { self.list = list }
        func next() -> PlayerAction { list.count > 1 ? list.removeFirst() : list[0] }
    }

    func testAPlayerButtonIsFollowedEverySecondUntilItIsAnswered() async {
        let time = FakeTime()
        let answers = Answers([action("sent"), action("sent"), action("done")])
        var seen: [String] = []
        let last = await PlayerActionWatch(clock: { time.clock() }, sleep: { time.sleep($0) }) { _ in answers.next() }
            .follow(action("sent")) { seen.append($0.state) }
        XCTAssertEqual(last.state, "done")
        XCTAssertEqual(time.waits, [1, 1, 1])
        XCTAssertEqual(seen, ["done"])
        XCTAssertEqual(Display.actionState(last.state).key, "players.state_done")
    }

    func testSentButNotConfirmedIsSaidHonestly() async {
        // The agent gives up after 20 s and says so.
        let time = FakeTime()
        let gaveUp = await PlayerActionWatch(clock: { time.clock() }, sleep: { time.sleep($0) }) { [self] _ in
            time.now >= 20 ? action("no_answer") : action("sent")
        }.follow(action("sent"))
        XCTAssertEqual(gaveUp.state, "no_answer")
        XCTAssertEqual(s.t(Display.actionState(gaveUp.state).key), "Sent, not confirmed")

        // No answer at all within 22 s: still "Sent", never "Done".
        let quiet = FakeTime()
        let still = await PlayerActionWatch(clock: { quiet.clock() }, sleep: { quiet.sleep($0) }) { [self] _ in action("sent") }
            .follow(action("sent"))
        XCTAssertEqual(still.state, "sent")
        XCTAssertEqual(quiet.waits.count, 22)
        XCTAssertEqual(s.t(Display.actionState(still.state).key), "Sent")

        // The PC stops answering: the last thing it said stands.
        let lost = await PlayerActionWatch(sleep: { _ in }) { _ in throw AgentError.unreachable }
            .follow(action("sent"))
        XCTAssertEqual(lost.state, "sent")
    }

    func testThePollGoesToTheServerTheActionWasSentTo() async throws {
        let c = client()
        StubAgent.json("{\"result\": \"SENT\", \"action\": {\"id\": \"abc123def456\", \"kind\": \"ban\", \"name\": \"Alex\", \"command\": \"ban Alex\", \"sent_at\": 1, \"state\": \"sent\", \"message\": null}}")
        StubAgent.json("{\"action\": {\"id\": \"abc123def456\", \"kind\": \"ban\", \"name\": \"Alex\", \"state\": \"done\", \"message\": \"Banned Alex\"}}")
        let sent = try await c.playerAction(serverId: "creative", action: PlayerActions.BAN, name: "Alex", reason: "griefing", confirm: true)
        let done = await PlayerActionWatch(sleep: { _ in }) { id in
            try await c.playerActionStatus(serverId: "creative", actionId: id).action
        }.follow(sent.action)
        XCTAssertEqual(done.state, "done")
        XCTAssertEqual(done.message, "Banned Alex")
        XCTAssertEqual(StubAgent.requests[0].request.url?.path, "/api/servers/creative/players/actions")
        XCTAssertTrue(body(0).contains("\"reason\":\"griefing\"") && body(0).contains("\"confirm\":true"), body(0))
        XCTAssertEqual(StubAgent.requests[1].request.url?.path, "/api/servers/creative/players/actions/abc123def456")
    }

    func testPlayerButtonsFollowTheListsAndThePermissions() {
        var page = PlayersPage(
            lists: PlayerLists(
                whitelist: PlayerList(players: [ListedPlayer(name: "Alex")]),
                ops: PlayerList(players: [ListedPlayer(name: "steve")]),
                banned: PlayerList(players: [ListedPlayer(name: "Griefer")])
            ),
            bans: true
        )
        XCTAssertEqual(
            PlayerButtons.forPlayer("alex", online: true, page: page, canManage: true, canOp: true),
            ["whitelist_remove", "op", "kick", "ban"]
        )
        // A helper: no operator buttons.
        XCTAssertEqual(PlayerButtons.forPlayer("Griefer", online: false, page: page, canManage: true, canOp: false), ["whitelist_add", "pardon"])
        XCTAssertEqual(PlayerButtons.forPlayer("Alex", online: true, page: page, canManage: false, canOp: true), [])
        XCTAssertEqual(PlayerButtons.tags("ALEX", page: page), ["players.tag_whitelisted"])
        XCTAssertEqual(PlayerButtons.removeFrom("ops"), "deop")
        page.bans = false
        XCTAssertEqual(PlayerButtons.forPlayer("Steve", online: false, page: page, canManage: true, canOp: true), ["whitelist_add", "deop"])
    }

    func testNamesAreCheckedAsTheAgentChecksThem() {
        XCTAssertTrue(PlayerButtons.validName("Alex_99", edition: "java"))
        XCTAssertTrue(PlayerButtons.validName(".BedrockGuy", edition: nil))
        XCTAssertFalse(PlayerButtons.validName("way_too_long_name_x", edition: "java"))
        XCTAssertFalse(PlayerButtons.validName("has space", edition: "java"))
        XCTAssertTrue(PlayerButtons.validName("Cool Gamer 7", edition: "bedrock"))
        XCTAssertFalse(PlayerButtons.validName("double  space", edition: "bedrock"))
        XCTAssertFalse(PlayerButtons.validName("trailing ", edition: "bedrock"))
    }

    // MARK: - Reading the agent's answers

    func testAnswersWithMissingValuesStillReadAndSayUnknown() throws {
        let players = try JSONDecoder().decode(PlayersPage.self, from: Data("""
        {"online": [{"username": "Alex", "session_seconds": 0, "session_started": null}],
         "online_count": null, "known": [], "lists": {"whitelist": {"players": null, "reason": "Not readable"}},
         "actions": [{"id": "a1", "kind": "op", "name": "Alex", "state": "something_new"}]}
        """.utf8))
        XCTAssertNil(players.onlineCount)
        XCTAssertEqual(Display.onlineNow(s, players.onlineCount, players.maxPlayers), "Players not known")
        XCTAssertEqual(Display.playingFor(s, players.online[0]), "Unknown")
        XCTAssertNil(players.lists?.whitelist?.players)
        XCTAssertEqual(s.t(Display.actionState(players.actions[0].state).key), "Unknown")

        let crash = try JSONDecoder().decode(Crash.self, from: Data("""
        {"id": 4, "ts": null, "exit_code": null, "category": null, "evidence": null}
        """.utf8))
        XCTAssertEqual(Display.exitCode(s, crash.exitCode), "Unknown")
        XCTAssertEqual(Display.cause(s, crash.category), "Not known")
        XCTAssertEqual(crash.evidence, [])
        XCTAssertNil(crash.logTail)

        let join = try JSONDecoder().decode(JoinInfo.self, from: Data("""
        {"java": {"port": 25565, "port_source": "server.properties", "default_port": true,
                  "local": [{"address": "192.168.1.20", "adapter": "Ethernet", "virtual": false}],
                  "tailscale": {"address": null, "connected": null, "verified": false}},
         "bedrock": {"port": 19132, "address": "100.64.0.1", "ready": false}}
        """.utf8))
        XCTAssertEqual(join.java?.local.first?.address, "192.168.1.20")
        XCTAssertNil(join.java?.tailscale?.address)
        XCTAssertEqual(join.bedrock?.address, "100.64.0.1")
        XCTAssertEqual(join.bedrock?.ready, false)
    }

    func testSuggestionAndChecklistActionsGoToTheirOwnRoutes() async throws {
        let c = client()
        StubAgent.json("{\"recommendations\": [], \"hidden\": [{\"id\": \"r1\", \"title\": \"Back up\"}]}")
        let after = try await c.recommendationAction(serverId: "survival", recId: "r1", action: "dismiss")
        XCTAssertEqual(after.hidden.map(\.id), ["r1"])
        XCTAssertEqual(StubAgent.requests[0].request.url?.path, "/api/servers/survival/recommendations/r1")
        XCTAssertTrue(body(0).contains("\"action\":\"dismiss\""), body(0))

        do {
            _ = try await c.recommendationAction(serverId: "survival", recId: "r1", action: "delete")
            XCTFail("expected a refusal")
        } catch let refused as AgentClient.NotAPageAction {
            XCTAssertEqual(refused.action, "delete")
        }
        XCTAssertEqual(StubAgent.requests.count, 1)

        StubAgent.json("{\"items\": [{\"id\": \"backup\", \"done\": true}], \"done\": 1, \"total\": 5, \"show\": false}")
        let hidden = try await c.hideGettingStarted(serverId: "survival")
        XCTAssertFalse(hidden.show)
        XCTAssertEqual(StubAgent.requests[1].request.url?.path, "/api/servers/survival/getting-started/dismiss")
    }
}
