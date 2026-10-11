import XCTest
@testable import Core

/// Mods, Plugins, Packs and Game settings: the screens' rules, the words,
/// and the agent's answers (mirrors ContentTest.kt).
final class ContentTests: XCTestCase {
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
        let url = StubAgent.requests[index].request.url
        return (url?.path ?? "") + (url?.query.map { "?" + $0 } ?? "")
    }

    private func method(_ index: Int) -> String {
        StubAgent.requests[index].request.httpMethod ?? ""
    }

    private func mod(enabled: Bool = true, status: String = "ok", issues: [ModIssue] = []) -> Mod {
        Mod(filename: "a.jar", modId: "a", name: "Alpha", version: "1.0", enabled: enabled, status: status, issues: issues)
    }

    private func json(_ value: [String: JSONValue]) -> String {
        String(data: (try? AgentClient.encode(value)) ?? Data(), encoding: .utf8) ?? ""
    }

    // MARK: - The screen's words

    func testTheScreenIsNamedForWhatTheServerTypeTakes() {
        let row = ServerRow(id: "s", name: "S")
        XCTAssertNil(Content.kind(nil))
        var mods = row
        mods.content = "mods"
        XCTAssertEqual(Content.kind(mods), .mods)
        var plugins = row
        plugins.content = "plugins"
        XCTAssertEqual(Content.kind(plugins), .plugins)
        var bedrock = row
        bedrock.edition = "bedrock"
        bedrock.capabilities = Capabilities(addons: true)
        XCTAssertEqual(Content.kind(bedrock), .packs)
        XCTAssertEqual(Content.kind(row), ContentKind.none)
        XCTAssertEqual(s.t(ContentKind.mods.titleKey), "Mods")
        XCTAssertEqual(s.t(ContentKind.plugins.titleKey), "Plugins")
        XCTAssertEqual(s.t(ContentKind.packs.titleKey), "Packs")
    }

    func testEachModSaysWhetherItWorksAndWhyNot() {
        let missing = ModIssue(kind: "missing_dependency", severity: "error", detail: "Alpha needs Fabric API, which isn't installed.")
        let version = ModIssue(kind: "version_mismatch", severity: "warn", detail: "Alpha is made for Minecraft 1.20.")
        let note = ModIssue(kind: "unverified", severity: "info", detail: "Checked from the file only.")
        let broken = mod(status: "error", issues: [version, note, missing])
        XCTAssertEqual(Content.status(broken).key, "mods.status_error")
        XCTAssertEqual(Content.status(broken).tone, .danger)
        XCTAssertEqual(Content.problems(broken), [missing.detail, version.detail])
        XCTAssertEqual(Content.status(mod(enabled: false, status: "disabled")).key, "mods.status_off")
        XCTAssertEqual(Content.status(mod(status: "something new")).key, "value.unknown")
    }

    func testANewerVersionAndTechnicalDetailsAreShownAsTheDashboardWordsThem() {
        var newer = mod()
        newer.updateAvailable = ModUpdate(latestVersion: "2.0")
        newer.minecraftRange = ">=1.21"
        XCTAssertEqual(Content.newer(s, newer), "Update: 2.0")
        XCTAssertNil(Content.newer(s, mod()))
        XCTAssertEqual(Content.technical(s, newer), "a · a.jar · For Minecraft >=1.21")
        XCTAssertEqual(Content.change(s, "1.0", "2.0"), "1.0 → 2.0")
        XCTAssertEqual(Content.change(s, nil, "2.0"), "Unknown → 2.0")
    }

    // MARK: - Who may change what, and when

    func testOnlySomeoneAllowedSeesChangeButtonsAndTheyWorkOnlyWhileStopped() {
        XCTAssertEqual(Content.changes(canManage: false, serverState: States.OFFLINE), .notAllowed)
        XCTAssertEqual(Content.changes(canManage: true, serverState: States.OFFLINE), .ready)
        XCTAssertEqual(Content.changes(canManage: true, serverState: States.CRASHED), .ready)
        for state in [States.ONLINE, States.STARTING, States.STOPPING, States.RESTART_PENDING] {
            XCTAssertEqual(Content.changes(canManage: true, serverState: state), .stopFirst, state)
        }
        // A state not known is never taken to be stopped.
        XCTAssertEqual(Content.changes(canManage: true, serverState: nil), .unknown)
        XCTAssertEqual(Content.changes(canManage: true, serverState: States.UNKNOWN), .unknown)
        // Bedrock packs change while running too (a restart is offered after).
        XCTAssertEqual(Content.packChanges(canManage: true), .ready)
        XCTAssertEqual(Content.packChanges(canManage: false), .notAllowed)
        // "Stop the server first" offers Stop only while it would work.
        XCTAssertTrue(Content.canStopHere(States.ONLINE, canControl: true))
        XCTAssertFalse(Content.canStopHere(States.ONLINE, canControl: false))
        XCTAssertFalse(Content.canStopHere(States.STOPPING, canControl: true))
    }

    func testOnlyAKeptVersionThatIsThereAndNotInUseCanBeRolledBackTo() {
        let kept = ModVersion(version: "1.0", archivePath: "p", exists: true)
        XCTAssertTrue(Content.canRollBack(kept))
        var current = kept
        current.isCurrent = true
        XCTAssertFalse(Content.canRollBack(current))
        var gone = kept
        gone.exists = false
        XCTAssertFalse(Content.canRollBack(gone))
    }

    func testHistoryRowsSayWhatHappenedInWords() {
        let row = ModHistoryRow(ts: 1, user: "admin", action: "rollback", modName: "Alpha", result: "ok")
        XCTAssertEqual(Content.action(s, row), "Rolled back")
        XCTAssertEqual(Content.action(s, ModHistoryRow(action: "something_new")), "something_new")
        XCTAssertEqual(Content.historyTone(ModHistoryRow(result: "failed")), .danger)
        XCTAssertEqual(Content.historyName(s, ModHistoryRow(action: "update_all", detail: "Alpha, Beta")), "Alpha, Beta")
    }

    func testOnlyTheFilesEachScreenTakesAreSent() {
        XCTAssertTrue(Content.accepts(.mods, "Sodium-0.6.JAR"))
        XCTAssertFalse(Content.accepts(.mods, "pack.mcpack"))
        XCTAssertTrue(Content.accepts(.packs, "skins.mcaddon"))
        XCTAssertFalse(Content.accepts(.packs, "mod.jar"))
        XCTAssertTrue(Content.accepts(.mods, "Pack 1.2.mrpack", modpack: true))
    }

    func testMissingDependenciesAreTheRequiredModsThatArentThere() {
        let report = DependencyReport(items: [
            DependencyItem(modId: "fabric-api", kind: "required", status: "missing"),
            DependencyItem(modId: "minecraft", kind: "required", platform: true, status: "platform_incompatible"),
            DependencyItem(modId: "modmenu", kind: "optional", status: "missing"),
            DependencyItem(modId: "cloth", kind: "required", status: "satisfied"),
        ])
        XCTAssertEqual(Content.missing(report).map(\.modId), ["fabric-api"])
        XCTAssertEqual(Content.missing(nil), [])
    }

    // MARK: - Modrinth

    func testTheInstallConfirmationListsVersionSizeLicenceAndSides() {
        let project = ModProject(
            project: ModrinthProject(slug: "sodium", title: "Sodium", license: "LGPL-3.0", serverSide: "unsupported", clientSide: "required"),
            versions: [
                ModrinthVersion(
                    versionId: "v1", versionNumber: "0.6.0", gameVersions: ["1.21.1"],
                    dependencies: [ModrinthDependency(projectId: "P1", type: "required"), ModrinthDependency(projectId: "P2", type: "optional")],
                    file: ModrinthFile(filename: "sodium.jar", size: 2048)
                ),
            ]
        )
        let version = Install.latest(project)!
        XCTAssertEqual(Install.required(version).map(\.projectId), ["P1"])
        XCTAssertEqual(Install.facts(s, project, version), [
            "Sodium 0.6.0", "Size: 2.0 KB", "For Minecraft 1.21.1", "Licence: LGPL-3.0",
            "Needed on the server: No", "Needed in the game: Yes",
        ])
        XCTAssertEqual(Install.downloads(s, 1_234_567), "1.2M downloads")
        XCTAssertEqual(Install.downloads(s, nil), "Unknown")
        XCTAssertEqual(Install.page("https://modrinth.com/mod/sodium")?.absoluteString, "https://modrinth.com/mod/sodium")
        XCTAssertNil(Install.page("https://example.com/mod/sodium"))
    }

    func testTheMissingOnesSayWhatHappenedToEachInTheAgentsThreeAnswers() {
        let results = [
            DependencyResult(title: "Fabric API", result: "installed"),
            DependencyResult(title: "Cloth", result: "skipped", detail: "Already installed"),
            DependencyResult(title: "Iris", result: "failed", detail: "Modrinth stopped answering."),
        ]
        XCTAssertEqual(
            Install.missingDone(s, results),
            "Done: Fabric API (Worked), Cloth (Already there), Iris (Failed: Modrinth stopped answering.)"
        )
        XCTAssertFalse(Install.allWorked(results))
        XCTAssertTrue(Install.allWorked(Array(results.prefix(2))))
    }

    // MARK: - Update all

    private let plan = UpdateAllPlan(updates: [
        UpdateAllRow(modId: "a", name: "Alpha", filename: "a.jar", enabled: true, installedVersion: "1.0", latestVersion: "2.0", versionId: "va"),
        UpdateAllRow(modId: "b", name: "Beta", filename: "b.jar.disabled", enabled: false, installedVersion: "1.0", latestVersion: "1.1", versionId: "vb"),
        UpdateAllRow(modId: "c", name: "Gamma", filename: "c.jar", enabled: true, installedVersion: "3", latestVersion: "4", versionId: nil),
    ])

    func testUpdateAllTicksTheOnesThatAreOnAndLeavesTurnedOffOnesForThePerson() throws {
        XCTAssertEqual(UpdateAll.ticked(plan), ["a.jar", "c.jar"])
        let body = String(data: try AgentClient.encode(UpdateAll.body(plan, ticked: ["c.jar", "b.jar.disabled"])), encoding: .utf8)
        XCTAssertEqual(body, #"{"mods":[{"filename":"b.jar.disabled","version_id":"vb"},{"filename":"c.jar","version_id":null}]}"#)
        var newer = mod()
        newer.updateAvailable = ModUpdate(latestVersion: "2.0")
        XCTAssertTrue(UpdateAll.offered(ModList(mods: [newer])))
        XCTAssertFalse(UpdateAll.offered(ModList(mods: [mod()])))
        XCTAssertFalse(UpdateAll.offered(nil))
    }

    func testUpdateAllSaysWhyItCantStartAndWhatItDid() {
        var running = plan
        running.serverRunning = true
        XCTAssertEqual(UpdateAll.blocked(s, running), s.t("mobile.content.stop_first"))
        var busy = plan
        busy.blockedBy = "Backing up"
        XCTAssertEqual(UpdateAll.blocked(s, busy), "Wait for Backing up to finish first.")
        XCTAssertNil(UpdateAll.blocked(s, plan))
        let done = UpdateAllResult(updated: [UpdateAllDone(name: "Alpha", previousVersion: "1.0", version: "2.0")], safetyBackup: SafetyBackup(name: "before-update-all.zip"))
        XCTAssertEqual(UpdateAll.done(s, done), "Updated 1. The backup made first is before-update-all.zip.")
        let job = Job(id: "j", kind: "mods", state: "running", step: "Updating Alpha (1 of 2)", serverId: "s")
        XCTAssertEqual(UpdateAll.progress(job, serverId: "s"), "Updating Alpha (1 of 2)")
        XCTAssertNil(UpdateAll.progress(job, serverId: "other"))
        var finished = job
        finished.state = "succeeded"
        XCTAssertNil(UpdateAll.progress(finished, serverId: "s"))
    }

    // MARK: - Modpacks

    func testAModpackImportListsItsStepsWithTheVersionChangeOnlyWhenNeeded() {
        let inspected = ModpackInspected(
            token: "t",
            pack: Modpack(name: "Pack", minecraftVersion: "1.21.1", typeName: "Fabric", downloadCount: 3, canImport: true),
            versionChange: true
        )
        let steps = Modpacks.steps(s, inspected)
        XCTAssertEqual(steps.count, 5)
        XCTAssertEqual(steps[2], s.t("pack.step_version", ["type": "Fabric", "version": "1.21.1"]))
        var same = inspected
        same.versionChange = false
        XCTAssertEqual(Modpacks.steps(s, same).count, 4)
        XCTAssertEqual(Modpacks.fileStatus(ModpackFile(status: "client_only")).key, "pack.status_client")
        XCTAssertEqual(Modpacks.fileStatus(ModpackFile(status: "refused")).tone, .danger)
    }

    // MARK: - Game settings

    private func setting(_ key: String, _ kind: String, _ value: JSONValue?, set: Bool? = nil, fallback: String = "", readOnly: String? = nil) -> GameSetting {
        GameSetting(key: key, kind: kind, value: value, set: set ?? (value != nil), minecraftDefault: fallback, readOnly: readOnly)
    }

    private var settings: GameSettings {
        GameSettings(exists: true, fields: [
            setting("difficulty", "choice", nil, fallback: "easy"),
            setting("max-players", "int", .number(20), fallback: "20"),
            setting("pvp", "bool", .bool(true), fallback: "true"),
            setting("white-list", "bool", nil, fallback: "false"),
            setting("motd", "text", .string("Hi"), fallback: "A Minecraft Server"),
            setting("level-seed", "seed", .string("123"), fallback: "", readOnly: "world_exists"),
            setting("server-port", "port", .number(25565), fallback: "25565"),
        ])
    }

    func testGameSettingsAreGroupedAsOnThePCWithEachFieldsHint() {
        let groups = GameForm.groups(settings)
        XCTAssertEqual(groups.map(\.titleKey), ["game.group_play", "game.group_who", "game.group_world"])
        XCTAssertEqual(groups[0].fields.map(\.key), ["difficulty", "pvp"])
        XCTAssertEqual(groups[1].fields.map(\.key), ["motd", "max-players", "white-list"])
        let difficulty = settings.fields[0]
        XCTAssertEqual(GameForm.initial(difficulty), "easy")
        XCTAssertEqual(GameForm.choiceLabel(s, "easy"), "Easy")
        XCTAssertEqual(GameForm.hint(s, difficulty), s.t("game.difficulty_hint") + " " + s.t("game.not_set", ["value": "Easy"]))
        XCTAssertEqual(GameForm.initial(settings.fields[2]), "true")
        XCTAssertEqual(GameForm.initial(settings.fields[3]), "false")
        XCTAssertEqual(GameForm.initial(settings.fields[1]), "20")
        // A value the file has but Minecraft won't take starts from the default.
        var bad = setting("view-distance", "int", nil, set: true, fallback: "10")
        bad.problem = "not a number"
        XCTAssertEqual(GameForm.initial(bad), "10")
        XCTAssertTrue(GameForm.fileProblem(s, bad)?.hasSuffix("not a number") == true)
        XCTAssertEqual(GameForm.label(s, setting("allow-list", "bool", nil)), "Allowlist")
    }

    func testTheSeedIsLockedOnceTheWorldExistsAndEverythingForSomeoneWhoMayNotEdit() {
        let seed = settings.fields.first { $0.key == "level-seed" }!
        XCTAssertTrue(GameForm.locked(seed, canEdit: true))
        XCTAssertEqual(GameForm.hint(s, seed), s.t("game.seed_locked"))
        XCTAssertFalse(GameForm.locked(settings.fields[0], canEdit: true))
        XCTAssertTrue(GameForm.locked(settings.fields[0], canEdit: false))
    }

    func testSaveSendsOnlyWhatChangedTypedAsTheAgentTakesIt() {
        let edits = [
            "difficulty": "hard", "max-players": "20", "pvp": "false", "motd": "Hi",
            "level-seed": "999", "server-port": "25570", "white-list": "false",
        ]
        XCTAssertEqual(json(GameForm.changed(settings, edits)), #"{"difficulty":"hard","pvp":false,"server-port":25570}"#)
        XCTAssertEqual(GameForm.changed(settings, [:]), [:])
        XCTAssertEqual(json(GameForm.changed(settings, ["max-players": "lots"])), #"{"max-players":"lots"}"#)
        XCTAssertEqual(GameForm.saved(s, GameSettingsSaved(keys: ["pvp"], running: true)), s.t("game.saved_running"))
        XCTAssertEqual(GameForm.saved(s, GameSettingsSaved(nothingChanged: true)), s.t("settings.nothing_changed"))
    }

    // MARK: - Icons

    func testAnIconFromAnywhereButModrinthsOwnAddressIsNeverLoaded() async {
        let icons = IconCache(directory: nil)
        XCTAssertTrue(icons.allowed("https://cdn.modrinth.com/data/abc/icon.png"))
        XCTAssertFalse(icons.allowed("http://cdn.modrinth.com/data/abc/icon.png"))
        XCTAssertFalse(icons.allowed("https://evil.example/icon.png"))
        let evil = await icons.load("https://evil.example/icon.png")
        XCTAssertNil(evil)
        let none = await icons.load(nil)
        XCTAssertNil(none)
    }

    func testAnIconIsLoadedOnceThenKept() async {
        let icons = IconCache(directory: nil, configuration: StubAgent.configuration(), hosts: ["localhost"], httpsOnly: false)
        StubAgent.enqueue(StubAgent.Answer(status: 200, headers: ["Content-Type": "image/png", "Cache-Control": "max-age=86400"], body: Data([1, 2, 3])))
        let first = await icons.load("http://localhost/data/abc/icon.png")
        let second = await icons.load("http://localhost/data/abc/icon.png")
        XCTAssertEqual(first, Data([1, 2, 3]))
        XCTAssertEqual(second, Data([1, 2, 3]))
        XCTAssertEqual(StubAgent.requests.count, 1)
    }

    func testAnIconTooBigIsNotLoaded() async {
        let icons = IconCache(directory: nil, configuration: StubAgent.configuration(), hosts: ["localhost"], httpsOnly: false)
        StubAgent.enqueue(StubAgent.Answer(status: 200, headers: ["Content-Type": "image/png"], body: Data(count: IconCache.MAX_ICON_BYTES + 1)))
        let huge = await icons.load("http://localhost/data/abc/huge.png")
        XCTAssertNil(huge)
    }

    // MARK: - The agent

    func testTheInstalledListUpdateAllAndHistoryAreRead() async throws {
        let c = client()
        StubAgent.json(#"{"mods": [{"filename": "a.jar", "path": "C:\\s\\mods\\a.jar", "mod_id": "a", "name": "Alpha", "version": "1.0", "enabled": true, "status": "warn", "issues": [{"kind": "version_mismatch", "severity": "warn", "detail": "Made for 1.20"}], "has_history": true, "update_available": {"mod_id": "a", "latest_version": "2.0", "version_id": "va"}}], "problems": [], "minecraft_version": null, "server_state": "OFFLINE", "updates_checked_at": null}"#)
        let list = try await c.mods(serverId: "s")
        XCTAssertEqual(list.mods.first?.updateAvailable?.latestVersion, "2.0")
        XCTAssertNil(list.minecraftVersion)
        XCTAssertEqual(path(0), "/api/servers/s/mods")

        StubAgent.json(#"{"updates": [{"mod_id": "b", "name": "Beta", "filename": "b.jar.disabled", "enabled": false, "installed_version": "1.0", "latest_version": "1.1", "version_id": "vb", "project": "beta"}], "unchecked": [{"mod_id": "c", "name": "Gamma", "filename": "c.jar", "reason": "Modrinth didn't answer."}], "server_running": false, "blocked_by": null, "checked_at": 5.0}"#)
        let plan = try await c.updateAllPlan(serverId: "s")
        XCTAssertEqual(plan.updates.first?.enabled, false)
        XCTAssertEqual(plan.unchecked.first?.reason, "Modrinth didn't answer.")

        StubAgent.json(#"{"ok": true, "job_id": "j", "updated": [{"mod_id": "b", "name": "Beta", "filename": "b-1.1.jar.disabled", "previous_version": "1.0", "version": "1.1"}], "safety_backup": {"id": 3, "name": "before-update-all.zip"}, "undo": {"kind": "restore_backup", "backup_id": 3, "backup": "before-update-all.zip"}}"#)
        let done = try await c.updateAll(serverId: "s", UpdateAll.body(plan, ticked: ["b.jar.disabled"]))
        XCTAssertEqual(done.updated.first?.version, "1.1")
        XCTAssertEqual(done.safetyBackup?.name, "before-update-all.zip")
        XCTAssertEqual(method(2), "POST")
        XCTAssertEqual(path(2), "/api/servers/s/mods/update-all")
        XCTAssertEqual(body(2), #"{"mods":[{"filename":"b.jar.disabled","version_id":"vb"}]}"#)

        StubAgent.json(#"{"history": [{"id": 9, "server_id": "s", "ts": 10.0, "user": "admin", "action": "update_all", "mod_id": null, "mod_name": null, "old_version": null, "new_version": null, "source": null, "sha256": null, "result": "failed", "detail": "Updating Beta failed"}]}"#)
        let history = try await c.modHistory(serverId: "s")
        XCTAssertEqual(history.history.first?.result, "failed")
        XCTAssertEqual(path(3), "/api/servers/s/mods/history?limit=100")
    }

    func testTurningOnRemovingRollingBackAndInstallingSendWhatTheDashboardSends() async throws {
        let c = client()
        StubAgent.json(#"{"ok": true, "mod": {"filename": "a.jar.disabled", "mod_id": "a", "name": "Alpha", "version": "1.0", "enabled": false}, "changed": true}"#)
        let off = try await c.setModEnabled(serverId: "s", filename: "a.jar", enabled: false)
        XCTAssertEqual(off.mod?.enabled, false)
        XCTAssertEqual(path(0), "/api/servers/s/mods/disable")
        XCTAssertEqual(body(0), #"{"filename":"a.jar"}"#)

        StubAgent.json(#"{"mod": {}, "dependents": [{"name": "Beta", "mod_id": "b", "filename": "b.jar", "requires": ">=1.0"}], "warning": "Beta needs it."}"#)
        let impact = try await c.modImpact(serverId: "s", filename: "my mod.jar")
        XCTAssertEqual(impact.dependents.first?.name, "Beta")
        XCTAssertEqual(StubAgent.requests[1].request.url?.absoluteString.hasSuffix("/api/servers/s/mods/impact?filename=my%20mod.jar"), true)

        StubAgent.json(#"{"versions": [{"id": 1, "version": "1.0", "filename": "a.jar", "archive_path": "C:\\kept\\a.jar", "created_at": 3.0, "is_current": false, "exists": true}]}"#)
        let kept = try await c.modVersions(serverId: "s", modId: "a").versions[0]
        StubAgent.json(#"{"ok": true, "restored": {"filename": "a.jar", "name": "Alpha", "version": "1.0"}, "previous_version": "2.0"}"#)
        let back = try await c.rollBackMod(serverId: "s", modId: "a", archivePath: kept.archivePath)
        XCTAssertEqual(back.previousVersion, "2.0")
        XCTAssertEqual(body(3), #"{"archive_path":"C:\\kept\\a.jar","mod_id":"a"}"#)

        StubAgent.json(#"{"hits": [{"project_id": "P", "slug": "sodium", "title": "Sodium", "description": "Fast", "downloads": 5, "icon_url": "https://cdn.modrinth.com/i.png", "page": "https://modrinth.com/mod/sodium"}], "total": 1, "offset": 0}"#)
        let found = try await c.searchMods(serverId: "s", query: "so dium")
        XCTAssertEqual(found.hits.first?.iconUrl, "https://cdn.modrinth.com/i.png")
        XCTAssertEqual(StubAgent.requests[4].request.url?.absoluteString.hasSuffix("/api/servers/s/mods/search?q=so%20dium&limit=20&offset=0"), true)

        StubAgent.json(#"{"ok": true, "installed": {"filename": "sodium.jar", "name": "Sodium", "version": "0.6"}, "dependencies_required": [{"mod_id": "fabric-api", "title": "Fabric API", "installed": false}], "dependencies_installed": []}"#)
        let installed = try await c.installMod(serverId: "s", slug: "sodium", versionId: "v1", withDependencies: false)
        XCTAssertEqual(installed.dependenciesRequired.first?.title, "Fabric API")
        XCTAssertEqual(body(5), #"{"install_dependencies":false,"project":"sodium","version_id":"v1"}"#)

        StubAgent.json(#"{"items": [], "unresolvable": [{"mod_id": "x", "name": "X", "required_by": ["Alpha"], "reason": "Not found on Modrinth. Install it manually.", "page": null}], "skipped": [], "minecraft_version": "1.21.1"}"#)
        let missing = try await c.planDependencies(serverId: "s")
        XCTAssertEqual(missing.unresolvable.first?.name, "X")
        XCTAssertEqual(path(6), "/api/servers/s/mods/dependencies/plan")
    }

    func testAFilePickedOnThePhoneIsSentAsAnUploadForm() async throws {
        let c = client()
        let jar = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".jar")
        try Data([80, 75, 3, 4]).write(to: jar)
        defer { try? FileManager.default.removeItem(at: jar) }
        StubAgent.json(#"{"ok": true, "installed": {"filename": "e.jar", "name": "Epsilon", "version": "3.0"}}"#)
        let added = try await c.uploadMod(serverId: "s", file: PickedFile(name: "e.jar", url: jar))
        XCTAssertEqual(added.installed?.name, "Epsilon")
        XCTAssertEqual(path(0), "/api/servers/s/mods/upload")
        let type = StubAgent.requests[0].request.value(forHTTPHeaderField: "Content-Type") ?? ""
        XCTAssertTrue(type.hasPrefix("multipart/form-data; boundary="), type)

        StubAgent.json(#"{"token": "tok", "pack": {"name": "Pack", "version": "1.2", "summary": null, "minecraft_version": "1.21.1", "type": "fabric", "type_name": "Fabric", "loader_version": "0.16.5", "files": [{"name": "lithium.jar", "path": "mods/lithium.jar", "size": 10, "status": "download", "reason": null, "env_server": "required"}], "download_count": 1, "download_bytes": 10, "client_only": [], "refused": [], "overrides": 0, "overrides_bytes": 0, "skipped_overrides": [], "problems": [], "can_import": true}, "into": {"version_change": false, "running": false}}"#)
        let pack = try await c.inspectModpack(serverId: "s", file: PickedFile(name: "p.mrpack", url: jar))
        XCTAssertEqual(pack.token, "tok")
        XCTAssertFalse(pack.versionChange)
        XCTAssertEqual(path(1), "/api/modpacks/inspect?server_id=s")
        StubAgent.json(#"{"ok": true, "job_id": "j", "modpack": {"name": "Pack"}, "version_change": false, "undo": null}"#)
        let imported = try await c.importModpack(serverId: "s", token: "tok")
        XCTAssertEqual(imported.name, "Pack")
        XCTAssertEqual(body(2), #"{"confirm":true,"token":"tok"}"#)
    }

    func testTheUploadFormHoldsTheFileUnderTheFieldTheAgentReads() throws {
        let jar = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".jar")
        let form = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".form")
        try Data("PK-bytes".utf8).write(to: jar)
        defer {
            try? FileManager.default.removeItem(at: jar)
            try? FileManager.default.removeItem(at: form)
        }
        try AgentClient.writeForm(PickedFile(name: "e\".jar", url: jar), boundary: "B", to: form)
        let text = String(data: try Data(contentsOf: form), encoding: .utf8) ?? ""
        XCTAssertEqual(
            text,
            "--B\r\nContent-Disposition: form-data; name=\"file\"; filename=\"e_.jar\"\r\nContent-Type: application/octet-stream\r\n\r\nPK-bytes\r\n--B--\r\n"
        )
    }

    func testBedrockPacksAndGameSettingsAreReadAndSaved() async throws {
        let c = client()
        StubAgent.json(#"{"addons": [{"uuid": "u1", "version": "1.0.0", "name": "Skins", "description": null, "kind": "resource", "folder": "resource_packs/skins", "enabled": true}], "world": "Bedrock level", "running": true, "restart_needed": true}"#)
        let packs = try await c.addons(serverId: "s")
        XCTAssertEqual(packs.world, "Bedrock level")
        XCTAssertEqual(Content.packKind(packs.addons[0]), "addons.kind_resource")
        StubAgent.json(#"{"ok": true, "installed": [], "restart_needed": true}"#)
        let toggled = try await c.setAddonEnabled(serverId: "s", uuid: "u1", enabled: false)
        XCTAssertEqual(toggled.restartNeeded, true)
        XCTAssertEqual(method(1), "PUT")
        XCTAssertEqual(body(1), #"{"enabled":false}"#)

        StubAgent.json(#"{"file": "C:\\s\\server.properties", "exists": true, "modified_at": 1.0, "world_exists": true, "world_folder": "world", "fields": [{"key": "max-players", "kind": "int", "value": 20, "raw": "20", "set": true, "problem": null, "minecraft_default": "20", "choices": [], "min": 1, "max": 10000, "max_length": 200, "read_only": null}], "text": "", "running": false, "restart_needed": false}"#)
        let game = try await c.gameSettings(serverId: "s")
        XCTAssertEqual(GameForm.initial(game.fields[0]), "20")
        StubAgent.json(#"{"detail": "Some values can't be used.", "problems": {"server-port": "Another program is using port 80."}}"#, status: 400)
        do {
            _ = try await c.saveGameSettings(serverId: "s", values: ["server-port": .number(80)])
            XCTFail("A refused port was saved")
        } catch AgentError.failed(_, _, _, let problems) {
            XCTAssertEqual(problems["server-port"], "Another program is using port 80.")
        }
        XCTAssertEqual(method(3), "PUT")
        XCTAssertEqual(body(3), #"{"values":{"server-port":80}}"#)
    }
}
