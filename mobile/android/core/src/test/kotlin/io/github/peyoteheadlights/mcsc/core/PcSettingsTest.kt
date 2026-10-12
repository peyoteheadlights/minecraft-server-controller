package io.github.peyoteheadlights.mcsc.core

import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.mockwebserver.MockResponse
import okio.Buffer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The owner's PC settings (agent/api/routes/settings.py and the routes beside it). */
class PcSettingsTest {
    private val json = Json { ignoreUnknownKeys = true }
    private val strings = Strings(Shared.strings)
    private val token = "secret-session-token-1234567890"

    private fun client(agent: TestAgent) =
        AgentClient(agent.pairing(), { token }, {}, AgentLog { }, systemTrust = TestAgent.trustingNothing())

    // What GET /api/settings sends: secrets only as "configured".
    private val view = json.decodeFromString(
        PcSettingsView.serializer(),
        """{"config": {
              "notifications": {"discord_enabled": true, "email_enabled": false, "push_enabled": true,
                "events": {"server_started": true, "player_left": false, "app_updates": true},
                "email": {"host": "smtp.example.com", "to_addresses": ["me@example.com"]},
                "min_interval_seconds": 300},
              "thresholds": {"cpu_percent": 90.0, "ram_percent": 90, "disk_free_gb": 20, "tps_min": 18, "mspt_max": 50},
              "power": {"keep_awake": true}, "updates": {"check": false}, "maintenance": {"enabled": true}},
            "editable": [], "secrets": {"discord_webhook_configured": true, "smtp_configured": false, "api_token_configured": false}}""",
    )

    @Test
    fun `the alert settings read as the PC has them`() {
        val alerts = PcSettings.alerts(view)
        assertTrue(alerts.discord)
        assertFalse(alerts.email)
        assertTrue(alerts.phone)
        assertEquals(listOf("server_started", "player_left", "app_updates"), alerts.events.keys.toList())
        assertEquals(90.0, alerts.thresholds["ram_percent"])
        assertEquals(300.0, alerts.repeatSeconds, 0.0)
        assertTrue(PcSettings.keepAwake(view))
        assertFalse(PcSettings.dailyCheck(view))
        assertTrue(PcSettings.maintenance(view))
        assertTrue(view.secrets.discord)
        assertFalse(view.secrets.email)
        assertEquals(listOf("me@example.com"), PcSettings.emailTo(view))
    }

    @Test
    fun `saving sends only what changed, with the agent's keys`() {
        val before = PcSettings.alerts(view)
        assertEquals(0, PcSettings.changes(before, before).size)
        val after = before.copy(
            discord = false,
            email = true,
            phone = false,
            events = before.events + ("player_left" to true),
            thresholds = before.thresholds + ("tps_min" to 15.0),
            repeatSeconds = 60.0,
        )
        val changes = PcSettings.changes(before, after)
        assertEquals(
            setOf(
                "notifications.discord_enabled", "notifications.email_enabled", "notifications.push_enabled",
                "notifications.events.player_left", "thresholds.tps_min", "notifications.min_interval_seconds",
            ),
            changes.keys,
        )
        assertEquals("true", changes.getValue("notifications.events.player_left").jsonPrimitive.content)
        assertEquals(15.0, changes.getValue("thresholds.tps_min").jsonPrimitive.content.toDouble(), 0.0)
        // Every key saved is one the dashboard's App settings saves too.
        for (key in changes.keys) assertTrue(key, PcSettings.KEYS.any { key == it || key.startsWith(it) })
    }

    @Test
    fun `a typed number must be one`() {
        assertEquals(12.5, PcSettings.number(" 12,5 ")!!, 0.0)
        assertNull(PcSettings.number("lots"))
        assertNull(PcSettings.number("-3"))
    }

    @Test
    fun `saving says the PC's reason for each refused setting`() {
        val refused = SettingsSaved(ok = true, rejected = mapOf("thresholds.cpu_percent" to "thresholds.cpu_percent must be at most 100"))
        assertEquals("thresholds.cpu_percent must be at most 100" to false, PcSettings.saved(strings, refused))
        assertEquals(strings.t("settings.saved") to true, PcSettings.saved(strings, SettingsSaved(ok = true)))
    }

    @Test
    fun `each setting saves through the agent`() = runBlocking {
        TestAgent().use { agent ->
            agent.server.enqueue(agent.json("""{"ok": true, "applied": {"power.keep_awake": false}, "rejected": {}}"""))
            agent.server.enqueue(agent.json("""{"ok": true, "maintenance": true}"""))
            agent.server.enqueue(agent.json("""{"channel": "discord", "sent": true}"""))
            val c = client(agent)
            val saved = c.savePcSettings(kotlinx.serialization.json.buildJsonObject { put("power.keep_awake", kotlinx.serialization.json.JsonPrimitive(false)) })
            assertTrue("power.keep_awake" in saved.applied)
            val put = agent.server.takeRequest()
            assertEquals("PUT", put.method)
            assertEquals("/api/settings", put.path)
            assertEquals("false", json.parseToJsonElement(put.body.readUtf8()).jsonObject["updates"]!!.jsonObject["power.keep_awake"]!!.jsonPrimitive.content)
            assertTrue(c.maintenance(true).maintenance)
            assertEquals("""{"enabled":true}""", agent.server.takeRequest().body.readUtf8())
            assertTrue(c.testAlert("discord").sent)
            assertEquals("/api/notifications/test?channel=discord", agent.server.takeRequest().path)
        }
    }

    @Test
    fun `keep awake says what Windows does now`() {
        val running = PowerStatus(supported = true, enabled = true, active = true, running = listOf("Survival"), stillSleeps = listOf("lid_sleeps", "something_new"))
        assertEquals(strings.t("awake.active", "names" to "Survival"), PcSettings.awake(strings, running))
        assertEquals(strings.t("awake.idle"), PcSettings.awake(strings, running.copy(active = false)))
        assertEquals(strings.t("awake.off_now"), PcSettings.awake(strings, running.copy(enabled = false)))
        assertEquals(strings.t("awake.unsupported"), PcSettings.awake(strings, PowerStatus()))
        // A reason the phone has no words for isn't shown as a guess.
        assertEquals(listOf(strings.t("awake.still_lid_sleeps")), PcSettings.stillSleeps(strings, running))
    }

    @Test
    fun `the start with Windows check shows what Windows said`() {
        val report = json.decodeFromString(
            StartupReport.serializer(),
            """{"supported": true, "verdict": "problems found", "registered": true, "points_to_current_app": false,
                "mechanism": "scheduled task", "problems": ["It points to an old copy."],
                "task": {"mode": "boot", "command": "C:\\old\\run.cmd", "working_directory": "C:\\old"},
                "runtime": {"last_run_time": "2026-10-11 08:00", "last_result": "0x0"},
                "last_startup": {"started_at": "2026-10-11 08:00:05", "launched_by": "task", "events": [{"event": "controller_initialized"}]},
                "startup_log": "x"}""",
        )
        assertEquals("startup.problems_found", PcSettings.verdict(report))
        assertEquals(false, PcSettings.verdictGood(report))
        val simple = PcSettings.startupRows(strings, report, technical = false).toMap()
        assertEquals(strings.t("startup.found"), simple[strings.t("startup.registered")])
        assertEquals(strings.t("startup.at_boot"), simple[strings.t("startup.mode")])
        assertEquals(strings.t("value.no"), simple[strings.t("startup.points_here")])
        assertEquals(strings.t("value.yes"), simple[strings.t("startup.initialised")])
        assertFalse(strings.t("startup.command") in simple)
        val technical = PcSettings.startupRows(strings, report, technical = true).toMap()
        assertEquals("C:\\old\\run.cmd", technical[strings.t("startup.command")])
        // Nothing read from Windows: unknown, never a guess.
        val blank = PcSettings.startupRows(strings, StartupReport(verdict = "not registered"), technical = false).toMap()
        assertEquals(strings.t("value.unknown"), blank[strings.t("startup.registered")])
        assertEquals(strings.t("startup.none"), blank[strings.t("startup.last_start")])
    }

    @Test
    fun `export needs a folder, and a passphrase when passwords go too`() {
        assertFalse(PcSettings.canExport(null, secrets = false, passphrase = ""))
        assertTrue(PcSettings.canExport("D:\\Moves", secrets = false, passphrase = ""))
        assertFalse(PcSettings.canExport("D:\\Moves", secrets = true, passphrase = "short"))
        assertTrue(PcSettings.canExport("D:\\Moves", secrets = true, passphrase = "long enough phrase"))
        val body = PcSettings.exportBody(worlds = true, backups = false, secrets = false, passphrase = "ignored", folder = "D:\\Moves")
        assertEquals("D:\\Moves", body["folder"]!!.jsonPrimitive.content)
        assertFalse("passphrase" in body)
        val totals = PcSettings.totals(ExportSizes(listOf(ExportServerSizes(files = 1, worlds = 10, backups = 100), ExportServerSizes(files = 2, worlds = 20, backups = 200))))
        assertEquals(PcSettings.Totals(3, 30, 300), totals)
    }

    @Test
    fun `export shows its progress, then where on the PC it was saved`() = runBlocking {
        TestAgent().use { agent ->
            agent.server.enqueue(agent.json("""{"ok": true, "job_id": "j1"}"""))
            agent.server.enqueue(agent.json("""{"id": "j1", "kind": "export", "title": "Exporting everything", "state": "running", "step": "Writing the export file", "progress": 0.5}"""))
            agent.server.enqueue(agent.json("""{"id": "j1", "kind": "export", "title": "Exporting everything", "state": "succeeded",
                "result": {"token": "t", "filename": "minecraft-server-control-export-20261012.zip", "size_bytes": 2048, "saved_to": "D:\\Moves\\minecraft-server-control-export-20261012.zip"}}"""))
            val c = client(agent)
            val started = c.startExport(PcSettings.exportBody(true, false, false, "", "D:\\Moves"))
            assertEquals("/api/export", agent.server.takeRequest().path)
            assertEquals(PcSettings.Exporting.Running("Writing the export file", 0.5), PcSettings.exporting(c.exportJob(started.jobId)))
            assertEquals("/api/jobs/j1", agent.server.takeRequest().path)
            val done = PcSettings.exporting(c.exportJob(started.jobId))
            assertEquals(PcSettings.Exporting.Saved("D:\\Moves\\minecraft-server-control-export-20261012.zip", 2048), done)
            assertTrue(PcSettings.exportSaid(strings, done)!!.contains("D:\\Moves\\minecraft-server-control-export-20261012.zip"))
        }
        // A failure says the PC's reason; a finished export with no folder isn't called saved.
        assertEquals("Disk full", PcSettings.exportSaid(strings, PcSettings.exporting(ExportJob("j", state = "failed", message = "Disk full"))))
        assertEquals(strings.t("export.failed"), PcSettings.exportSaid(strings, PcSettings.exporting(ExportJob("j", state = "succeeded", result = ExportResult(token = "t")))))
    }

    @Test
    fun `get help lists its files, then downloads one zip to share`() = runBlocking {
        TestAgent().use { agent ->
            agent.server.enqueue(agent.json("""{"files": [{"name": "logs/agent.log", "size": 1200}, {"name": "system-check.json", "size": null}]}"""))
            agent.server.enqueue(agent.json("""{"ok": true, "token": "abc", "filename": "minecraft-server-control-help-20261012-0900.zip", "files": []}"""))
            agent.server.enqueue(MockResponse().setHeader("Content-Type", "application/zip").setBody(Buffer().write(ByteArray(300))))
            val c = client(agent)
            assertEquals(listOf("logs/agent.log", "system-check.json"), c.helpFiles().files.map { it.name })
            agent.server.takeRequest()
            val made = c.makeHelpFile()
            assertEquals("""{"confirm":true}""", agent.server.takeRequest().body.readUtf8())
            val out = java.io.ByteArrayOutputStream()
            assertEquals(300L, c.downloadHelpFile(made, out))
            val download = agent.server.takeRequest()
            assertEquals("/api/help-bundle/abc?filename=minecraft-server-control-help-20261012-0900.zip", download.path)
            assertEquals("Bearer $token", download.getHeader("Authorization"))
        }
    }

    @Test
    fun `signed-in devices list every account, and everyone can be signed out`() = runBlocking {
        val devices = listOf(
            Device("1", "sam", "Pixel 8", lastUsed = 50.0),
            Device("2", "mark", "Firefox", lastUsed = 90.0),
            Device("3", "mark", "This phone", lastUsed = 10.0, current = true),
            Device("4", "alex", "iPhone", lastUsed = 20.0),
        )
        val grouped = PcSettings.byAccount(devices, me = "mark")
        assertEquals(listOf("mark", "alex", "sam"), grouped.map { it.user })
        assertEquals(listOf("3", "2"), grouped.first().devices.map { it.id })
        TestAgent().use { agent ->
            agent.server.enqueue(agent.json("""{"ok": true}"""))
            agent.server.enqueue(agent.json("""{"ok": true, "revoked": 4}"""))
            val c = client(agent)
            c.signOutDevice("1")
            val one = agent.server.takeRequest()
            assertEquals("DELETE", one.method)
            assertEquals("/api/sessions/1", one.path)
            assertEquals(4, c.signEveryoneOut().revoked)
            assertEquals("/api/security/revoke-sessions", agent.server.takeRequest().path)
        }
    }

    // ------------------------------------------------------------ the app update
    private val upToDate = UpdateStatus(current = "1.9.0", checkedAt = 1.0, canInstall = true)
    private val ready = upToDate.copy(available = true, latest = Release("1.10.0", notes = "- Faster\n\n* Moderators\n"))

    @Test
    fun `the update screen's states`() {
        assertEquals(PcUpdate.Shows.UP_TO_DATE, PcUpdate.shows(upToDate))
        assertEquals(PcUpdate.Shows.READY, PcUpdate.shows(ready))
        assertEquals(PcUpdate.Shows.CANT_INSTALL, PcUpdate.shows(ready.copy(canInstall = false, cannotInstallReason = "Run setup.ps1")))
        assertEquals(PcUpdate.Shows.UPDATING, PcUpdate.shows(ready, updating = "1.10.0"))
        val updated = UpdateStatus(current = "1.10.0", lastResult = UpdateResult(ok = true, version = "1.10.0"))
        assertEquals(PcUpdate.Shows.UPDATED, PcUpdate.shows(updated))
        val failed = UpdateStatus(current = "1.9.0", lastResult = UpdateResult(ok = false, version = "1.10.0", rolledBack = true))
        assertEquals(PcUpdate.Shows.FAILED, PcUpdate.shows(failed))
        assertEquals(
            strings.t("update.last_failed", "version" to "1.10.0") + " " + strings.t("update.rolled_back"),
            PcUpdate.lastResult(strings, failed.lastResult),
        )
        assertEquals(listOf("Faster", "Moderators"), PcUpdate.notes(ready.latest))
        // Notes written on Windows end their lines with \r\n.
        assertEquals(listOf("Fix A", "Fix B"), PcUpdate.notes(Release("1.10.0", notes = "- Fix A\r\n- Fix B\r\n")))
    }

    @Test
    fun `the phone knows when the PC is back`() {
        // Still the old copy answering: not back yet.
        assertFalse(PcUpdate.back(ready, ready, "1.10.0"))
        assertTrue(PcUpdate.back(ready, ready.copy(current = "1.10.0", available = false), "1.10.0"))
        // Back on the old version, saying the update didn't work: back too.
        assertTrue(PcUpdate.back(ready, ready.copy(lastResult = UpdateResult(ok = false, version = "1.10.0", rolledBack = true)), "1.10.0"))
    }

    @Test
    fun `the confirmation says who is playing, only when the PC could tell`() {
        assertEquals(strings.t("update.confirm_body"), PcUpdate.confirmBody(strings, ready.copy(playersOnline = 0)))
        assertTrue(PcUpdate.confirmBody(strings, ready.copy(playersOnline = 3)).endsWith(strings.t("update.confirm_players", "count" to 3)))
        assertTrue(PcUpdate.confirmBody(strings, ready.copy(playersOnline = null)).endsWith(strings.t("update.confirm_players_unknown")))
        assertEquals(strings.t("update.install_anyway"), PcUpdate.confirmLabel(strings, ready.copy(playersOnline = 3)))
    }

    @Test
    fun `installing, the old copy and its removal go through the agent`() = runBlocking {
        TestAgent().use { agent ->
            agent.server.enqueue(agent.json("""{"current": "1.9.0", "available": true, "checking": true, "install_kind": "installer", "can_install": true,
                "latest": {"version": "1.10.0"}, "players_online": 2, "players": []}"""))
            agent.server.enqueue(agent.json("""{"ok": true, "job": {"id": "u1", "kind": "app_update", "title": "Updating", "state": "running"}}"""))
            agent.server.enqueue(agent.json("""{"old_copy": {"path": "C:\\Users\\me\\mcsc", "offer": true, "problems": [], "removes": []}}"""))
            agent.server.enqueue(agent.json("""{"ok": true, "path": "C:\\Users\\me\\mcsc", "removed": ["a"], "kept": ["backups", "worlds"], "failed": [], "folder_removed": false}"""))
            val c = client(agent)
            assertEquals(2, c.updateChecks().playersOnline)
            assertEquals("/api/updates/preflight", agent.server.takeRequest().path)
            assertEquals("u1", c.installUpdate().job.id)
            assertEquals("/api/updates/install", agent.server.takeRequest().path)
            assertTrue(c.oldCopy().oldCopy!!.offer)
            agent.server.takeRequest()
            assertEquals(strings.t("oldcopy.removed_kept", "count" to 2), PcUpdate.oldCopyRemoved(strings, c.removeOldCopy()))
        }
    }
}
