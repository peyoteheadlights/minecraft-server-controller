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

    // ------------------------------------------------------------ version and type
    private val versionJson = """{"type": "fabric", "capabilities": {"id": "fabric", "name": "Fabric", "edition": "java", "content": "mods"},
        "minecraft_version": "1.21.1", "minecraft_version_source": "console", "loader_version": "0.16.5", "loader_name": "Fabric Loader",
        "detected_type": "fabric", "pending_version": null, "eula_required": true, "eula_url": "https://aka.ms/MinecraftEULA",
        "last_change": {"at": 1.0, "type": "fabric", "previous_type": "fabric", "minecraft_version": "1.21.1", "can_roll_back": true, "install_log": null, "moved_aside": []}}"""

    private val preflightJson = """{"current": {"type": "fabric", "type_name": "Fabric", "minecraft_version": "1.21.1", "loader_version": "0.16.5", "observed": true},
        "target": {"type": "paper", "type_name": "Paper", "minecraft_version": "1.20.4", "loader_version": null, "stable": true},
        "type_change": true, "gentle_type_change": false, "direction": "older", "downgrade_warning": true,
        "java": {"verdict": "unknown", "detail": "Java couldn't be checked on this PC."}, "java_required": 17,
        "latest_only": false, "kept": false, "content_kind": "mods", "target_content_kind": "plugins", "content": [],
        "moved_aside": ["sodium.jar", "lithium.jar"], "unknown_support": [], "not_supporting": [],
        "backup_first": true, "crossplay": true, "crossplay_available": true}"""

    @Test
    fun `the version is what the console said, and roll back and the eula follow the agent`() {
        val version = json.decodeFromString(ServerVersion.serializer(), versionJson)
        assertEquals("Fabric 1.21.1", VersionChange.now(strings, version))
        assertEquals(strings.t("version.not_seen_yet"), VersionChange.now(strings, version.copy(minecraftVersion = null)))
        assertTrue(VersionChange.eulaNeeded(version))
        assertFalse(VersionChange.eulaNeeded(version.copy(eulaRequired = false)))
        assertTrue(VersionChange.canRollBack(version))
        assertFalse(VersionChange.canRollBack(version.copy(lastChange = null)))
        assertEquals("https://aka.ms/MinecraftEULA", version.eulaUrl)
    }

    @Test
    fun `only the same edition's kinds are offered, and snapshots only when asked`() {
        val version = json.decodeFromString(ServerVersion.serializer(), versionJson)
        val types = listOf(ServerTypeInfo("fabric", "Fabric"), ServerTypeInfo("paper", "Paper"), ServerTypeInfo("bedrock", "Bedrock", edition = "bedrock"))
        assertEquals(listOf("fabric", "paper"), VersionChange.sameEdition(types, version).map { it.id })
        val offered = TypeVersions(versions = listOf(OfferedVersion("1.21.4"), OfferedVersion("25w01a", stable = false)))
        assertEquals(listOf("1.21.4"), VersionChange.choices(offered, snapshots = false).map { it.minecraft })
        assertEquals(2, VersionChange.choices(offered, snapshots = true).size)
    }

    @Test
    fun `the check says what might break before anything changes`() {
        val report = json.decodeFromString(VersionPreflight.serializer(), preflightJson)
        val lines = VersionChange.lines(strings, report)
        assertEquals(strings.t("version.downgrade"), lines[0].text)
        assertEquals(Tone.WARNING, lines[1].tone)
        assertTrue(lines[1].text.startsWith("This changes the server from Fabric to Paper."))
        assertTrue(lines.any { it.text.startsWith("2 add-ons don't fit") })
        assertEquals(strings.t("version.java_unknown"), lines[lines.size - 2].text)
        assertEquals(strings.t("version.backup_first"), lines.last().text)
        assertTrue(VersionChange.danger(report))
        assertFalse(VersionChange.danger(report.copy(downgradeWarning = false, gentleTypeChange = true)))
        assertEquals("Paper 1.20.4", VersionChange.target(report))
        val incompatible = report.copy(java = JavaCheck("incompatible", "Minecraft 1.20.4 needs Java 17; this PC has Java 8."))
        assertEquals(Tone.DANGER, VersionChange.lines(strings, incompatible).first().tone)
    }

    @Test
    fun `a running change is found again when the screen opens`() {
        val jobs = listOf(
            Job("a", kind = "backup", state = "running", serverId = "s"),
            Job("b", kind = "version_change", state = "succeeded", serverId = "s"),
            Job("c", kind = "version_change", state = "running", serverId = "other"),
            Job("d", kind = "version_rollback", state = "running", serverId = "s", step = "Putting the previous version back"),
        )
        assertEquals("d", VersionChange.running(jobs, "s")?.id)
        assertNull(VersionChange.running(jobs.take(3), "s"))
    }

    @Test
    fun `version routes are called as the dashboard calls them`() = runBlocking {
        TestAgent().use { agent ->
            val c = client(agent)
            agent.server.enqueue(agent.json("""{"types": [{"id": "fabric", "name": "Fabric", "edition": "java", "ease": "easy", "recommended": true}], "recommended": "fabric", "default": "fabric"}"""))
            assertEquals("fabric", c.serverTypes().types.single().id)
            assertEquals("/api/server-types", agent.server.takeRequest().path)
            agent.server.enqueue(agent.json("""{"type": "fabric", "type_name": "Fabric", "latest_stable": "1.21.4", "versions": [{"minecraft": "1.21.4", "stable": true, "loaders": ["0.16.9"], "java_required": 21}], "source_problem": null}"""))
            assertEquals(21, c.typeVersions("fabric").versions.single().javaRequired)
            assertEquals("/api/server-types/fabric/versions", agent.server.takeRequest().path)
            agent.server.enqueue(agent.json(versionJson))
            assertTrue(c.serverVersion("s").eulaRequired)
            agent.server.takeRequest()
            agent.server.enqueue(agent.json(preflightJson))
            assertTrue(c.versionPreflight("s", "paper", "1.20.4", null).typeChange)
            val check = agent.server.takeRequest()
            assertEquals("/api/servers/s/version/preflight", check.path)
            assertEquals("""{"type":"paper","minecraft_version":"1.20.4","confirm":false}""", check.body.readUtf8())
            agent.server.enqueue(agent.json("""{"ok": true, "job_id": "j1", "pending": true}"""))
            assertEquals("j1", c.changeVersion("s", "fabric", "1.21.4", "0.16.9").jobId)
            assertEquals("""{"type":"fabric","minecraft_version":"1.21.4","loader_version":"0.16.9","confirm":true}""", agent.server.takeRequest().body.readUtf8())
            agent.server.enqueue(agent.json("""{"ok": true, "job_id": "j2", "type": "fabric", "restored": []}"""))
            assertEquals("j2", c.rollBackVersion("s").jobId)
            assertEquals("/api/servers/s/version/roll-back", agent.server.takeRequest().path)
            agent.server.enqueue(agent.json("""{"ok": true, "file": "C:\\s\\eula.txt", "url": "https://aka.ms/MinecraftEULA"}"""))
            assertEquals("https://aka.ms/MinecraftEULA", c.acceptEula("s").url)
            assertEquals("/api/servers/s/eula", agent.server.takeRequest().path)
        }
    }
}
