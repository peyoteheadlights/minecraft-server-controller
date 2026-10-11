import XCTest
@testable import Core

final class SetupTests: XCTestCase {
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

    private func body(_ index: Int) -> String {
        String(data: StubAgent.requests[index].body, encoding: .utf8) ?? ""
    }

    private func path(_ index: Int) -> String {
        StubAgent.requests[index].request.url?.path ?? ""
    }

    private func method(_ index: Int) -> String {
        StubAgent.requests[index].request.httpMethod ?? ""
    }

    private let settingsJSON = #"""
    {"server_id": "s", "server": {"name": "Survival", "autosleep": true, "autosleep_minutes": 30,
     "start_timeout": 300.0, "stop_timeout": 90, "autostart_minecraft": false, "cpu_cores": []},
     "color": "#3366CC", "palette": [{"id": "blue", "name": "Blue", "hex": "#3366CC"}],
     "monitor": {"auto_restart": true, "restart_delay": 10.5, "max_crashes": 5, "crash_window_minutes": 10},
     "backups": {"keep_daily": 7, "keep_weekly": 4, "keep_monthly": 3}, "mods": {}, "overrides": {}, "editable": [],
     "cpu": {"logical_cores": 8, "supported": true, "unsupported_reason": null, "others": [],
       "status": {"configured": null, "applied": null, "applied_reason": "The server is not running", "problems": []}},
     "sleep": {"enabled": true, "minutes": 30, "players_online": 0, "stops_in": 125.0, "list_answered": true}}
    """#

    private func settings() throws -> ServerSettings {
        try JSONDecoder().decode(ServerSettings.self, from: Data(settingsJSON.utf8))
    }

    private func me(_ permissions: String...) -> Me {
        Me(user: "x", role: "helper", permissions: permissions)
    }

    func testServerSettingsDecodeAndEveryFieldStartsAtItsSavedValue() throws {
        let settings = try settings()
        XCTAssertEqual(ServerForm.initial(settings, ServerForm.NAME), "Survival")
        XCTAssertEqual(ServerForm.initial(settings, "monitor.auto_restart"), "true")
        XCTAssertEqual(ServerForm.initial(settings, "monitor.restart_delay"), "10.5")
        XCTAssertEqual(ServerForm.initial(settings, "server.start_timeout"), "300")
        XCTAssertEqual(ServerForm.initial(settings, "backups.keep_daily"), "7")
        XCTAssertEqual(ServerForm.initial(settings, "server.autostart_minecraft"), "false")
        XCTAssertEqual(settings.cpu.logicalCores, 8)
        XCTAssertNil(settings.cpu.status.configured)
        XCTAssertEqual(settings.palette.first?.id, "blue")
    }

    func testOnlySomeoneWhoMayEditSettingsCanChangeThemAndOnlyViewersSeeThem() {
        XCTAssertFalse(ServerForm.visible(nil))
        XCTAssertFalse(ServerForm.visible(me()))
        XCTAssertTrue(ServerForm.visible(me(Permissions.SETTINGS_VIEW)))
        XCTAssertFalse(ServerForm.editable(me(Permissions.SETTINGS_VIEW)))
        XCTAssertTrue(ServerForm.editable(me(Permissions.SETTINGS_VIEW, Permissions.SETTINGS_EDIT)))
    }

    func testSaveSendsOnlyWhatChangedTypedAsTheAgentTakesIt() throws {
        let settings = try settings()
        let nothing = ServerForm.changed(settings, ["monitor.auto_restart": "true", "server.start_timeout": "300", ServerForm.NAME: " Survival "])
        XCTAssertTrue(nothing.isEmpty)
        let sent = ServerForm.changed(settings, [
            ServerForm.NAME: "  Creative ",
            "monitor.auto_restart": "false",
            "monitor.restart_delay": "20",
            "backups.keep_daily": "3",
            "server.autosleep_minutes": "soon",
        ])
        XCTAssertEqual(sent, [
            "server.name": .string("Creative"),
            "monitor.auto_restart": .bool(false),
            "monitor.restart_delay": .number(20),
            "server.autosleep_minutes": .string("soon"),
            "backups.keep_daily": .number(3),
        ])
        XCTAssertTrue(ServerForm.changed(settings, [ServerForm.NAME: "  "]).isEmpty)
    }

    func testSayingWhatHappened() {
        XCTAssertEqual(ServerForm.saved(s, sent: false, result: nil), "Nothing changed.")
        XCTAssertEqual(ServerForm.saved(s, sent: true, result: ServerSettingsSaved()), "Settings saved.")
        let refused = ServerSettingsSaved(rejected: ["server.autosleep_minutes": "Pick between 1 minute and 24 hours."])
        XCTAssertEqual(ServerForm.saved(s, sent: true, result: refused), s.t("mobile.game.fix_marked"))
    }

    func testATypedColorMustBeOne() {
        XCTAssertEqual(ServerForm.color("#3366cc"), "#3366CC")
        XCTAssertEqual(ServerForm.color("3366cc"), "#3366CC")
        XCTAssertNil(ServerForm.color("#36c"))
        XCTAssertNil(ServerForm.color("blue"))
    }

    func testSleepSaysOnlyWhatWasMeasured() throws {
        var settings = try settings()
        XCTAssertEqual(ServerForm.sleepLine(s, settings), "Empty. Stopping in 2m.")
        settings.sleep?.playersOnline = nil
        XCTAssertEqual(ServerForm.sleepLine(s, settings), s.t("serverset.sleep_unknown_players"))
        settings.sleep = nil
        XCTAssertEqual(ServerForm.sleepLine(s, settings), s.t("value.unknown"))
        settings.server = ["autosleep": .bool(false)]
        XCTAssertEqual(ServerForm.sleepLine(s, settings), s.t("serverset.sleep_off"))
    }

    func testServerSettingsAndColorGoToTheAgentsRoutes() async throws {
        let c = client()
        StubAgent.json(settingsJSON)
        let read = try await c.serverSettings(serverId: "s")
        XCTAssertEqual(ServerForm.initial(read, ServerForm.NAME), "Survival")
        XCTAssertEqual(path(0), "/api/servers/s/settings")
        StubAgent.json(#"{"ok": true, "applied": {"server.name": "C"}, "rejected": {"server.autosleep_minutes": "Pick between 1 minute and 24 hours."}}"#)
        let saved = try await c.saveServerSettings(serverId: "s", updates: ["server.name": .string("C")])
        XCTAssertEqual(saved.applied["server.name"], .string("C"))
        XCTAssertEqual(saved.rejected["server.autosleep_minutes"], "Pick between 1 minute and 24 hours.")
        XCTAssertEqual(method(1), "PUT")
        XCTAssertEqual(body(1), #"{"updates":{"server.name":"C"}}"#)
        StubAgent.json(#"{"ok": true, "color": "#3366CC"}"#)
        let color = try await c.setColor(serverId: "s", color: "#3366CC")
        XCTAssertEqual(color.color, "#3366CC")
        XCTAssertEqual(path(2), "/api/servers/s/color")
        XCTAssertEqual(body(2), #"{"color":"#3366CC"}"#)
    }
}
