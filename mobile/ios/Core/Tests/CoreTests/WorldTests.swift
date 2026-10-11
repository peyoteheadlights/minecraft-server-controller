import XCTest
@testable import Core

/// Backups, Restore world, Schedules and Performance: the graphs' rules,
/// the words, and the agent's answers (mirrors WorldTest.kt).
final class WorldTests: XCTestCase {
    private let token = "secret-session-token-1234567890"
    private let s = Strings(Shared.strings)
    private let utc = TimeZone(identifier: "UTC")!
    private let us = Locale(identifier: "en_US")

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
        let url = StubAgent.requests[index].request.url
        return (url?.path ?? "") + (url?.query.map { "?" + $0 } ?? "")
    }

    // MARK: - Graphs

    func testAMissingSampleBreaksTheLineInsteadOfDrawingThroughIt() {
        let points: [(Double, Double?)] = [(0, 1), (60, 2), (120, nil), (180, 4), (240, 5), (900, 6)]
        let runs = Graphs.segments(points, gap: 150)
        XCTAssertEqual(runs.map { $0.map(\.ts) }, [[0, 60], [180, 240], [900]])
        // A bucket or two missing is jitter; more is a gap.
        XCTAssertEqual(Graphs.gap(bucketSeconds: 60, sampleInterval: 30), 150)
        XCTAssertEqual(Graphs.gap(bucketSeconds: 10, sampleInterval: 30), 90)
    }

    func testValueAxesUseRoundNumbers() {
        XCTAssertEqual(Graphs.niceTicks(4), [0, 1, 2, 3, 4])
        XCTAssertEqual(Graphs.niceTicks(10), [0, 2.5, 5, 7.5, 10])
        XCTAssertEqual(Graphs.niceTicks(1800), [0, 500, 1000, 1500, 2000])
        XCTAssertEqual(Graphs.niceTicks(0), [0, 1])
    }

    func testTimeTicksFallOnWholeClockTimesAndOnMidnightsForAWeek() {
        let quarter = Graphs.timeTicks(from: 1000, to: 1000 + 3600, zone: utc)
        XCTAssertFalse(quarter.days)
        XCTAssertEqual(quarter.ticks, [1800, 2700, 3600, 4500])
        let week = Graphs.timeTicks(from: 0, to: 7 * 86400, zone: utc)
        XCTAssertTrue(week.days)
        XCTAssertEqual(week.ticks, (1...7).map { Double($0) * 86400 })
        // In a zone three hours ahead, hours fall on the local hour.
        let hours = Graphs.timeTicks(from: 0, to: 6 * 3600, zone: TimeZone(secondsFromGMT: 3 * 3600)!)
        XCTAssertTrue(hours.ticks.allSatisfy { ($0 + 3 * 3600).truncatingRemainder(dividingBy: 3600) == 0 })
    }

    func testClockTicksStayOnTheLocalHourAcrossADaylightSavingChange() {
        // London leaves summer time at 01:00 UTC on 25 October 2026.
        let london = TimeZone(identifier: "Europe/London")!
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = london
        let change = ISO8601DateFormatter().date(from: "2026-10-25T01:00:00Z")!.timeIntervalSince1970
        let fours = Graphs.timeTicks(from: change - 12 * 3600, to: change + 12 * 3600, zone: london).ticks
        let hours = fours.map { calendar.component(.hour, from: Date(timeIntervalSince1970: $0)) }
        XCTAssertTrue(hours.allSatisfy { $0 % 4 == 0 }, "\(hours)")
        XCTAssertTrue(fours.contains { $0 > change })
        let hourly = Graphs.timeTicks(from: change - 3 * 3600, to: change + 3 * 3600, zone: london).ticks
        XCTAssertTrue(hourly.allSatisfy { calendar.component(.minute, from: Date(timeIntervalSince1970: $0)) == 0 })
    }

    func testAGraphsSpokenSummarySaysToTouchNotToUseArrowKeys() {
        let graph = Graphs.performance(s, perf([SeriesPoint(ts: 100, cpuPercent: 5)]), now: 3600, speedReported: true, zone: utc)[0]
        let said = graph.summary(s)
        XCTAssertTrue(said.hasPrefix("CPU use: latest 5%"), said)
        XCTAssertTrue(said.contains("Touch"), said)
        XCTAssertFalse(said.contains("arrow"), said)
    }

    private func perf(_ points: [SeriesPoint], limit: Double? = nil) -> Performance {
        Performance(series: Series(points: points, hours: 1, bucketSeconds: 10), sampleInterval: 30, memoryLimitMb: limit)
    }

    func testTheGraphsFollowTheDashboardsRangesAndUnits() {
        let now = 3600.0
        let data = perf([
            SeriesPoint(ts: 100, cpuPercent: 20, procRamMb: 900, tps: 19.96, players: 2, playersMax: 3),
            SeriesPoint(ts: 130, cpuPercent: 30, procRamMb: 1000, tps: 20, players: 3, playersMax: 3),
        ], limit: 2048)
        let graphs = Graphs.performance(s, data, now: now, speedReported: true, zone: utc)
        XCTAssertEqual(graphs.map(\.title), ["CPU use", "Server memory", "Game speed", "Players"])
        let (cpu, memory, speed, players) = (graphs[0], graphs[1], graphs[2], graphs[3])
        XCTAssertEqual(cpu.yTicks, [0, 25, 50, 75, 100])
        XCTAssertEqual(cpu.format(20.4, false), "20%")
        // A 2 GB limit puts memory in GB, on whole gigabytes.
        XCTAssertEqual(memory.unit, "GB")
        XCTAssertEqual(memory.yTicks, [0, 1024, 2048, 3072])
        XCTAssertEqual(memory.format(2048, true), "2 GB")
        XCTAssertEqual(memory.format(1000, false), "1.0 GB")
        XCTAssertEqual(memory.guide?.label, "Limit 2.0 GB")
        XCTAssertEqual(speed.format(19.96, false), "20.0 / 20")
        XCTAssertEqual(speed.format(15, true), "15")
        XCTAssertEqual(players.yTicks, [0, 1, 2, 3, 4])
        XCTAssertNil(cpu.empty)
        XCTAssertEqual(cpu.from, 0)
        XCTAssertEqual(cpu.to, now)
    }

    func testSmallMemoryStaysInMBAndNothingMeasuredIsSaidNotDrawnAsZero() {
        let graphs = Graphs.performance(s, perf([SeriesPoint(ts: 100, cpuPercent: 5)]), now: 3600, speedReported: false, zone: utc)
        let memory = graphs[1]
        XCTAssertEqual(memory.unit, "MB")
        XCTAssertEqual(memory.empty, "Shown while running.")
        XCTAssertTrue(memory.runs.isEmpty)
        XCTAssertEqual(graphs[2].empty, s.t("perf.speed_not_bedrock"))
        XCTAssertEqual(graphs[3].empty, s.t("perf.players_empty"))
    }

    func testTechnicalWordsAddTimePerTickAndThePCsMemory() {
        let technical = Strings(Shared.strings)
        technical.technical = true
        let data = perf([SeriesPoint(ts: 100, ramUsedMb: 8000, ramTotalMb: 16384, mspt: 12.34)])
        let graphs = Graphs.performance(technical, data, now: 3600, speedReported: true, zone: utc)
        XCTAssertEqual(graphs.count, 6)
        XCTAssertEqual(graphs[4].format(12.34, false), "12.3 ms")
        XCTAssertEqual(graphs[4].guide?.value, 50)
        XCTAssertEqual(graphs[5].yTicks, [0, 5, 10, 15, 20].map { $0 * 1024 })
    }

    // MARK: - Backups

    func testBackupsSayWhatWasCheckedAndWhereTheSecondCopyIs() {
        XCTAssertEqual(Backups.kind("safety")?.key, "backups.kind_safety")
        XCTAssertNil(Backups.kind("pre-mod"))
        XCTAssertEqual(Backups.status("ok").key, "backup.checked")
        XCTAssertEqual(Backups.status(nil).key, "value.unknown")
        XCTAssertEqual(Backups.copy(s, nil).text, "Not copied")
        XCTAssertEqual(Backups.copy(s, BackupCopy(state: "failed", reason: "disk full")).text, "Failed: disk full")
        XCTAssertEqual(Backups.copy(s, BackupCopy(state: "unreachable", reason: "unplugged")).tone, .warning)
        XCTAssertEqual(Backups.copy(s, BackupCopy(state: "weird")).text, s.t("value.unknown"))

        let good = Backup(id: 1, status: "ok", copy: BackupCopy(state: "failed"))
        let on = Offsite(directory: "E:\\Backups")
        XCTAssertTrue(Backups.canCopyAgain(good, offsite: on, canCreate: true))
        XCTAssertFalse(Backups.canCopyAgain(good, offsite: Offsite(), canCreate: true))
        var unchecked = good
        unchecked.status = "unverified"
        XCTAssertFalse(Backups.canCopyAgain(unchecked, offsite: on, canCreate: true))
        var copied = good
        copied.copy = BackupCopy(state: "ok")
        XCTAssertFalse(Backups.canCopyAgain(copied, offsite: on, canCreate: true))
        XCTAssertFalse(Backups.canCopyAgain(good, offsite: on, canCreate: false))
        var gone = good
        gone.exists = false
        XCTAssertFalse(Backups.onDisk(gone))
        XCTAssertTrue(Backups.onDisk(good))
    }

    // MARK: - Undo and Redo

    private func change(_ id: Int64, _ title: String, at: Double) -> Change {
        Change(id: id, title: title, user: "mark", madeAt: at, backup: "b\(id).zip", backupAt: at - 5, playedSeconds: 600)
    }

    func testUndoAndRedoWorkOnlyWithTheRestorePermissionSomethingToMoveAndNoTaskHoldingTheServer() {
        let both = UndoRedo(undo: [change(2, "Restore", at: 100)], redo: [change(1, "Mods", at: 50)])
        XCTAssertTrue(ChangeList.canMove(both, "undo", canRestore: true))
        XCTAssertTrue(ChangeList.canMove(both, "redo", canRestore: true))
        XCTAssertFalse(ChangeList.canMove(both, "undo", canRestore: false))
        var held = both
        held.blockedBy = "Backing up"
        XCTAssertFalse(ChangeList.canMove(held, "undo", canRestore: true))
        // A new change empties Redo: nothing to put back.
        var afterNew = both
        afterNew.redo = []
        XCTAssertFalse(ChangeList.canMove(afterNew, "redo", canRestore: true))
        XCTAssertFalse(ChangeList.canMove(UndoRedo(), "undo", canRestore: true))
    }

    func testTheListsAreSaidNewestFirstWithWhoMadeTheChange() {
        let now = 10_000.0
        var undone = change(9, "Game settings", at: 0)
        undone.undoneAt = now - 120
        let changes = UndoRedo(undo: (1...5).reversed().map { change(Int64($0), "Change \($0)", at: now - Double($0) * 3600) }, redo: [undone])
        let next = ChangeList.next(s, changes, now: now)
        XCTAssertTrue(next.contains("Change 5") && next.contains("mark"), next)
        XCTAssertEqual(ChangeList.later(s, changes, now: now).count, ChangeList.LATER)
        XCTAssertTrue(ChangeList.later(s, changes, now: now)[0].contains("Change 4"))
        XCTAssertTrue(ChangeList.nextRedo(s, changes, now: now)?.contains("Game settings") ?? false)
        XCTAssertNil(ChangeList.nextRedo(s, UndoRedo(), now: now))
        XCTAssertEqual(ChangeList.next(s, UndoRedo(), now: now), s.t("changes.nothing_to_undo"))
    }

    func testUndoSaysWhatGoesBackAndHowMuchPlayWouldBeLost() {
        let now = 7200.0
        var c = change(3, "Restore world", at: 3605)
        c.scope = ["world"]
        let asked = ChangeList.ask(s, "undo", c, now: now)
        XCTAssertEqual(asked.title, s.t("changes.undo_title", ["title": "Restore world"]))
        XCTAssertTrue(asked.body.contains(s.t("world.play_lost", ["duration": Display.duration(s, 600)])), asked.body)
        XCTAssertTrue(asked.body.hasSuffix(s.t("changes.server_stops")))
        c.scope = nil
        c.playedSeconds = nil
        let all = ChangeList.ask(s, "redo", c, now: now).body
        XCTAssertTrue(all.contains(s.t("changes.everything")) && all.contains(s.t("world.play_unknown")), all)
    }

    func testWhatIsKeptAndWhatARestoreDidAreSaidInTheDashboardsWords() {
        XCTAssertEqual(
            Backups.keeping(s, Retention(daily: 7, weekly: 4, monthly: 3)),
            "Old backups delete automatically. Kept: last 7 days, 4 weeks, 3 months."
        )
        XCTAssertNil(Backups.keeping(s, Retention(daily: 7, weekly: nil, monthly: 3)))
        XCTAssertEqual(
            Backups.made(s, BackupMade(name: "b.zip", verification: BackupCheck(ok: true, entries: 12))),
            "Backup saved and checked: b.zip (12 files)"
        )
        XCTAssertEqual(Backups.made(s, BackupMade(name: "b.zip")), "Backup saved: b.zip")
        XCTAssertEqual(
            Backups.restored(s, Restored(restored: "a.zip", safetyBackup: SafetyBackup(name: "pre.zip"))),
            "a.zip restored. The old world was saved as pre.zip."
        )
        XCTAssertEqual(Backups.restored(s, Restored(restored: "a.zip")), "a.zip restored.")
        XCTAssertEqual(Backups.checked(s, BackupCheck(ok: false, reason: "bad zip")), "Backup is damaged: bad zip")
    }

    // MARK: - Schedules

    func testSchedulesReadAsTheDashboardSaysThemAndKeepTheirPayload() throws {
        let tasks = ["backup", "restart"]
        let nightly = Schedule(
            id: 3, name: "Nightly", task: "backup", kind: "daily", expr: "04:00",
            payload: ["note": .string("keep")], enabled: true
        )
        XCTAssertEqual(Schedules.whenText(s, nightly), "Every day at 04:00")
        var cron = nightly
        cron.kind = "cron"
        cron.expr = "0 4 * * *"
        XCTAssertEqual(Schedules.whenText(s, cron), "cron 0 4 * * *")
        XCTAssertEqual(Schedules.taskName(s, "backup", tasks: tasks), "Back up")
        XCTAssertEqual(Schedules.taskName(s, "mystery", tasks: tasks), "mystery")
        var off = nightly
        off.enabled = false
        XCTAssertEqual(Schedules.next(s, off), "Off")
        XCTAssertEqual(Schedules.next(s, nightly), "Never")

        let toggled = Schedules.toggled(nightly)
        XCTAssertFalse(toggled.enabled)
        XCTAssertEqual(toggled.payload["note"], .string("keep"))
        XCTAssertEqual(toggled.expr, "04:00")
        let sent = try JSONSerialization.jsonObject(with: AgentClient.encode(toggled)) as? [String: Any]
        XCTAssertEqual((sent?["payload"] as? [String: Any])?["note"] as? String, "keep")

        let added = Schedules.newBody(s, name: "  ", task: "backup", kind: "interval", expr: " 6h ", tasks: tasks)
        XCTAssertEqual(added.name, "Back up")
        XCTAssertEqual(added.expr, "6h")
        XCTAssertTrue(added.enabled)
    }

    // MARK: - Restore world

    func testPointsInTimeReadAsAPersonSaysThem() {
        let now = 10 * 86400.0 + 15 * 3600 // day 10, 15:00 UTC
        let day = 86400.0
        XCTAssertTrue(WorldRestore.whenLabel(s, now - 3600, now: now, zone: utc, locale: us).hasPrefix("Today, 2:00"))
        XCTAssertTrue(WorldRestore.whenLabel(s, now - day, now: now, zone: utc, locale: us).hasPrefix("Yesterday, 3:00"))
        XCTAssertTrue(WorldRestore.whenLabel(s, now - 3 * day, now: now, zone: utc, locale: us).hasPrefix("Thursday, "))
        XCTAssertTrue(WorldRestore.whenLabel(s, now - 9 * day, now: now, zone: utc, locale: us).hasPrefix("Jan 2, "))
    }

    func testWhatGoingBackWouldLoseIsNeverGuessed() {
        var point = WorldPoint(backupId: 1, ageSeconds: 7800, checked: true)
        XCTAssertEqual(WorldRestore.lossLine(s, point), "2h 10m ago · play since then not known")
        point.playedSeconds = 30
        XCTAssertEqual(WorldRestore.lossLine(s, point), "2h 10m ago · no play since then")
        point.playedSeconds = 5400
        XCTAssertEqual(WorldRestore.lossLine(s, point), "2h 10m ago · about 1h 30m of play would be lost")
        XCTAssertEqual(WorldRestore.blocked(s, WorldTimeline(serverRunning: true)), s.t("world.stop_first"))
        XCTAssertEqual(WorldRestore.blocked(s, WorldTimeline(blockedBy: "Backing up")), "Wait for Backing up to finish first.")
        XCTAssertNil(WorldRestore.blocked(s, WorldTimeline(canRestore: true)))
    }

    // MARK: - Health and numbers

    func testHealthChecksShowWhatWasMeasuredItsLimitAndItsSource() {
        let check = HealthCheck(name: "CPU", status: "ok", value: .number(12.5), threshold: .number(90), detail: "Whole PC", source: "psutil")
        XCTAssertEqual(HealthChecks.value(s, check), "12.5")
        XCTAssertEqual(HealthChecks.detail(s, check), "Whole PC (limit 90) [psutil]")
        var unmeasured = check
        unmeasured.value = nil
        XCTAssertEqual(HealthChecks.value(s, unmeasured), "Unknown")
        XCTAssertEqual(HealthChecks.tone("unknown"), .neutral)
        XCTAssertEqual(HealthChecks.overall("ATTENTION NEEDED")?.key, "health.attention")
        XCTAssertNil(HealthChecks.overall("SOMETHING NEW"))
    }

    func testSizesAndSharesReadAsTheDashboardWritesThem() {
        XCTAssertEqual(Display.bytes(s, 512), "512 B")
        XCTAssertEqual(Display.bytes(s, 1536), "1.5 KB")
        XCTAssertEqual(Display.bytes(s, 200 * 1024 * 1024), "200 MB")
        XCTAssertEqual(Display.bytes(s, nil), "Unknown")
        XCTAssertEqual(Display.gb(s, 12.34), "12.3 GB")
        XCTAssertEqual(Display.pct(s, 41.6), "42%")
        XCTAssertNil(Display.memory(nil))
        XCTAssertEqual(Display.memory(800), "800 MB")
        XCTAssertEqual(Display.memory(2560), "2.5 GB")
        XCTAssertEqual(Display.dateTime(s, nil), "Never")
    }

    // MARK: - The agent

    func testARestoreIsPreviewedFirstAndOnlyConfirmedAfter() async throws {
        let c = client()
        StubAgent.json("{\"confirmation_required\": true, \"will_happen\": [\"The server will stay offline\"], \"backup\": {\"id\": 4}}")
        let preview = try await c.restoreBackup(serverId: "survival", backupId: 4, confirm: false)
        XCTAssertEqual(preview.willHappen, ["The server will stay offline"])
        XCTAssertEqual(path(0), "/api/servers/survival/backups/4/restore")
        let asked = try JSONSerialization.jsonObject(with: StubAgent.requests[0].body) as? [String: Any]
        XCTAssertEqual(asked?["confirm"] as? Bool, false)
        XCTAssertEqual(asked?["safety_backup"] as? Bool, true)

        StubAgent.json(
            "{\"ok\": true, \"restored\": \"a.zip\", \"safety_backup\": {\"id\": 9, \"name\": \"pre.zip\"}, "
                + "\"undo\": {\"kind\": \"restore_backup\", \"backup_id\": 9, \"backup\": \"pre.zip\"}, \"job_id\": \"j1\"}"
        )
        let done = try await c.restoreBackup(serverId: "survival", backupId: 4, confirm: true, startAfter: true)
        XCTAssertEqual(done.safetyBackup?.name, "pre.zip")
        let sent = try JSONSerialization.jsonObject(with: StubAgent.requests[1].body) as? [String: Any]
        XCTAssertEqual(sent?["confirm"] as? Bool, true)
        XCTAssertEqual(sent?["start_after"] as? Bool, true)
    }

    func testTheChangeListsAreReadAndUndoAndRedoSentToTheServersOwnRoutes() async throws {
        let c = client()
        StubAgent.json(
            #"{"undo": [{"id": 4, "title": "Install Sodium", "user": "mark", "made_at": 100, "undone_at": null, "scope": ["mods"], "#
                + #""backup_id": 7, "backup": "pre.zip", "backup_at": 99, "played_seconds": null}], "redo": [], "server_running": true, "blocked_by": null}"#
        )
        let changes = try await c.changes(serverId: "survival")
        XCTAssertEqual(changes.undo.first?.title, "Install Sodium")
        XCTAssertEqual(changes.undo.first?.scope, ["mods"])
        XCTAssertNil(changes.undo.first?.playedSeconds)
        XCTAssertTrue(changes.serverRunning)
        XCTAssertEqual(path(0), "/api/servers/survival/changes")

        StubAgent.json(
            #"{"ok": true, "change": {"id": 4, "title": "Install Sodium", "made_at": 100, "backup_id": 7, "backup": "pre.zip", "backup_at": 99}, "#
                + #""restored": "pre.zip", "safety_backup": {"id": 8, "name": "now.zip"}, "job_id": "j"}"#
        )
        let moved = try await c.moveChange(serverId: "survival", direction: "undo", startAfter: true)
        XCTAssertEqual(ChangeList.done(s, "undo", moved), s.t("changes.undo_done", ["title": "Install Sodium"]))
        XCTAssertEqual(path(1), "/api/servers/survival/changes/undo")
        let sent = try JSONSerialization.jsonObject(with: StubAgent.requests[1].body) as? [String: Any]
        XCTAssertEqual(sent?["start_after"] as? Bool, true)

        StubAgent.json(#"{"ok": true, "change": {"id": 4, "title": "Install Sodium", "made_at": 100, "backup": "now.zip", "backup_at": 150}, "restored": "now.zip"}"#)
        _ = try await c.moveChange(serverId: "survival", direction: "redo", startAfter: false)
        XCTAssertEqual(path(2), "/api/servers/survival/changes/redo")
    }

    func testABackupDownloadsWithTheSignInInAHeaderNeverInTheAddress() async throws {
        let zip = Data((0..<200_000).map { UInt8($0 % 251) })
        StubAgent.enqueue(StubAgent.Answer(status: 200, headers: ["Content-Type": "application/zip"], body: zip))
        let out = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".zip")
        defer { try? FileManager.default.removeItem(at: out) }
        let written = try await client().downloadBackup(serverId: "survival", backupId: 4, to: out)
        XCTAssertEqual(written, Int64(zip.count))
        XCTAssertEqual(try Data(contentsOf: out), zip)
        let request = StubAgent.requests[0].request
        XCTAssertEqual(path(0), "/api/servers/survival/backups/4/download")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer \(token)")
        XCTAssertFalse(request.url?.absoluteString.contains(token) ?? true)
    }

    func testSlowWorkWithNoAnswerInTimeMayStillBeRunningOnThePC() async {
        let value = token
        let slow = AgentClient(
            pairing: Pairing(host: "localhost", port: 8765, fingerprint: String(repeating: "ab", count: 32), apiVersion: 1),
            token: { value },
            configuration: StubAgent.configuration(),
            slowWait: 0.3
        )
        StubAgent.enqueue(StubAgent.Answer(status: 0, headers: [:], body: Data(), delay: 0.6, failure: URLError(.timedOut)))
        do {
            _ = try await slow.backUp(serverId: "survival")
            XCTFail("A backup with no answer read as done")
        } catch {
            XCTAssertEqual(error as? AgentError, .stillWorking)
        }
        // A quick call that times out is still the PC not answering.
        StubAgent.enqueue(StubAgent.Answer(status: 0, headers: [:], body: Data(), failure: URLError(.timedOut)))
        do {
            _ = try await slow.backups(serverId: "survival")
            XCTFail("No answer read as a list")
        } catch {
            XCTAssertEqual(error as? AgentError, .unreachable)
        }
    }

    func testABackupThatIsntThereComesBackInTheAgentsWords() async {
        StubAgent.json("{\"detail\": \"That backup isn't on this server's list.\"}", status: 404)
        let out = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".zip")
        do {
            _ = try await client().downloadBackup(serverId: "survival", backupId: 99, to: out)
            XCTFail("A missing backup downloaded")
        } catch {
            XCTAssertEqual(error as? AgentError, .failed(status: 404, reason: "That backup isn't on this server's list.", requestId: nil))
        }
        XCTAssertFalse(FileManager.default.fileExists(atPath: out.path))
    }

    func testTheAgentsAnswersForTheseScreensAreRead() async throws {
        let c = client()
        StubAgent.json(
            "{\"backups\": [{\"id\": 1, \"name\": \"manual-1.zip\", \"kind\": \"manual\", \"created_at\": 10.5, \"size_bytes\": 2048, "
                + "\"status\": \"ok\", \"exists\": true, \"copy\": {\"state\": \"none\", \"reason\": null}}], "
                + "\"directory\": \"C:\\\\b\", \"retention\": {\"daily\": 7, \"weekly\": 4, \"monthly\": 3}}"
        )
        let list = try await c.backups(serverId: "survival")
        XCTAssertEqual(list.backups.first?.sizeBytes, 2048)
        XCTAssertEqual(list.backups.first?.copy?.state, "none")

        StubAgent.json(
            "{\"schedules\": [{\"id\": 2, \"name\": \"Nightly\", \"task\": \"backup\", \"kind\": \"daily\", \"expr\": \"04:00\", "
                + "\"payload\": {}, \"enabled\": true, \"next_run\": 1700000000.0, \"last_run\": null, \"last_result\": null}], "
                + "\"tasks\": [\"backup\", \"restart\"]}"
        )
        let schedules = try await c.schedules(serverId: "survival")
        XCTAssertEqual(schedules.schedules.first?.name, "Nightly")

        StubAgent.json(
            "{\"current\": {\"ts\": 1, \"cpu_percent\": 12.0, \"proc_ram_mb\": null}, \"history\": [], "
                + "\"series\": {\"points\": [{\"ts\": 5.0, \"cpu_percent\": 3.0, \"tps\": null, \"samples\": 2}], \"hours\": 6, \"bucket_seconds\": 60}, "
                + "\"sample_interval\": 30, \"memory_limit_mb\": 4096, \"thresholds\": {}, \"storage\": null}"
        )
        let perf = try await c.performance(serverId: "survival", hours: 6)
        XCTAssertNil(perf.current.procRamMb)
        XCTAssertNil(perf.series.points.first?.tps)
        XCTAssertEqual(perf.memoryLimitMb, 4096)
        XCTAssertEqual(path(2), "/api/servers/survival/performance?hours=6&storage=true")

        StubAgent.json("{\"jobs\": []}")
        _ = try await c.jobs(serverId: "survival")
        XCTAssertEqual(path(3), "/api/jobs?server_id=survival&limit=20")
    }

    func testOnePlayerTheAppCantReadDoesntEmptyTheList() throws {
        let json = "{\"online\": [{\"username\": \"Alex\"}, {\"username\": 5}, {\"username\": \"Steve\"}], \"online_count\": 3, \"known\": [7, {\"username\": \"Alex\"}]}"
        let page = try JSONDecoder().decode(PlayersPage.self, from: Data(json.utf8))
        XCTAssertEqual(page.online.map(\.username), ["Alex", "Steve"])
        XCTAssertEqual(page.known.map(\.username), ["Alex"])
        XCTAssertEqual(page.onlineCount, 3)
    }

    // MARK: - Bringing a world in, taking it home

    private func me(_ permissions: String...) -> Me {
        Me(user: "x", role: "helper", permissions: permissions)
    }

    func testImportingNeedsWorldReplaceTakingItHomeNeedsBackupsDownload() {
        XCTAssertFalse(WorldImport.canImport(me(Permissions.BACKUPS_RESTORE)))
        XCTAssertTrue(WorldImport.canImport(me(Permissions.WORLD_REPLACE)))
        XCTAssertFalse(WorldImport.canDownload(me(Permissions.WORLD_REPLACE)))
        XCTAssertTrue(WorldImport.canDownload(me(Permissions.BACKUPS_DOWNLOAD)))
        XCTAssertFalse(WorldImport.canImport(nil))
        XCTAssertTrue(WorldImport.accepts("My World.ZIP"))
        XCTAssertTrue(WorldImport.accepts("island.mcworld"))
        XCTAssertFalse(WorldImport.accepts("level.dat"))
    }

    func testARunningServerHasToBeStoppedBeforeAWorldComesIn() {
        XCTAssertEqual(WorldImport.blocked(s, WorldTimeline(serverRunning: true)), s.t("import.stop_first"))
        XCTAssertEqual(WorldImport.blocked(s, WorldTimeline(blockedBy: "A backup")), s.t("world.busy", ["job": "A backup"]))
        XCTAssertNil(WorldImport.blocked(s, WorldTimeline()))
    }

    func testAWorldReadIsShownWithWhatIsKnownAndTheWrongEditionIsntOffered() throws {
        let token = String(repeating: "a", count: 32)
        let read = try JSONDecoder().decode(WorldRead.self, from: Data(("{\"token\": \"\(token)\", " + #""world": {"source": "zip", "folder_name": "Island", "name": null, "version": null, "last_played": null, "size_bytes": 2048, "files": 3, "read_problem": "truncated", "edition": "bedrock"}, "edition_matches": false, "server_edition": "java", "server_version": "1.21.1", "newer_than_server": null, "level_name": null}"#).utf8))
        XCTAssertEqual(WorldImport.title(read), "Island")
        let facts = WorldImport.facts(s, read.world, zone: utc, locale: us)
        XCTAssertEqual(facts[0].0, s.t("import.name"))
        XCTAssertEqual(facts[0].1, "Island")
        XCTAssertEqual(facts[1].1, s.t("value.unknown"))
        XCTAssertEqual(facts[2].1, s.t("import.size_value", ["size": Display.bytes(s, 2048), "files": "3"]))
        XCTAssertEqual(facts[3].1, s.t("value.unknown"))
        XCTAssertEqual(WorldImport.lines(s, read).map(\.text), [s.t("import.read_problem", ["problem": "truncated"]), s.t("import.is_bedrock")])
        XCTAssertFalse(WorldImport.canUse(read))

        var newer = read
        newer.world.edition = "java"
        newer.world.version = "1.21.4"
        newer.world.readProblem = nil
        newer.editionMatches = true
        newer.newerThanServer = true
        XCTAssertEqual(WorldImport.lines(s, newer).map(\.text), [s.t("import.newer", ["world": "1.21.4", "server": "1.21.1"])])
        XCTAssertTrue(WorldImport.canUse(newer))
    }

    func testAnImportWithABackupFirstSaysItCanBeUndone() throws {
        var result = try JSONDecoder().decode(WorldImported.self, from: Data(#"{"ok": true, "job_id": "j1", "world": {"source": "folder", "folder_name": "New", "size_bytes": 1, "files": 1}, "safety_backup": {"id": 7, "name": "pre-import.zip"}, "undo": {"kind": "restore_backup", "backup_id": 7, "backup": "pre-import.zip"}}"#.utf8))
        XCTAssertEqual(WorldImport.done(s, result), s.t("import.done_with_undo"))
        result.undo = nil
        XCTAssertEqual(WorldImport.done(s, result), s.t("import.done"))
    }

    func testWorldsAreReadImportedForgottenAndTakenHomeThroughTheAgentsRoutes() async throws {
        let c = client()
        let token = String(repeating: "b", count: 32)
        let readJSON = "{\"token\": \"\(token)\", " + #""world": {"source": "zip", "folder_name": "W", "size_bytes": 5, "files": 1}, "edition_matches": true, "server_edition": "java"}"#
        StubAgent.json(readJSON)
        let picked = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".zip")
        try Data(repeating: 1, count: 2000).write(to: picked)
        defer { try? FileManager.default.removeItem(at: picked) }
        let read = try await c.uploadWorld(serverId: "survival", file: PickedFile(name: "w.zip", url: picked))
        XCTAssertEqual(read.token, token)
        XCTAssertEqual(path(0), "/api/servers/survival/world/import/upload")

        StubAgent.json(readJSON)
        _ = try await c.pickWorldFolder(serverId: "survival", path: "C:\\saves\\W")
        XCTAssertEqual(path(1), "/api/servers/survival/world/import/folder")
        XCTAssertEqual(body(1), #"{"path":"C:\\saves\\W"}"#)

        StubAgent.json(#"{"folder": null, "worlds": []}"#)
        let saves = try await c.savedWorlds(serverId: "survival")
        XCTAssertNil(saves.folder)
        XCTAssertEqual(path(2), "/api/servers/survival/world/saves")

        StubAgent.json(#"{"ok": true, "job_id": "j", "world": {"source": "zip", "folder_name": "W", "size_bytes": 5, "files": 1}}"#)
        _ = try await c.importWorld(serverId: "survival", token: token)
        XCTAssertEqual(body(3), "{\"confirm\":true,\"token\":\"\(token)\"}")

        StubAgent.json(#"{"ok": true}"#)
        try await c.forgetWorld(serverId: "survival", token: token)
        XCTAssertEqual(StubAgent.requests[4].request.httpMethod, "DELETE")
        XCTAssertEqual(path(4), "/api/servers/survival/world/import/\(token)")

        StubAgent.json(#"{"ok": true, "token": "t1", "files": 2, "size_bytes": 3, "filename": "My World.zip"}"#)
        let packed = try await c.packWorld(serverId: "survival")
        XCTAssertEqual(path(5), "/api/servers/survival/world/download")
        let zip = Data([80, 75, 3, 4])
        StubAgent.enqueue(StubAgent.Answer(status: 200, headers: ["Content-Type": "application/zip"], body: zip))
        let out = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".zip")
        defer { try? FileManager.default.removeItem(at: out) }
        let written = try await c.downloadWorld(serverId: "survival", packed: packed, to: out)
        XCTAssertEqual(written, 4)
        XCTAssertEqual(try Data(contentsOf: out), zip)
        XCTAssertEqual(StubAgent.requests[6].request.url?.path, "/api/servers/survival/world/download/t1")
        XCTAssertEqual(StubAgent.requests[6].request.url?.query, "filename=My%20World.zip")
        XCTAssertEqual(StubAgent.requests[6].request.value(forHTTPHeaderField: "Authorization"), "Bearer \(self.token)")
    }
}
