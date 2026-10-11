import Core
import Foundation
import Observation

/// What a button did, said once it is done: good news or a problem.
struct Said: Equatable {
    let text: String
    let good: Bool
}

/// A restore waiting for "yes": the backup and what the agent says will happen.
struct RestoreAsk: Identifiable {
    let backup: Backup
    let willHappen: [String]

    var id: Int64 { backup.id }
}

/// Undo or Redo waiting for "yes": "undo" or "redo", and the change it moves.
struct MoveAsk: Identifiable {
    let direction: String
    let change: Change

    var id: String { "\(direction):\(change.id)" }
}

/// A backup on its way to this phone: bytes so far and the size, when the
/// PC said it.
struct Downloading: Equatable {
    let name: String
    let done: Int64
    let size: Int64?
}

/// A downloaded backup waiting for the person to pick where it goes.
struct Downloaded: Identifiable {
    let name: String
    let file: URL

    var id: URL { file }
}

/// Everything Backups, Restore world, Schedules and Performance show for
/// one server (mirrors WorldPages.kt). Each button is the dashboard's own
/// route, with the person's own sign-in, so the agent decides what they
/// may do.
@MainActor
@Observable
final class WorldPages {
    let serverId: String
    @ObservationIgnored private let client: () -> AgentClient?
    @ObservationIgnored private let noted: (AgentError) -> Void

    init(serverId: String, client: @escaping () -> AgentClient?, noted: @escaping (AgentError) -> Void) {
        self.serverId = serverId
        self.client = client
        self.noted = noted
    }

    /// "backup", "save", "check:4", "restore:4" while that button works.
    private(set) var busy: String? = nil
    var said: Said? = nil

    // MARK: - Backups

    private(set) var backups = PageRead<BackupList>()
    private(set) var offsite: Offsite? = nil
    private(set) var worlds = PageRead<WorldList>()
    /// The Undo and Redo lists; nil until read, or when they couldn't be.
    private(set) var changes: UndoRedo? = nil
    var moving: MoveAsk? = nil
    var restoring: RestoreAsk? = nil
    private(set) var downloading: Downloading? = nil
    var downloaded: Downloaded? = nil
    /// Counts downloads, so a progress report that arrives late never
    /// brings back a finished one.
    @ObservationIgnored private var downloadRun = 0

    func loadBackups() async {
        guard let client = client() else { return }
        backups.loading = true
        do {
            backups = PageRead(value: try await client.backups(serverId: serverId))
        } catch let problem as AgentError {
            noted(problem)
            backups.problem = problem
            backups.loading = false
        } catch {
            backups.loading = false
        }
        // As the dashboard: without these the list still shows.
        offsite = try? await client.offsite(serverId: serverId)
        changes = try? await client.changes(serverId: serverId)
        do {
            worlds = PageRead(value: try await client.worlds(serverId: serverId))
        } catch let problem as AgentError {
            worlds = PageRead(problem: problem)
        } catch {}
    }

    func backUp(_ strings: Strings) async {
        await work("backup", strings, reload: loadBackups) { client, id in
            Said(text: Backups.made(strings, try await client.backUp(serverId: id)), good: true)
        }
    }

    func saveWorld(_ strings: Strings) async {
        await work("save", strings) { client, id in
            _ = try await client.saveWorld(serverId: id)
            return Said(text: strings.t("backups.save_sent"), good: true)
        }
    }

    func check(_ backup: Backup, _ strings: Strings) async {
        await work("check:\(backup.id)", strings) { client, id in
            let check = try await client.checkBackup(serverId: id, backupId: backup.id)
            return Said(text: Backups.checked(strings, check), good: check.ok)
        }
    }

    func copyAgain(_ backup: Backup, _ strings: Strings) async {
        await work("copy:\(backup.id)", strings, reload: loadBackups) { client, id in
            let copied = try await client.copyBackup(serverId: id, backupId: backup.id)
            if copied.copy?.state == "ok" {
                return Said(text: strings.t("offsite.copy_done"), good: true)
            }
            return Said(text: strings.t("offsite.copy_failed", ["reason": copied.copy?.reason ?? strings.t("value.unknown")]), good: false)
        }
    }

    /// Asks the agent what a restore would do; nothing changes yet.
    func askRestore(_ backup: Backup, _ strings: Strings) async {
        await work("restore:\(backup.id)", strings) { [weak self] client, id in
            let preview = try await client.restoreBackup(serverId: id, backupId: backup.id, confirm: false)
            self?.restoring = RestoreAsk(backup: backup, willHappen: preview.willHappen ?? [])
            return nil
        }
    }

    func restore(_ ask: RestoreAsk, startAfter: Bool, _ strings: Strings) async {
        restoring = nil
        await work("restore:\(ask.backup.id)", strings, reload: loadBackups) { client, id in
            let done = try await client.restoreBackup(serverId: id, backupId: ask.backup.id, confirm: true, startAfter: startAfter)
            return Said(text: Backups.restored(strings, done), good: true)
        }
    }

    func delete(_ backup: Backup, _ strings: Strings) async {
        await work("delete:\(backup.id)", strings, reload: loadBackups) { client, id in
            try await client.deleteBackup(serverId: id, backupId: backup.id)
            return Said(text: strings.t("backups.deleted"), good: true)
        }
    }

    /// A task finished on another device (or here) may have added a change:
    /// read the lists again while Backups is open.
    func onTask(_ job: Job) {
        if Backups.FINISHED.contains(job.state) && backups.value != nil && busy == nil {
            Task { await loadBackups() }
        }
    }

    /// Asks before Undo ("undo") or Redo ("redo") of the first change on that list.
    func askMove(_ direction: String) {
        guard let lists = changes else { return }
        moving = (direction == "undo" ? lists.undo : lists.redo).first.map { MoveAsk(direction: direction, change: $0) }
    }

    func move(_ ask: MoveAsk, startAfter: Bool, _ strings: Strings) async {
        moving = nil
        await work(ask.direction, strings, reload: loadBackups) { client, id in
            let moved = try await client.moveChange(serverId: id, direction: ask.direction, startAfter: startAfter)
            return Said(text: ChangeList.done(strings, ask.direction, moved), good: true)
        }
    }

    func setOffsite(_ directory: String, _ strings: Strings) async {
        await work("offsite", strings, reload: loadBackups) { client, id in
            _ = try await client.setOffsite(serverId: id, directory: directory)
            return Said(text: strings.t("offsite.saved"), good: true)
        }
    }

    func offsiteOff(_ strings: Strings) async {
        await work("offsite", strings, reload: loadBackups) { client, id in
            _ = try await client.turnOffsiteOff(serverId: id)
            return Said(text: strings.t("offsite.turned_off"), good: true)
        }
    }

    /// Downloads the backup into this app's own temporary folder; then the
    /// person picks where it goes (`downloaded`), and it never stays here.
    func download(_ backup: Backup, _ strings: Strings) async {
        guard let client = client(), busy == nil else { return }
        busy = "download:\(backup.id)"
        said = nil
        downloadRun += 1
        let run = downloadRun
        downloading = Downloading(name: backup.name, done: 0, size: backup.sizeBytes)
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        let name = (backup.name as NSString).lastPathComponent
        let file = folder.appendingPathComponent(name.isEmpty ? "backup-\(backup.id).zip" : name)
        do {
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            _ = try await client.downloadBackup(serverId: serverId, backupId: backup.id, to: file) { done, size in
                Task { @MainActor [weak self] in
                    guard let self = self, self.downloadRun == run, self.downloading != nil else { return }
                    self.downloading = Downloading(name: backup.name, done: done, size: size)
                }
            }
            downloaded = Downloaded(name: backup.name, file: file)
        } catch let problem as AgentError {
            noted(problem)
            try? FileManager.default.removeItem(at: folder)
            said = Said(text: problem.message(strings), good: false)
        } catch {
            try? FileManager.default.removeItem(at: folder)
            said = Said(text: strings.t("mobile.backups.save_failed", ["reason": error.localizedDescription]), good: false)
        }
        downloading = nil
        busy = nil
    }

    /// The person picked a place for the download, or cancelled: either
    /// way the copy in the app's own folder goes.
    func finishDownload(_ result: Result<URL, Error>?, _ strings: Strings) {
        guard let done = downloaded else { return }
        downloaded = nil
        switch result {
        case .success:
            said = Said(text: strings.t("mobile.backups.saved_file", ["name": done.name]), good: true)
        case .failure(let error):
            said = Said(text: strings.t("mobile.backups.save_failed", ["reason": error.localizedDescription]), good: false)
        case nil:
            break
        }
        try? FileManager.default.removeItem(at: done.file.deletingLastPathComponent())
    }

    // MARK: - Restore world

    private(set) var timeline = PageRead<WorldTimeline>()

    func loadTimeline() async {
        await read(\.timeline) { client, id in try await client.worldTimeline(serverId: id) }
    }

    func restoreWorld(_ point: WorldPoint, _ strings: Strings) async {
        await work("world:\(point.backupId)", strings, reload: loadTimeline) { client, id in
            Said(text: WorldRestore.done(strings, try await client.restoreWorld(serverId: id, backupId: point.backupId)), good: true)
        }
    }

    // MARK: - Schedules

    private(set) var schedules = PageRead<ScheduleList>()

    func loadSchedules() async {
        await read(\.schedules) { client, id in try await client.schedules(serverId: id) }
    }

    func toggle(_ schedule: Schedule, _ strings: Strings) async {
        await work("toggle:\(schedule.id)", strings, reload: loadSchedules) { client, id in
            _ = try await client.updateSchedule(serverId: id, scheduleId: schedule.id, Schedules.toggled(schedule))
            return nil
        }
    }

    func runNow(_ schedule: Schedule, _ strings: Strings) async {
        await work("run:\(schedule.id)", strings, reload: loadSchedules) { client, id in
            let ran = try await client.runSchedule(serverId: id, scheduleId: schedule.id)
            return Said(text: strings.t("mobile.schedules.ran", ["name": schedule.name, "result": ran.result ?? ""]), good: true)
        }
    }

    func deleteSchedule(_ schedule: Schedule, _ strings: Strings) async {
        await work("delete:\(schedule.id)", strings, reload: loadSchedules) { client, id in
            try await client.deleteSchedule(serverId: id, scheduleId: schedule.id)
            return Said(text: strings.t("schedules.deleted"), good: true)
        }
    }

    /// Adds a schedule; true once the agent took it, to empty the form.
    func addSchedule(name: String, task: String, kind: String, expr: String, _ strings: Strings) async -> Bool {
        let tasks = schedules.value?.tasks ?? []
        var added = false
        await work("add", strings, reload: loadSchedules) { client, id in
            _ = try await client.addSchedule(
                serverId: id, Schedules.newBody(strings, name: name, task: task, kind: kind, expr: expr, tasks: tasks)
            )
            added = true
            return Said(text: strings.t("schedules.created"), good: true)
        }
        return added
    }

    // MARK: - Performance

    private(set) var range = Graphs.DEFAULT_RANGE
    private(set) var performance = PageRead<Performance>()
    private(set) var health = PageRead<ServerHealth>()
    /// When `performance` was read, for drawing the graphs up to then.
    private(set) var readAt: Double = 0
    /// Counts performance reads, so an answer for a range no longer shown is dropped.
    @ObservationIgnored private var performanceRead = 0

    func loadPerformance() async {
        await loadSeries(storage: true, kept: nil)
        // Last: it can take a few seconds while the PC asks Tailscale.
        await read(\.health) { client, id in try await client.serverHealth(serverId: id) }
    }

    /// Only the graphs change with the range: the disk use and the health
    /// checks (both slow on the PC) are kept from the last full read.
    func showRange(_ hours: Int) async {
        guard Graphs.RANGES.contains(hours), hours != range else { return }
        let kept = performance.value?.storage
        range = hours
        performance = PageRead()
        await loadSeries(storage: false, kept: kept)
    }

    private func loadSeries(storage: Bool, kept: Storage?) async {
        guard let client = client() else { return }
        let hours = range
        performanceRead += 1
        let mine = performanceRead
        performance.loading = true
        do {
            var data = try await client.performance(serverId: serverId, hours: hours, storage: storage)
            guard mine == performanceRead else { return }
            if !storage { data.storage = kept }
            performance = PageRead(value: data)
            readAt = Date().timeIntervalSince1970
        } catch let problem as AgentError {
            guard mine == performanceRead else { return }
            noted(problem)
            performance.problem = problem
            performance.loading = false
        } catch {
            guard mine == performanceRead else { return }
            performance.loading = false
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
        } catch {}
        busy = nil
        await reload?()
    }

    private func read<T>(
        _ path: ReferenceWritableKeyPath<WorldPages, PageRead<T>>,
        _ call: (AgentClient, String) async throws -> T
    ) async {
        guard let client = client() else { return }
        self[keyPath: path].loading = true
        do {
            let value = try await call(client, serverId)
            self[keyPath: path] = PageRead(value: value)
        } catch let problem as AgentError {
            noted(problem)
            self[keyPath: path].problem = problem
            self[keyPath: path].loading = false
        } catch {
            self[keyPath: path].loading = false
        }
    }
}
