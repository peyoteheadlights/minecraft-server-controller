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
}
