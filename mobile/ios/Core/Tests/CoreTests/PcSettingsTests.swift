import XCTest
@testable import Core

/// The owner's PC settings (agent/api/routes/settings.py and the routes beside it).
final class PcSettingsTests: XCTestCase {
    private let strings = Strings(Shared.strings)
    private let token = "secret-session-token-1234567890"
    private let pairing = Pairing(host: "localhost", port: 8765, fingerprint: String(repeating: "ab", count: 32), apiVersion: 1)

    // What GET /api/settings sends: secrets only as "configured".
    private let view = try! JSONDecoder().decode(PcSettingsView.self, from: Data("""
        {"config": {
           "notifications": {"discord_enabled": true, "email_enabled": false, "push_enabled": true,
             "events": {"server_started": true, "player_left": false, "app_updates": true},
             "email": {"host": "smtp.example.com", "to_addresses": ["me@example.com"]},
             "min_interval_seconds": 300},
           "thresholds": {"cpu_percent": 90.0, "ram_percent": 90, "disk_free_gb": 20, "tps_min": 18, "mspt_max": 50},
           "power": {"keep_awake": true}, "updates": {"check": false}, "maintenance": {"enabled": true}},
         "editable": [], "secrets": {"discord_webhook_configured": true, "smtp_configured": false, "api_token_configured": false}}
        """.utf8))

    override func setUp() {
        super.setUp()
        StubAgent.reset()
    }

    private func client() -> AgentClient {
        let value: String? = token
        return AgentClient(pairing: pairing, token: { value }, onSignedOut: {}, log: NoLog(), configuration: StubAgent.configuration())
    }

    private func body(_ index: Int) -> [String: JSONValue] {
        (try? JSONDecoder().decode([String: JSONValue].self, from: StubAgent.requests[index].body)) ?? [:]
    }

    private func path(_ index: Int) -> String {
        let url = StubAgent.requests[index].request.url
        return (url?.path ?? "") + (url?.query.map { "?" + $0 } ?? "")
    }

    func testTheAlertSettingsReadAsThePCHasThem() {
        let alerts = PcSettings.alerts(view)
        XCTAssertTrue(alerts.discord)
        XCTAssertFalse(alerts.email)
        XCTAssertTrue(alerts.phone)
        XCTAssertEqual(alerts.events.map(\.key), ["app_updates", "player_left", "server_started"])
        XCTAssertEqual(alerts.thresholds["ram_percent"], 90)
        XCTAssertEqual(alerts.repeatSeconds, 300)
        XCTAssertTrue(PcSettings.keepAwake(view))
        XCTAssertFalse(PcSettings.dailyCheck(view))
        XCTAssertTrue(PcSettings.maintenance(view))
        XCTAssertTrue(view.secrets.discord)
        XCTAssertFalse(view.secrets.email)
        XCTAssertEqual(PcSettings.emailTo(view), ["me@example.com"])
    }

    func testSavingSendsOnlyWhatChangedWithTheAgentsKeys() {
        let before = PcSettings.alerts(view)
        XCTAssertTrue(PcSettings.changes(before, before).isEmpty)
        var after = before
        after.discord = false
        after.email = true
        after.phone = false
        after.set(event: "player_left", true)
        after.thresholds["tps_min"] = 15
        after.repeatSeconds = 60
        let changes = PcSettings.changes(before, after)
        XCTAssertEqual(Set(changes.keys), [
            "notifications.discord_enabled", "notifications.email_enabled", "notifications.push_enabled",
            "notifications.events.player_left", "thresholds.tps_min", "notifications.min_interval_seconds",
        ])
        XCTAssertEqual(changes["notifications.events.player_left"], .bool(true))
        XCTAssertEqual(changes["thresholds.tps_min"], .number(15))
        // Every key saved is one the dashboard's App settings saves too.
        for key in changes.keys {
            XCTAssertTrue(PcSettings.keys.contains { key == $0 || key.hasPrefix($0) }, key)
        }
    }

    func testATypedNumberMustBeOne() {
        XCTAssertEqual(PcSettings.number(" 12,5 "), 12.5)
        XCTAssertNil(PcSettings.number("lots"))
        XCTAssertNil(PcSettings.number("-3"))
    }

    func testSavingSaysThePCsReasonForEachRefusedSetting() {
        let refused = SettingsSaved(rejected: ["thresholds.cpu_percent": "thresholds.cpu_percent must be at most 100"])
        XCTAssertEqual(PcSettings.saved(strings, refused).text, "thresholds.cpu_percent must be at most 100")
        XCTAssertFalse(PcSettings.saved(strings, refused).good)
        XCTAssertEqual(PcSettings.saved(strings, SettingsSaved()).text, strings.t("settings.saved"))
    }

    func testEachSettingSavesThroughTheAgent() async throws {
        let c = client()
        StubAgent.json("{\"ok\": true, \"applied\": {\"power.keep_awake\": false}, \"rejected\": {}}")
        StubAgent.json("{\"ok\": true, \"maintenance\": true}")
        StubAgent.json("{\"channel\": \"discord\", \"sent\": true}")
        let saved = try await c.savePcSettings(["power.keep_awake": .bool(false)])
        XCTAssertNotNil(saved.applied["power.keep_awake"])
        XCTAssertEqual(StubAgent.requests[0].request.httpMethod, "PUT")
        XCTAssertEqual(path(0), "/api/settings")
        XCTAssertEqual(body(0)["updates"], .object(["power.keep_awake": .bool(false)]))
        let set = try await c.maintenance(true)
        XCTAssertTrue(set.maintenance)
        XCTAssertEqual(body(1)["enabled"], .bool(true))
        let test = try await c.testAlert("discord")
        XCTAssertTrue(test.sent)
        XCTAssertEqual(path(2), "/api/notifications/test?channel=discord")
    }

    func testKeepAwakeSaysWhatWindowsDoesNow() {
        let running = PowerStatus(supported: true, enabled: true, active: true, running: ["Survival"], stillSleeps: ["lid_sleeps", "something_new"])
        XCTAssertEqual(PcSettings.awake(strings, running), strings.t("awake.active", ["names": "Survival"]))
        var idle = running
        idle.active = false
        XCTAssertEqual(PcSettings.awake(strings, idle), strings.t("awake.idle"))
        var off = running
        off.enabled = false
        XCTAssertEqual(PcSettings.awake(strings, off), strings.t("awake.off_now"))
        XCTAssertEqual(PcSettings.awake(strings, PowerStatus()), strings.t("awake.unsupported"))
        // A reason the phone has no words for isn't shown as a guess.
        XCTAssertEqual(PcSettings.stillSleeps(strings, running), [strings.t("awake.still_lid_sleeps")])
    }

    func testTheStartWithWindowsCheckShowsWhatWindowsSaid() throws {
        let report = try JSONDecoder().decode(StartupReport.self, from: Data(##"""
            {"supported": true, "verdict": "problems found", "registered": true, "points_to_current_app": false,
             "mechanism": "scheduled task", "problems": ["It points to an old copy."],
             "task": {"mode": "boot", "command": "C:\\old\\run.cmd", "working_directory": "C:\\old"},
             "runtime": {"last_run_time": "2026-10-11 08:00", "last_result": "0x0"},
             "last_startup": {"started_at": "2026-10-11 08:00:05", "launched_by": "task", "events": [{"event": "controller_initialized"}]},
             "startup_log": "x"}
            """##.utf8))
        XCTAssertEqual(PcSettings.verdict(report), "startup.problems_found")
        XCTAssertEqual(PcSettings.verdictGood(report), false)
        func rows(_ r: StartupReport, technical: Bool) -> [String: String] {
            Dictionary(PcSettings.startupRows(strings, r, technical: technical).map { ($0.name, $0.value) }, uniquingKeysWith: { a, _ in a })
        }
        let simple = rows(report, technical: false)
        XCTAssertEqual(simple[strings.t("startup.registered")], strings.t("startup.found"))
        XCTAssertEqual(simple[strings.t("startup.mode")], strings.t("startup.at_boot"))
        XCTAssertEqual(simple[strings.t("startup.points_here")], strings.t("value.no"))
        XCTAssertEqual(simple[strings.t("startup.initialised")], strings.t("value.yes"))
        XCTAssertNil(simple[strings.t("startup.command")])
        XCTAssertEqual(rows(report, technical: true)[strings.t("startup.command")], "C:\\old\\run.cmd")
        // Nothing read from Windows: unknown, never a guess.
        let blank = rows(try JSONDecoder().decode(StartupReport.self, from: Data(#"{"verdict": "not registered"}"#.utf8)), technical: false)
        XCTAssertEqual(blank[strings.t("startup.registered")], strings.t("value.unknown"))
        XCTAssertEqual(blank[strings.t("startup.last_start")], strings.t("startup.none"))
    }

    func testExportNeedsAFolderAndAPassphraseWhenPasswordsGoToo() {
        XCTAssertFalse(PcSettings.canExport(folder: nil, secrets: false, passphrase: ""))
        XCTAssertTrue(PcSettings.canExport(folder: "D:\\Moves", secrets: false, passphrase: ""))
        XCTAssertFalse(PcSettings.canExport(folder: "D:\\Moves", secrets: true, passphrase: "short"))
        XCTAssertTrue(PcSettings.canExport(folder: "D:\\Moves", secrets: true, passphrase: "long enough phrase"))
        let body = PcSettings.exportBody(worlds: true, backups: false, secrets: false, passphrase: "ignored", folder: "D:\\Moves")
        XCTAssertEqual(body["folder"], .string("D:\\Moves"))
        XCTAssertNil(body["passphrase"])
        let totals = PcSettings.totals(ExportSizes(servers: [
            ExportServerSizes(files: 1, worlds: 10, backups: 100), ExportServerSizes(files: 2, worlds: 20, backups: 200),
        ]))
        XCTAssertEqual(totals, PcSettings.Totals(files: 3, worlds: 30, backups: 300))
    }

    func testExportShowsItsProgressThenWhereOnThePCItWasSaved() async throws {
        let c = client()
        StubAgent.json("{\"ok\": true, \"job_id\": \"j1\"}")
        StubAgent.json("{\"id\": \"j1\", \"kind\": \"export\", \"title\": \"Exporting everything\", \"state\": \"running\", \"step\": \"Writing the export file\", \"progress\": 0.5}")
        StubAgent.json(##"{"id": "j1", "kind": "export", "title": "Exporting everything", "state": "succeeded", "result": {"token": "t", "filename": "e.zip", "size_bytes": 2048, "saved_to": "D:\\Moves\\e.zip"}}"##)
        let started = try await c.startExport(PcSettings.exportBody(worlds: true, backups: false, secrets: false, passphrase: "", folder: "D:\\Moves"))
        XCTAssertEqual(path(0), "/api/export")
        XCTAssertEqual(body(0)["folder"], .string("D:\\Moves"))
        let running = PcSettings.exporting(try await c.exportJob(started.jobId))
        XCTAssertEqual(running, .running(step: "Writing the export file", progress: 0.5))
        XCTAssertEqual(path(1), "/api/jobs/j1")
        let done = PcSettings.exporting(try await c.exportJob(started.jobId))
        XCTAssertEqual(done, .saved(path: "D:\\Moves\\e.zip", size: 2048))
        XCTAssertTrue(PcSettings.exportSaid(strings, done)?.contains("D:\\Moves\\e.zip") ?? false)
        // A failure says the PC's reason; a finished export with no folder isn't called saved.
        XCTAssertEqual(PcSettings.exportSaid(strings, .failed("Disk full")), "Disk full")
        let noFolder = try JSONDecoder().decode(ExportJob.self, from: Data(#"{"id": "j", "state": "succeeded", "result": {"token": "t"}}"#.utf8))
        XCTAssertEqual(PcSettings.exportSaid(strings, PcSettings.exporting(noFolder)), strings.t("export.failed"))
    }

    func testGetHelpListsItsFilesThenMakesOne() async throws {
        let c = client()
        StubAgent.json("{\"files\": [{\"name\": \"logs/agent.log\", \"size\": 1200}, {\"name\": \"system-check.json\", \"size\": null}]}")
        StubAgent.json("{\"ok\": true, \"token\": \"abc\", \"filename\": \"help.zip\", \"files\": []}")
        let files = try await c.helpFiles()
        XCTAssertEqual(files.files.map(\.name), ["logs/agent.log", "system-check.json"])
        XCTAssertNil(files.files[1].size)
        let made = try await c.makeHelpFile()
        XCTAssertEqual(made.token, "abc")
        XCTAssertEqual(body(1)["confirm"], .bool(true))
    }

    func testSignedInDevicesListEveryAccountAndEveryoneCanBeSignedOut() async throws {
        let devices = try JSONDecoder().decode(DeviceList.self, from: Data("""
            {"sessions": [{"id": "1", "user": "sam", "label": "Pixel 8", "last_used": 50},
                          {"id": "2", "user": "mark", "label": "Firefox", "last_used": 90},
                          {"id": "3", "user": "mark", "label": "This phone", "last_used": 10, "current": true},
                          {"id": "4", "user": "alex", "label": "iPhone", "last_used": 20}]}
            """.utf8)).sessions
        let grouped = PcSettings.byAccount(devices, me: "mark")
        XCTAssertEqual(grouped.map(\.user), ["mark", "alex", "sam"])
        XCTAssertEqual(grouped[0].devices.map(\.id), ["3", "2"])
        let c = client()
        StubAgent.json("{\"ok\": true}")
        StubAgent.json("{\"ok\": true, \"revoked\": 4}")
        try await c.signOutDevice(id: "1")
        XCTAssertEqual(StubAgent.requests[0].request.httpMethod, "DELETE")
        XCTAssertEqual(path(0), "/api/sessions/1")
        let revoked = try await c.signEveryoneOut()
        XCTAssertEqual(revoked.revoked, 4)
        XCTAssertEqual(path(1), "/api/security/revoke-sessions")
    }

    // MARK: - The app update

    private let upToDate = UpdateStatus(current: "1.9.0", checkedAt: 1, canInstall: true)
    private var ready: UpdateStatus {
        var status = upToDate
        status.available = true
        status.latest = Release(version: "1.10.0", notes: "- Faster\n\n* Moderators\n")
        return status
    }

    func testTheUpdateScreensStates() {
        XCTAssertEqual(PcUpdate.shows(upToDate), .upToDate)
        XCTAssertEqual(PcUpdate.shows(ready), .ready)
        var cant = ready
        cant.canInstall = false
        XCTAssertEqual(PcUpdate.shows(cant), .cantInstall)
        XCTAssertEqual(PcUpdate.shows(ready, updating: "1.10.0"), .updating)
        XCTAssertEqual(PcUpdate.shows(UpdateStatus(current: "1.10.0", lastResult: UpdateResult(ok: true, version: "1.10.0"))), .updated)
        let failed = UpdateStatus(current: "1.9.0", lastResult: UpdateResult(ok: false, version: "1.10.0", rolledBack: true))
        XCTAssertEqual(PcUpdate.shows(failed), .failed)
        XCTAssertEqual(
            PcUpdate.lastResult(strings, failed.lastResult),
            strings.t("update.last_failed", ["version": "1.10.0"]) + " " + strings.t("update.rolled_back")
        )
        XCTAssertEqual(PcUpdate.notes(ready.latest), ["Faster", "Moderators"])
    }

    func testThePhoneKnowsWhenThePCIsBack() {
        // Still the old copy answering: not back yet.
        XCTAssertFalse(PcUpdate.back(before: ready, now: ready, target: "1.10.0"))
        var moved = ready
        moved.current = "1.10.0"
        XCTAssertTrue(PcUpdate.back(before: ready, now: moved, target: "1.10.0"))
        // Back on the old version, saying the update didn't work: back too.
        var failed = ready
        failed.lastResult = UpdateResult(ok: false, version: "1.10.0", rolledBack: true)
        XCTAssertTrue(PcUpdate.back(before: ready, now: failed, target: "1.10.0"))
    }

    func testTheConfirmationSaysWhoIsPlayingOnlyWhenThePCCouldTell() {
        var check = ready
        check.playersOnline = 0
        XCTAssertEqual(PcUpdate.confirmBody(strings, check), strings.t("update.confirm_body"))
        check.playersOnline = 3
        XCTAssertTrue(PcUpdate.confirmBody(strings, check).hasSuffix(strings.t("update.confirm_players", ["count": 3])))
        XCTAssertEqual(PcUpdate.confirmLabel(strings, check), strings.t("update.install_anyway"))
        check.playersOnline = nil
        XCTAssertTrue(PcUpdate.confirmBody(strings, check).hasSuffix(strings.t("update.confirm_players_unknown")))
    }

    func testInstallingTheOldCopyAndItsRemovalGoThroughTheAgent() async throws {
        let c = client()
        StubAgent.json(#"{"current": "1.9.0", "available": true, "checking": true, "install_kind": "installer", "can_install": true, "latest": {"version": "1.10.0"}, "players_online": 2, "players": []}"#)
        StubAgent.json(#"{"ok": true, "job": {"id": "u1", "kind": "app_update", "title": "Updating", "state": "running"}}"#)
        StubAgent.json(##"{"old_copy": {"path": "C:\\Users\\me\\mcsc", "offer": true, "problems": [], "removes": []}}"##)
        StubAgent.json(##"{"ok": true, "path": "C:\\Users\\me\\mcsc", "removed": ["a"], "kept": ["backups", "worlds"], "failed": [], "folder_removed": false}"##)
        let checks = try await c.updateChecks()
        XCTAssertEqual(checks.playersOnline, 2)
        XCTAssertEqual(path(0), "/api/updates/preflight")
        let started = try await c.installUpdate()
        XCTAssertEqual(started.job.id, "u1")
        XCTAssertEqual(path(1), "/api/updates/install")
        let old = try await c.oldCopy()
        XCTAssertEqual(old.oldCopy?.offer, true)
        let removed = try await c.removeOldCopy()
        XCTAssertEqual(PcUpdate.oldCopyRemoved(strings, removed), strings.t("oldcopy.removed_kept", ["count": 2]))
    }
}
