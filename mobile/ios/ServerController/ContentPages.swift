import Core
import Foundation
import Observation

/// A remove waiting for "yes", with what else needs the mod.
struct RemoveAsk: Identifiable {
    let mod: Mod
    let impact: ModImpact

    var id: String { mod.filename }
}

/// The kept versions of one mod, shown to roll back to.
struct VersionsAsk: Identifiable {
    let mod: Mod
    var versions: PageRead<ModVersions>

    var id: String { mod.filename }
}

/// Search results so far, and whether more can be asked for.
struct Found {
    let query: String
    let hits: [ModrinthHit]
    let total: Int?

    var more: Bool { total.map { hits.count < $0 } ?? false }
}

/// A sheet the add-ons screen shows: one at a time.
enum ContentSheet: String, Identifiable {
    case updateAll, project, missing, modpack

    var id: String { rawValue }
}

/// Everything the Mods / Plugins / Packs and Game settings screens show for
/// one server (mirrors ContentPages.kt). Every button is the dashboard's own
/// route with the person's own sign-in, so the agent decides what they may
/// do and explains a refusal.
@MainActor
@Observable
final class ContentPages {
    let serverId: String
    @ObservationIgnored private let client: () -> AgentClient?
    @ObservationIgnored private let noted: (AgentError) -> Void

    init(serverId: String, client: @escaping () -> AgentClient?, noted: @escaping (AgentError) -> Void) {
        self.serverId = serverId
        self.client = client
        self.noted = noted
    }

    /// "toggle:file", "remove:file", "update_all", ... while that button works.
    private(set) var busy: String? = nil
    var said: Said? = nil
    var sheet: ContentSheet? = nil

    // MARK: - Installed

    private(set) var mods = PageRead<ModList>()
    private(set) var history = PageRead<ModHistory>()
    private(set) var dependencies: DependencyReport? = nil
    var removing: RemoveAsk? = nil
    var updating: Mod? = nil
    var versions: VersionsAsk? = nil

    /// The server's state as the list last said; Unknown when it couldn't be read.
    var serverState: String? {
        mods.problem != nil ? States.UNKNOWN : mods.value?.serverState
    }

    func loadMods() async {
        guard let client = client() else { return }
        mods.loading = true
        do {
            mods = PageRead(value: try await client.mods(serverId: serverId))
        } catch let problem as AgentError {
            noted(problem)
            // Never the old list as if current: Unknown until the PC answers.
            mods = PageRead(problem: problem)
            dependencies = nil
            return
        } catch {
            mods.loading = false
            return
        }
        // As the dashboard: the list still shows without these.
        dependencies = try? await client.dependencies(serverId: serverId)
        do {
            history = PageRead(value: try await client.modHistory(serverId: serverId))
        } catch let problem as AgentError {
            history = PageRead(problem: problem)
        } catch {}
    }

    func setEnabled(_ mod: Mod, _ on: Bool, _ strings: Strings) async {
        await work("toggle:\(mod.filename)", strings, reload: loadMods) { client, id in
            _ = try await client.setModEnabled(serverId: id, filename: mod.filename, enabled: on)
            return Said(text: strings.t(on ? "mods.turned_on" : "mods.turned_off", ["name": mod.name]), good: true)
        }
    }

    /// Asks the agent what else needs `mod`; nothing changes yet.
    func askRemove(_ mod: Mod, _ strings: Strings) async {
        await work("remove:\(mod.filename)", strings) { [weak self] client, id in
            self?.removing = RemoveAsk(mod: mod, impact: try await client.modImpact(serverId: id, filename: mod.filename))
            return nil
        }
    }

    func remove(_ ask: RemoveAsk, _ strings: Strings) async {
        removing = nil
        await work("remove:\(ask.mod.filename)", strings, reload: loadMods) { client, id in
            _ = try await client.removeMod(serverId: id, filename: ask.mod.filename)
            return Said(text: strings.t("mods.removed_toast", ["name": ask.mod.name]), good: true)
        }
    }

    func update(_ mod: Mod, _ strings: Strings) async {
        updating = nil
        await work("update:\(mod.filename)", strings, reload: loadMods) { client, id in
            let done = try await client.updateMod(serverId: id, filename: mod.filename, versionId: mod.updateAvailable?.versionId)
            return Said(text: strings.t("mods.updated_toast", ["version": done.updated?.version ?? strings.t("value.unknown")]), good: true)
        }
    }

    func showVersions(_ mod: Mod) async {
        guard let client = client() else { return }
        versions = VersionsAsk(mod: mod, versions: PageRead(loading: true))
        var read = PageRead<ModVersions>()
        do {
            read = PageRead(value: try await client.modVersions(serverId: serverId, modId: mod.modId))
        } catch let problem as AgentError {
            noted(problem)
            read = PageRead(problem: problem)
        } catch {}
        if versions?.mod == mod {
            versions?.versions = read
        }
    }

    func rollBack(_ mod: Mod, _ version: ModVersion, _ strings: Strings) async {
        guard Content.canRollBack(version) else { return }
        versions = nil
        await work("rollback:\(mod.filename)", strings, reload: loadMods) { client, id in
            let done = try await client.rollBackMod(serverId: id, modId: mod.modId, archivePath: version.archivePath)
            let name = done.restored?.version ?? version.version ?? strings.t("value.unknown")
            return Said(text: strings.t("mods.rolled_back", ["version": name]), good: true)
        }
    }

    /// Stop from "Stop the server first"; the list then says whether it stopped.
    func stop(_ strings: Strings) async {
        await work("stop", strings, reload: loadMods) { client, id in
            _ = try await client.serverAction(serverId: id, action: "stop")
            return Said(text: strings.t("mobile.server.done_stop"), good: true)
        }
    }

    /// The server started or stopped: the list says again whether changes work.
    func onStateChanged() {
        guard mods.value != nil, busy == nil else { return }
        Task { await loadMods() }
    }

    // MARK: - Update all

    private(set) var plan: PageRead<UpdateAllPlan>? = nil
    var ticked: Set<String> = []

    /// The live feed's latest word on a task of this server.
    private(set) var task: Job? = nil

    func onTask(_ job: Job) {
        task = job
    }

    /// Asks Modrinth (through the PC) what Update all would change.
    func openUpdateAll() async {
        guard let client = client() else { return }
        plan = PageRead(loading: true)
        sheet = .updateAll
        do {
            let read = try await client.updateAllPlan(serverId: serverId)
            ticked = UpdateAll.ticked(read)
            plan = PageRead(value: read)
        } catch let problem as AgentError {
            noted(problem)
            plan = PageRead(problem: problem)
        } catch {
            plan = nil
        }
    }

    func updateAll(_ strings: Strings) async {
        guard let read = plan?.value else { return }
        let body = UpdateAll.body(read, ticked: ticked)
        sheet = nil
        plan = nil
        task = nil
        await work("update_all", strings, reload: loadMods) { client, id in
            Said(text: UpdateAll.done(strings, try await client.updateAll(serverId: id, body)), good: true)
        }
    }

    /// A sheet closed without its button: nothing it read is kept, and a
    /// modpack read but not imported is forgotten on the PC.
    func sheetClosed() {
        sheet = nil
        plan = nil
        project = nil
        missingPlan = nil
        cancelModpack()
    }

    // MARK: - Modrinth

    private(set) var found: PageRead<Found>? = nil
    private(set) var project: PageRead<ModProject>? = nil
    private(set) var missingPlan: PageRead<DependencyPlan>? = nil
    /// Counts searches, so an answer for an older query is dropped.
    @ObservationIgnored private var searchRead = 0

    func search(_ query: String) async {
        guard let client = client() else { return }
        let q = query.trimmingCharacters(in: .whitespaces)
        guard !q.isEmpty else { return }
        searchRead += 1
        let mine = searchRead
        found = PageRead(loading: true)
        var read = PageRead<Found>()
        do {
            let page = try await client.searchMods(serverId: serverId, query: q)
            read = PageRead(value: Found(query: q, hits: page.hits, total: page.total))
        } catch let problem as AgentError {
            noted(problem)
            read = PageRead(problem: problem)
        } catch {}
        if mine == searchRead { found = read }
    }

    func searchMore() async {
        guard let client = client(), let now = found?.value, now.more, found?.loading != true else { return }
        searchRead += 1
        let mine = searchRead
        found = PageRead(value: now, loading: true)
        var read = PageRead<Found>(value: now)
        do {
            let page = try await client.searchMods(serverId: serverId, query: now.query, offset: now.hits.count)
            let fresh = page.hits.filter { hit in !now.hits.contains { $0.slug == hit.slug } }
            read = PageRead(value: Found(query: now.query, hits: now.hits + fresh, total: page.total))
        } catch let problem as AgentError {
            noted(problem)
            read.problem = problem
        } catch {}
        if mine == searchRead { found = read }
    }

    /// Reads a project's versions that fit this server, for the install question.
    func openProject(_ hit: ModrinthHit) async {
        guard let client = client() else { return }
        project = PageRead(loading: true)
        sheet = .project
        do {
            project = PageRead(value: try await client.modProject(serverId: serverId, slug: hit.slug))
        } catch let problem as AgentError {
            noted(problem)
            project = PageRead(problem: problem)
        } catch {
            project = nil
        }
    }

    func install(withDependencies: Bool, _ strings: Strings) async {
        guard let read = project?.value, let version = Install.latest(read) else { return }
        sheet = nil
        project = nil
        await work("install:\(read.project.slug)", strings, reload: loadMods) { client, id in
            let done = try await client.installMod(serverId: id, slug: read.project.slug, versionId: version.versionId, withDependencies: withDependencies)
            let name = done.installed?.name ?? read.project.title
            let number = done.installed?.version ?? version.versionNumber ?? strings.t("value.unknown")
            return Said(text: strings.t("mobile.content.installed", ["name": name, "version": number]), good: true)
        }
    }

    /// What "Install the missing ones" would download; nothing is yet.
    func planMissing() async {
        guard let client = client() else { return }
        missingPlan = PageRead(loading: true)
        sheet = .missing
        do {
            missingPlan = PageRead(value: try await client.planDependencies(serverId: serverId))
        } catch let problem as AgentError {
            noted(problem)
            missingPlan = PageRead(problem: problem)
        } catch {
            missingPlan = nil
        }
    }

    func installMissing(_ strings: Strings) async {
        sheet = nil
        missingPlan = nil
        await work("missing", strings, reload: loadMods) { client, id in
            let results = try await client.installDependencies(serverId: id).results
            return Said(text: Install.missingDone(strings, results), good: Install.allWorked(results))
        }
    }

    // MARK: - Files

    private(set) var modpack: ModpackInspected? = nil

    func uploadMod(_ file: PickedFile, _ strings: Strings) async {
        defer { try? FileManager.default.removeItem(at: file.url) }
        await work("upload", strings, reload: loadMods) { client, id in
            let done = try await client.uploadMod(serverId: id, file: file)
            return Said(text: strings.t("mobile.content.added", ["name": done.installed?.name ?? file.name]), good: true)
        }
    }

    /// Reads the modpack on the PC; nothing changes until Import.
    func inspectModpack(_ file: PickedFile, _ strings: Strings) async {
        defer { try? FileManager.default.removeItem(at: file.url) }
        await work("modpack", strings) { [weak self] client, id in
            self?.modpack = try await client.inspectModpack(serverId: id, file: file)
            self?.sheet = .modpack
            return nil
        }
    }

    /// No import after all: the PC forgets the pack it read.
    func cancelModpack() {
        guard let token = modpack?.token else { return }
        modpack = nil
        guard let client = client() else { return }
        Task { try? await client.forgetModpack(token: token) }
    }

    func importModpack(_ strings: Strings) async {
        guard let read = modpack else { return }
        sheet = nil
        modpack = nil
        task = nil
        await work("modpack", strings, reload: loadMods) { client, id in
            let done = try await client.importModpack(serverId: id, token: read.token)
            return Said(text: strings.t("mobile.content.modpack_done", ["name": done.name.isEmpty ? read.pack.name : done.name]), good: true)
        }
    }

    // MARK: - Bedrock packs

    private(set) var addons = PageRead<AddonList>()
    /// Set after a pack change while the server runs: "Restart now" shows.
    var restartOffered = false

    func loadAddons() async {
        guard let client = client() else { return }
        addons.loading = true
        do {
            addons = PageRead(value: try await client.addons(serverId: serverId))
        } catch let problem as AgentError {
            noted(problem)
            addons = PageRead(problem: problem)
        } catch {
            addons.loading = false
        }
    }

    func setAddon(_ addon: Addon, _ on: Bool, _ strings: Strings) async {
        await work("pack:\(addon.uuid)", strings, reload: loadAddons) { [weak self] client, id in
            let done = try await client.setAddonEnabled(serverId: id, uuid: addon.uuid, enabled: on)
            self?.restartOffered = done.restartNeeded == true
            return Said(text: strings.t(on ? "addons.turned_on" : "addons.turned_off", ["name": addon.name]), good: true)
        }
    }

    func removeAddon(_ addon: Addon, _ strings: Strings) async {
        await work("pack:\(addon.uuid)", strings, reload: loadAddons) { [weak self] client, id in
            let done = try await client.removeAddon(serverId: id, uuid: addon.uuid)
            self?.restartOffered = done.restartNeeded == true
            return Said(text: strings.t("addons.removed", ["name": addon.name]), good: true)
        }
    }

    func uploadAddon(_ file: PickedFile, _ strings: Strings) async {
        defer { try? FileManager.default.removeItem(at: file.url) }
        await work("upload", strings, reload: loadAddons) { [weak self] client, id in
            let done = try await client.uploadAddon(serverId: id, file: file)
            self?.restartOffered = done.restartNeeded == true
            let names = done.installed.map(\.name).joined(separator: ", ")
            return Said(text: strings.t("addons.installed_done", ["name": names.isEmpty ? file.name : names]), good: true)
        }
    }

    /// Restart now, after a pack change or a game settings save.
    func restart(_ strings: Strings, reload: @escaping () async -> Void) async {
        restartOffered = false
        gameRestart = false
        await work("restart", strings, reload: reload) { client, id in
            _ = try await client.serverAction(serverId: id, action: "restart")
            return Said(text: strings.t("mobile.server.done_restart"), good: true)
        }
    }

    // MARK: - Game settings

    private(set) var game = PageRead<GameSettings>()
    /// What the person typed or picked, by key, as text.
    var edits: [String: String] = [:]
    /// Each refused value's reason, by key, from the last Save.
    private(set) var fieldProblems: [String: String] = [:]
    /// Saved while running: "Restart now" shows next to the words.
    private(set) var gameRestart = false

    func loadGame() async {
        guard let client = client() else { return }
        game.loading = true
        do {
            game = PageRead(value: try await client.gameSettings(serverId: serverId))
            edits = [:]
            fieldProblems = [:]
        } catch let problem as AgentError {
            noted(problem)
            game = PageRead(problem: problem)
        } catch {
            game.loading = false
        }
    }

    func edit(_ key: String, _ value: String) {
        edits[key] = value
        fieldProblems[key] = nil
    }

    /// The value a field shows now: what was typed, else what the file says.
    func shown(_ field: GameSetting) -> String {
        edits[field.key] ?? GameForm.initial(field)
    }

    /// True when Save would send something.
    var gameChanged: Bool {
        guard let settings = game.value else { return false }
        return !GameForm.changed(settings, edits).isEmpty
    }

    func saveGame(_ strings: Strings) async {
        guard let settings = game.value, let client = client(), busy == nil else { return }
        let values = GameForm.changed(settings, edits)
        busy = "game"
        said = nil
        do {
            let done = try await client.saveGameSettings(serverId: serverId, values: values)
            said = Said(text: GameForm.saved(strings, done), good: true)
            gameRestart = done.running && done.nothingChanged != true
            busy = nil
            await loadGame()
        } catch let problem as AgentError {
            noted(problem)
            if case .failed(_, _, _, let problems) = problem, !problems.isEmpty {
                fieldProblems = problems
                said = Said(text: strings.t("mobile.game.fix_marked"), good: false)
            } else {
                said = Said(text: problem.message(strings), good: false)
            }
            busy = nil
        } catch {
            busy = nil
        }
    }

    /// Saves the whole file as typed in Technical mode. A refused value
    /// leaves the file as it was, and its reason is shown.
    func saveGameText(_ text: String, _ strings: Strings) async {
        guard let client = client(), busy == nil else { return }
        busy = "game_text"
        said = nil
        do {
            let done = try await client.saveGameSettingsText(serverId: serverId, text: text)
            said = Said(text: GameForm.saved(strings, done), good: true)
            gameRestart = done.running && done.nothingChanged != true
            busy = nil
            await loadGame()
        } catch let problem as AgentError {
            noted(problem)
            if case .failed(_, _, _, let problems) = problem, !problems.isEmpty {
                said = Said(text: problems.keys.sorted().compactMap { problems[$0] }.joined(separator: " "), good: false)
            } else {
                said = Said(text: problem.message(strings), good: false)
            }
            busy = nil
        } catch {
            busy = nil
        }
    }

    // MARK: - Doing

    /// One button at a time: says what it did (or the agent's reason it
    /// didn't), then reads the screen again.
    private func work(
        _ name: String,
        _ strings: Strings,
        reload: (() async -> Void)? = nil,
        _ call: (AgentClient, String) async throws -> Said?
    ) async {
        guard let client = client(), busy == nil else { return }
        busy = name
        said = nil
        do {
            if let done = try await call(client, serverId) {
                said = done
            }
        } catch let problem as AgentError {
            noted(problem)
            said = Said(text: problem.message(strings), good: false)
        } catch {
            // Reading the picked file on the phone failed: said as such.
            said = Said(text: strings.t("mobile.error.failed", ["reason": error.localizedDescription]), good: false)
        }
        busy = nil
        await reload?()
    }
}
