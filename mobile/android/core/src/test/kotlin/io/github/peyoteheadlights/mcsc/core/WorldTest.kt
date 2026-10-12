package io.github.peyoteheadlights.mcsc.core

import java.io.ByteArrayOutputStream
import java.time.ZoneId
import java.time.ZoneOffset
import java.util.Locale
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import okhttp3.mockwebserver.MockResponse
import okio.Buffer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class WorldTest {
    private val token = "secret-session-token-1234567890"
    private val strings = Strings(Shared.strings)
    private val utc: ZoneId = ZoneOffset.UTC

    private fun client(agent: TestAgent) = AgentClient(agent.pairing(), { token }, systemTrust = TestAgent.trustingNothing())

    // ------------------------------------------------------------ graphs
    @Test
    fun `a missing sample breaks the line instead of drawing through it`() {
        val points = listOf(0.0 to 1.0, 60.0 to 2.0, 120.0 to null, 180.0 to 4.0, 240.0 to 5.0, 900.0 to 6.0)
        val runs = Charts.segments(points, gap = 150.0)
        assertEquals(listOf(listOf(0.0, 60.0), listOf(180.0, 240.0), listOf(900.0)), runs.map { run -> run.map { it.ts } })
        // A bucket or two missing is jitter; more is a gap.
        assertEquals(150.0, Charts.gap(bucketSeconds = 60.0, sampleInterval = 30.0), 0.0)
        assertEquals(90.0, Charts.gap(bucketSeconds = 10.0, sampleInterval = 30.0), 0.0)
    }

    @Test
    fun `value axes use round numbers`() {
        assertEquals(listOf(0.0, 1.0, 2.0, 3.0, 4.0), Charts.niceTicks(4.0))
        assertEquals(listOf(0.0, 2.5, 5.0, 7.5, 10.0), Charts.niceTicks(10.0))
        assertEquals(listOf(0.0, 500.0, 1000.0, 1500.0, 2000.0), Charts.niceTicks(1800.0))
        assertEquals(listOf(0.0, 1.0), Charts.niceTicks(0.0))
    }

    @Test
    fun `time ticks fall on whole clock times and on midnights for a week`() {
        val (quarter, days) = Charts.timeTicks(1000.0, 1000.0 + 3600, utc)
        assertFalse(days)
        assertEquals(listOf(1800.0, 2700.0, 3600.0, 4500.0), quarter)
        val (week, weekDays) = Charts.timeTicks(0.0, 7 * 86400.0, utc)
        assertTrue(weekDays)
        assertEquals((1..7).map { it * 86400.0 }, week)
        // In a zone three hours ahead, hours fall on the local hour.
        val (hours, _) = Charts.timeTicks(0.0, 6 * 3600.0, ZoneOffset.ofHours(3))
        assertTrue(hours.all { (it + 3 * 3600) % 3600 == 0.0 })
    }

    @Test
    fun `clock ticks stay on the local hour across a daylight-saving change`() {
        // London leaves summer time at 01:00 UTC on 25 October 2026.
        val london = ZoneId.of("Europe/London")
        val change = java.time.Instant.parse("2026-10-25T01:00:00Z").epochSecond.toDouble()
        val (fours, _) = Charts.timeTicks(change - 12 * 3600, change + 12 * 3600, london)
        val hours = fours.map { java.time.Instant.ofEpochSecond(it.toLong()).atZone(london).hour }
        assertTrue(hours.toString(), hours.all { it % 4 == 0 })
        assertTrue(fours.any { it > change })
        val (hourly, _) = Charts.timeTicks(change - 3 * 3600, change + 3 * 3600, london)
        assertTrue(hourly.all { java.time.Instant.ofEpochSecond(it.toLong()).atZone(london).minute == 0 })
    }

    @Test
    fun `a graph's spoken summary says to touch, not to use arrow keys`() {
        val chart = Charts.performance(strings, perf(SeriesPoint(ts = 100.0, cpuPercent = 5.0)), 3600.0, speedReported = true, zone = utc)[0]
        val said = chart.summary(strings)
        assertTrue(said, said.startsWith("CPU use: latest 5%") && said.contains("Touch") && !said.contains("arrow"))
    }

    private fun perf(vararg points: SeriesPoint, limit: Double? = null) = Performance(
        series = Series(points = points.toList(), hours = 1.0, bucketSeconds = 10.0),
        sampleInterval = 30.0,
        memoryLimitMb = limit,
    )

    @Test
    fun `the graphs follow the dashboard's ranges and units`() {
        val now = 3600.0
        val data = perf(
            SeriesPoint(ts = 100.0, cpuPercent = 20.0, procRamMb = 900.0, tps = 19.96, players = 2.0, playersMax = 3.0),
            SeriesPoint(ts = 130.0, cpuPercent = 30.0, procRamMb = 1000.0, tps = 20.0, players = 3.0, playersMax = 3.0),
            limit = 2048.0,
        )
        val charts = Charts.performance(strings, data, now, speedReported = true, zone = utc)
        assertEquals(listOf("CPU use", "Server memory", "Game speed", "Players"), charts.map { it.title })
        val (cpu, memory, speed, players) = charts
        assertEquals(listOf(0.0, 25.0, 50.0, 75.0, 100.0), cpu.yTicks)
        assertEquals("20%", cpu.format(20.4, false))
        // A 2 GB limit puts memory in GB, on whole gigabytes.
        assertEquals("GB", memory.unit)
        assertEquals(listOf(0.0, 1024.0, 2048.0, 3072.0), memory.yTicks)
        assertEquals("2 GB", memory.format(2048.0, true))
        assertEquals("1.0 GB", memory.format(1000.0, false))
        assertEquals("Limit 2.0 GB", memory.guide?.label)
        assertEquals("20.0 / 20", speed.format(19.96, false))
        assertEquals("15", speed.format(15.0, true))
        assertEquals(listOf(0.0, 1.0, 2.0, 3.0, 4.0), players.yTicks)
        assertNull(cpu.empty)
        assertEquals(0.0, cpu.from, 0.0)
        assertEquals(now, cpu.to, 0.0)
    }

    @Test
    fun `small memory stays in MB and nothing measured is said, not drawn as zero`() {
        val data = perf(SeriesPoint(ts = 100.0, cpuPercent = 5.0))
        val charts = Charts.performance(strings, data, 3600.0, speedReported = false, zone = utc)
        val memory = charts[1]
        assertEquals("MB", memory.unit)
        assertEquals("Shown while running.", memory.empty)
        assertTrue(memory.runs.isEmpty())
        assertEquals(strings.t("perf.speed_not_bedrock"), charts[2].empty)
        assertEquals(strings.t("perf.players_empty"), charts[3].empty)
    }

    @Test
    fun `technical words add time per tick and the PC's memory`() {
        val technical = Strings(Shared.strings).also { it.technical = true }
        val data = perf(SeriesPoint(ts = 100.0, mspt = 12.34, ramUsedMb = 8000.0, ramTotalMb = 16384.0))
        val charts = Charts.performance(technical, data, 3600.0, speedReported = true, zone = utc)
        assertEquals(6, charts.size)
        val mspt = charts[4]
        assertEquals("12.3 ms", mspt.format(12.34, false))
        assertEquals(50.0, mspt.guide?.value)
        assertEquals(listOf(0.0, 5.0, 10.0, 15.0, 20.0).map { it * 1024 }, charts[5].yTicks)
    }

    // ------------------------------------------------------------ backups
    @Test
    fun `backups say what was checked and where the second copy is`() {
        assertEquals("backups.kind_safety", Backups.kind("safety")?.key)
        assertNull(Backups.kind("pre-mod"))
        assertEquals("backup.checked", Backups.status("ok").key)
        assertEquals("value.unknown", Backups.status(null).key)
        assertEquals("Not copied", Backups.copy(strings, null).first)
        assertEquals("Failed: disk full", Backups.copy(strings, BackupCopy("failed", "disk full")).first)
        assertEquals(Tone.WARNING, Backups.copy(strings, BackupCopy("unreachable", "unplugged")).second)
        assertEquals(strings.t("value.unknown"), Backups.copy(strings, BackupCopy("weird")).first)

        val good = Backup(id = 1, status = "ok", copy = BackupCopy("failed"))
        val on = Offsite(directory = "E:\\Backups")
        assertTrue(Backups.canCopyAgain(good, on, canCreate = true))
        assertFalse(Backups.canCopyAgain(good, Offsite(), canCreate = true))
        assertFalse(Backups.canCopyAgain(good.copy(status = "unverified"), on, canCreate = true))
        assertFalse(Backups.canCopyAgain(good.copy(copy = BackupCopy("ok")), on, canCreate = true))
        assertFalse(Backups.canCopyAgain(good, on, canCreate = false))
        assertFalse(Backups.onDisk(good.copy(exists = false)))
        assertTrue(Backups.onDisk(good))
    }

    // ------------------------------------------------------------ undo and redo
    private fun change(id: Long, title: String, at: Double) =
        Change(id, title, user = "mark", madeAt = at, backup = "b$id.zip", backupAt = at - 5, playedSeconds = 600.0)

    @Test
    fun `Undo and Redo work only with the restore permission, something to move and no task holding the server`() {
        val both = UndoRedo(undo = listOf(change(2, "Restore", 100.0)), redo = listOf(change(1, "Mods", 50.0)))
        assertTrue(ChangeList.canMove(both, "undo", canRestore = true))
        assertTrue(ChangeList.canMove(both, "redo", canRestore = true))
        assertFalse(ChangeList.canMove(both, "undo", canRestore = false))
        assertFalse(ChangeList.canMove(both.copy(blockedBy = "Backing up"), "undo", canRestore = true))
        // A new change empties Redo: nothing to put back.
        val afterNew = both.copy(redo = emptyList())
        assertFalse(ChangeList.canMove(afterNew, "redo", canRestore = true))
        assertFalse(ChangeList.canMove(UndoRedo(), "undo", canRestore = true))
    }

    @Test
    fun `the lists are said newest first, with who made the change`() {
        val now = 10_000.0
        val changes = UndoRedo(
            undo = (5L downTo 1L).map { change(it, "Change $it", now - it * 3600) },
            redo = listOf(change(9, "Game settings", 0.0).copy(undoneAt = now - 120), change(8, "Mods", 0.0).copy(undoneAt = now - 60)),
        )
        val next = ChangeList.next(strings, changes, now)
        assertTrue(next, next.contains("Change 5") && next.contains("mark"))
        assertEquals(ChangeList.LATER, ChangeList.later(strings, changes, now).size)
        assertTrue(ChangeList.later(strings, changes, now).first().let { it.contains("Change 4") && it.contains("mark") })
        assertEquals(1, ChangeList.laterRedo(strings, changes, now).size)
        assertTrue(ChangeList.laterRedo(strings, changes, now).first().let { it.contains("Mods") && it.contains("mark") })
        assertTrue(ChangeList.nextRedo(strings, changes, now)!!.contains("Game settings"))
        assertNull(ChangeList.nextRedo(strings, UndoRedo(), now))
        assertEquals(strings.t("changes.nothing_to_undo"), ChangeList.next(strings, UndoRedo(), now))
    }

    @Test
    fun `Undo says what goes back and how much play would be lost`() {
        val now = 7200.0
        val c = change(3, "Restore world", 3605.0).copy(scope = listOf("world"))
        val (title, body) = ChangeList.ask(strings, "undo", c, now)
        assertEquals(strings.t("changes.undo_title", "title" to "Restore world"), title)
        assertTrue(body, body.contains("world"))
        assertTrue(body, body.contains(strings.t("world.play_lost", "duration" to Display.duration(strings, 600.0))))
        assertTrue(body, body.endsWith(strings.t("changes.server_stops")))
        // Everything in the backup when the change names nothing; play unknown stays unknown.
        val (_, all) = ChangeList.ask(strings, "redo", c.copy(scope = null, playedSeconds = null), now)
        assertTrue(all, all.contains(strings.t("changes.everything")) && all.contains(strings.t("world.play_unknown")))
    }

    @Test
    fun `what is kept and what a restore did are said in the dashboard's words`() {
        assertEquals(
            "Old backups delete automatically. Kept: last 7 days, 4 weeks, 3 months.",
            Backups.keeping(strings, Retention(7, 4, 3)),
        )
        assertNull(Backups.keeping(strings, Retention(7, null, 3)))
        assertEquals(
            "Backup saved and checked: b.zip (12 files)",
            Backups.made(strings, BackupMade("b.zip", BackupCheck(ok = true, entries = 12))),
        )
        assertEquals("Backup saved: b.zip", Backups.made(strings, BackupMade("b.zip")))
        assertEquals(
            "a.zip restored. The old world was saved as pre.zip.",
            Backups.restored(strings, Restored(restored = "a.zip", safetyBackup = SafetyBackup(1, "pre.zip"))),
        )
        assertEquals("a.zip restored.", Backups.restored(strings, Restored(restored = "a.zip")))
        assertEquals("Backup is damaged: bad zip", Backups.checked(strings, BackupCheck(ok = false, reason = "bad zip")))
    }

    // ------------------------------------------------------------ schedules
    @Test
    fun `schedules read as the dashboard says them and keep their payload`() {
        val tasks = listOf("backup", "restart")
        val nightly = Schedule(
            id = 3, name = "Nightly", task = "backup", kind = "daily", expr = "04:00",
            payload = buildJsonObject { put("note", "keep") }, enabled = true, nextRun = null,
        )
        assertEquals("Every day at 04:00", Schedules.whenText(strings, nightly))
        assertEquals("cron 0 4 * * *", Schedules.whenText(strings, nightly.copy(kind = "cron", expr = "0 4 * * *")))
        assertEquals("Back up", Schedules.taskName(strings, "backup", tasks))
        assertEquals("mystery", Schedules.taskName(strings, "mystery", tasks))
        assertEquals("Off", Schedules.next(strings, nightly.copy(enabled = false)))
        assertEquals("Never", Schedules.next(strings, nightly))

        val off = Schedules.toggled(nightly)
        assertEquals(false, off["enabled"]?.jsonPrimitive?.content?.toBoolean())
        assertEquals("keep", (off["payload"] as kotlinx.serialization.json.JsonObject)["note"]?.jsonPrimitive?.content)
        assertEquals("04:00", off["expr"]?.jsonPrimitive?.content)

        val added = Schedules.newBody(strings, "  ", "backup", "interval", " 6h ", tasks)
        assertEquals("Back up", added["name"]?.jsonPrimitive?.content)
        assertEquals("6h", added["expr"]?.jsonPrimitive?.content)
        assertEquals(JsonPrimitive(true), added["enabled"])
    }

    // ------------------------------------------------------------ restore world
    @Test
    fun `points in time read as a person says them`() {
        val now = 10 * 86400.0 + 15 * 3600.0 // day 10, 15:00 UTC
        val day = 86400.0
        assertTrue(WorldRestore.whenLabel(strings, now - 3600, now, utc, Locale.US).startsWith("Today, 2:00"))
        assertTrue(WorldRestore.whenLabel(strings, now - day, now, utc, Locale.US).startsWith("Yesterday, 3:00"))
        assertTrue(WorldRestore.whenLabel(strings, now - 3 * day, now, utc, Locale.US).startsWith("Thursday, "))
        assertTrue(WorldRestore.whenLabel(strings, now - 9 * day, now, utc, Locale.US).startsWith("Jan 2, "))
    }

    @Test
    fun `what going back would lose is never guessed`() {
        val point = WorldPoint(backupId = 1, ageSeconds = 7800.0, checked = true)
        assertEquals("2h 10m ago · play since then not known", WorldRestore.lossLine(strings, point))
        assertEquals("2h 10m ago · no play since then", WorldRestore.lossLine(strings, point.copy(playedSeconds = 30.0)))
        assertEquals(
            "2h 10m ago · about 1h 30m of play would be lost",
            WorldRestore.lossLine(strings, point.copy(playedSeconds = 5400.0)),
        )
        assertEquals(strings.t("world.stop_first"), WorldRestore.blocked(strings, WorldTimeline(serverRunning = true)))
        assertEquals("Wait for Backing up to finish first.", WorldRestore.blocked(strings, WorldTimeline(blockedBy = "Backing up")))
        assertNull(WorldRestore.blocked(strings, WorldTimeline(canRestore = true)))
    }

    // ------------------------------------------------------------ health and numbers
    @Test
    fun `health checks show what was measured, its limit and its source`() {
        val check = HealthCheck(
            name = "CPU", status = "ok", value = JsonPrimitive(12.5), threshold = JsonPrimitive(90),
            detail = "Whole PC", source = "psutil",
        )
        assertEquals("12.5", HealthChecks.value(strings, check))
        assertEquals("Whole PC (limit 90) [psutil]", HealthChecks.detail(strings, check))
        assertEquals("Unknown", HealthChecks.value(strings, check.copy(value = null)))
        assertEquals(Tone.NEUTRAL, HealthChecks.tone("unknown"))
        assertEquals("health.attention", HealthChecks.overall("ATTENTION NEEDED")?.key)
        assertNull(HealthChecks.overall("SOMETHING NEW"))
    }

    @Test
    fun `sizes and shares read as the dashboard writes them`() {
        assertEquals("512 B", Display.bytes(strings, 512))
        assertEquals("1.5 KB", Display.bytes(strings, 1536))
        assertEquals("200 MB", Display.bytes(strings, 200L * 1024 * 1024))
        assertEquals("Unknown", Display.bytes(strings, null))
        assertEquals("12.3 GB", Display.gb(strings, 12.34))
        assertEquals("42%", Display.pct(strings, 41.6))
        assertNull(Display.memory(null))
        assertEquals("800 MB", Display.memory(800.0))
        assertEquals("2.5 GB", Display.memory(2560.0))
        assertEquals("Never", Display.dateTime(strings, null))
    }

    // ------------------------------------------------------------ the agent
    @Test
    fun `a restore is previewed first and only confirmed after`() = runBlocking {
        TestAgent().use { agent ->
            val c = client(agent)
            agent.server.enqueue(agent.json("""{"confirmation_required": true, "will_happen": ["The server will stay offline"], "backup": {"id": 4}}"""))
            val preview = c.restoreBackup("survival", 4, confirm = false)
            assertEquals(listOf("The server will stay offline"), preview.willHappen)
            val asked = agent.server.takeRequest()
            assertEquals("/api/servers/survival/backups/4/restore", asked.path)
            val body = asked.body.readUtf8()
            assertTrue(body, body.contains("\"confirm\":false") && body.contains("\"safety_backup\":true"))

            agent.server.enqueue(agent.json("""{"ok": true, "restored": "a.zip", "safety_backup": {"id": 9, "name": "pre.zip"}, "undo": {"kind": "restore_backup", "backup_id": 9, "backup": "pre.zip"}, "job_id": "j1"}"""))
            val done = c.restoreBackup("survival", 4, confirm = true, startAfter = true)
            assertEquals("pre.zip", done.safetyBackup?.name)
            val sent = agent.server.takeRequest().body.readUtf8()
            assertTrue(sent, sent.contains("\"confirm\":true") && sent.contains("\"start_after\":true"))
        }
    }

    @Test
    fun `the change lists are read and Undo and Redo sent to the server's own routes`() = runBlocking {
        TestAgent().use { agent ->
            val c = client(agent)
            agent.server.enqueue(agent.json("""{"undo": [{"id": 4, "title": "Install Sodium", "user": "mark", "made_at": 100, "undone_at": null, "scope": ["mods"], "backup_id": 7, "backup": "pre.zip", "backup_at": 99, "played_seconds": null}], "redo": [], "server_running": true, "blocked_by": null}"""))
            val changes = c.changes("survival")
            assertEquals("Install Sodium", changes.undo.single().title)
            assertEquals(listOf("mods"), changes.undo.single().scope)
            assertNull(changes.undo.single().playedSeconds)
            assertTrue(changes.serverRunning)
            assertEquals("/api/servers/survival/changes", agent.server.takeRequest().path)

            agent.server.enqueue(agent.json("""{"ok": true, "change": {"id": 4, "title": "Install Sodium", "made_at": 100, "backup_id": 7, "backup": "pre.zip", "backup_at": 99}, "restored": "pre.zip", "safety_backup": {"id": 8, "name": "now.zip"}, "job_id": "j"}"""))
            val moved = c.moveChange("survival", "undo", startAfter = true)
            assertEquals(strings.t("changes.undo_done", "title" to "Install Sodium"), ChangeList.done(strings, "undo", moved))
            val sent = agent.server.takeRequest()
            assertEquals("/api/servers/survival/changes/undo", sent.path)
            assertTrue(sent.body.readUtf8().contains("\"start_after\":true"))

            agent.server.enqueue(agent.json("""{"ok": true, "change": {"id": 4, "title": "Install Sodium", "made_at": 100, "backup_id": 8, "backup": "now.zip", "backup_at": 150}, "restored": "now.zip"}"""))
            c.moveChange("survival", "redo", startAfter = false)
            assertEquals("/api/servers/survival/changes/redo", agent.server.takeRequest().path)
        }
    }

    @Test
    fun `a backup downloads with the sign-in in a header, never in the address`() = runBlocking {
        TestAgent().use { agent ->
            val zip = ByteArray(200_000) { (it % 251).toByte() }
            agent.server.enqueue(
                MockResponse().setHeader("Content-Type", "application/zip").setBody(Buffer().write(zip)),
            )
            val out = ByteArrayOutputStream()
            var last = 0L
            val written = client(agent).downloadBackup("survival", 4, out) { n, _ -> last = n }
            assertEquals(zip.size.toLong(), written)
            assertEquals(written, last)
            assertTrue(zip.contentEquals(out.toByteArray()))
            val request = agent.server.takeRequest()
            assertEquals("/api/servers/survival/backups/4/download", request.path)
            assertEquals("Bearer $token", request.getHeader("Authorization"))
            assertFalse(request.path!!.contains(token))
        }
    }

    @Test
    fun `a full phone is the phone's problem, not the PC's`() {
        TestAgent().use { agent ->
            agent.server.enqueue(MockResponse().setHeader("Content-Type", "application/zip").setBody(Buffer().write(ByteArray(1000))))
            val full = object : java.io.OutputStream() {
                override fun write(b: Int) = throw java.io.IOException("No space left on device")
                override fun write(b: ByteArray, off: Int, len: Int) = throw java.io.IOException("No space left on device")
            }
            val e = assertThrows(SaveFileException::class.java) {
                runBlocking { client(agent).downloadBackup("survival", 4, full) }
            }
            assertEquals("No space left on device", e.message)
        }
    }

    @Test
    fun `slow work with no answer in time may still be running on the PC`() {
        TestAgent().use { agent ->
            agent.server.enqueue(agent.json("""{"name": "b.zip"}""").setHeadersDelay(4, java.util.concurrent.TimeUnit.SECONDS))
            val slow = AgentClient(agent.pairing(), { token }, systemTrust = TestAgent.trustingNothing(), slowSeconds = 1)
            assertThrows(AgentException.StillWorking::class.java) { runBlocking { slow.backUp("survival") } }
        }
    }

    @Test
    fun `a backup that isn't there comes back in the agent's words`() {
        TestAgent().use { agent ->
            agent.server.enqueue(agent.json("""{"detail": "That backup isn't on this server's list."}""", code = 404))
            val e = assertThrows(AgentException.Failed::class.java) {
                runBlocking { client(agent).downloadBackup("survival", 99, ByteArrayOutputStream()) }
            }
            assertEquals(404, e.status)
            assertEquals("That backup isn't on this server's list.", e.reason)
        }
    }

    @Test
    fun `the agent's answers for these screens are read`() = runBlocking {
        TestAgent().use { agent ->
            val c = client(agent)
            agent.server.enqueue(agent.json("""{"backups": [{"id": 1, "name": "manual-1.zip", "kind": "manual", "created_at": 10.5, "size_bytes": 2048, "status": "ok", "exists": true, "copy": {"state": "none", "reason": null}}], "directory": "C:\\b", "retention": {"daily": 7, "weekly": 4, "monthly": 3}}"""))
            val list = c.backups("survival")
            assertEquals(2048L, list.backups.single().sizeBytes)
            assertEquals("none", list.backups.single().copy?.state)
            agent.server.takeRequest()

            agent.server.enqueue(agent.json("""{"schedules": [{"id": 2, "name": "Nightly", "task": "backup", "kind": "daily", "expr": "04:00", "payload": {}, "enabled": true, "next_run": 1700000000.0, "last_run": null, "last_result": null}], "tasks": ["backup", "restart"]}"""))
            assertEquals("Nightly", c.schedules("survival").schedules.single().name)
            agent.server.takeRequest()

            agent.server.enqueue(agent.json("""{"current": {"ts": 1, "cpu_percent": 12.0, "proc_ram_mb": null}, "history": [], "series": {"points": [{"ts": 5.0, "cpu_percent": 3.0, "tps": null, "samples": 2}], "hours": 6, "bucket_seconds": 60}, "sample_interval": 30, "memory_limit_mb": 4096, "thresholds": {}, "storage": null}"""))
            val perf = c.performance("survival", 6)
            assertNull(perf.current.procRamMb)
            assertNull(perf.series.points.single().tps)
            assertEquals(4096.0, perf.memoryLimitMb!!, 0.0)
            assertEquals("/api/servers/survival/performance?hours=6&storage=true", agent.server.takeRequest().path)

            agent.server.enqueue(agent.json("""{"jobs": []}"""))
            c.jobs("survival")
            assertEquals("/api/jobs?server_id=survival&limit=20", agent.server.takeRequest().path)
        }
    }

    // ------------------------------------------------------------ bringing a world in, taking it home
    private fun me(vararg permissions: String) = Me(user = "x", role = "helper", permissions = permissions.toList())

    @Test
    fun `importing needs world replace, taking it home needs backups download`() {
        assertFalse(WorldImport.canImport(me(Permissions.BACKUPS_RESTORE)))
        assertTrue(WorldImport.canImport(me(Permissions.WORLD_REPLACE)))
        assertFalse(WorldImport.canDownload(me(Permissions.WORLD_REPLACE)))
        assertTrue(WorldImport.canDownload(me(Permissions.BACKUPS_DOWNLOAD)))
        assertFalse(WorldImport.canImport(null))
        assertTrue(WorldImport.accepts("My World.ZIP"))
        assertTrue(WorldImport.accepts("island.mcworld"))
        assertFalse(WorldImport.accepts("level.dat"))
    }

    @Test
    fun `a running server has to be stopped before a world comes in`() {
        assertEquals(strings.t("import.stop_first"), WorldImport.blocked(strings, WorldTimeline(serverRunning = true)))
        assertEquals(strings.t("world.busy", "job" to "A backup"), WorldImport.blocked(strings, WorldTimeline(blockedBy = "A backup")))
        assertNull(WorldImport.blocked(strings, WorldTimeline()))
    }

    @Test
    fun `a world read is shown with what is known, and the wrong edition isn't offered`() {
        val read = AgentJson.decodeFromString<WorldRead>(
            """{"token": "${"a".repeat(32)}", "world": {"source": "zip", "folder_name": "Island", "name": null, "version": null,
              "last_played": null, "size_bytes": 2048, "files": 3, "read_problem": "truncated", "edition": "bedrock"},
              "edition_matches": false, "server_edition": "java", "server_version": "1.21.1", "newer_than_server": null, "level_name": null}"""
        )
        assertEquals("Island", WorldImport.title(read))
        val facts = WorldImport.facts(strings, read.world, utc, Locale.US)
        assertEquals(strings.t("import.name") to "Island", facts[0])
        assertEquals(strings.t("value.unknown"), facts[1].second)
        assertEquals(strings.t("import.size_value", "size" to Display.bytes(strings, 2048), "files" to "3"), facts[2].second)
        assertEquals(strings.t("value.unknown"), facts[3].second)
        assertEquals(
            listOf(strings.t("import.read_problem", "problem" to "truncated"), strings.t("import.is_bedrock")),
            WorldImport.lines(strings, read).map { it.text },
        )
        assertFalse(WorldImport.canUse(read))

        val newer = read.copy(
            world = read.world.copy(edition = "java", version = "1.21.4", readProblem = null),
            editionMatches = true, newerThanServer = true,
        )
        assertEquals(
            listOf(strings.t("import.newer", "world" to "1.21.4", "server" to "1.21.1")),
            WorldImport.lines(strings, newer).map { it.text },
        )
        assertTrue(WorldImport.canUse(newer))
    }

    @Test
    fun `an import with a backup first says it can be undone`() {
        val result = AgentJson.decodeFromString<WorldImported>(
            """{"ok": true, "job_id": "j1", "world": {"source": "folder", "folder_name": "New", "size_bytes": 1, "files": 1},
              "safety_backup": {"id": 7, "name": "pre-import.zip"}, "undo": {"kind": "restore_backup", "backup_id": 7, "backup": "pre-import.zip"}}"""
        )
        assertEquals(strings.t("import.done_with_undo"), WorldImport.done(strings, result))
        assertEquals(strings.t("import.done"), WorldImport.done(strings, result.copy(undo = null)))
    }

    @Test
    fun `worlds are read, imported, forgotten and taken home through the agent's routes`() = runBlocking {
        TestAgent().use { agent ->
            val c = client(agent)
            val readJson = """{"token": "${"b".repeat(32)}", "world": {"source": "zip", "folder_name": "W", "size_bytes": 5, "files": 1},
              "edition_matches": true, "server_edition": "java"}"""
            agent.server.enqueue(agent.json(readJson))
            val bytes = ByteArray(200_000) { 1 }
            var sent = 0L
            val read = c.uploadWorld("survival", PickedFile.of("w.zip", bytes)) { n, _ -> sent = n }
            assertEquals("b".repeat(32), read.token)
            assertEquals(bytes.size.toLong(), sent)
            val upload = agent.server.takeRequest()
            assertEquals("/api/servers/survival/world/import/upload", upload.path)
            assertTrue(upload.body.readUtf8().contains("filename=\"w.zip\""))

            agent.server.enqueue(agent.json(readJson))
            c.pickWorldFolder("survival", "C:\\saves\\W")
            val folder = agent.server.takeRequest()
            assertEquals("/api/servers/survival/world/import/folder", folder.path)
            assertEquals("""{"path":"C:\\saves\\W"}""", folder.body.readUtf8())

            agent.server.enqueue(agent.json("""{"folder": null, "worlds": []}"""))
            assertNull(c.savedWorlds("survival").folder)
            assertEquals("/api/servers/survival/world/saves", agent.server.takeRequest().path)

            agent.server.enqueue(agent.json("""{"ok": true, "job_id": "j", "world": {"source": "zip", "folder_name": "W", "size_bytes": 5, "files": 1}}"""))
            c.importWorld("survival", read.token)
            assertEquals("""{"token":"${"b".repeat(32)}","confirm":true}""", agent.server.takeRequest().body.readUtf8())

            agent.server.enqueue(agent.json("""{"ok": true}"""))
            c.forgetWorld("survival", read.token)
            val forget = agent.server.takeRequest()
            assertEquals("DELETE", forget.method)
            assertEquals("/api/servers/survival/world/import/${"b".repeat(32)}", forget.path)

            agent.server.enqueue(agent.json("""{"ok": true, "token": "t1", "files": 2, "size_bytes": 3, "filename": "My World.zip"}"""))
            val packed = c.packWorld("survival")
            assertEquals("/api/servers/survival/world/download", agent.server.takeRequest().path)
            val zip = byteArrayOf(80, 75, 3, 4)
            agent.server.enqueue(MockResponse().setHeader("Content-Type", "application/zip").setBody(Buffer().write(zip)))
            val out = ByteArrayOutputStream()
            assertEquals(4L, c.downloadWorld("survival", packed, out))
            assertTrue(zip.contentEquals(out.toByteArray()))
            val download = agent.server.takeRequest()
            assertEquals("/api/servers/survival/world/download/t1?filename=My%20World.zip", download.path)
            assertEquals("Bearer $token", download.getHeader("Authorization"))
        }
    }
}
