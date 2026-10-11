package io.github.peyoteheadlights.mcsc.core

import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okio.Buffer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class ContentTest {
    private val token = "secret-session-token-1234567890"
    private val strings = Strings(Shared.strings)

    private fun client(agent: TestAgent) = AgentClient(agent.pairing(), { token }, systemTrust = TestAgent.trustingNothing())

    private fun mod(filename: String = "a.jar", enabled: Boolean = true, status: String = "ok", vararg issues: ModIssue) =
        Mod(filename = filename, modId = "a", name = "Alpha", version = "1.0", enabled = enabled, status = status, issues = issues.toList())

    // ------------------------------------------------------------ the screen's words
    @Test
    fun `the screen is named for what the server type takes`() {
        val row = ServerRow(id = "s", name = "S")
        assertNull(Content.kind(null))
        assertEquals(ContentKind.MODS, Content.kind(row.copy(content = "mods")))
        assertEquals(ContentKind.PLUGINS, Content.kind(row.copy(content = "plugins")))
        assertEquals(ContentKind.PACKS, Content.kind(row.copy(edition = "bedrock", capabilities = Capabilities(addons = true))))
        assertEquals(ContentKind.NONE, Content.kind(row))
        assertEquals("Mods", strings.t(ContentKind.MODS.titleKey))
        assertEquals("Plugins", strings.t(ContentKind.PLUGINS.titleKey))
        assertEquals("Packs", strings.t(ContentKind.PACKS.titleKey))
    }

    @Test
    fun `each mod says whether it works and why not`() {
        val missing = ModIssue("missing_dependency", "error", "Alpha needs Fabric API, which isn't installed.")
        val version = ModIssue("version_mismatch", "warn", "Alpha is made for Minecraft 1.20.")
        val note = ModIssue("unverified", "info", "Checked from the file only.")
        val broken = mod(status = "error", issues = arrayOf(version, note, missing))
        assertEquals("mods.status_error", Content.status(broken).key)
        assertEquals(Tone.DANGER, Content.status(broken).tone)
        assertEquals(listOf(missing.detail, version.detail), Content.problems(broken))
        assertEquals("mods.status_off", Content.status(mod(enabled = false, status = "disabled")).key)
        assertEquals("value.unknown", Content.status(mod(status = "something new")).key)
    }

    @Test
    fun `a newer version and technical details are shown as the dashboard words them`() {
        val newer = mod().copy(updateAvailable = ModUpdate(latestVersion = "2.0"), minecraftRange = ">=1.21")
        assertEquals("Update: 2.0", Content.newer(strings, newer))
        assertNull(Content.newer(strings, mod()))
        assertEquals("a · a.jar · For Minecraft >=1.21", Content.technical(strings, newer))
        assertEquals("1.0 → 2.0", Content.change(strings, "1.0", "2.0"))
        assertEquals("Unknown → 2.0", Content.change(strings, null, "2.0"))
    }

    // ------------------------------------------------------------ who may change what, and when
    @Test
    fun `only someone allowed sees change buttons, and they work only while stopped`() {
        assertEquals(Changes.NOT_ALLOWED, Content.changes(canManage = false, serverState = States.OFFLINE))
        assertEquals(Changes.READY, Content.changes(canManage = true, serverState = States.OFFLINE))
        assertEquals(Changes.READY, Content.changes(canManage = true, serverState = States.CRASHED))
        for (state in listOf(States.ONLINE, States.STARTING, States.STOPPING, States.RESTART_PENDING)) {
            assertEquals(state, Changes.STOP_FIRST, Content.changes(canManage = true, serverState = state))
        }
        // A state not known is never taken to be stopped.
        assertEquals(Changes.UNKNOWN, Content.changes(canManage = true, serverState = null))
        assertEquals(Changes.UNKNOWN, Content.changes(canManage = true, serverState = States.UNKNOWN))
        // Bedrock packs change while running too (a restart is offered after).
        assertEquals(Changes.READY, Content.packChanges(canManage = true))
        assertEquals(Changes.NOT_ALLOWED, Content.packChanges(canManage = false))
        // "Stop the server first" offers Stop only while it would work.
        assertTrue(Content.canStopHere(States.ONLINE, canControl = true))
        assertFalse(Content.canStopHere(States.ONLINE, canControl = false))
        assertFalse(Content.canStopHere(States.STOPPING, canControl = true))
    }

    @Test
    fun `only a kept version that is there and not in use can be rolled back to`() {
        val kept = ModVersion(version = "1.0", archivePath = "p", exists = true)
        assertTrue(Content.canRollBack(kept))
        assertFalse(Content.canRollBack(kept.copy(isCurrent = true)))
        assertFalse(Content.canRollBack(kept.copy(exists = false)))
    }

    @Test
    fun `history rows say what happened in words`() {
        val row = ModHistoryRow(ts = 1.0, user = "admin", action = "rollback", modName = "Alpha", result = "ok")
        assertEquals("Rolled back", Content.action(strings, row))
        assertEquals("something_new", Content.action(strings, row.copy(action = "something_new")))
        assertEquals(Tone.DANGER, Content.historyTone(row.copy(result = "failed")))
        assertEquals("Alpha, Beta", Content.historyName(strings, ModHistoryRow(action = "update_all", detail = "Alpha, Beta")))
    }

    @Test
    fun `only the files each screen takes are sent`() {
        assertTrue(Content.accepts(ContentKind.MODS, "Sodium-0.6.JAR"))
        assertFalse(Content.accepts(ContentKind.MODS, "pack.mcpack"))
        assertTrue(Content.accepts(ContentKind.PACKS, "skins.mcaddon"))
        assertFalse(Content.accepts(ContentKind.PACKS, "mod.jar"))
        assertTrue(Content.accepts(ContentKind.MODS, "Pack 1.2.mrpack", modpack = true))
    }

    @Test
    fun `missing dependencies are the required mods that aren't there`() {
        val report = DependencyReport(
            items = listOf(
                DependencyItem("fabric-api", kind = "required", status = "missing"),
                DependencyItem("minecraft", kind = "required", platform = true, status = "platform_incompatible"),
                DependencyItem("modmenu", kind = "optional", status = "missing"),
                DependencyItem("cloth", kind = "required", status = "satisfied"),
            ),
        )
        assertEquals(listOf("fabric-api"), Content.missing(report).map { it.modId })
        assertEquals(emptyList<DependencyItem>(), Content.missing(null))
    }

    // ------------------------------------------------------------ Modrinth
    @Test
    fun `the install confirmation lists version, size, licence and sides`() {
        val project = ModProject(
            project = ModrinthProject(slug = "sodium", title = "Sodium", license = "LGPL-3.0", serverSide = "unsupported", clientSide = "required"),
            versions = listOf(
                ModrinthVersion(
                    versionId = "v1", versionNumber = "0.6.0", gameVersions = listOf("1.21.1"),
                    dependencies = listOf(ModrinthDependency("P1", "required"), ModrinthDependency("P2", "optional")),
                    file = ModrinthFile("sodium.jar", 2048),
                ),
            ),
        )
        val version = Install.latest(project)!!
        assertEquals(listOf("P1"), Install.required(version).map { it.projectId })
        assertEquals(
            listOf(
                "Sodium 0.6.0", "Size: 2.0 KB", "For Minecraft 1.21.1", "Licence: LGPL-3.0",
                "Needed on the server: No", "Needed in the game: Yes",
            ),
            Install.facts(strings, project, version),
        )
        assertEquals("1.2M downloads", Install.downloads(strings, 1_234_567))
        assertEquals("Unknown", Install.downloads(strings, null))
        assertEquals("https://modrinth.com/mod/sodium", Install.page("https://modrinth.com/mod/sodium"))
        assertNull(Install.page("https://example.com/mod/sodium"))
    }

    // ------------------------------------------------------------ Update all
    private val plan = UpdateAllPlan(
        updates = listOf(
            UpdateAllRow(modId = "a", name = "Alpha", filename = "a.jar", enabled = true, installedVersion = "1.0", latestVersion = "2.0", versionId = "va"),
            UpdateAllRow(modId = "b", name = "Beta", filename = "b.jar.disabled", enabled = false, installedVersion = "1.0", latestVersion = "1.1", versionId = "vb"),
            UpdateAllRow(modId = "c", name = "Gamma", filename = "c.jar", enabled = true, installedVersion = "3", latestVersion = "4", versionId = null),
        ),
    )

    @Test
    fun `update all ticks the ones that are on and leaves turned-off ones for the person`() {
        assertEquals(setOf("a.jar", "c.jar"), UpdateAll.ticked(plan))
        val body = UpdateAll.body(plan, setOf("c.jar", "b.jar.disabled")).toString()
        assertEquals(
            """{"mods":[{"filename":"b.jar.disabled","version_id":"vb"},{"filename":"c.jar","version_id":null}]}""",
            body,
        )
        assertTrue(UpdateAll.offered(ModList(mods = listOf(mod().copy(updateAvailable = ModUpdate("2.0"))))))
        assertFalse(UpdateAll.offered(ModList(mods = listOf(mod()))))
        assertFalse(UpdateAll.offered(null))
    }

    @Test
    fun `update all says why it can't start and what it did`() {
        assertEquals(strings.t("mobile.content.stop_first"), UpdateAll.blocked(strings, plan.copy(serverRunning = true)))
        assertEquals("Wait for Backing up to finish first.", UpdateAll.blocked(strings, plan.copy(blockedBy = "Backing up")))
        assertNull(UpdateAll.blocked(strings, plan))
        val done = UpdateAllResult(updated = listOf(UpdateAllDone("Alpha", "1.0", "2.0")), safetyBackup = SafetyBackup(4, "before-update-all.zip"))
        assertEquals("Updated 1. The backup made first is before-update-all.zip.", UpdateAll.done(strings, done))
        val running = Job(id = "j", kind = "mods", state = "running", step = "Updating Alpha (1 of 2)", serverId = "s")
        assertEquals("Updating Alpha (1 of 2)", UpdateAll.progress(running, "s"))
        assertNull(UpdateAll.progress(running, "other"))
        assertNull(UpdateAll.progress(running.copy(state = "succeeded"), "s"))
    }

    // ------------------------------------------------------------ modpacks
    @Test
    fun `a modpack import lists its steps, with the version change only when needed`() {
        val inspected = ModpackInspected(
            token = "t",
            pack = Modpack(name = "Pack", minecraftVersion = "1.21.1", typeName = "Fabric", downloadCount = 3, canImport = true),
            into = ModpackInto(versionChange = true),
        )
        val steps = Modpacks.steps(strings, inspected)
        assertEquals(5, steps.size)
        assertEquals(strings.t("pack.step_version", "type" to "Fabric", "version" to "1.21.1"), steps[2])
        assertEquals(4, Modpacks.steps(strings, inspected.copy(into = ModpackInto(false))).size)
        assertEquals("pack.status_client", Modpacks.fileStatus(ModpackFile(status = "client_only")).key)
        assertEquals(Tone.DANGER, Modpacks.fileStatus(ModpackFile(status = "refused")).tone)
    }

    // ------------------------------------------------------------ game settings
    private fun setting(key: String, kind: String, value: kotlinx.serialization.json.JsonElement?, set: Boolean = value != null, default: String = "", readOnly: String? = null) =
        GameSetting(key = key, kind = kind, value = value, set = set, minecraftDefault = default, readOnly = readOnly)

    private val settings = GameSettings(
        exists = true,
        fields = listOf(
            setting("difficulty", "choice", null, default = "easy"),
            setting("max-players", "int", JsonPrimitive(20), default = "20"),
            setting("pvp", "bool", JsonPrimitive(true), default = "true"),
            setting("white-list", "bool", null, default = "false"),
            setting("motd", "text", JsonPrimitive("Hi"), default = "A Minecraft Server"),
            setting("level-seed", "seed", JsonPrimitive("123"), default = "", readOnly = "world_exists"),
            setting("server-port", "port", JsonPrimitive(25565), default = "25565"),
        ),
    )

    @Test
    fun `game settings are grouped as on the PC, with each field's hint`() {
        val groups = GameForm.groups(settings)
        assertEquals(listOf("game.group_play", "game.group_who", "game.group_world"), groups.map { it.titleKey })
        assertEquals(listOf("difficulty", "pvp"), groups[0].fields.map { it.key })
        assertEquals(listOf("motd", "max-players", "white-list"), groups[1].fields.map { it.key })
        val difficulty = settings.fields[0]
        assertEquals("easy", GameForm.initial(difficulty))
        assertEquals("Easy", GameForm.choiceLabel(strings, "easy"))
        assertEquals(
            strings.t("game.difficulty_hint") + " " + strings.t("game.not_set", "value" to "Easy"),
            GameForm.hint(strings, difficulty),
        )
        assertEquals("true", GameForm.initial(settings.fields[2]))
        assertEquals("false", GameForm.initial(settings.fields[3]))
        assertEquals("20", GameForm.initial(settings.fields[1]))
        // A value the file has but Minecraft won't take starts from the default.
        val bad = setting("view-distance", "int", null, set = true, default = "10").copy(problem = "not a number")
        assertEquals("10", GameForm.initial(bad))
        assertTrue(GameForm.fileProblem(strings, bad)!!.endsWith("not a number"))
        assertEquals("Allowlist", strings.t(GameForm.LABELS.getValue("allow-list").first))
    }

    @Test
    fun `the seed is locked once the world exists, and everything for someone who may not edit`() {
        val seed = settings.fields.first { it.key == "level-seed" }
        assertTrue(GameForm.locked(seed, canEdit = true))
        assertEquals(strings.t("game.seed_locked"), GameForm.hint(strings, seed))
        assertFalse(GameForm.locked(settings.fields[0], canEdit = true))
        assertTrue(GameForm.locked(settings.fields[0], canEdit = false))
    }

    @Test
    fun `save sends only what changed, typed as the agent takes it`() {
        val edits = mapOf(
            "difficulty" to "hard",
            "max-players" to "20",
            "pvp" to "false",
            "motd" to "Hi",
            "level-seed" to "999",
            "server-port" to "25570",
            "white-list" to "false",
        )
        assertEquals(
            """{"difficulty":"hard","pvp":false,"server-port":25570}""",
            GameForm.changed(settings, edits).toString(),
        )
        assertEquals("{}", GameForm.changed(settings, emptyMap()).toString())
        assertEquals("""{"max-players":"lots"}""", GameForm.changed(settings, mapOf("max-players" to "lots")).toString())
        assertEquals(strings.t("game.saved_running"), GameForm.saved(strings, GameSettingsSaved(keys = listOf("pvp"), running = true)))
        assertEquals(strings.t("settings.nothing_changed"), GameForm.saved(strings, GameSettingsSaved(nothingChanged = true)))
    }

    // ------------------------------------------------------------ icons
    @Test
    fun `icons come from Modrinth once, then from the phone's cache`() = runBlocking {
        val cdn = MockWebServer()
        cdn.enqueue(MockResponse().setHeader("Cache-Control", "max-age=86400").setBody(Buffer().write(byteArrayOf(1, 2, 3))))
        cdn.start()
        try {
            val dir = kotlin.io.path.createTempDirectory("icons").toFile()
            val icons = IconCache(dir, hosts = setOf(cdn.hostName), httpsOnly = false)
            val url = cdn.url("/data/abc/icon.png").toString()
            assertTrue(byteArrayOf(1, 2, 3).contentEquals(icons.load(url)))
            assertTrue(byteArrayOf(1, 2, 3).contentEquals(icons.load(url)))
            assertEquals(1, cdn.requestCount)
            // A fresh cache on the same folder reads the disk, not Modrinth.
            val again = IconCache(dir, hosts = setOf(cdn.hostName), httpsOnly = false)
            assertTrue(byteArrayOf(1, 2, 3).contentEquals(again.load(url)))
            assertEquals(1, cdn.requestCount)
        } finally {
            cdn.shutdown()
        }
    }

    @Test
    fun `an icon from anywhere but Modrinth's own address is never loaded`() = runBlocking {
        val icons = IconCache(null)
        assertTrue(icons.allowed("https://cdn.modrinth.com/data/abc/icon.png"))
        assertFalse(icons.allowed("http://cdn.modrinth.com/data/abc/icon.png"))
        assertFalse(icons.allowed("https://evil.example/icon.png"))
        assertNull(icons.load("https://evil.example/icon.png"))
        assertNull(icons.load(null))
    }

    // ------------------------------------------------------------ the agent
    @Test
    fun `the installed list, update all and history are read`() = runBlocking {
        TestAgent().use { agent ->
            val c = client(agent)
            agent.server.enqueue(agent.json("""{"mods": [{"filename": "a.jar", "path": "C:\\s\\mods\\a.jar", "mod_id": "a", "name": "Alpha", "version": "1.0", "enabled": true, "status": "warn", "issues": [{"kind": "version_mismatch", "severity": "warn", "detail": "Made for 1.20"}], "has_history": true, "update_available": {"mod_id": "a", "latest_version": "2.0", "version_id": "va"}}], "problems": [], "minecraft_version": null, "server_state": "OFFLINE", "updates_checked_at": null}"""))
            val list = c.mods("s")
            assertEquals("2.0", list.mods.single().updateAvailable?.latestVersion)
            assertNull(list.minecraftVersion)
            assertEquals("/api/servers/s/mods", agent.server.takeRequest().path)

            agent.server.enqueue(agent.json("""{"updates": [{"mod_id": "b", "name": "Beta", "filename": "b.jar.disabled", "enabled": false, "installed_version": "1.0", "latest_version": "1.1", "version_id": "vb", "project": "beta"}], "unchecked": [{"mod_id": "c", "name": "Gamma", "filename": "c.jar", "reason": "Modrinth didn't answer."}], "server_running": false, "blocked_by": null, "checked_at": 5.0}"""))
            val plan = c.updateAllPlan("s")
            assertFalse(plan.updates.single().enabled)
            assertEquals("Modrinth didn't answer.", plan.unchecked.single().reason)
            agent.server.takeRequest()

            agent.server.enqueue(agent.json("""{"ok": true, "job_id": "j", "updated": [{"mod_id": "b", "name": "Beta", "filename": "b-1.1.jar.disabled", "previous_version": "1.0", "version": "1.1"}], "safety_backup": {"id": 3, "name": "before-update-all.zip"}, "undo": {"kind": "restore_backup", "backup_id": 3, "backup": "before-update-all.zip"}}"""))
            val done = c.updateAll("s", UpdateAll.body(plan, setOf("b.jar.disabled")))
            assertEquals("1.1", done.updated.single().version)
            val sent = agent.server.takeRequest()
            assertEquals("POST", sent.method)
            assertEquals("/api/servers/s/mods/update-all", sent.path)
            assertEquals("""{"mods":[{"filename":"b.jar.disabled","version_id":"vb"}]}""", sent.body.readUtf8())

            agent.server.enqueue(agent.json("""{"history": [{"id": 9, "server_id": "s", "ts": 10.0, "user": "admin", "action": "update_all", "mod_id": null, "mod_name": null, "old_version": null, "new_version": null, "source": null, "sha256": null, "result": "failed", "detail": "Updating Beta failed"}]}"""))
            assertEquals("failed", c.modHistory("s").history.single().result)
            assertEquals("/api/servers/s/mods/history?limit=100", agent.server.takeRequest().path)
        }
    }

    @Test
    fun `turning on, removing, rolling back and installing send what the dashboard sends`() = runBlocking {
        TestAgent().use { agent ->
            val c = client(agent)
            agent.server.enqueue(agent.json("""{"ok": true, "mod": {"filename": "a.jar.disabled", "mod_id": "a", "name": "Alpha", "version": "1.0", "enabled": false}, "changed": true}"""))
            assertFalse(c.setModEnabled("s", "a.jar", enabled = false).mod!!.enabled)
            val off = agent.server.takeRequest()
            assertEquals("/api/servers/s/mods/disable", off.path)
            assertEquals("""{"filename":"a.jar"}""", off.body.readUtf8())

            agent.server.enqueue(agent.json("""{"mod": {}, "dependents": [{"name": "Beta", "mod_id": "b", "filename": "b.jar", "requires": ">=1.0"}], "warning": "Beta needs it."}"""))
            assertEquals("Beta", c.modImpact("s", "my mod.jar").dependents.single().name)
            assertEquals("/api/servers/s/mods/impact?filename=my%20mod.jar", agent.server.takeRequest().path)

            agent.server.enqueue(agent.json("""{"versions": [{"id": 1, "version": "1.0", "filename": "a.jar", "archive_path": "C:\\kept\\a.jar", "created_at": 3.0, "is_current": false, "exists": true}]}"""))
            val kept = c.modVersions("s", "a").versions.single()
            agent.server.takeRequest()
            agent.server.enqueue(agent.json("""{"ok": true, "restored": {"filename": "a.jar", "name": "Alpha", "version": "1.0"}, "previous_version": "2.0"}"""))
            assertEquals("2.0", c.rollBackMod("s", "a", kept.archivePath).previousVersion)
            assertTrue(agent.server.takeRequest().body.readUtf8().contains("\"archive_path\":\"C:\\\\kept\\\\a.jar\""))

            agent.server.enqueue(agent.json("""{"hits": [{"project_id": "P", "slug": "sodium", "title": "Sodium", "description": "Fast", "downloads": 5, "icon_url": "https://cdn.modrinth.com/i.png", "page": "https://modrinth.com/mod/sodium"}], "total": 1, "offset": 0}"""))
            assertEquals("https://cdn.modrinth.com/i.png", c.searchMods("s", "so dium").hits.single().iconUrl)
            assertEquals("/api/servers/s/mods/search?q=so%20dium&limit=20&offset=0", agent.server.takeRequest().path)

            agent.server.enqueue(agent.json("""{"ok": true, "installed": {"filename": "sodium.jar", "name": "Sodium", "version": "0.6"}, "dependencies_required": [{"mod_id": "fabric-api", "title": "Fabric API", "installed": false}], "dependencies_installed": []}"""))
            assertEquals("Fabric API", c.installMod("s", "sodium", "v1", withDependencies = false).dependenciesRequired.single().title)
            assertEquals("""{"project":"sodium","version_id":"v1","install_dependencies":false}""", agent.server.takeRequest().body.readUtf8())

            agent.server.enqueue(agent.json("""{"items": [], "unresolvable": [{"mod_id": "x", "name": "X", "required_by": ["Alpha"], "reason": "Not found on Modrinth. Install it manually.", "page": null}], "skipped": [], "minecraft_version": "1.21.1"}"""))
            assertEquals("X", c.planDependencies("s").unresolvable.single().name)
            assertEquals("/api/servers/s/mods/dependencies/plan", agent.server.takeRequest().path)
        }
    }

    @Test
    fun `a file picked on the phone is sent as an upload form`() = runBlocking {
        TestAgent().use { agent ->
            val c = client(agent)
            agent.server.enqueue(agent.json("""{"ok": true, "installed": {"filename": "e.jar", "name": "Epsilon", "version": "3.0"}}"""))
            assertEquals("Epsilon", c.uploadMod("s", "e.jar", byteArrayOf(80, 75, 3, 4)).installed?.name)
            val sent = agent.server.takeRequest()
            assertEquals("/api/servers/s/mods/upload", sent.path)
            assertTrue(sent.getHeader("Content-Type")!!.startsWith("multipart/form-data"))
            val body = sent.body.readUtf8()
            assertTrue(body, body.contains("name=\"file\"; filename=\"e.jar\""))

            agent.server.enqueue(agent.json("""{"token": "tok", "pack": {"name": "Pack", "version": "1.2", "summary": null, "minecraft_version": "1.21.1", "type": "fabric", "type_name": "Fabric", "loader_version": "0.16.5", "files": [{"name": "lithium.jar", "path": "mods/lithium.jar", "size": 10, "status": "download", "reason": null, "env_server": "required"}], "download_count": 1, "download_bytes": 10, "client_only": [], "refused": [], "overrides": 0, "overrides_bytes": 0, "skipped_overrides": [], "problems": [], "can_import": true}, "into": {"version_change": false, "running": false}}"""))
            val pack = c.inspectModpack("s", "p.mrpack", byteArrayOf(1))
            assertEquals("tok", pack.token)
            assertEquals("/api/modpacks/inspect?server_id=s", agent.server.takeRequest().path)
            agent.server.enqueue(agent.json("""{"ok": true, "job_id": "j", "modpack": {"name": "Pack"}, "version_change": false, "undo": null}"""))
            assertEquals("Pack", c.importModpack("s", "tok").modpack.name)
            assertEquals("""{"token":"tok","confirm":true}""", agent.server.takeRequest().body.readUtf8())
        }
    }

    @Test
    fun `bedrock packs and game settings are read and saved`() = runBlocking {
        TestAgent().use { agent ->
            val c = client(agent)
            agent.server.enqueue(agent.json("""{"addons": [{"uuid": "u1", "version": "1.0.0", "name": "Skins", "description": null, "kind": "resource", "folder": "resource_packs/skins", "enabled": true}], "world": "Bedrock level", "running": true, "restart_needed": true}"""))
            val packs = c.addons("s")
            assertEquals("Bedrock level", packs.world)
            assertEquals("addons.kind_resource", Content.packKind(packs.addons.single()))
            agent.server.takeRequest()
            agent.server.enqueue(agent.json("""{"ok": true, "installed": [], "restart_needed": true}"""))
            assertEquals(true, c.setAddonEnabled("s", "u1", enabled = false).restartNeeded)
            val toggled = agent.server.takeRequest()
            assertEquals("PUT", toggled.method)
            assertEquals("""{"enabled":false}""", toggled.body.readUtf8())

            agent.server.enqueue(agent.json("""{"file": "C:\\s\\server.properties", "exists": true, "modified_at": 1.0, "world_exists": true, "world_folder": "world", "fields": [{"key": "max-players", "kind": "int", "value": 20, "raw": "20", "set": true, "problem": null, "minecraft_default": "20", "choices": [], "min": 1, "max": 10000, "max_length": 200, "read_only": null}], "text": "", "running": false, "restart_needed": false}"""))
            assertEquals("20", GameForm.initial(c.gameSettings("s").fields.single()))
            agent.server.takeRequest()
            agent.server.enqueue(agent.json("""{"detail": "Some values can't be used.", "problems": {"server-port": "Another program is using port 80."}}""", code = 400))
            val e = assertThrows(AgentException.Failed::class.java) {
                runBlocking { c.saveGameSettings("s", buildJsonObject { put("server-port", 80) }) }
            }
            assertEquals("Another program is using port 80.", e.problems["server-port"])
            val saved = agent.server.takeRequest()
            assertEquals("PUT", saved.method)
            assertEquals("""{"values":{"server-port":80}}""", saved.body.readUtf8())
        }
    }
}
