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

    @Test
    fun `only a finished change with a backup made before it can be undone`() {
        val undo = JobResult(Undo("restore_backup", 7, "safety-1.zip"))
        val jobs = listOf(
            Job("a", state = "running", result = undo),
            Job("b", state = "succeeded"),
            Job("c", state = "succeeded", result = undo),
            Job("d", state = "succeeded", result = undo),
        )
        assertEquals("c", Backups.lastUndoable(jobs)?.id)
        assertNull(Backups.lastUndoable(jobs.take(2)))
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
}
