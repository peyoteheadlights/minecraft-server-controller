import Core
import Foundation
import Observation

/// Everything the Server settings screen shows for one server: how Command
/// Block runs it (mirrors SetupPages.kt). Each button is the dashboard's
/// own route with the person's own sign-in, so the agent decides and
/// explains a refusal. `listChanged` reloads All servers after a rename or
/// a new color.
@MainActor
@Observable
final class SetupPages {
    let serverId: String
    @ObservationIgnored private let client: () -> AgentClient?
    @ObservationIgnored private let noted: (AgentError) -> Void
    @ObservationIgnored private let listChanged: () async -> Void

    init(serverId: String, client: @escaping () -> AgentClient?, noted: @escaping (AgentError) -> Void,
         listChanged: @escaping () async -> Void) {
        self.serverId = serverId
        self.client = client
        self.noted = noted
        self.listChanged = listChanged
    }

    private(set) var busy: String? = nil
    var said: Said? = nil

    // MARK: - Server settings

    private(set) var settings = PageRead<ServerSettings>()
    /// What the person typed or switched, by key, as text.
    private(set) var edits: [String: String] = [:]
    /// Each refused value's reason, by key, from the last Save.
    private(set) var fieldProblems: [String: String] = [:]
    /// The color picked or typed; nil while it is the saved one.
    private(set) var color: String? = nil

    func loadSettings() async {
        guard let client = client() else { return }
        settings.loading = true
        do {
            settings = PageRead(value: try await client.serverSettings(serverId: serverId))
            edits = [:]
            fieldProblems = [:]
            color = nil
        } catch let problem as AgentError {
            noted(problem)
            settings = PageRead(value: settings.value, problem: problem)
        } catch {
            settings.loading = false
        }
    }

    func edit(_ key: String, _ value: String) {
        edits[key] = value
        fieldProblems[key] = nil
    }

    /// The value a field shows now: what was typed, else what the agent has.
    func shown(_ key: String) -> String {
        guard let settings = settings.value else { return edits[key] ?? "" }
        return edits[key] ?? ServerForm.initial(settings, key)
    }

    func pickColor(_ hex: String) {
        color = hex
    }

    /// Saves what changed: the settings, then the color. Nothing changed
    /// says so; a refused value says why under its field.
    func saveSettings(_ strings: Strings) async {
        guard let current = settings.value, let client = client(), busy == nil else { return }
        let updates = ServerForm.changed(current, edits)
        let newColor = color.flatMap { $0.caseInsensitiveCompare(current.color ?? "") == .orderedSame ? nil : $0 }
        if updates.isEmpty && newColor == nil {
            said = Said(text: ServerForm.saved(strings, sent: false, result: nil), good: true)
            return
        }
        busy = "settings"
        said = nil
        defer { busy = nil }
        do {
            var result: ServerSettingsSaved? = nil
            if !updates.isEmpty { result = try await client.saveServerSettings(serverId: serverId, updates: updates) }
            if let newColor { _ = try await client.setColor(serverId: serverId, color: newColor) }
            let refused = result?.rejected ?? [:]
            said = Said(text: ServerForm.saved(strings, sent: true, result: result), good: refused.isEmpty)
            if newColor != nil || result?.applied[ServerForm.NAME] != nil { await listChanged() }
            settings = PageRead(value: try await client.serverSettings(serverId: serverId))
            color = nil
            // The refused values stay as typed, each with its reason.
            edits = edits.filter { refused[$0.key] != nil }
            fieldProblems = refused
        } catch let problem as AgentError {
            noted(problem)
            said = Said(text: problem.message(strings), good: false)
        } catch {}
    }

    // MARK: - CPU cores

    /// Every core ticked; nil while it is the saved setting.
    private(set) var allCores: Bool? = nil
    /// The cores ticked; nil while they are the saved ones.
    private(set) var cores: Set<Int>? = nil

    var everyCore: Bool { allCores ?? (settings.value?.cpu.status.configured ?? []).isEmpty }

    var pickedCores: Set<Int> { cores ?? Set(settings.value?.cpu.status.configured ?? []) }

    func setAllCores(_ on: Bool) {
        allCores = on
        if on { cores = [] }
    }

    func toggleCore(_ core: Int) {
        allCores = false
        var now = pickedCores
        if now.contains(core) { now.remove(core) } else { now.insert(core) }
        cores = now
    }

    func pickHalf(_ count: Int) {
        allCores = false
        cores = CpuCores.half(count)
    }

    func saveCores(_ strings: Strings) async {
        guard let client = client(), busy == nil else { return }
        guard let chosen = CpuCores.toSave(all: everyCore, picked: pickedCores) else {
            said = Said(text: strings.t("serverset.pick_a_core"), good: false)
            return
        }
        busy = "cores"
        said = nil
        defer { busy = nil }
        do {
            let result = try await client.saveServerSettings(serverId: serverId, updates: CpuCores.update(chosen))
            if let refused = result.rejected["server.cpu_cores"] {
                said = Said(text: refused, good: false)
                return
            }
            said = Said(text: CpuCores.saved(strings, result), good: result.cpuCores?.ok != false)
            settings = PageRead(value: try await client.serverSettings(serverId: serverId))
            allCores = nil
            cores = nil
        } catch let problem as AgentError {
            noted(problem)
            said = Said(text: problem.message(strings), good: false)
        } catch {}
    }

    // MARK: - Memory

    private(set) var memory = PageRead<MemoryOverview>()
    /// The slider's position; nil while it is the saved limit.
    private(set) var memoryChoice: Int? = nil

    func loadMemory() async {
        guard let client = client() else { return }
        memory.loading = true
        do {
            memory = PageRead(value: try await client.memory(serverId: serverId))
            memoryChoice = nil
        } catch let problem as AgentError {
            noted(problem)
            memory = PageRead(problem: problem)
        } catch {
            memory.loading = false
        }
    }

    func slideMemory(_ mb: Double) {
        guard let current = memory.value else { return }
        memoryChoice = Memory.snap(current, mb)
    }

    func saveMemory(_ strings: Strings) async {
        guard let current = memory.value, let client = client(), busy == nil else { return }
        let mb = memoryChoice ?? Memory.start(current)
        if mb == current.limitMb {
            said = Said(text: strings.t("settings.nothing_changed"), good: true)
            return
        }
        busy = "memory"
        said = nil
        defer { busy = nil }
        do {
            let done = try await client.setMemory(serverId: serverId, mb: mb)
            memory = PageRead(value: done)
            memoryChoice = nil
            said = Said(text: strings.t(done.running ? "memory.saved_running" : "memory.saved"), good: true)
        } catch let problem as AgentError {
            noted(problem)
            said = Said(text: problem.message(strings), good: false)
        } catch {}
    }

    // MARK: - Version and type

    private(set) var version = PageRead<ServerVersion>()
    /// This edition's kinds, read when the changer is opened.
    private(set) var types: [ServerTypeInfo] = []
    private(set) var versions = PageRead<TypeVersions>()
    private(set) var pickedType: String? = nil
    private(set) var pickedVersion: String? = nil
    private(set) var pickedLoader: String? = nil
    var snapshots = false
    /// The check's report for the picked version; the change needs one.
    private(set) var report: PageRead<VersionPreflight>? = nil
    /// A version change or roll back running now, from the live feed or
    /// found again when the screen opens.
    private(set) var task: Job? = nil

    func loadVersion() async {
        guard let client = client() else { return }
        version.loading = true
        do {
            version = PageRead(value: try await client.serverVersion(serverId: serverId))
        } catch let problem as AgentError {
            noted(problem)
            version = PageRead(problem: problem)
        } catch {
            version.loading = false
        }
        // Left while it ran: its progress is shown again.
        if busy == nil, let jobs = try? await client.jobs(serverId: serverId, limit: 10) {
            task = VersionChange.running(jobs.jobs, serverId: serverId)
        }
    }

    func onTask(_ job: Job) {
        guard VersionChange.KINDS.contains(job.kind), job.serverId == serverId else { return }
        task = job.state == "running" ? job : nil
        if job.state != "running" && busy == nil {
            Task { await loadVersion() }
        }
    }

    /// Opens the changer: this edition's kinds and the current kind's versions.
    func openChanger() async {
        guard let client = client(), let current = version.value else { return }
        if pickedType == nil { await pickType(current.type) }
        do {
            types = VersionChange.sameEdition(try await client.serverTypes().types, current)
        } catch let problem as AgentError {
            noted(problem)
        } catch {}
    }

    func pickType(_ id: String) async {
        guard let client = client() else { return }
        pickedType = id
        pickedVersion = nil
        pickedLoader = nil
        report = nil
        versions = PageRead(loading: true)
        do {
            let read = try await client.typeVersions(typeId: id)
            pickedVersion = read.latestStable ?? read.versions.first?.minecraft
            pickedLoader = read.versions.first { $0.minecraft == pickedVersion }?.loaders.first
            versions = PageRead(value: read)
        } catch let problem as AgentError {
            noted(problem)
            versions = PageRead(problem: problem)
        } catch {
            versions.loading = false
        }
    }

    func pickVersion(_ minecraft: String) {
        pickedVersion = minecraft
        pickedLoader = versions.value?.versions.first { $0.minecraft == minecraft }?.loaders.first
        report = nil
    }

    func pickLoader(_ loader: String) {
        pickedLoader = loader
        report = nil
    }

    func check() async {
        guard let client = client(), let type = pickedType, let minecraft = pickedVersion else { return }
        report = PageRead(loading: true)
        do {
            report = PageRead(value: try await client.versionPreflight(serverId: serverId, type: type, minecraft: minecraft, loader: pickedLoader))
        } catch let problem as AgentError {
            noted(problem)
            report = PageRead(problem: problem)
        } catch {
            report = nil
        }
    }

    /// After the one confirmation: the server stops, a backup is taken,
    /// and the change runs as a task.
    func changeVersion(_ strings: Strings) async {
        guard let checked = report?.value, let type = pickedType, let minecraft = pickedVersion,
              let client = client(), busy == nil else { return }
        busy = "version"
        said = nil
        do {
            let done = try await client.changeVersion(serverId: serverId, type: type, minecraft: minecraft, loader: pickedLoader)
            var notes = [strings.t("version.changed", ["version": VersionChange.target(checked)])]
            if done.verified == false { notes.append(strings.t("new.unverified")) }
            if done.crossplayTurnedOff == true { notes.append(strings.t("version.crossplay_off")) }
            said = Said(text: notes.joined(separator: " "), good: true)
            report = nil
            await listChanged()
        } catch let problem as AgentError {
            noted(problem)
            said = Said(text: problem.message(strings), good: false)
        } catch {}
        busy = nil
        task = nil
        await loadVersion()
    }

    func rollBack(_ strings: Strings) async {
        await versionWork("roll_back", strings) { client, id in
            _ = try await client.rollBackVersion(serverId: id)
            return Said(text: strings.t("version.went_back"), good: true)
        }
    }

    /// Only from the person's own tick.
    func acceptEula(_ strings: Strings) async {
        await versionWork("eula", strings) { client, id in
            _ = try await client.acceptEula(serverId: id)
            return Said(text: strings.t("version.eula_done"), good: true)
        }
    }

    private func versionWork(_ name: String, _ strings: Strings, _ call: (AgentClient, String) async throws -> Said) async {
        guard let client = client(), busy == nil else { return }
        busy = name
        said = nil
        do {
            said = try await call(client, serverId)
        } catch let problem as AgentError {
            noted(problem)
            said = Said(text: problem.message(strings), good: false)
        } catch {}
        busy = nil
        task = nil
        await loadVersion()
    }
}
