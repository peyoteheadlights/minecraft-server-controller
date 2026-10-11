package io.github.peyoteheadlights.mcsc.core

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject

/*
 * What Backups, Restore world, Schedules and Performance read. As in
 * PageModels.kt, only the fields the app uses are listed, and a value the
 * agent can leave out is null here and shown as Unknown.
 */

/** A backup's second copy off the PC, as the agent found it just now. */
@Serializable
data class BackupCopy(
    val state: String = "none",
    val reason: String? = null,
    val path: String? = null,
)

@Serializable
data class Backup(
    val id: Long,
    val name: String = "",
    val kind: String? = null,
    @SerialName("created_at") val createdAt: Double? = null,
    @SerialName("size_bytes") val sizeBytes: Long? = null,
    val status: String? = null,
    val note: String? = null,
    val exists: Boolean? = null,
    val copy: BackupCopy? = null,
)

@Serializable
data class Retention(val daily: Int? = null, val weekly: Int? = null, val monthly: Int? = null)

@Serializable
data class BackupList(
    val backups: List<Backup> = emptyList(),
    val retention: Retention? = null,
)

/** Opening the archive and checking it. [reason] says why it failed. */
@Serializable
data class BackupCheck(
    val ok: Boolean = false,
    val reason: String? = null,
    val entries: Int? = null,
)

@Serializable
data class BackupMade(
    val name: String = "",
    val verification: BackupCheck? = null,
)

@Serializable
data class SafetyBackup(val id: Long? = null, val name: String = "")

/** How a change is undone: by restoring the backup made just before it. */
@Serializable
data class Undo(
    val kind: String = "",
    @SerialName("backup_id") val backupId: Long? = null,
    val backup: String = "",
)

/** A restore asked without confirm answers [willHappen]; a confirmed one
 * says what was put back and the backup made just before. */
@Serializable
data class Restored(
    @SerialName("confirmation_required") val confirmationRequired: Boolean? = null,
    @SerialName("will_happen") val willHappen: List<String>? = null,
    val restored: String? = null,
    @SerialName("safety_backup") val safetyBackup: SafetyBackup? = null,
    val undo: Undo? = null,
    @SerialName("job_id") val jobId: String? = null,
)

@Serializable
data class BackupDeleted(val deleted: String = "")

/** Where second copies go; [directory] is empty when they are off. */
@Serializable
data class Offsite(
    val directory: String = "",
    val unavailable: String? = null,
    val subfolder: String? = null,
)

@Serializable
data class BackupCopied(val ok: Boolean = false, val copy: BackupCopy? = null)

@Serializable
data class LastBackup(
    val name: String? = null,
    @SerialName("created_at") val createdAt: Double? = null,
)

@Serializable
data class World(
    val key: String,
    val label: String = "",
    val exists: Boolean = false,
    @SerialName("size_bytes") val sizeBytes: Long? = null,
    val modified: Double? = null,
    @SerialName("last_backup") val lastBackup: LastBackup? = null,
)

@Serializable
data class WorldList(val worlds: List<World> = emptyList())

/** Written to the console; Minecraft gives no answer to check. */
@Serializable
data class Requested(val result: String = "", val detail: String? = null)

/** A point Restore world can go back to: a backup that holds the world. */
@Serializable
data class WorldPoint(
    @SerialName("backup_id") val backupId: Long,
    val name: String = "",
    @SerialName("created_at") val createdAt: Double = 0.0,
    @SerialName("age_seconds") val ageSeconds: Double = 0.0,
    @SerialName("size_bytes") val sizeBytes: Long? = null,
    val kind: String? = null,
    val note: String? = null,
    val checked: Boolean = false,
    /** Time with players online since; null when sessions weren't recorded. */
    @SerialName("played_seconds") val playedSeconds: Double? = null,
)

@Serializable
data class WorldTimeline(
    val points: List<WorldPoint> = emptyList(),
    @SerialName("server_running") val serverRunning: Boolean = false,
    @SerialName("can_restore") val canRestore: Boolean = false,
    @SerialName("blocked_by") val blockedBy: String? = null,
)

@Serializable
data class JobResult(val undo: Undo? = null)

/** A task the agent ran (a backup, a restore, a mod install). */
@Serializable
data class Job(
    val id: String,
    val kind: String = "",
    val title: String = "",
    val state: String = "",
    /** What it is doing now ("Updating Sodium (2 of 5)"). */
    val step: String? = null,
    @SerialName("server_id") val serverId: String? = null,
    @SerialName("finished_at") val finishedAt: Double? = null,
    val result: JobResult? = null,
)

@Serializable
data class JobList(val jobs: List<Job> = emptyList())

@Serializable
data class JobUndone(val restored: String = "")

@Serializable
data class Schedule(
    val id: Long,
    val name: String = "",
    val task: String = "",
    val kind: String = "",
    val expr: String = "",
    /** Sent back unchanged when the schedule is switched on or off. */
    val payload: JsonObject = JsonObject(emptyMap()),
    val enabled: Boolean = false,
    @SerialName("next_run") val nextRun: Double? = null,
    @SerialName("last_result") val lastResult: String? = null,
)

@Serializable
data class ScheduleList(
    val schedules: List<Schedule> = emptyList(),
    val tasks: List<String> = emptyList(),
)

@Serializable
data class ScheduleSaved(val schedule: Schedule)

@Serializable
data class ScheduleRan(val result: String = "")

/** The values now. Each is null when it couldn't be measured. */
@Serializable
data class Snapshot(
    @SerialName("cpu_percent") val cpuPercent: Double? = null,
    @SerialName("process_cpu_percent") val processCpuPercent: Double? = null,
    @SerialName("ram_percent") val ramPercent: Double? = null,
    @SerialName("proc_ram_mb") val procRamMb: Double? = null,
    @SerialName("disk_free_gb") val diskFreeGb: Double? = null,
    @SerialName("disk_unknown_reason") val diskUnknownReason: String? = null,
    @SerialName("net_recv_mb_s") val netRecvMbS: Double? = null,
    @SerialName("net_sent_mb_s") val netSentMbS: Double? = null,
)

/** One time bucket's averages; null where nothing was measured. */
@Serializable
data class SeriesPoint(
    val ts: Double,
    @SerialName("cpu_percent") val cpuPercent: Double? = null,
    @SerialName("ram_used_mb") val ramUsedMb: Double? = null,
    @SerialName("ram_total_mb") val ramTotalMb: Double? = null,
    @SerialName("proc_ram_mb") val procRamMb: Double? = null,
    val tps: Double? = null,
    val mspt: Double? = null,
    val players: Double? = null,
    @SerialName("players_max") val playersMax: Double? = null,
)

@Serializable
data class Series(
    val points: List<SeriesPoint> = emptyList(),
    val hours: Double = 6.0,
    @SerialName("bucket_seconds") val bucketSeconds: Double = 60.0,
)

@Serializable
data class Storage(
    @SerialName("worlds_gb") val worldsGb: Double? = null,
    @SerialName("backups_gb") val backupsGb: Double? = null,
    @SerialName("mods_gb") val modsGb: Double? = null,
    @SerialName("logs_gb") val logsGb: Double? = null,
    @SerialName("other_gb") val otherGb: Double? = null,
    @SerialName("free_gb") val freeGb: Double? = null,
    @SerialName("free_unknown_reason") val freeUnknownReason: String? = null,
)

@Serializable
data class Performance(
    val current: Snapshot = Snapshot(),
    val series: Series = Series(),
    @SerialName("sample_interval") val sampleInterval: Double = 30.0,
    @SerialName("memory_limit_mb") val memoryLimitMb: Double? = null,
    val storage: Storage? = null,
)

@Serializable
data class HealthCheck(
    val name: String = "",
    val status: String = "unknown",
    val value: JsonElement? = null,
    val threshold: JsonElement? = null,
    val detail: String? = null,
    val source: String? = null,
)

/** The health checks. An unknown one is never counted as passing. */
@Serializable
data class ServerHealth(
    val overall: String = "",
    val note: String? = null,
    val checks: List<HealthCheck> = emptyList(),
)
