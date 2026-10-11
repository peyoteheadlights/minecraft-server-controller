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

    func testOnlyAFinishedChangeWithABackupMadeBeforeItCanBeUndone() {
        let undo = Undo(backup: "safety-1.zip")
        let jobs = [
            Job(id: "a", state: "running", undo: undo),
            Job(id: "b", state: "succeeded"),
            Job(id: "c", state: "succeeded", undo: undo),
            Job(id: "d", state: "succeeded", undo: undo),
        ]
        XCTAssertEqual(Backups.lastUndoable(jobs)?.id, "c")
        XCTAssertNil(Backups.lastUndoable(Array(jobs.prefix(2))))
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
}
