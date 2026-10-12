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
        StubAgent.json(##"{"ok": true, "color": "#3366CC"}"##)
        let color = try await c.setColor(serverId: "s", color: "#3366CC")
        XCTAssertEqual(color.color, "#3366CC")
        XCTAssertEqual(path(2), "/api/servers/s/color")
        XCTAssertEqual(body(2), ##"{"color":"#3366CC"}"##)
    }

    // MARK: - CPU cores and memory

    func testCpuCoresShowWhoElseUsesEachCoreAndWhatTheServerGot() {
        let cpu = CpuOverview(
            logicalCores: 8, supported: true,
            others: [CpuOther(id: "b", name: "Creative", cores: [0, 1]), CpuOther(id: "c", name: "Modded", cores: [1])],
            status: CpuStatus(configured: [0, 1, 2, 3], applied: [0, 1, 2, 3])
        )
        XCTAssertEqual(CpuCores.sharedBy(cpu), [0: ["Creative"], 1: ["Creative", "Modded"]])
        XCTAssertEqual(CpuCores.describe([6, 3, 0, 1, 2]), "1-4, 7")
        XCTAssertEqual(CpuCores.half(7), [0, 1, 2, 3])
        XCTAssertEqual(CpuCores.nowLine(s, cpu), "Using 1-4 now.")
        var every = cpu
        every.status = CpuStatus(applied: Array(0...7))
        XCTAssertEqual(CpuCores.nowLine(s, every), "Using all cores now.")
        var unknown = cpu
        unknown.status = CpuStatus(appliedReason: "The server is not running")
        XCTAssertEqual(CpuCores.nowLine(s, unknown), "Cores in use now unknown: The server is not running")
        XCTAssertEqual(CpuCores.toSave(all: true, picked: [2]), [])
        XCTAssertNil(CpuCores.toSave(all: false, picked: []))
        XCTAssertEqual(CpuCores.toSave(all: false, picked: [3, 1]), [1, 3])
    }

    func testAfterSavingCoresThePhoneSaysWhetherTheRunningServerGotThem() throws {
        XCTAssertEqual(CpuCores.saved(s, ServerSettingsSaved()), s.t("serverset.cores_next_start"))
        XCTAssertEqual(CpuCores.saved(s, ServerSettingsSaved(cpuCores: CpuApplied(ok: true, applied: [0]))), s.t("serverset.cores_applied"))
        XCTAssertEqual(CpuCores.saved(s, ServerSettingsSaved(cpuCores: CpuApplied(ok: false, reason: "Access denied"))), "Saved, but not applied yet: Access denied")
        let decoded = try JSONDecoder().decode(ServerSettingsSaved.self, from: Data(#"{"ok": true, "applied": {"server.cpu_cores": [0]}, "rejected": {}, "cpu_cores": {"ok": true, "applied": [0], "reason": null}}"#.utf8))
        XCTAssertEqual(decoded.cpuCores?.applied, [0])
    }

    private let memoryJSON = #"""
    {"total_mb": 16384, "total_source": "measured (psutil)", "limit_mb": 6144, "jvm_args": ["-Xmx6G"],
     "takes_memory_limit": true, "min_mb": 1024, "max_mb": 16384, "step_mb": 512, "together_mb": 14336,
     "servers": [{"id": "s", "name": "Survival", "limit_mb": 6144, "running": false, "this": true},
                 {"id": "b", "name": "Creative", "limit_mb": 8192, "running": true, "this": false}], "over": false, "running": false}
    """#

    private func memory() throws -> MemoryOverview {
        try JSONDecoder().decode(MemoryOverview.self, from: Data(memoryJSON.utf8))
    }

    func testTheMemorySliderKeepsToWhatThePcHas() throws {
        let memory = try memory()
        XCTAssertTrue(Memory.slider(memory))
        XCTAssertEqual(Memory.start(memory), 6144)
        XCTAssertEqual(Memory.snap(memory, 100), 1024)
        XCTAssertEqual(Memory.snap(memory, 99999), 16384)
        XCTAssertEqual(Memory.snap(memory, 2700), 2560)
        XCTAssertEqual(Memory.gb(6144), "6 GB")
        XCTAssertEqual(Memory.gb(1536), "1.5 GB")
        XCTAssertEqual(Memory.nowLine(s, memory), "Now: up to 6 GB. Changes apply on the next start.")
        var unmeasured = memory
        unmeasured.totalMb = nil
        XCTAssertFalse(Memory.slider(unmeasured))
        XCTAssertEqual(Memory.noSlider(s, unmeasured, bedrock: false), s.t("memory.pc_unknown"))
    }

    func testMemoryWarnsWhenEveryServerTogetherWouldUseMoreThanThePcHas() throws {
        let memory = try memory()
        XCTAssertNil(Memory.warning(s, memory, 8192))
        XCTAssertEqual(Memory.warning(s, memory, 8704), "With Creative running, servers may use 16.5 GB, more than this PC has (16 GB).")
        var alone = memory
        alone.servers = Array(memory.servers.prefix(1))
        XCTAssertEqual(Memory.warning(s, alone, 17408), "17 GB is more than this PC has (16 GB). Windows may slow down or the server may crash.")
        var unmeasured = memory
        unmeasured.totalMb = nil
        XCTAssertNil(Memory.warning(s, unmeasured, 99999))
    }

    func testBedrockServersHaveNoMemorySetting() {
        let bedrock = MemoryOverview(totalMb: 16384, takesMemoryLimit: false)
        XCTAssertFalse(Memory.slider(bedrock))
        XCTAssertEqual(Memory.noSlider(s, bedrock, bedrock: true), s.t("memory.not_bedrock"))
    }

    func testMemoryGoesToTheAgentsRoute() async throws {
        let c = client()
        StubAgent.json(memoryJSON)
        let read = try await c.memory(serverId: "s")
        XCTAssertEqual(read.limitMb, 6144)
        XCTAssertEqual(path(0), "/api/servers/s/memory")
        StubAgent.json(memoryJSON)
        _ = try await c.setMemory(serverId: "s", mb: 4096)
        XCTAssertEqual(method(1), "PUT")
        XCTAssertEqual(body(1), #"{"memory_mb":4096}"#)
    }

    // MARK: - Version and type

    private let versionJSON = #"""
    {"type": "fabric", "capabilities": {"id": "fabric", "name": "Fabric", "edition": "java", "content": "mods"},
     "minecraft_version": "1.21.1", "minecraft_version_source": "console", "loader_version": "0.16.5", "loader_name": "Fabric Loader",
     "detected_type": "fabric", "pending_version": null, "eula_required": true, "eula_url": "https://aka.ms/MinecraftEULA",
     "last_change": {"at": 1.0, "type": "fabric", "previous_type": "fabric", "minecraft_version": "1.21.1", "can_roll_back": true, "install_log": null, "moved_aside": []}}
    """#

    private let preflightJSON = #"""
    {"current": {"type": "fabric", "type_name": "Fabric", "minecraft_version": "1.21.1", "loader_version": "0.16.5", "observed": true},
     "target": {"type": "paper", "type_name": "Paper", "minecraft_version": "1.20.4", "loader_version": null, "stable": true},
     "type_change": true, "gentle_type_change": false, "direction": "older", "downgrade_warning": true,
     "java": {"verdict": "unknown", "detail": "Java couldn't be checked on this PC."}, "java_required": 17,
     "latest_only": false, "kept": false, "content_kind": "mods", "target_content_kind": "plugins", "content": [],
     "moved_aside": ["sodium.jar", "lithium.jar"], "unknown_support": [], "not_supporting": [],
     "backup_first": true, "crossplay": true, "crossplay_available": true}
    """#

    private func decode<T: Decodable>(_ type: T.Type, _ text: String) throws -> T {
        try JSONDecoder().decode(type, from: Data(text.utf8))
    }

    func testTheVersionIsWhatTheConsoleSaidAndRollBackAndTheEulaFollowTheAgent() throws {
        var version = try decode(ServerVersion.self, versionJSON)
        XCTAssertEqual(VersionChange.now(s, version), "Fabric 1.21.1")
        XCTAssertTrue(VersionChange.eulaNeeded(version))
        XCTAssertTrue(VersionChange.canRollBack(version))
        XCTAssertEqual(version.eulaUrl, "https://aka.ms/MinecraftEULA")
        version.minecraftVersion = nil
        version.eulaRequired = false
        version.lastChange = nil
        XCTAssertEqual(VersionChange.now(s, version), s.t("version.not_seen_yet"))
        XCTAssertFalse(VersionChange.eulaNeeded(version))
        XCTAssertFalse(VersionChange.canRollBack(version))
    }

    func testOnlyTheSameEditionsKindsAreOfferedAndSnapshotsOnlyWhenAsked() throws {
        let version = try decode(ServerVersion.self, versionJSON)
        let types = [ServerTypeInfo(id: "fabric", name: "Fabric"), ServerTypeInfo(id: "paper", name: "Paper"), ServerTypeInfo(id: "bedrock", name: "Bedrock", edition: "bedrock")]
        XCTAssertEqual(VersionChange.sameEdition(types, version).map(\.id), ["fabric", "paper"])
        let offered = TypeVersions(versions: [OfferedVersion(minecraft: "1.21.4"), OfferedVersion(minecraft: "25w01a", stable: false)])
        XCTAssertEqual(VersionChange.choices(offered, snapshots: false).map(\.minecraft), ["1.21.4"])
        XCTAssertEqual(VersionChange.choices(offered, snapshots: true).count, 2)
    }

    func testTheCheckSaysWhatMightBreakBeforeAnythingChanges() throws {
        let report = try decode(VersionPreflight.self, preflightJSON)
        let lines = VersionChange.lines(s, report)
        XCTAssertEqual(lines[0].text, s.t("version.downgrade"))
        XCTAssertEqual(lines[1].tone, .warning)
        XCTAssertTrue(lines[1].text.hasPrefix("This changes the server from Fabric to Paper."))
        XCTAssertTrue(lines.contains { $0.text.hasPrefix("2 add-ons don't fit") })
        XCTAssertEqual(lines[lines.count - 2].text, s.t("version.java_unknown"))
        XCTAssertEqual(lines.last?.text, s.t("version.backup_first"))
        XCTAssertTrue(VersionChange.danger(report))
        var gentle = report
        gentle.downgradeWarning = false
        gentle.gentleTypeChange = true
        XCTAssertFalse(VersionChange.danger(gentle))
        XCTAssertEqual(VersionChange.target(report), "Paper 1.20.4")
        var incompatible = report
        incompatible.java = JavaCheck(verdict: "incompatible", detail: "Minecraft 1.20.4 needs Java 17; this PC has Java 8.")
        XCTAssertEqual(VersionChange.lines(s, incompatible).first?.tone, .danger)
    }

    func testARunningChangeIsFoundAgainWhenTheScreenOpens() {
        let jobs = [
            Job(id: "a", kind: "backup", state: "running", serverId: "s"),
            Job(id: "b", kind: "version_change", state: "succeeded", serverId: "s"),
            Job(id: "c", kind: "version_change", state: "running", serverId: "other"),
            Job(id: "d", kind: "version_rollback", state: "running", step: "Putting the previous version back", serverId: "s"),
        ]
        XCTAssertEqual(VersionChange.running(jobs, serverId: "s")?.id, "d")
        XCTAssertNil(VersionChange.running(Array(jobs.prefix(3)), serverId: "s"))
    }

    func testVersionRoutesAreCalledAsTheDashboardCallsThem() async throws {
        let c = client()
        StubAgent.json(#"{"types": [{"id": "fabric", "name": "Fabric", "edition": "java", "ease": "easy", "recommended": true}], "recommended": "fabric", "default": "fabric"}"#)
        let types = try await c.serverTypes()
        XCTAssertEqual(types.types.first?.id, "fabric")
        XCTAssertEqual(path(0), "/api/server-types")
        StubAgent.json(#"{"type": "fabric", "type_name": "Fabric", "latest_stable": "1.21.4", "versions": [{"minecraft": "1.21.4", "stable": true, "loaders": ["0.16.9"], "java_required": 21}], "source_problem": null}"#)
        let offered = try await c.typeVersions(typeId: "fabric")
        XCTAssertEqual(offered.versions.first?.javaRequired, 21)
        XCTAssertEqual(path(1), "/api/server-types/fabric/versions")
        StubAgent.json(versionJSON)
        let version = try await c.serverVersion(serverId: "s")
        XCTAssertTrue(version.eulaRequired)
        StubAgent.json(preflightJSON)
        let report = try await c.versionPreflight(serverId: "s", type: "paper", minecraft: "1.20.4", loader: nil)
        XCTAssertTrue(report.typeChange)
        XCTAssertEqual(path(3), "/api/servers/s/version/preflight")
        XCTAssertEqual(body(3), #"{"confirm":false,"minecraft_version":"1.20.4","type":"paper"}"#)
        StubAgent.json(#"{"ok": true, "job_id": "j1", "pending": true}"#)
        let changed = try await c.changeVersion(serverId: "s", type: "fabric", minecraft: "1.21.4", loader: "0.16.9")
        XCTAssertEqual(changed.jobId, "j1")
        XCTAssertEqual(body(4), #"{"confirm":true,"loader_version":"0.16.9","minecraft_version":"1.21.4","type":"fabric"}"#)
        StubAgent.json(#"{"ok": true, "job_id": "j2", "type": "fabric", "restored": []}"#)
        let back = try await c.rollBackVersion(serverId: "s")
        XCTAssertEqual(back.jobId, "j2")
        XCTAssertEqual(path(5), "/api/servers/s/version/roll-back")
        StubAgent.json(#"{"ok": true, "file": "C:\\s\\eula.txt", "url": "https://aka.ms/MinecraftEULA"}"#)
        let eula = try await c.acceptEula(serverId: "s")
        XCTAssertEqual(eula.url, "https://aka.ms/MinecraftEULA")
        XCTAssertEqual(path(6), "/api/servers/s/eula")
    }

    // MARK: - Crossplay and duplicate

    func testCrossplayIsOfferedOnlyWhereGeyserIsBuiltWithTheAgentsReason() throws {
        var off = try decode(CrossplayInfo.self, #"{"available": false, "unavailable_reason": "GeyserMC publishes no build for Forge servers.", "enabled": false, "port": null, "default_port": 19132, "suggested_port": null, "differences": []}"#)
        XCTAssertEqual(Crossplay.whyNot(s, off), "GeyserMC publishes no build for Forge servers.")
        off.unavailableReason = nil
        XCTAssertEqual(Crossplay.whyNot(s, off), s.t("cross.not_for_type"))
        let on = CrossplayInfo(available: true, enabled: false, suggestedPort: 19133)
        XCTAssertNil(Crossplay.whyNot(s, on))
        XCTAssertEqual(Crossplay.port(on), "19133")
        XCTAssertEqual(Crossplay.port(CrossplayInfo(available: true)), "19132")
        XCTAssertEqual(Crossplay.typedPort(" 19140 "), 19140)
        XCTAssertNil(Crossplay.typedPort("99999"))
        var enabled = on
        enabled.enabled = true
        XCTAssertEqual(Crossplay.ready(s, enabled), s.t("cross.files_missing"))
    }

    func testDuplicateIsForTheOwnerAndOffersTheWorldChoicesThereAre() {
        XCTAssertFalse(Duplicate.allowed(me(Permissions.SETTINGS_EDIT)))
        XCTAssertTrue(Duplicate.allowed(me(Permissions.SERVERS_MANAGE)))
        XCTAssertEqual(Duplicate.worlds(DuplicateOptions(worldFolders: ["world"])), ["copy", "fresh"])
        XCTAssertEqual(Duplicate.worlds(DuplicateOptions()), ["fresh"])
        XCTAssertFalse(Duplicate.ready(" ", "D:/mc"))
        XCTAssertTrue(Duplicate.ready("Copy", "D:/mc"))
        XCTAssertEqual(Duplicate.progress(Job(id: "j", kind: "duplicate", state: "running", step: "Copying files", serverId: "s"), serverId: "s"), "Copying files")
        XCTAssertNil(Duplicate.progress(Job(id: "j", kind: "duplicate", state: "succeeded", serverId: "s"), serverId: "s"))
    }

    func testCrossplayAndDuplicateGoToTheAgentsRoutes() async throws {
        let c = client()
        StubAgent.json(#"{"available": true, "enabled": false, "default_port": 19132, "suggested_port": 19132, "username_prefix": ".", "differences": ["a"], "address": null, "address_unknown": null}"#)
        let info = try await c.crossplay(serverId: "s")
        XCTAssertTrue(info.available)
        StubAgent.json(#"{"ok": true, "available": true, "enabled": true, "port": 19132, "default_port": 19132, "ready": true}"#)
        let turned = try await c.setCrossplay(serverId: "s", enabled: true, port: 19132)
        XCTAssertTrue(turned.ready)
        XCTAssertEqual(method(1), "PUT")
        XCTAssertEqual(body(1), #"{"enabled":true,"port":19132}"#)
        StubAgent.json(#"{"name": "Survival copy", "directory": "D:/mc/Survival copy", "running": true, "crossplay": false, "world_folders": ["world"]}"#)
        let options = try await c.duplicateOptions(serverId: "s")
        XCTAssertEqual(options.name, "Survival copy")
        StubAgent.json(#"{"ok": true, "job": {"id": "j", "kind": "duplicate", "title": "Copying", "state": "running", "server_id": "s"}}"#)
        let started = try await c.duplicate(serverId: "s", name: "Copy", directory: "D:/mc/Copy", world: "fresh")
        XCTAssertEqual(started.job.id, "j")
        XCTAssertEqual(body(3), #"{"directory":"D:/mc/Copy","name":"Copy","world":"fresh"}"#)
    }

    func testRemoveServerIsForTheOwnerAndNeverOnTheLastServer() {
        XCTAssertFalse(RemoveServer.allowed(me(Permissions.SETTINGS_EDIT)))
        XCTAssertTrue(RemoveServer.allowed(me(Permissions.SERVERS_MANAGE)))
        XCTAssertEqual(RemoveServer.blocked(s, serverCount: 1), s.t("serverset.remove_last"))
        XCTAssertNil(RemoveServer.blocked(s, serverCount: 2))
        XCTAssertEqual(RemoveServer.hint(s, serverCount: 2), s.t("serverset.remove_hint"))
        XCTAssertEqual(RemoveServer.hint(s, serverCount: 1), s.t("serverset.remove_last"))
    }

    func testRemoveServerGoesToTheAgentsRoute() async throws {
        StubAgent.json(#"{"ok": true, "removed": "s", "name": "Survival", "directory": "D:/mc"}"#)
        let removed = try await client().removeServer(serverId: "s")
        XCTAssertEqual(removed.name, "Survival")
        XCTAssertEqual(method(0), "DELETE")
        XCTAssertEqual(path(0), "/api/servers/s")
    }

    func testTheChangeListShowsAddedRemovedAndChangedKeysAndIgnoresComments() {
        let before = "#Minecraft server properties\nmotd=Hello\npvp=true\nmax-players=20\n"
        let after = "# my note\r\nmotd = Hi there\r\nmax-players=20\r\nallow-flight=true\r\n"
        XCTAssertEqual(RawText.propertyChanges(before, after), [
            RawChange("allow-flight", nil, "true"),
            RawChange("motd", "Hello", "Hi there"),
            RawChange("pvp", "true", nil),
        ])
        XCTAssertEqual(RawText.propertyChanges(before, "# new comment\n" + before), [])
    }

    func testPropertiesAreReadTheWayTheAgentReadsThem() {
        let read = RawText.properties("  a : 1\nb\\\n  c=2\n! old\nmotd=caf\\u00e9\nempty=\na=3\n")
        XCTAssertEqual(read, ["a": "3", "bc": "2", "motd": "café", "empty": ""])
    }

    func testJavaOptionsAreComparedByOptionNotByPosition() {
        let before = ["-Xms1G", "-Xmx4G", "-XX:+UseG1GC", "-Dfile.encoding=UTF-8"]
        XCTAssertEqual(RawText.args(" -Xms1G  -Xmx6G\n-XX:-UseG1GC "), ["-Xms1G", "-Xmx6G", "-XX:-UseG1GC"])
        XCTAssertEqual(RawText.argChanges(before, RawText.args("-Xmx6G -Xms1G -XX:-UseG1GC")), [
            RawChange("-Dfile.encoding", "-Dfile.encoding=UTF-8", nil),
            RawChange("-XX:UseG1GC", "-XX:+UseG1GC", "-XX:-UseG1GC"),
            RawChange("-Xmx", "-Xmx4G", "-Xmx6G"),
        ])
        XCTAssertEqual(RawText.argChanges(before, before.reversed()), [])
        // An option given twice: taking one out is a change, not "nothing changed".
        XCTAssertEqual(
            RawText.argChanges(RawText.args("-Dx=1 -Dx=2"), RawText.args("-Dx=1")),
            [RawChange("-Dx (2)", "-Dx=2", nil)]
        )
    }

    func testEachChangeIsSaidInPlainWords() {
        XCTAssertEqual(RawText.line(s, RawChange("a", nil, "1")), s.t("mobile.raw.added", ["key": "a", "new": "1"]))
        XCTAssertEqual(RawText.line(s, RawChange("a", "1", nil)), s.t("mobile.raw.removed", ["key": "a", "old": "1"]))
        XCTAssertEqual(RawText.line(s, RawChange("a", "1", "2")), s.t("mobile.raw.changed", ["key": "a", "old": "1", "new": "2"]))
        XCTAssertTrue(RawText.allowed(me(Permissions.SETTINGS_EDIT), technical: true))
        XCTAssertFalse(RawText.allowed(me(Permissions.SETTINGS_EDIT), technical: false))
        XCTAssertFalse(RawText.allowed(me(Permissions.SETTINGS_VIEW), technical: true))
    }

    func testRawGameSettingsGoToTheAgentsRoute() async throws {
        StubAgent.json(#"{"ok": true, "keys": ["motd"], "running": false, "restart_needed": false}"#)
        let saved = try await client().saveGameSettingsText(serverId: "s", text: "motd=Hi\n")
        XCTAssertEqual(saved.keys, ["motd"])
        XCTAssertEqual(method(0), "PUT")
        XCTAssertEqual(path(0), "/api/servers/s/game-settings/raw")
        XCTAssertEqual(body(0), #"{"text":"motd=Hi\n"}"#)
    }

    func testTheFolderPickerReadsTheListingAndGoesUpToTheDrivesFromARoot() throws {
        let top = try JSONDecoder().decode(FolderListing.self, from: Data(#"{"path": null, "parent": null, "folders": [], "drives": [{"name": "C:", "path": "C:\\"}], "shortcuts": [{"key": "saves", "path": "C:\\saves"}]}"#.utf8))
        XCTAssertTrue(FolderPicker.atTop(top))
        XCTAssertNil(FolderPicker.up(top))
        XCTAssertEqual(FolderPicker.shortcutName(s, top.shortcuts[0]), s.t("folders.saves"))
        XCTAssertEqual(FolderPicker.driveName(s, top.drives[0]), s.t("folders.drive", ["name": "C:"]))
        let root = try JSONDecoder().decode(FolderListing.self, from: Data(#"{"path": "C:\\", "parent": null, "folders": [{"name": "mc", "path": "C:\\mc", "world": false}]}"#.utf8))
        XCTAssertFalse(FolderPicker.atTop(root))
        XCTAssertEqual(FolderPicker.up(root), "")
        let inside = try JSONDecoder().decode(FolderListing.self, from: Data(#"{"path": "C:\\mc", "parent": "C:\\", "folders": [], "truncated": true, "world": true}"#.utf8))
        XCTAssertEqual(FolderPicker.up(inside), "C:\\")
        XCTAssertEqual(FolderPicker.notes(s, inside), [s.t("folders.empty"), s.t("folders.truncated")])
    }

    func testTheFolderPickerIsTheOwnersAndTypingAPathIsForTechnicalMode() {
        XCTAssertFalse(FolderPicker.allowed(me(Permissions.SETTINGS_EDIT)))
        XCTAssertTrue(FolderPicker.allowed(me(Permissions.FILES_BROWSE)))
        XCTAssertFalse(FolderPicker.canType(technical: false))
        XCTAssertTrue(FolderPicker.canType(technical: true))
    }

    func testFoldersAndTheOffPCFolderGoToTheAgentsRoutes() async throws {
        let c = client()
        StubAgent.json(#"{"path": null, "parent": null, "folders": [], "drives": [], "shortcuts": []}"#)
        _ = try await c.folders(path: nil)
        XCTAssertEqual(path(0), "/api/folders")
        StubAgent.json(#"{"path": "D:\\My stuff", "parent": "D:\\", "folders": []}"#)
        _ = try await c.folders(path: "D:\\My stuff")
        XCTAssertEqual(StubAgent.requests[1].request.url?.query, "path=D%3A%5CMy%20stuff")
        StubAgent.json(#"{"ok": true, "directory": "D:\\Backups"}"#)
        _ = try await c.setOffsite(serverId: "s", directory: "D:\\Backups")
        XCTAssertEqual(body(2), #"{"directory":"D:\\Backups"}"#)
    }

    private let optionsJSON = #"""
    {"types": [
      {"id": "vanilla", "name": "Vanilla", "edition": "java", "ease": "easy", "snapshots": true, "version_source": "Mojang version list"},
      {"id": "fabric", "name": "Fabric", "edition": "java", "content": "mods", "ease": "easy", "modrinth": true, "picks_loader": true, "loader_name": "Fabric Loader", "metadata_files": ["fabric.mod.json"], "recommended": true},
      {"id": "bedrock", "name": "Bedrock", "edition": "bedrock", "takes_memory_limit": false, "latest_only": true}
    ], "recommended": "fabric", "memory_mb": 4096, "memory_reason": null, "port": 25566, "color": "#F87906",
    "palette": [{"id": "orange", "name": "Orange", "hex": "#F87906"}], "eula_url": "https://aka.ms/MinecraftEULA",
    "bedrock": {"port": 19132, "port_v6": 19133, "eula_url": "https://minecraft.net/eula", "privacy_url": "https://privacy", "terms": null}}
    """#

    private func options() throws -> NewServerOptions {
        try JSONDecoder().decode(NewServerOptions.self, from: Data(optionsJSON.utf8))
    }

    func testNewServersAreTheOwnersAndBedrockSkipsTheTableOfKinds() throws {
        let read = try options()
        XCTAssertFalse(AddServer.allowed(me(Permissions.SETTINGS_EDIT)))
        XCTAssertTrue(AddServer.allowed(me(Permissions.SERVERS_MANAGE)))
        XCTAssertEqual(AddServer.kinds(read).map(\.id), ["vanilla", "fabric"])
        XCTAssertEqual(AddServer.steps("java"), [AddServer.EDITION, AddServer.KIND, AddServer.VERSION, AddServer.DETAILS, AddServer.RULES])
        XCTAssertEqual(AddServer.steps("bedrock"), [AddServer.EDITION, AddServer.VERSION, AddServer.DETAILS, AddServer.RULES])
        XCTAssertEqual(AddServer.bedrockType(read)?.id, "bedrock")
        XCTAssertTrue(AddServer.memoryShown(read.types[1]))
        XCTAssertFalse(AddServer.memoryShown(read.types[2]))
        XCTAssertEqual(read.bedrock.privacyUrl, "https://privacy")
    }

    func testTheTableOfKindsComesFromTheAgentsTypes() throws {
        let fabric = try options().types[1]
        let rows = AddServer.rows(s, fabric, technical: false)
        XCTAssertEqual(rows.map(\.0), [s.t("new.col_best_for"), s.t("new.col_content"), s.t("new.col_modrinth"), s.t("new.col_crossplay"), s.t("new.col_ease")])
        XCTAssertEqual(rows.map(\.1), [s.t("types.fabric.best"), s.t("new.content_mods"), s.t("value.yes"), s.t("value.no"), s.t("new.ease_easy")])
        let technical = AddServer.rows(s, fabric, technical: true)
        XCTAssertEqual(technical[5].1, "Fabric Loader")
        XCTAssertEqual(technical[6].1, "fabric.mod.json")
    }

    func testTheNewestFinishedVersionIsPickedFirst() throws {
        let versions = try JSONDecoder().decode(TypeVersions.self, from: Data(#"{"type": "vanilla", "type_name": "Vanilla", "source": "Mojang version list", "versions": [{"minecraft": "25w01a", "stable": false}, {"minecraft": "1.21.4", "latest": true}, {"minecraft": "1.21.3"}]}"#.utf8))
        XCTAssertEqual(AddServer.firstVersion(versions)?.minecraft, "1.21.4")
        XCTAssertEqual(versions.source, "Mojang version list")
        XCTAssertNil(AddServer.firstVersion(TypeVersions()))
    }

    func testTheFolderIsANewOneNamedAfterTheServerInsideTheOnePicked() {
        XCTAssertEqual(AddServer.folderFor("D:\\Minecraft", " Survival "), "D:\\Minecraft\\Survival")
        XCTAssertEqual(AddServer.folderFor("D:\\", "Survival"), "D:\\Survival")
        XCTAssertEqual(AddServer.folderFor("/srv/mc/", "My: world?"), "/srv/mc/My world")
        XCTAssertEqual(AddServer.folderFor("D:\\Minecraft", "  "), "D:\\Minecraft")
    }

    func testCreateWaitsForTheRulesToBeTicked() {
        XCTAssertFalse(AddServer.ready(name: "A", folder: "D:\\A", version: "1.21.4", ruled: false))
        XCTAssertFalse(AddServer.ready(name: "A", folder: "", version: "1.21.4", ruled: true))
        XCTAssertFalse(AddServer.ready(name: "A", folder: "D:\\A", version: nil, ruled: true))
        XCTAssertTrue(AddServer.ready(name: "A", folder: "D:\\A", version: "1.21.4", ruled: true))
        XCTAssertEqual(AddServer.ruleKey("java"), "new.eula_tick")
        XCTAssertEqual(AddServer.ruleKey("bedrock"), "new.bedrock_tick")
    }

    func testACreationStillRunningIsFoundAgainAndTheAgentsWarningsAreSaid() throws {
        let running = Job(id: "j", kind: "server_create", state: "running", step: "Downloading")
        XCTAssertEqual(AddServer.creating([Job(id: "k", kind: "backup", state: "running"), running])?.id, "j")
        XCTAssertNil(AddServer.creating([Job(id: "j", kind: "server_create", state: "succeeded")]))
        let added = try JSONDecoder().decode(ServerAdded.self, from: Data(#"{"ok": true, "server": {"id": "sky", "name": "Skyblock", "state": "OFFLINE"}, "warnings": ["No port is set."]}"#.utf8))
        XCTAssertEqual(AddServer.addedLines(s, added), [s.t("add.added", ["name": "Skyblock"]), "No port is set."])
    }

    func testAddingAndCreatingGoToTheAgentsRoutes() async throws {
        let c = client()
        StubAgent.json(optionsJSON)
        let read = try await c.newServerOptions()
        XCTAssertEqual(read.recommended, "fabric")
        XCTAssertEqual(path(0), "/api/new-server/options")
        StubAgent.json(#"{"ok": true, "server_id": "fresh", "name": "Fresh", "directory": "D:/Fresh", "job_id": "j", "server": {"id": "fresh", "name": "Fresh", "state": "OFFLINE"}}"#)
        let made = try await c.createServer(NewServerRequest(name: "Fresh", directory: "D:/Fresh", type: "fabric", minecraft: "1.21.4", loader: nil, memoryMb: 4096, color: "#F87906", eulaAccepted: true))
        XCTAssertEqual(made.serverId, "fresh")
        XCTAssertEqual(body(1), #"{"color":"#F87906","directory":"D:/Fresh","eula_accepted":true,"memory_mb":4096,"minecraft_version":"1.21.4","name":"Fresh","type":"fabric"}"#)
        StubAgent.json(#"{"ok": true, "server": {"id": "sky", "name": "Sky", "state": "OFFLINE"}, "warnings": []}"#)
        let added = try await c.addServer(name: "Sky", directory: "D:/Sky", type: "paper", jar: "")
        XCTAssertEqual(added.server.id, "sky")
        XCTAssertEqual(body(2), #"{"directory":"D:/Sky","jar":"","name":"Sky","type":"paper"}"#)
        StubAgent.json(#"{"ok": true, "server_id": "pack", "name": "Pack", "directory": "D:/Pack", "job_id": "j", "server": {"id": "pack", "name": "Pack", "state": "OFFLINE"}}"#)
        _ = try await c.modpackServer(token: "abc", name: "Pack", directory: "D:/Pack", memoryMb: nil, color: nil, eulaAccepted: true)
        XCTAssertEqual(path(3), "/api/modpacks/abc/new-server")
        XCTAssertEqual(body(3), #"{"directory":"D:/Pack","eula_accepted":true,"name":"Pack"}"#)
        StubAgent.json(#"{"jobs": []}"#)
        _ = try await c.runningJobs()
        XCTAssertEqual(StubAgent.requests[4].request.url?.query, "running=true")
        // Leaving without making the server: the pack read is thrown away.
        StubAgent.json(#"{"ok": true}"#)
        try await c.forgetModpack(token: "abc")
        XCTAssertEqual(method(5), "DELETE")
        XCTAssertEqual(path(5), "/api/modpacks/abc")
    }
}

