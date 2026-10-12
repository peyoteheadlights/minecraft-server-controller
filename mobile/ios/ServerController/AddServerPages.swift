import Core
import Foundation
import Observation

/// The "+" on All servers (mirrors AddServerPages.kt): a new server, one
/// from a modpack, or one already on the PC. Kept for the whole app, so a
/// server being set up still shows its progress when the screen is opened
/// again. `opened` is the server to open once it exists.
@MainActor
@Observable
final class AddServerPages {
    @ObservationIgnored private let client: () -> AgentClient?
    @ObservationIgnored private let noted: (AgentError) -> Void
    @ObservationIgnored private let listChanged: () async -> Void

    init(client: @escaping () -> AgentClient?, noted: @escaping (AgentError) -> Void, listChanged: @escaping () async -> Void) {
        self.client = client
        self.noted = noted
        self.listChanged = listChanged
    }

    private(set) var way: String?
    private(set) var options = PageRead<NewServerOptions>()
    private(set) var edition = "java"
    private(set) var type: ServerTypeInfo?
    private(set) var versions = PageRead<TypeVersions>()
    var snapshots = false
    private(set) var version: OfferedVersion?
    var loader: String?
    var name = ""
    var color: String?
    var memoryMb: Int?
    /// The folder picked on the PC; the server's own folder goes inside it.
    var parent: String?
    /// Technical mode's typed folder, used as it is.
    var typedFolder: String?
    var ruled = false
    var jar = ""
    private(set) var pack: ModpackInspected?
    private(set) var task: Job?
    private(set) var busy: String?
    var said: Said?
    /// Shown after adding a server already on the PC: its name and the agent's warnings.
    private(set) var addedLines: [String] = []
    private(set) var opened: String?
    /// A server already on the PC that came with warnings: it opens when the person is ready.
    private(set) var added: ServerAdded?

    /// The folder that will be sent: the typed one, or a new one inside the picked one.
    var folder: String {
        if let typedFolder { return typedFolder }
        guard let parent else { return "" }
        return way == AddServer.HAVE ? parent : AddServer.folderFor(parent, name)
    }

    var choices: [OfferedVersion] {
        guard let read = versions.value else { return [] }
        return VersionChange.choices(read, snapshots: snapshots)
    }

    func begin(_ chosen: String) async {
        way = chosen
        said = nil
        addedLines = []
        added = nil
        if options.value == nil { await loadOptions() }
    }

    /// Back to the three ways; a pack read but not used is thrown away.
    func startOver() async {
        await dropPack()
        way = nil
        type = nil
        version = nil
        loader = nil
        versions = PageRead()
        name = ""
        parent = nil
        typedFolder = nil
        ruled = false
        jar = ""
        said = nil
        addedLines = []
        added = nil
    }

    /// Leaving the screen: a pack read but not used is thrown away, unless it is being made into a server now.
    func leave() async {
        if busy != "create" { await dropPack() }
    }

    /// Opens the server added with warnings, once they've been read.
    func openAdded() {
        opened = added?.server.id
    }

    func loadOptions() async {
        guard let client = client() else { return }
        options.loading = true
        do {
            let read = try await client.newServerOptions()
            color = color ?? read.color
            memoryMb = memoryMb ?? read.memoryMb
            options = PageRead(value: read)
        } catch let problem as AgentError {
            noted(problem)
            options = PageRead(problem: problem)
        } catch {
            options.loading = false
        }
        await resume()
    }

    /// A new server still being set up after the app was closed shows its progress again.
    func resume() async {
        guard let client = client() else { return }
        do {
            if let running = AddServer.creating(try await client.runningJobs().jobs) { task = running }
        } catch let problem as AgentError {
            noted(problem)
        } catch {}
    }

    func pickEdition(_ chosen: String) async {
        edition = chosen
        ruled = false
        if chosen == "bedrock", let read = options.value, let bedrock = AddServer.bedrockType(read) {
            await pickType(bedrock)
        } else {
            type = nil
            version = nil
            versions = PageRead()
        }
    }

    func pickType(_ chosen: ServerTypeInfo) async {
        type = chosen
        guard way != AddServer.HAVE, let client = client() else { return }
        version = nil
        loader = nil
        versions = PageRead(loading: true)
        do {
            let read = try await client.typeVersions(typeId: chosen.id)
            // Another kind was tapped meanwhile: its own answer is the one shown.
            guard type?.id == chosen.id else { return }
            version = AddServer.firstVersion(read)
            loader = version?.loaders.first
            versions = PageRead(value: read)
        } catch let problem as AgentError {
            noted(problem)
            if type?.id == chosen.id { versions = PageRead(problem: problem) }
        } catch {
            if type?.id == chosen.id { versions.loading = false }
        }
    }

    func pickVersion(_ minecraft: String) {
        version = versions.value?.versions.first { $0.minecraft == minecraft }
        loader = version?.loaders.first
    }

    func nudgeMemory(_ stepMb: Int) {
        guard let now = memoryMb else { return }
        memoryMb = AddServer.nudged(now, stepMb, totalMb: options.value?.totalMb)
    }

    func create(_ strings: Strings) async {
        guard let client = client(), let kind = type, let chosen = version, busy == nil else { return }
        busy = "create"
        said = nil
        defer {
            busy = nil
            task = nil
        }
        let request = NewServerRequest(
            name: name.trimmingCharacters(in: .whitespaces), directory: folder, type: kind.id, minecraft: chosen.minecraft,
            loader: kind.picksLoader ? loader : nil, memoryMb: AddServer.memoryShown(kind) ? memoryMb : nil,
            color: color, eulaAccepted: ruled
        )
        do {
            let made = try await client.createServer(request)
            await done(strings, made.serverId, made.name)
        } catch let problem as AgentError {
            noted(problem)
            said = Said(text: problem.message(strings), good: false)
        } catch {}
    }

    func add(_ strings: Strings) async {
        guard let client = client(), let kind = type, busy == nil else { return }
        busy = "add"
        said = nil
        defer { busy = nil }
        do {
            let result = try await client.addServer(
                name: name.trimmingCharacters(in: .whitespaces), directory: folder, type: kind.id,
                jar: jar.trimmingCharacters(in: .whitespaces)
            )
            addedLines = AddServer.addedLines(strings, result)
            await listChanged()
            // Warnings stay on screen so they can be fixed before starting.
            if result.warnings.isEmpty { opened = result.server.id } else { added = result }
        } catch let problem as AgentError {
            noted(problem)
            said = Said(text: problem.message(strings), good: false)
        } catch {}
    }

    func inspect(_ file: PickedFile, _ strings: Strings) async {
        guard let client = client(), busy == nil else { return }
        busy = "inspect"
        said = nil
        defer { busy = nil }
        await dropPack()
        do {
            let read = try await client.inspectModpack(serverId: nil, file: file)
            pack = read
            if name.trimmingCharacters(in: .whitespaces).isEmpty { name = read.pack.name }
        } catch let problem as AgentError {
            noted(problem)
            said = Said(text: problem.message(strings), good: false)
        } catch {}
    }

    func createFromPack(_ strings: Strings) async {
        guard let client = client(), let read = pack, busy == nil else { return }
        busy = "create"
        said = nil
        defer {
            busy = nil
            task = nil
        }
        do {
            let made = try await client.modpackServer(
                token: read.token, name: name.trimmingCharacters(in: .whitespaces), directory: folder,
                memoryMb: memoryMb, color: color, eulaAccepted: ruled
            )
            pack = nil
            await done(strings, made.serverId, made.name)
        } catch let problem as AgentError {
            noted(problem)
            said = Said(text: problem.message(strings), good: false)
        } catch {}
    }

    /// Throws an uploaded pack away on the agent.
    func dropPack() async {
        guard let token = pack?.token else { return }
        pack = nil
        guard let client = client() else { return }
        do {
            try await client.forgetModpack(token: token)
        } catch let problem as AgentError {
            noted(problem)
        } catch {}
    }

    func onTask(_ job: Job) {
        guard job.kind == "server_create" else { return }
        task = job.state == "running" ? job : nil
        if job.state == "succeeded" { Task { await listChanged() } }
    }

    func openedShown() async {
        opened = nil
        await startOver()
    }

    private func done(_ strings: Strings, _ serverId: String, _ made: String) async {
        said = Said(text: strings.t("new.created", ["name": made]), good: true)
        await listChanged()
        opened = serverId
    }
}
