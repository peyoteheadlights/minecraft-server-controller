import XCTest
@testable import Core

/// The owner's moderator screens and a moderator's invite (agent/api/routes/accounts.py).
final class ModeratorsTests: XCTestCase {
    private let strings = Strings(Shared.strings)
    private let token = "secret-session-token-1234567890"
    private let pairing = Pairing(host: "localhost", port: 8765, fingerprint: String(repeating: "ab", count: 32), apiVersion: 1)

    // The catalogue GET /api/accounts sends (agent/security/permissions.py).
    private let catalogue = try! JSONDecoder().decode(PermissionCatalogue.self, from: Data("""
        {"levels": [
           {"id": "start_and_stop", "permissions": ["server.control", "server.view"]},
           {"id": "look_after_it", "permissions": ["backups.create", "chat.send", "console.read", "players.manage", "server.control", "server.view"]},
           {"id": "run_it", "permissions": ["backups.create", "backups.restore", "chat.send", "console.read", "mods.manage", "players.manage", "schedules.manage", "server.control", "server.view", "settings.game", "settings.server"]}],
         "default_level": "look_after_it",
         "groups": [
           {"id": "server", "permissions": ["server.control", "console.read", "console.send"]},
           {"id": "players", "permissions": ["players.manage", "chat.send", "players.op"]},
           {"id": "addons", "permissions": ["mods.manage"]},
           {"id": "backups", "permissions": ["backups.create", "backups.restore", "backups.download", "backups.delete", "world.replace"]},
           {"id": "settings", "permissions": ["settings.game", "settings.server", "schedules.manage"]}],
         "technical": ["backups.delete", "backups.download", "console.send", "players.op", "world.replace"],
         "warn": ["console.send", "players.op"],
         "needs": {"players.op": ["players.manage"], "console.send": ["console.read"]}}
        """.utf8))

    private var lookAfterIt: Set<String> { Moderators.level(Levels.LOOK_AFTER_IT, catalogue) }

    override func setUp() {
        super.setUp()
        StubAgent.reset()
    }

    private func client(signedIn: Bool = true) -> AgentClient {
        let value: String? = signedIn ? token : nil
        return AgentClient(pairing: pairing, token: { value }, onSignedOut: {}, log: NoLog(), configuration: StubAgent.configuration())
    }

    private func names(_ value: JSONValue?) -> Set<String> {
        guard case .array(let items)? = value else { return [] }
        return Set(items.compactMap { if case .string(let s) = $0 { return s } else { return nil } })
    }

    func testASetReadsAsItsLevelOrCustom() {
        XCTAssertEqual(Moderators.levelOf(lookAfterIt, catalogue), Levels.LOOK_AFTER_IT)
        XCTAssertEqual(Moderators.levelOf([], catalogue), Levels.NONE)
        let custom = Moderators.toggle(lookAfterIt, Permissions.CHAT_SEND, on: false, catalogue)
        XCTAssertEqual(Moderators.levelOf(custom, catalogue), Levels.CUSTOM)
        XCTAssertEqual(Moderators.levelOf(Moderators.toggle(custom, Permissions.CHAT_SEND, on: true, catalogue), catalogue), Levels.LOOK_AFTER_IT)
    }

    func testJoinedSwitchesMoveTogether() {
        let start = Moderators.level(Levels.START_AND_STOP, catalogue)
        let op = Moderators.toggle(start, Permissions.PLAYERS_OP, on: true, catalogue)
        XCTAssertTrue(op.contains(Permissions.PLAYERS_MANAGE))
        XCTAssertFalse(Moderators.toggle(op, Permissions.PLAYERS_MANAGE, on: false, catalogue).contains(Permissions.PLAYERS_OP))
        XCTAssertTrue(Moderators.toggle(start, Permissions.CONSOLE_SEND, on: true, catalogue).contains(Permissions.CONSOLE_READ))
    }

    func testAnythingTickedSeesTheServerNothingTickedHidesIt() {
        let one = Moderators.toggle([], Permissions.CHAT_SEND, on: true, catalogue)
        XCTAssertEqual(one, [Permissions.CHAT_SEND, Permissions.SERVER_VIEW])
        XCTAssertEqual(Moderators.toggle(one, Permissions.CHAT_SEND, on: false, catalogue), [])
    }

    func testSimpleModeHidesTheTechnicalOnlySwitchesAndCountsTheTickedOnes() {
        let backups = catalogue.groups.first { $0.id == "backups" }!
        XCTAssertEqual(Moderators.shown(backups, technical: false, catalogue), ["backups.create", "backups.restore"])
        XCTAssertEqual(Moderators.shown(backups, technical: true, catalogue).count, 5)
        let withConsole = Moderators.toggle(lookAfterIt, Permissions.CONSOLE_SEND, on: true, catalogue)
        let withDelete = Moderators.toggle(withConsole, Permissions.BACKUPS_DELETE, on: true, catalogue)
        XCTAssertEqual(Moderators.hiddenTicked(withDelete, technical: false, catalogue), 2)
        XCTAssertEqual(Moderators.hiddenTicked(withDelete, technical: true, catalogue), 0)
        XCTAssertEqual(Moderators.hiddenTicked(lookAfterIt, technical: false, catalogue), 0)
    }

    func testConsoleCommandsAndMakeOpsWarn() {
        XCTAssertFalse(Moderators.warns(lookAfterIt, catalogue))
        XCTAssertTrue(Moderators.warns(Moderators.toggle(lookAfterIt, Permissions.PLAYERS_OP, on: true, catalogue), catalogue))
    }

    func testTheSummaryNamesTheLevelOrTheFirstFewSwitches() {
        XCTAssertEqual(Moderators.summary(lookAfterIt, catalogue, strings), "Look after it")
        XCTAssertEqual(Moderators.summary([], catalogue, strings), "No access")
        let few = Moderators.toggle(Moderators.level(Levels.START_AND_STOP, catalogue), Permissions.CHAT_SEND, on: true, catalogue)
        XCTAssertEqual(Moderators.summary(few, catalogue, strings), "Start and stop, Chat")
        let many = Moderators.toggle(lookAfterIt, Permissions.CHAT_SEND, on: false, catalogue)
        XCTAssertEqual(Moderators.summary(many, catalogue, strings), "Start and stop, See the Console and Activity, Players and 1 more")
    }

    func testEverySwitchHasAName() {
        for permission in catalogue.groups.flatMap(\.permissions) {
            XCTAssertNotNil(Shared.strings[Moderators.switchKey(permission)], permission)
        }
        for level in catalogue.levels {
            XCTAssertNotNil(Shared.strings["mobile.mod.level_\(level.id)"], level.id)
        }
    }

    func testSaveForAndApplyToAllSendEachServerTheSameSet() {
        let body = Moderators.saveFor(["survival", "creative"], lookAfterIt)
        guard case .object(let grants)? = body["grants"] else { return XCTFail("no grants") }
        XCTAssertEqual(Set(grants.keys), ["survival", "creative"])
        XCTAssertEqual(names(grants["creative"]), lookAfterIt)
        XCTAssertNil(body["new_server"])
        XCTAssertEqual(names(Moderators.applyToAll(["survival"], lookAfterIt, allServers: true)["new_server"]), lookAfterIt)
        XCTAssertNil(Moderators.applyToAll(["survival"], lookAfterIt, allServers: false)["new_server"])
    }

    func testAllServersGivesNewServersWhatMostOfTheirServersHave() {
        let sam = Moderator(username: "sam", access: [
            ServerAccess(id: "a", name: "A", permissions: Array(lookAfterIt)),
            ServerAccess(id: "b", name: "B", permissions: Array(lookAfterIt)),
            ServerAccess(id: "c", name: "C", permissions: [Permissions.SERVER_VIEW, Permissions.SERVER_CONTROL]),
            ServerAccess(id: "d", name: "D"),
        ])
        XCTAssertEqual(names(Moderators.allServers(true, sam, catalogue)["new_server"]), lookAfterIt)
        XCTAssertEqual(names(Moderators.allServers(true, Moderator(username: "jo"), catalogue)["new_server"]), lookAfterIt)
        let off = Moderators.allServers(false, sam, catalogue)
        XCTAssertEqual(off["all_servers"], .bool(false))
        XCTAssertNil(off["new_server"])
    }

    func testNamesTheAgentTakes() {
        XCTAssertTrue(Moderators.nameOk("sam"))
        XCTAssertTrue(Moderators.nameOk("sam.b-2"))
        XCTAssertFalse(Moderators.nameOk("s"))
        XCTAssertFalse(Moderators.nameOk("sam smith"))
        XCTAssertFalse(Moderators.nameOk("-sam"))
    }

    func testTheModeratorListReadsWithItsCatalogue() async throws {
        StubAgent.json("""
            {"owner": "admin", "helpers": [{"username": "sam", "role": "helper", "servers": null, "all_servers": true,
              "new_server": {"permissions": ["server.control", "server.view"], "level": "start_and_stop"},
              "access": [{"id": "survival", "name": "Survival", "permissions": ["server.control", "server.view"], "level": "start_and_stop"},
                         {"id": "creative", "name": "Creative", "permissions": [], "level": "none"}],
              "invite_waiting": true, "invite": {"created_at": 1.0, "expires_at": 86401.0},
              "active_sessions": 0, "last_used": null}],
             "permissions": {"levels": [], "groups": []}, "servers": [{"id": "survival", "name": "Survival"}]}
            """)
        let sam = try await client().moderators().helpers[0]
        XCTAssertTrue(sam.inviteWaiting)
        XCTAssertTrue(sam.allServers)
        XCTAssertEqual(sam.seen.map(\.id), ["survival"])
        XCTAssertEqual(sam.newServer.level, Levels.START_AND_STOP)
    }

    func testSavingAndInvitingSendWhatTheAgentReads() async throws {
        let c = client()
        StubAgent.json("{\"ok\": true, \"username\": \"sam\"}")
        _ = try await c.saveModerator(username: "sam", body: Moderators.saveFor(["survival"], lookAfterIt))
        let put = StubAgent.requests[0]
        XCTAssertEqual(put.request.httpMethod, "PUT")
        XCTAssertTrue(put.request.url?.absoluteString.hasSuffix("/api/accounts/sam") ?? false)
        XCTAssertTrue(String(decoding: put.body, as: UTF8.self).contains("\"grants\""))

        StubAgent.json("{\"ok\": true, \"username\": \"sam\", \"expires_at\": 2.0, \"url\": \"https://pc:8765/?pair=1&invite=x&user=sam\", \"qr\": [\"101\"]}")
        let code = try await c.inviteModerator(username: "sam", forgetPassword: true)
        XCTAssertEqual(code.qr, ["101"])
        XCTAssertTrue(StubAgent.requests[1].request.url?.absoluteString.hasSuffix("/api/accounts/sam/invite") ?? false)
        XCTAssertEqual(String(decoding: StubAgent.requests[1].body, as: UTF8.self), "{\"forget_password\":true}")

        StubAgent.json("{\"ok\": true, \"username\": \"jo\", \"invite\": {\"ok\": true, \"username\": \"jo\", \"expires_at\": 3.0}}")
        let added = try await c.addModerator(username: "jo", servers: nil, permissions: lookAfterIt)
        XCTAssertEqual(added.invite?.username, "jo")
        let sent = String(decoding: StubAgent.requests[2].body, as: UTF8.self)
        XCTAssertFalse(sent.contains("\"servers\""), sent)
        XCTAssertFalse(sent.contains("\"password\""), sent)
    }

    func testYourOwnDevicesAndSigningOneOut() async throws {
        let c = client()
        StubAgent.json("""
            {"sessions": [{"id": "a1", "user": "sam", "label": "Command Block on iPhone", "last_used": 5.0, "current": true},
                          {"id": "b2", "user": "sam", "label": "Firefox", "last_used": 3.0}], "remember_days": 30}
            """)
        let devices = try await c.devices().sessions
        XCTAssertEqual(devices.map(\.current), [true, false])
        StubAgent.json("{\"ok\": true}")
        try await c.signOutDevice(id: "b2")
        XCTAssertEqual(StubAgent.requests[1].request.httpMethod, "DELETE")
        XCTAssertTrue(StubAgent.requests[1].request.url?.absoluteString.hasSuffix("/api/sessions/b2") ?? false)
    }

    // MARK: - Invites

    private let link = "https://pc.tail1234.ts.net:8765/?pair=1&fp=\(String(repeating: "ab", count: 32))&api=1&invite=Zx_9-abcdefghijklmnopqrstu&user=sam"

    func testAnInviteIsReadFromACodePastedTextOrALink() throws {
        XCTAssertEqual(InviteLink.parse(link), Invite(token: "Zx_9-abcdefghijklmnopqrstu", username: "sam"))
        XCTAssertEqual(InviteLink.parse("Here it is:\n\(link)\nIt works once.")?.username, "sam")
        let pairing = try PairingLink.parse(InviteLink.url(link)!)
        XCTAssertEqual(pairing.host, "pc.tail1234.ts.net")
        XCTAssertEqual(pairing.fingerprint, String(repeating: "ab", count: 32))
    }

    func testABrokenInviteIsRefused() {
        XCTAssertNil(InviteLink.parse("https://pc:8765/?pair=1&fp=\(String(repeating: "ab", count: 32))"))
        XCTAssertNil(InviteLink.parse(link.replacingOccurrences(of: "invite=Zx_9-abcdefghijklmnopqrstu", with: "invite=short")))
        XCTAssertNil(InviteLink.parse(link.replacingOccurrences(of: "user=sam", with: "user=")))
        XCTAssertNil(InviteLink.parse(link.replacingOccurrences(of: "user=sam", with: "user=a%20b")))
        XCTAssertNil(InviteLink.parse(""))
    }

    func testUsedCancelledAndRunOutInvitesSayToAskForANewOne() async {
        let c = client(signedIn: false)
        for words in [
            "This invite was already used. Ask the owner for a new one.",
            "This invite was cancelled. Ask the owner for a new one.",
            "This invite has run out. Ask the owner for a new one.",
        ] {
            StubAgent.json("{\"detail\": \"\(words)\"}", status: 410)
            do {
                _ = try await c.checkInvite(token: "Zx_9-abcdefghijklmnopqrstu")
                XCTFail("an ended invite was taken")
            } catch let error as AgentError {
                guard case .failed(_, let reason, _, _) = error else { return XCTFail("\(error)") }
                XCTAssertEqual(reason, words)
            } catch {
                XCTFail("\(error)")
            }
        }
    }

    func testAcceptingAnInviteNeedsNoSignInAndReturnsOne() async throws {
        StubAgent.json("{\"token\": \"new-token-for-sam-1234567890\", \"user\": \"sam\", \"role\": \"helper\", \"expires_at\": null}")
        let result = try await client(signedIn: false).acceptInvite(token: "Zx_9-abcdefghijklmnopqrstu", password: "a long password", device: "Command Block on iPhone")
        XCTAssertEqual(result.token, "new-token-for-sam-1234567890")
        XCTAssertTrue(StubAgent.requests[0].request.url?.absoluteString.hasSuffix("/api/invite/accept") ?? false)
        XCTAssertNil(StubAgent.requests[0].request.value(forHTTPHeaderField: "Authorization"))
    }

    func testTheConsoleChatActivityAndCrashesNeedSeeTheConsole() throws {
        func me(_ body: String) throws -> Me { try JSONDecoder().decode(Me.self, from: Data(body.utf8)) }
        let sam = try me("""
            {"user": "sam", "role": "helper", "permissions": [], "account_permissions": [],
             "server_permissions": {"survival": ["server.view", "server.control"], "creative": ["server.view", "console.read"]}}
            """)
        XCTAssertFalse(sam.forServer("survival").readsConsole)
        XCTAssertTrue(sam.forServer("creative").readsConsole)
        XCTAssertTrue(try me(#"{"user": "mark", "role": "owner", "permissions": []}"#).readsConsole)
        // An agent older than part 6 doesn't say: they show, as before.
        XCTAssertTrue(try me(#"{"user": "sam", "role": "helper", "permissions": ["server.view"]}"#).readsConsole)
    }
}
