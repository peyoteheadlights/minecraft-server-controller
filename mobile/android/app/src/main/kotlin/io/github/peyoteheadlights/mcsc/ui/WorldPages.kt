package io.github.peyoteheadlights.mcsc.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import io.github.peyoteheadlights.mcsc.core.AgentClient
import io.github.peyoteheadlights.mcsc.core.AgentException
import io.github.peyoteheadlights.mcsc.core.Backup
import io.github.peyoteheadlights.mcsc.core.BackupList
import io.github.peyoteheadlights.mcsc.core.Backups
import io.github.peyoteheadlights.mcsc.core.Charts
import io.github.peyoteheadlights.mcsc.core.Job
import io.github.peyoteheadlights.mcsc.core.Offsite
import io.github.peyoteheadlights.mcsc.core.Performance
import io.github.peyoteheadlights.mcsc.core.Schedule
import io.github.peyoteheadlights.mcsc.core.ScheduleList
import io.github.peyoteheadlights.mcsc.core.Schedules
import io.github.peyoteheadlights.mcsc.core.ServerHealth
import io.github.peyoteheadlights.mcsc.core.Strings
import io.github.peyoteheadlights.mcsc.core.WorldList
import io.github.peyoteheadlights.mcsc.core.WorldPoint
import io.github.peyoteheadlights.mcsc.core.WorldRestore
import io.github.peyoteheadlights.mcsc.core.WorldTimeline
import java.io.OutputStream
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch

/** What a button did, said once it is done: good news or a problem. */
data class Said(val text: String, val good: Boolean)

/** A backup on its way to this phone: bytes so far and the size, when the PC said it. */
data class Downloading(val name: String, val done: Long, val size: Long?)

/** A restore waiting for "yes": the backup and what the agent says will happen. */
data class RestoreAsk(val backup: Backup, val willHappen: List<String>)

/**
 * Everything Backups, Restore world, Schedules and Performance show for one
 * server. Each button is the dashboard's own route, with the person's own
 * sign-in, so the agent decides what they may do.
 */
class WorldPages(
    val serverId: String,
    private val scope: CoroutineScope,
    private val client: () -> AgentClient?,
    private val noted: (AgentException) -> Unit,
) {
    /** "backup", "save", "check:4", "restore:4" while that button works. */
    var busy: String? by mutableStateOf(null)
        private set
    var said: Said? by mutableStateOf(null)
        private set

    fun clearSaid() {
        said = null
    }

    // ------------------------------------------------------------ backups
    var backups: Read<BackupList> by mutableStateOf(Read())
        private set
    var offsite: Offsite? by mutableStateOf(null)
        private set
    var worlds: Read<WorldList> by mutableStateOf(Read())
        private set
    var lastChange: Job? by mutableStateOf(null)
        private set
    var restoring: RestoreAsk? by mutableStateOf(null)
        private set

    var downloading: Downloading? by mutableStateOf(null)
        private set

    fun loadBackups() {
        val c = client() ?: return
        backups = backups.copy(loading = true)
        scope.launch {
            try {
                backups = Read(c.backups(serverId))
            } catch (e: AgentException) {
                noted(e)
                backups = backups.copy(problem = Message.of(e), loading = false)
            }
            // As the dashboard: without these the list still shows.
            offsite = try { c.offsite(serverId) } catch (e: AgentException) { null }
            lastChange = try { Backups.lastUndoable(c.jobs(serverId).jobs) } catch (e: AgentException) { null }
            worlds = try { Read(c.worlds(serverId)) } catch (e: AgentException) { Read(problem = Message.of(e)) }
        }
    }

    fun backUp(strings: Strings) = work("backup", strings, reload = ::loadBackups) {
        Said(Backups.made(strings, it.backUp(serverId)), good = true)
    }

    fun saveWorld(strings: Strings) = work("save", strings) {
        it.saveWorld(serverId)
        Said(strings.t("backups.save_sent"), good = true)
    }

    fun check(backup: Backup, strings: Strings) = work("check:${backup.id}", strings) {
        val check = it.checkBackup(serverId, backup.id)
        Said(Backups.checked(strings, check), good = check.ok)
    }

    fun copyAgain(backup: Backup, strings: Strings) = work("copy:${backup.id}", strings, reload = ::loadBackups) {
        val copied = it.copyBackup(serverId, backup.id)
        if (copied.copy?.state == "ok") Said(strings.t("offsite.copy_done"), good = true)
        else Said(strings.t("offsite.copy_failed", "reason" to (copied.copy?.reason ?: strings.t("value.unknown"))), good = false)
    }

    /** Asks the agent what a restore would do; nothing changes yet. */
    fun askRestore(backup: Backup, strings: Strings) = work("restore:${backup.id}", strings) {
        val preview = it.restoreBackup(serverId, backup.id, confirm = false)
        restoring = RestoreAsk(backup, preview.willHappen.orEmpty())
        null
    }

    fun cancelRestore() {
        restoring = null
    }

    fun restore(startAfter: Boolean, strings: Strings) {
        val ask = restoring ?: return
        restoring = null
        work("restore:${ask.backup.id}", strings, reload = ::loadBackups) {
            Said(Backups.restored(strings, it.restoreBackup(serverId, ask.backup.id, confirm = true, startAfter)), good = true)
        }
    }

    fun delete(backup: Backup, strings: Strings) = work("delete:${backup.id}", strings, reload = ::loadBackups) {
        it.deleteBackup(serverId, backup.id)
        Said(strings.t("backups.deleted"), good = true)
    }

    fun undo(job: Job, strings: Strings) = work("undo", strings, reload = ::loadBackups) {
        Said(strings.t("backups.undone", "name" to it.undoJob(job.id).restored), good = true)
    }

    fun offsiteOff(strings: Strings) = work("offsite", strings, reload = ::loadBackups) {
        it.turnOffsiteOff(serverId)
        Said(strings.t("offsite.turned_off"), good = true)
    }

    /** Streams the backup into the file the person chose. [open] gives that
     * file; [discard] removes it again when the download didn't finish. */
    fun download(backup: Backup, open: () -> OutputStream?, discard: () -> Unit, strings: Strings) {
        val c = client() ?: return
        busy = "download:${backup.id}"
        said = null
        downloading = Downloading(backup.name, 0L, backup.sizeBytes)
        scope.launch {
            said = try {
                val out = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) { open() }
                    ?: throw java.io.IOException(strings.t("value.unknown"))
                var shown = -1L
                out.use { stream ->
                    c.downloadBackup(serverId, backup.id, stream) { done, size ->
                        // A step per percent (or per megabyte), not per read.
                        val step = if (size != null && size > 0) done * 100 / size else done / (1024 * 1024)
                        if (step != shown) {
                            shown = step
                            downloading = Downloading(backup.name, done, size)
                        }
                    }
                }
                Said(strings.t("mobile.backups.saved_file", "name" to backup.name), good = true)
            } catch (e: AgentException) {
                noted(e)
                discard()
                Said(Message.of(e).text(strings), good = false)
            } catch (e: java.io.IOException) {
                discard()
                Said(strings.t("mobile.backups.save_failed", "reason" to (e.message ?: strings.t("value.unknown"))), good = false)
            }
            downloading = null
            busy = null
        }
    }

    // ------------------------------------------------------------ restore world
    var timeline: Read<WorldTimeline> by mutableStateOf(Read())
        private set

    fun loadTimeline() = read({ timeline }, { timeline = it }) { it.worldTimeline(serverId) }

    fun restoreWorld(point: WorldPoint, strings: Strings) = work("world:${point.backupId}", strings, reload = ::loadTimeline) {
        Said(WorldRestore.done(strings, it.restoreWorld(serverId, point.backupId)), good = true)
    }

    // ------------------------------------------------------------ schedules
    var schedules: Read<ScheduleList> by mutableStateOf(Read())
        private set

    fun loadSchedules() = read({ schedules }, { schedules = it }) { it.schedules(serverId) }

    fun toggle(schedule: Schedule, strings: Strings) = work("toggle:${schedule.id}", strings, reload = ::loadSchedules) {
        it.updateSchedule(serverId, schedule.id, Schedules.toggled(schedule))
        null
    }

    fun runNow(schedule: Schedule, strings: Strings) = work("run:${schedule.id}", strings, reload = ::loadSchedules) {
        Said(strings.t("mobile.schedules.ran", "name" to schedule.name, "result" to it.runSchedule(serverId, schedule.id).result), good = true)
    }

    fun deleteSchedule(schedule: Schedule, strings: Strings) = work("delete:${schedule.id}", strings, reload = ::loadSchedules) {
        it.deleteSchedule(serverId, schedule.id)
        Said(strings.t("schedules.deleted"), good = true)
    }

    /** Adds a schedule; [added] runs once the agent took it, to empty the form. */
    fun addSchedule(name: String, task: String, kind: String, expr: String, strings: Strings, added: () -> Unit) {
        val tasks = schedules.value?.tasks.orEmpty()
        work("add", strings, reload = ::loadSchedules) {
            it.addSchedule(serverId, Schedules.newBody(strings, name, task, kind, expr, tasks))
            added()
            Said(strings.t("schedules.created"), good = true)
        }
    }

    // ------------------------------------------------------------ performance
    var range: Int by mutableStateOf(Charts.DEFAULT_RANGE)
        private set
    var performance: Read<Performance> by mutableStateOf(Read())
        private set
    var health: Read<ServerHealth> by mutableStateOf(Read())
        private set

    /** When [performance] was read, for drawing the graphs up to then. */
    var readAt: Double by mutableStateOf(0.0)
        private set

    fun loadPerformance() {
        val hours = range
        read({ performance }, { performance = it }) {
            val data = it.performance(serverId, hours)
            readAt = now()
            data
        }
        read({ health }, { health = it }) { it.serverHealth(serverId) }
    }

    fun showRange(hours: Int) {
        if (hours !in Charts.RANGES || hours == range) return
        range = hours
        performance = Read()
        loadPerformance()
    }

    // ------------------------------------------------------------ doing
    private fun work(name: String, strings: Strings, reload: (() -> Unit)? = null, call: suspend (AgentClient) -> Said?) {
        val c = client() ?: return
        if (busy != null) return
        busy = name
        said = null
        scope.launch {
            try {
                call(c)?.let { said = it }
            } catch (e: AgentException) {
                noted(e)
                said = Said(Message.of(e).text(strings), good = false)
            }
            busy = null
            reload?.invoke()
        }
    }

    private fun <T> read(current: () -> Read<T>, store: (Read<T>) -> Unit, call: suspend (AgentClient) -> T) {
        val c = client() ?: return
        store(current().copy(loading = true))
        scope.launch {
            try {
                store(Read(call(c)))
            } catch (e: AgentException) {
                noted(e)
                store(current().copy(problem = Message.of(e), loading = false))
            }
        }
    }
}
