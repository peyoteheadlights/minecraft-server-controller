import Foundation

/// Backups, Restore world, Schedules and Performance (mobile/api-routes.txt).
/// Making, checking, copying and restoring a backup answer only once done,
/// so those calls use the slow session.
extension AgentClient {
    public func backups(serverId: String) async throws -> BackupList {
        try await call("GET", world(serverId) + "/backups", as: BackupList.self)
    }

    public func backUp(serverId: String) async throws -> BackupMade {
        try await call("POST", world(serverId) + "/backups", body: Data("{}".utf8), slow: true, as: BackupMade.self)
    }

    /// Opens the archive on the PC and checks it, now.
    public func checkBackup(serverId: String, backupId: Int64) async throws -> BackupCheck {
        try await call("GET", world(serverId) + "/backups/\(backupId)/verify", slow: true, as: BackupCheck.self)
    }

    /// Without `confirm`, only what would happen; nothing changes. A backup
    /// of the world as it is now is always made first.
    public func restoreBackup(serverId: String, backupId: Int64, confirm: Bool, startAfter: Bool = false) async throws -> Restored {
        let body = try AgentClient.encode(RestoreBody(confirm: confirm, startAfter: confirm && startAfter, safetyBackup: true))
        return try await call("POST", world(serverId) + "/backups/\(backupId)/restore", body: body, slow: confirm, as: Restored.self)
    }

    public func deleteBackup(serverId: String, backupId: Int64) async throws {
        _ = try await call("DELETE", world(serverId) + "/backups/\(backupId)", as: Ok.self)
    }

    /// Copies one backup to the second-copy folder (again).
    public func copyBackup(serverId: String, backupId: Int64) async throws -> BackupCopied {
        try await call("POST", world(serverId) + "/backups/\(backupId)/copy", body: Data("{}".utf8), slow: true, as: BackupCopied.self)
    }

    public func offsite(serverId: String) async throws -> Offsite {
        try await call("GET", world(serverId) + "/backups/offsite", as: Offsite.self)
    }

    /// Turns second copies off. Choosing a folder needs the PC's folder list.
    public func turnOffsiteOff(serverId: String) async throws -> Offsite {
        try await call("PUT", world(serverId) + "/backups/offsite", body: Data("{\"directory\": \"\"}".utf8), as: Offsite.self)
    }

    /// Downloads a backup's zip to `destination`, with the sign-in in a
    /// header (never in the address), and returns its size. `progress` gets
    /// the bytes so far and the size, when the PC said it.
    public func downloadBackup(
        serverId: String,
        backupId: Int64,
        to destination: URL,
        progress: @escaping @Sendable (Int64, Int64?) -> Void = { _, _ in }
    ) async throws -> Int64 {
        try await downloadZip(world(serverId) + "/backups/\(backupId)/download", to: destination, progress: progress)
    }

    /// Sends a world's zip (or .mcworld) and says what it is. Nothing is
    /// replaced until `importWorld`; `forgetWorld` throws it away.
    public func uploadWorld(
        serverId: String,
        file: PickedFile,
        progress: (@Sendable (Int64, Int64?) -> Void)? = nil
    ) async throws -> WorldRead {
        try await upload(world(serverId) + "/world/import/upload", file, sent: progress, as: WorldRead.self)
    }

    /// Reads a world folder on the PC (one from the folder picker or single-player's saves).
    public func pickWorldFolder(serverId: String, path: String) async throws -> WorldRead {
        let body = try AgentClient.encode(["path": path])
        return try await call("POST", world(serverId) + "/world/import/folder", body: body, slow: true, as: WorldRead.self)
    }

    /// Single-player's worlds on the PC.
    public func savedWorlds(serverId: String) async throws -> SavedWorlds {
        try await call("GET", world(serverId) + "/world/saves", as: SavedWorlds.self)
    }

    /// Replaces this server's world with the one read; a backup is taken first.
    public func importWorld(serverId: String, token: String) async throws -> WorldImported {
        let body = try AgentClient.encode(WorldImportBody(token: token, confirm: true))
        return try await call("POST", world(serverId) + "/world/import", body: body, slow: true, as: WorldImported.self)
    }

    public func forgetWorld(serverId: String, token: String) async throws {
        _ = try await call("DELETE", world(serverId) + "/world/import/" + AgentClient.pathSegment(token), as: Ok.self)
    }

    /// Packs this server's world as a zip for single-player; `downloadWorld` fetches it.
    public func packWorld(serverId: String) async throws -> WorldPacked {
        try await call("POST", world(serverId) + "/world/download", body: Data("{}".utf8), slow: true, as: WorldPacked.self)
    }

    /// Downloads the world packed by `packWorld` to `destination`, as `downloadBackup` does.
    public func downloadWorld(
        serverId: String,
        packed: WorldPacked,
        to destination: URL,
        progress: @escaping @Sendable (Int64, Int64?) -> Void = { _, _ in }
    ) async throws -> Int64 {
        let path = world(serverId) + "/world/download/" + AgentClient.pathSegment(packed.token)
            + "?filename=" + AgentClient.pathSegment(packed.filename)
        return try await downloadZip(path, to: destination, progress: progress)
    }

    public func worlds(serverId: String) async throws -> WorldList {
        try await call("GET", world(serverId) + "/worlds", as: WorldList.self)
    }

    /// Asks Minecraft to save the world now (save-all flush).
    public func saveWorld(serverId: String) async throws -> Requested {
        try await call("POST", world(serverId) + "/worlds/save", body: Data("{}".utf8), as: Requested.self)
    }

    public func worldTimeline(serverId: String) async throws -> WorldTimeline {
        try await call("GET", world(serverId) + "/world/timeline", as: WorldTimeline.self)
    }

    /// Puts back only the world from that backup; the server must be off.
    public func restoreWorld(serverId: String, backupId: Int64) async throws -> Restored {
        let body = try AgentClient.encode(WorldRestoreBody(backupId: backupId, confirm: true))
        return try await call("POST", world(serverId) + "/world/undo", body: body, slow: true, as: Restored.self)
    }

    /// Every server's tasks running now, including a new server being set up.
    public func runningJobs() async throws -> JobList {
        try await call("GET", "/api/jobs?running=true", as: JobList.self)
    }

    /// This server's recent tasks, newest first.
    public func jobs(serverId: String, limit: Int = 20) async throws -> JobList {
        let count = Swift.min(Swift.max(limit, 1), 200)
        return try await call("GET", "/api/jobs?server_id=" + AgentClient.pathSegment(serverId) + "&limit=\(count)", as: JobList.self)
    }

    /// The server's Undo and Redo lists.
    public func changes(serverId: String) async throws -> UndoRedo {
        try await call("GET", world(serverId) + "/changes", as: UndoRedo.self)
    }

    /// Reverses the newest change ("undo") or puts back the one undone last
    /// ("redo"). The server stops for it; `startAfter` starts it again.
    public func moveChange(serverId: String, direction: String, startAfter: Bool) async throws -> ChangeMoved {
        precondition(direction == "undo" || direction == "redo")
        let body = try AgentClient.encode(MoveBody(startAfter: startAfter))
        return try await call("POST", world(serverId) + "/changes/" + direction, body: body, slow: true, as: ChangeMoved.self)
    }

    public func schedules(serverId: String) async throws -> ScheduleList {
        try await call("GET", world(serverId) + "/schedules", as: ScheduleList.self)
    }

    public func addSchedule(serverId: String, _ body: ScheduleBody) async throws -> ScheduleSaved {
        try await call("POST", world(serverId) + "/schedules", body: try AgentClient.encode(body), as: ScheduleSaved.self)
    }

    /// Replaces the whole schedule, payload included.
    public func updateSchedule(serverId: String, scheduleId: Int64, _ body: ScheduleBody) async throws -> ScheduleSaved {
        try await call("PUT", world(serverId) + "/schedules/\(scheduleId)", body: try AgentClient.encode(body), as: ScheduleSaved.self)
    }

    public func deleteSchedule(serverId: String, scheduleId: Int64) async throws {
        _ = try await call("DELETE", world(serverId) + "/schedules/\(scheduleId)", as: Ok.self)
    }

    public func runSchedule(serverId: String, scheduleId: Int64) async throws -> ScheduleRan {
        try await call("POST", world(serverId) + "/schedules/\(scheduleId)/run", body: Data("{}".utf8), slow: true, as: ScheduleRan.self)
    }

    /// The graphs' samples for the last `hours` (1 to 168), the values now
    /// and, with `storage`, the disk use (slow: the PC walks the server folder).
    public func performance(serverId: String, hours: Int, storage: Bool = true) async throws -> Performance {
        let range = Swift.min(Swift.max(hours, 1), 168)
        return try await call("GET", world(serverId) + "/performance?hours=\(range)&storage=\(storage)", as: Performance.self)
    }

    /// The health checks. Can take a few seconds: the PC asks Tailscale.
    public func serverHealth(serverId: String) async throws -> ServerHealth {
        try await call("GET", world(serverId) + "/health/server", as: ServerHealth.self)
    }

    private func world(_ id: String) -> String {
        "/api/servers/" + AgentClient.pathSegment(id)
    }

    private struct WorldImportBody: Encodable {
        let token: String
        let confirm: Bool
    }

    private struct RestoreBody: Encodable {
        let confirm: Bool
        let startAfter: Bool
        let safetyBackup: Bool

        enum CodingKeys: String, CodingKey {
            case confirm
            case startAfter = "start_after"
            case safetyBackup = "safety_backup"
        }
    }

    private struct MoveBody: Encodable {
        let startAfter: Bool

        enum CodingKeys: String, CodingKey { case startAfter = "start_after" }
    }

    private struct WorldRestoreBody: Encodable {
        let backupId: Int64
        let confirm: Bool

        enum CodingKeys: String, CodingKey {
            case backupId = "backup_id"
            case confirm
        }
    }
}
