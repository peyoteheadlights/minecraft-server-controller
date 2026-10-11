package io.github.peyoteheadlights.mcsc.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import io.github.peyoteheadlights.mcsc.core.AgentClient
import io.github.peyoteheadlights.mcsc.core.AgentException
import io.github.peyoteheadlights.mcsc.core.Backup
import io.github.peyoteheadlights.mcsc.core.BackupList
import io.github.peyoteheadlights.mcsc.core.Backups
import io.github.peyoteheadlights.mcsc.core.Change
import io.github.peyoteheadlights.mcsc.core.ChangeList
import io.github.peyoteheadlights.mcsc.core.Charts
import io.github.peyoteheadlights.mcsc.core.Job
import io.github.peyoteheadlights.mcsc.core.Offsite
import io.github.peyoteheadlights.mcsc.core.Performance
import io.github.peyoteheadlights.mcsc.core.PickedFile
import io.github.peyoteheadlights.mcsc.core.SavedWorlds
import io.github.peyoteheadlights.mcsc.core.Schedule
import io.github.peyoteheadlights.mcsc.core.ScheduleList
import io.github.peyoteheadlights.mcsc.core.Schedules
import io.github.peyoteheadlights.mcsc.core.ServerHealth
import io.github.peyoteheadlights.mcsc.core.Storage
import io.github.peyoteheadlights.mcsc.core.Strings
import io.github.peyoteheadlights.mcsc.core.UndoRedo
import io.github.peyoteheadlights.mcsc.core.WorldImport
import io.github.peyoteheadlights.mcsc.core.WorldList
import io.github.peyoteheadlights.mcsc.core.WorldPoint
import io.github.peyoteheadlights.mcsc.core.WorldRead
import io.github.peyoteheadlights.mcsc.core.WorldRestore
import io.github.peyoteheadlights.mcsc.core.WorldTimeline
import java.io.File
import java.io.OutputStream
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch

/** What a button did, said once it is done: good news or a problem. */
data class Said(val text: String, val good: Boolean)

/** A backup on its way to this phone: bytes so far and the size, when the PC said it. */
data class Downloading(val name: String, val done: Long, val size: Long?)

/** A restore waiting for "yes": the backup and what the agent says will happen. */
data class RestoreAsk(val backup: Backup, val willHappen: List<String>)

/** Undo or Redo waiting for "yes": "undo" or "redo", and the change it moves. */
data class MoveAsk(val direction: String, val change: Change)

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
    /** The Undo and Redo lists; null until read, or when they couldn't be. */
    var changes: UndoRedo? by mutableStateOf(null)
        private set
    var moving: MoveAsk? by mutableStateOf(null)
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
            changes = try { c.changes(serverId) } catch (e: AgentException) { null }
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

    /** A task finished on another device (or here) may have added a change:
     * read the lists again while Backups is open. */
    fun onTask(job: Job) {
        if (job.state in Backups.FINISHED && backups.loaded && busy == null) loadBackups()
    }

    /** Asks before Undo ("undo") or Redo ("redo") of the first change on that list. */
    fun askMove(direction: String) {
        val lists = changes ?: return
        moving = (if (direction == "undo") lists.undo else lists.redo).firstOrNull()?.let { MoveAsk(direction, it) }
    }

    fun cancelMove() {
        moving = null
    }

    fun move(startAfter: Boolean, strings: Strings) {
        val ask = moving ?: return
        moving = null
        work(ask.direction, strings, reload = ::loadBackups) {
            Said(ChangeList.done(strings, ask.direction, it.moveChange(serverId, ask.direction, startAfter)), good = true)
        }
    }

    fun setOffsite(directory: String, strings: Strings) = work("offsite", strings, reload = ::loadBackups) {
        it.setOffsite(serverId, directory)
        Said(strings.t("offsite.saved"), good = true)
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
                out.use { stream ->
                    c.downloadBackup(serverId, backup.id, stream, steps { done, size -> downloading = Downloading(backup.name, done, size) })
                }
                Said(strings.t("mobile.backups.saved_file", "name" to backup.name), good = true)
            } catch (e: AgentException) {
                noted(e)
                discard()
                Said(Message.of(e).text(strings), good = false)
            } catch (e: kotlinx.coroutines.CancellationException) {
                discard()
                throw e
            } catch (e: Exception) {
                // Writing on the phone failed (full, or the place picked
                // refused it): said as such, never as the PC's problem.
                discard()
                Said(strings.t("mobile.backups.save_failed", "reason" to (e.message ?: strings.t("value.unknown"))), good = false)
            } finally {
                downloading = null
                busy = null
            }
        }
    }

    // ------------------------------------------------------------ restore world
    var timeline: Read<WorldTimeline> by mutableStateOf(Read())
        private set

    fun loadTimeline() = read({ timeline }, { timeline = it }) { it.worldTimeline(serverId) }

    fun restoreWorld(point: WorldPoint, strings: Strings) = work("world:${point.backupId}", strings, reload = ::loadTimeline) {
        Said(WorldRestore.done(strings, it.restoreWorld(serverId, point.backupId)), good = true)
    }

    // ------------------------------------------------------------ bringing a world in, taking it home
    /** Single-player's worlds on the PC; null until read or when they couldn't be. */
    var saves: SavedWorlds? by mutableStateOf(null)
        private set
    /** A world zip on its way to the PC: bytes sent so far and its size. */
    var sending: Downloading? by mutableStateOf(null)
        private set
    /** The world read and waiting for "Replace world" (or Cancel). */
    var worldRead: WorldRead? by mutableStateOf(null)
        private set
    private var sendJob: kotlinx.coroutines.Job? = null

    fun loadSaves() {
        val c = client() ?: return
        scope.launch { saves = try { c.savedWorlds(serverId) } catch (e: AgentException) { null } }
    }

    /** Sends a world's zip picked on the phone; the agent reads it and nothing changes yet. */
    fun sendWorld(file: PickedFile, strings: Strings) {
        val c = client() ?: return
        if (busy != null) return
        if (!WorldImport.accepts(file.name)) {
            said = Said(strings.t("mobile.import.not_a_world"), good = false)
            return
        }
        busy = "import"
        said = null
        sending = Downloading(file.name, 0L, file.size)
        sendJob = scope.launch {
            try {
                worldRead = c.uploadWorld(serverId, file, steps { done, size -> sending = Downloading(file.name, done, size) })
            } catch (e: AgentException) {
                noted(e)
                said = Said(Message.of(e).text(strings), good = false)
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                said = Said(strings.t("mobile.error.failed", "reason" to (e.message ?: strings.t("value.unknown"))), good = false)
            } finally {
                sending = null
                busy = null
                sendJob = null
            }
        }
    }

    /** Stops sending; the agent throws away the part it got. */
    fun cancelSending() {
        sendJob?.cancel()
    }

    /** Reads a world folder on the PC (picked, or one of single-player's saves). */
    fun pickWorldFolder(path: String, strings: Strings) = work("import", strings) {
        worldRead = it.pickWorldFolder(serverId, path)
        null
    }

    /** Cancel on the read world: the agent forgets it. */
    fun forgetWorld() {
        val read = worldRead ?: return
        worldRead = null
        val c = client() ?: return
        scope.launch { runCatching { c.forgetWorld(serverId, read.token) } }
    }

    /** Replaces this server's world with the one read; the backup made first is on the Undo list. */
    fun importWorld(strings: Strings) {
        val read = worldRead ?: return
        worldRead = null
        work("import", strings, reload = {
            loadTimeline()
            if (backups.loaded) loadBackups()
        }) {
            Said(WorldImport.done(strings, it.importWorld(serverId, read.token)), good = true)
        }
    }

    /** Packs the world as a zip, downloads it into [folder] (only the newest
     * is kept there) and hands it to [share] for the phone's share menu. */
    fun takeHome(folder: File, strings: Strings, share: (File) -> Unit) {
        val c = client() ?: return
        if (busy != null) return
        busy = "take_home"
        said = null
        scope.launch {
            try {
                val packed = c.packWorld(serverId)
                val name = packed.filename.substringAfterLast('/').substringAfterLast('\\').ifBlank { "world.zip" }
                downloading = Downloading(name, 0L, packed.sizeBytes)
                val file = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
                    folder.mkdirs()
                    folder.listFiles()?.forEach { it.delete() }
                    File(folder, name)
                }
                try {
                    file.outputStream().use { out ->
                        c.downloadWorld(serverId, packed, out, steps { done, size -> downloading = Downloading(name, done, size) })
                    }
                } catch (e: Exception) {
                    file.delete()
                    throw e
                }
                share(file)
            } catch (e: AgentException) {
                noted(e)
                said = Said(Message.of(e).text(strings), good = false)
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                said = Said(strings.t("mobile.download.save_failed", "reason" to (e.message ?: strings.t("value.unknown"))), good = false)
            } finally {
                downloading = null
                busy = null
            }
        }
    }

    /** Passes progress on a step per percent (or per megabyte), not per read. */
    private fun steps(show: (Long, Long?) -> Unit): (Long, Long?) -> Unit {
        var shown = -1L
        return { done, size ->
            val step = if (size != null && size > 0) done * 100 / size else done / (1024 * 1024)
            if (step != shown) {
                shown = step
                show(done, size)
            }
        }
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

    /** Counts performance reads, so an answer for a range no longer shown is dropped. */
    private var performanceRead = 0

    fun loadPerformance() {
        loadSeries(storage = true)
        read({ health }, { health = it }) { it.serverHealth(serverId) }
    }

    /** Only the graphs change with the range: the disk use and the health
     * checks (both slow on the PC) are kept from the last full read. */
    fun showRange(hours: Int) {
        if (hours !in Charts.RANGES || hours == range) return
        val kept = performance.value?.storage
        range = hours
        performance = Read()
        loadSeries(storage = false, kept = kept)
    }

    private fun loadSeries(storage: Boolean, kept: Storage? = null) {
        val c = client() ?: return
        val hours = range
        val mine = ++performanceRead
        performance = performance.copy(loading = true)
        scope.launch {
            try {
                val data = c.performance(serverId, hours, storage)
                if (mine != performanceRead) return@launch
                performance = Read(if (storage) data else data.copy(storage = kept))
                readAt = now()
            } catch (e: AgentException) {
                if (mine != performanceRead) return@launch
                noted(e)
                performance = performance.copy(problem = Message.of(e), loading = false)
            }
        }
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
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (e: Exception) {
                said = Said(strings.t("mobile.error.failed", "reason" to (e.message ?: strings.t("value.unknown"))), good = false)
            } finally {
                busy = null
            }
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
