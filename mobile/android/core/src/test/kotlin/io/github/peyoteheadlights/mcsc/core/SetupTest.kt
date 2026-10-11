package io.github.peyoteheadlights.mcsc.core

import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SetupTest {
    private val token = "secret-session-token-1234567890"
    private val strings = Strings(Shared.strings)
    private val json = Json { ignoreUnknownKeys = true }

    private fun client(agent: TestAgent) = AgentClient(agent.pairing(), { token }, systemTrust = TestAgent.trustingNothing())

    private val settingsJson = """{"server_id": "s", "server": {"name": "Survival", "autosleep": true, "autosleep_minutes": 30,
        "start_timeout": 300.0, "stop_timeout": 90, "autostart_minecraft": false, "cpu_cores": []},
        "color": "#3366CC", "palette": [{"id": "blue", "name": "Blue", "hex": "#3366CC"}],
        "monitor": {"auto_restart": true, "restart_delay": 10.5, "max_crashes": 5, "crash_window_minutes": 10},
        "backups": {"keep_daily": 7, "keep_weekly": 4, "keep_monthly": 3}, "mods": {}, "overrides": {}, "editable": [],
        "cpu": {"logical_cores": 8, "supported": true, "unsupported_reason": null, "others": [],
            "status": {"configured": null, "applied": null, "applied_reason": "The server is not running", "problems": []}},
        "sleep": {"enabled": true, "minutes": 30, "players_online": 0, "stops_in": 125.0, "list_answered": true}}"""

    private fun settings() = json.decodeFromString(ServerSettings.serializer(), settingsJson)

    private fun me(vararg permissions: String) = Me(user = "x", role = "helper", permissions = permissions.toList())

    @Test
    fun `server settings decode and every field starts at its saved value`() {
        val s = settings()
        assertEquals("Survival", ServerForm.initial(s, ServerForm.NAME))
        assertEquals("true", ServerForm.initial(s, "monitor.auto_restart"))
        assertEquals("10.5", ServerForm.initial(s, "monitor.restart_delay"))
        assertEquals("300", ServerForm.initial(s, "server.start_timeout"))
        assertEquals("7", ServerForm.initial(s, "backups.keep_daily"))
        assertEquals("false", ServerForm.initial(s, "server.autostart_minecraft"))
        assertEquals(8, s.cpu.logicalCores)
        assertNull(s.cpu.status.configured)
        assertEquals("blue", s.palette.single().id)
    }

    @Test
    fun `only someone who may edit settings can change them, and only viewers see them`() {
        assertFalse(ServerForm.visible(null))
        assertFalse(ServerForm.visible(me()))
        assertTrue(ServerForm.visible(me(Permissions.SETTINGS_VIEW)))
        assertFalse(ServerForm.editable(me(Permissions.SETTINGS_VIEW)))
        assertTrue(ServerForm.editable(me(Permissions.SETTINGS_VIEW, Permissions.SETTINGS_EDIT)))
    }

    @Test
    fun `save sends only what changed, typed as the agent takes it`() {
        val s = settings()
        val nothing = ServerForm.changed(s, mapOf("monitor.auto_restart" to "true", "server.start_timeout" to "300", ServerForm.NAME to " Survival "))
        assertTrue(nothing.isEmpty())
        val sent = ServerForm.changed(s, mapOf(
            ServerForm.NAME to "  Creative ",
            "monitor.auto_restart" to "false",
            "monitor.restart_delay" to "20",
            "backups.keep_daily" to "3",
            "server.autosleep_minutes" to "soon",
        ))
        assertEquals(buildJsonObject {
            put("server.name", "Creative")
            put("monitor.auto_restart", false)
            put("monitor.restart_delay", 20.0)
            put("server.autosleep_minutes", "soon")
            put("backups.keep_daily", 3)
        }, sent)
        // A blank name is never sent.
        assertTrue(ServerForm.changed(s, mapOf(ServerForm.NAME to "  ")).isEmpty())
    }

    @Test
    fun `saying what happened`() {
        assertEquals("Nothing changed.", ServerForm.saved(strings, sent = false, result = null))
        assertEquals("Settings saved.", ServerForm.saved(strings, sent = true, result = ServerSettingsSaved()))
        val refused = ServerSettingsSaved(rejected = mapOf("server.autosleep_minutes" to "Pick between 1 minute and 24 hours."))
        assertEquals(strings.t("mobile.game.fix_marked"), ServerForm.saved(strings, sent = true, result = refused))
    }

    @Test
    fun `a typed color must be one`() {
        assertEquals("#3366CC", ServerForm.color("#3366cc"))
        assertEquals("#3366CC", ServerForm.color("3366cc"))
        assertNull(ServerForm.color("#36c"))
        assertNull(ServerForm.color("blue"))
    }

    @Test
    fun `sleep says only what was measured`() {
        val s = settings()
        assertEquals("Empty. Stopping in 2m.", ServerForm.sleepLine(strings, s))
        assertEquals(strings.t("serverset.sleep_unknown_players"), ServerForm.sleepLine(strings, s.copy(sleep = s.sleep!!.copy(playersOnline = null))))
        assertEquals(strings.t("value.unknown"), ServerForm.sleepLine(strings, s.copy(sleep = null)))
        val off = s.copy(server = buildJsonObject { put("autosleep", false) })
        assertEquals(strings.t("serverset.sleep_off"), ServerForm.sleepLine(strings, off))
    }

    @Test
    fun `server settings and color go to the agent's routes`() = runBlocking {
        TestAgent().use { agent ->
            val c = client(agent)
            agent.server.enqueue(agent.json(settingsJson))
            assertEquals("Survival", ServerForm.initial(c.serverSettings("s"), ServerForm.NAME))
            assertEquals("/api/servers/s/settings", agent.server.takeRequest().path)
            agent.server.enqueue(agent.json("""{"ok": true, "applied": {"server.name": "C"}, "rejected": {"server.autosleep_minutes": "Pick between 1 minute and 24 hours."}}"""))
            val saved = c.saveServerSettings("s", buildJsonObject { put("server.name", "C") })
            assertEquals(JsonPrimitive("C"), saved.applied["server.name"])
            assertEquals("Pick between 1 minute and 24 hours.", saved.rejected["server.autosleep_minutes"])
            val put = agent.server.takeRequest()
            assertEquals("PUT", put.method)
            assertEquals("""{"updates":{"server.name":"C"}}""", put.body.readUtf8())
            agent.server.enqueue(agent.json("""{"ok": true, "color": "#3366CC"}"""))
            assertEquals("#3366CC", c.setColor("s", "#3366CC").color)
            val color = agent.server.takeRequest()
            assertEquals("/api/servers/s/color", color.path)
            assertEquals("""{"color":"#3366CC"}""", color.body.readUtf8())
        }
    }

    // ------------------------------------------------------------ CPU cores and memory
    @Test
    fun `cpu cores show who else uses each core and what the server got`() {
        val cpu = CpuOverview(
            logicalCores = 8, supported = true,
            others = listOf(CpuOther("b", "Creative", listOf(0, 1)), CpuOther("c", "Modded", listOf(1))),
            status = CpuStatus(configured = listOf(0, 1, 2, 3), applied = listOf(0, 1, 2, 3)),
        )
        assertEquals(mapOf(0 to listOf("Creative"), 1 to listOf("Creative", "Modded")), CpuCores.sharedBy(cpu))
        assertEquals("1-4, 7", CpuCores.describe(listOf(6, 3, 0, 1, 2)))
        assertEquals(setOf(0, 1, 2, 3), CpuCores.half(7))
        assertEquals("Using 1-4 now.", CpuCores.nowLine(strings, cpu))
        assertEquals("Using all cores now.", CpuCores.nowLine(strings, cpu.copy(status = CpuStatus(applied = (0..7).toList()))))
        assertEquals("Cores in use now unknown: The server is not running", CpuCores.nowLine(strings, cpu.copy(status = CpuStatus(appliedReason = "The server is not running"))))
        assertEquals(emptyList<Int>(), CpuCores.toSave(all = true, picked = setOf(2)))
        assertNull(CpuCores.toSave(all = false, picked = emptySet()))
        assertEquals(listOf(1, 3), CpuCores.toSave(all = false, picked = setOf(3, 1)))
    }

    @Test
    fun `after saving cores the phone says whether the running server got them`() {
        assertEquals(strings.t("serverset.cores_next_start"), CpuCores.saved(strings, ServerSettingsSaved()))
        assertEquals(strings.t("serverset.cores_applied"), CpuCores.saved(strings, ServerSettingsSaved(cpuCores = CpuApplied(ok = true, applied = listOf(0)))))
        assertEquals("Saved, but not applied yet: Access denied", CpuCores.saved(strings, ServerSettingsSaved(cpuCores = CpuApplied(ok = false, reason = "Access denied"))))
        val decoded = json.decodeFromString(ServerSettingsSaved.serializer(), """{"ok": true, "applied": {"server.cpu_cores": [0]}, "rejected": {}, "cpu_cores": {"ok": true, "applied": [0], "reason": null}}""")
        assertEquals(listOf(0), decoded.cpuCores?.applied)
    }

    private val memoryJson = """{"total_mb": 16384, "total_source": "measured (psutil)", "limit_mb": 6144, "jvm_args": ["-Xmx6G"],
        "takes_memory_limit": true, "min_mb": 1024, "max_mb": 16384, "step_mb": 512, "together_mb": 14336,
        "servers": [{"id": "s", "name": "Survival", "limit_mb": 6144, "running": false, "this": true},
                    {"id": "b", "name": "Creative", "limit_mb": 8192, "running": true, "this": false}], "over": false, "running": false}"""

    @Test
    fun `the memory slider keeps to what the pc has`() {
        val memory = json.decodeFromString(MemoryOverview.serializer(), memoryJson)
        assertTrue(Memory.slider(memory))
        assertEquals(6144, Memory.start(memory))
        assertEquals(1024, Memory.snap(memory, 100f))
        assertEquals(16384, Memory.snap(memory, 99999f))
        assertEquals(2560, Memory.snap(memory, 2700f))
        assertEquals("6 GB", Memory.gb(6144))
        assertEquals("1.5 GB", Memory.gb(1536))
        assertEquals("Now: up to 6 GB. Changes apply on the next start.", Memory.nowLine(strings, memory))
        assertFalse(Memory.slider(memory.copy(totalMb = null)))
        assertEquals(strings.t("memory.pc_unknown"), Memory.noSlider(strings, memory.copy(totalMb = null), bedrock = false))
    }

    @Test
    fun `memory warns when every server together would use more than the pc has`() {
        val memory = json.decodeFromString(MemoryOverview.serializer(), memoryJson)
        assertNull(Memory.warning(strings, memory, 8192))
        assertEquals("With Creative running, servers may use 16.5 GB, more than this PC has (16 GB).", Memory.warning(strings, memory, 8704))
        val alone = memory.copy(servers = memory.servers.take(1))
        assertEquals("17 GB is more than this PC has (16 GB). Windows may slow down or the server may crash.", Memory.warning(strings, alone, 17408))
        assertNull(Memory.warning(strings, memory.copy(totalMb = null), 99999))
    }

    @Test
    fun `bedrock servers have no memory setting`() {
        val bedrock = MemoryOverview(totalMb = 16384, takesMemoryLimit = false)
        assertFalse(Memory.slider(bedrock))
        assertEquals(strings.t("memory.not_bedrock"), Memory.noSlider(strings, bedrock, bedrock = true))
    }

    @Test
    fun `memory goes to the agent's route`() = runBlocking {
        TestAgent().use { agent ->
            val c = client(agent)
            agent.server.enqueue(agent.json(memoryJson))
            assertEquals(6144, c.memory("s").limitMb)
            assertEquals("/api/servers/s/memory", agent.server.takeRequest().path)
            agent.server.enqueue(agent.json(memoryJson.replace("\"limit_mb\": 6144, \"jvm", "\"limit_mb\": 4096, \"jvm").replace("{\"total_mb\"", "{\"ok\": true, \"total_mb\"")))
            assertEquals(4096, c.setMemory("s", 4096).limitMb)
            val put = agent.server.takeRequest()
            assertEquals("PUT", put.method)
            assertEquals("""{"memory_mb":4096}""", put.body.readUtf8())
        }
    }
}
