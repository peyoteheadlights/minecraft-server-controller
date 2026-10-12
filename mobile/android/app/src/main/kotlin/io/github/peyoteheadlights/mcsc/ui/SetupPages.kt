package io.github.peyoteheadlights.mcsc.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import io.github.peyoteheadlights.mcsc.core.AgentClient
import io.github.peyoteheadlights.mcsc.core.AgentException
import io.github.peyoteheadlights.mcsc.core.CpuCores
import io.github.peyoteheadlights.mcsc.core.Crossplay
import io.github.peyoteheadlights.mcsc.core.CrossplayInfo
import io.github.peyoteheadlights.mcsc.core.Duplicate
import io.github.peyoteheadlights.mcsc.core.DuplicateOptions
import io.github.peyoteheadlights.mcsc.core.Job
import io.github.peyoteheadlights.mcsc.core.Memory
import io.github.peyoteheadlights.mcsc.core.MemoryOverview
import io.github.peyoteheadlights.mcsc.core.ServerForm
import io.github.peyoteheadlights.mcsc.core.ServerSettings
import io.github.peyoteheadlights.mcsc.core.ServerSettingsSaved
import io.github.peyoteheadlights.mcsc.core.ServerTypeInfo
import io.github.peyoteheadlights.mcsc.core.ServerVersion
import io.github.peyoteheadlights.mcsc.core.Strings
import io.github.peyoteheadlights.mcsc.core.TypeVersions
import io.github.peyoteheadlights.mcsc.core.VersionChange
import io.github.peyoteheadlights.mcsc.core.VersionPreflight
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject

/**
 * Everything the Server settings screen shows for one server: how Command
 * Block runs it. Each button is the dashboard's own route with the
 * person's own sign-in, so the agent decides and explains a refusal.
 * [onListChanged] reloads All servers after a rename or new color.
 */
class SetupPages(
    val serverId: String,
    private val scope: CoroutineScope,
    private val client: () -> AgentClient?,
    private val noted: (AgentException) -> Unit,
    private val onListChanged: () -> Unit,
) {
    var busy: String? by mutableStateOf(null)
        private set
    var said: Said? by mutableStateOf(null)
        private set

    // ------------------------------------------------------------ server settings
    var settings: Read<ServerSettings> by mutableStateOf(Read())
        private set

    /** What the person typed or switched, by key, as text. */
    var edits: Map<String, String> by mutableStateOf(emptyMap())
        private set

    /** Each refused value's reason, by key, from the last Save. */
    var fieldProblems: Map<String, String> by mutableStateOf(emptyMap())
        private set

    /** The color picked or typed; null while it is the saved one. */
    var color: String? by mutableStateOf(null)
        private set

    fun clearSaid() {
        said = null
    }

    fun loadSettings() {
        val c = client() ?: return
        settings = settings.copy(loading = true)
        scope.launch {
            settings = try {
                Read(c.serverSettings(serverId)).also {
                    edits = emptyMap()
                    fieldProblems = emptyMap()
                    color = null
                }
            } catch (e: AgentException) {
                noted(e)
                Read(settings.value, problem = Message.of(e))
            }
        }
    }

    fun edit(key: String, value: String) {
        edits = edits + (key to value)
        fieldProblems = fieldProblems - key
    }

    fun pickColor(hex: String) {
        color = hex
    }

    /** Saves what changed: the settings, then the color. Nothing changed
     * says so; a refused value says why under its field. */
    fun saveSettings(strings: Strings) {
        val current = settings.value ?: return
        val c = client() ?: return
        if (busy != null) return
        val updates = ServerForm.changed(current, edits)
        val newColor = color?.takeIf { !it.equals(current.color, ignoreCase = true) }
        if (updates.isEmpty() && newColor == null) {
            said = Said(ServerForm.saved(strings, sent = false, result = null), good = true)
            return
        }
        busy = "settings"
        said = null
        scope.launch {
            try {
                var result: ServerSettingsSaved? = null
                if (updates.isNotEmpty()) result = c.saveServerSettings(serverId, updates)
                if (newColor != null) c.setColor(serverId, newColor)
                val refused = result?.rejected.orEmpty()
                said = Said(ServerForm.saved(strings, sent = true, result = result), good = refused.isEmpty())
                if (newColor != null || result?.applied?.containsKey(ServerForm.NAME) == true) onListChanged()
                settings = Read(c.serverSettings(serverId))
                color = null
                // The refused values stay as typed, each with its reason.
                edits = edits.filterKeys { it in refused }
                fieldProblems = refused
            } catch (e: AgentException) {
                noted(e)
                said = Said(Message.of(e).text(strings), good = false)
            } finally {
                busy = null
            }
        }
    }

    // ------------------------------------------------------------ CPU cores
    /** Every core ticked; null while it is the saved setting. */
    var allCores: Boolean? by mutableStateOf(null)
        private set

    /** The cores ticked; null while they are the saved ones. */
    var cores: Set<Int>? by mutableStateOf(null)
        private set

    fun saved(): Set<Int> = settings.value?.cpu?.status?.configured.orEmpty().toSet()

    fun everyCore(): Boolean = allCores ?: settings.value?.cpu?.status?.configured.isNullOrEmpty()

    fun pickedCores(): Set<Int> = cores ?: saved()

    fun setAllCores(on: Boolean) {
        allCores = on
        if (on) cores = emptySet()
    }

    fun toggleCore(core: Int) {
        allCores = false
        val now = pickedCores()
        cores = if (core in now) now - core else now + core
    }

    fun pickHalf(count: Int) {
        allCores = false
        cores = CpuCores.half(count)
    }

    fun saveCores(strings: Strings) {
        val c = client() ?: return
        if (busy != null) return
        val chosen = CpuCores.toSave(everyCore(), pickedCores())
        if (chosen == null) {
            said = Said(strings.t("serverset.pick_a_core"), good = false)
            return
        }
        busy = "cores"
        said = null
        scope.launch {
            try {
                val result = c.saveServerSettings(serverId, CpuCores.update(chosen))
                val refused = result.rejected["server.cpu_cores"]
                said = if (refused != null) Said(refused, good = false) else Said(CpuCores.saved(strings, result), good = result.cpuCores?.ok != false)
                if (refused == null) {
                    settings = Read(c.serverSettings(serverId))
                    allCores = null
                    cores = null
                }
            } catch (e: AgentException) {
                noted(e)
                said = Said(Message.of(e).text(strings), good = false)
            } finally {
                busy = null
            }
        }
    }

    // ------------------------------------------------------------ memory
    var memory: Read<MemoryOverview> by mutableStateOf(Read())
        private set

    /** The slider's position; null while it is the saved limit. */
    var memoryChoice: Int? by mutableStateOf(null)
        private set

    fun loadMemory() {
        val c = client() ?: return
        memory = memory.copy(loading = true)
        scope.launch {
            memory = try {
                Read(c.memory(serverId)).also { memoryChoice = null }
            } catch (e: AgentException) {
                noted(e)
                Read(problem = Message.of(e))
            }
        }
    }

    fun slideMemory(mb: Float) {
        val current = memory.value ?: return
        memoryChoice = Memory.snap(current, mb)
    }

    fun saveMemory(strings: Strings) {
        val current = memory.value ?: return
        val c = client() ?: return
        if (busy != null) return
        val mb = memoryChoice ?: Memory.start(current)
        if (mb == current.limitMb) {
            said = Said(strings.t("settings.nothing_changed"), good = true)
            return
        }
        busy = "memory"
        said = null
        scope.launch {
            try {
                val done = c.setMemory(serverId, mb)
                memory = Read(done)
                memoryChoice = null
                said = Said(strings.t(if (done.running) "memory.saved_running" else "memory.saved"), good = true)
            } catch (e: AgentException) {
                noted(e)
                said = Said(Message.of(e).text(strings), good = false)
            } finally {
                busy = null
            }
        }
    }

    // ------------------------------------------------------------ version and type
    var version: Read<ServerVersion> by mutableStateOf(Read())
        private set

    /** This edition's kinds, read when the changer is opened. */
    var types: List<ServerTypeInfo> by mutableStateOf(emptyList())
        private set
    var versions: Read<TypeVersions> by mutableStateOf(Read())
        private set
    var pickedType: String? by mutableStateOf(null)
        private set
    var pickedVersion: String? by mutableStateOf(null)
        private set
    var pickedLoader: String? by mutableStateOf(null)
        private set
    var snapshots: Boolean by mutableStateOf(false)
        private set

    /** The check's report for the picked version; the change needs one. */
    var report: Read<VersionPreflight>? by mutableStateOf(null)
        private set

    /** A version change or roll back running now, from the live feed or
     * found again when the screen opens. */
    var task: Job? by mutableStateOf(null)
        private set

    fun loadVersion() {
        val c = client() ?: return
        version = version.copy(loading = true)
        scope.launch {
            version = try {
                Read(c.serverVersion(serverId))
            } catch (e: AgentException) {
                noted(e)
                Read(problem = Message.of(e))
            }
            // Left while it ran: its progress is shown again.
            if (busy == null) {
                task = runCatching { VersionChange.running(c.jobs(serverId, 10).jobs, serverId) }.getOrNull()
            }
        }
    }

    fun onTask(job: Job) {
        if (job.kind == "duplicate" && job.serverId == serverId) {
            copying = job.takeIf { it.state == "running" }
            if (job.state == "succeeded") onListChanged()
            return
        }
        if (job.kind !in VersionChange.KINDS || job.serverId != serverId) return
        task = job.takeIf { it.state == "running" }
        if (job.state != "running" && busy == null) loadVersion()
    }

    /** Opens the changer: this edition's kinds and the current kind's versions. */
    fun openChanger() {
        val c = client() ?: return
        val current = version.value ?: return
        scope.launch {
            try {
                types = VersionChange.sameEdition(c.serverTypes().types, current)
            } catch (e: AgentException) {
                noted(e)
            }
        }
        if (pickedType == null) pickType(current.type)
    }

    fun pickType(id: String) {
        val c = client() ?: return
        pickedType = id
        pickedVersion = null
        pickedLoader = null
        report = null
        versions = Read(loading = true)
        scope.launch {
            val answer: Read<TypeVersions> = try {
                Read(c.typeVersions(id))
            } catch (e: AgentException) {
                noted(e)
                Read(problem = Message.of(e))
            }
            // Another kind was tapped meanwhile: its own answer is the one shown.
            if (pickedType != id) return@launch
            versions = answer
            answer.value?.let { read ->
                pickedVersion = read.latestStable ?: read.versions.firstOrNull()?.minecraft
                pickedLoader = read.versions.firstOrNull { it.minecraft == pickedVersion }?.loaders?.firstOrNull()
            }
        }
    }

    fun pickVersion(minecraft: String) {
        pickedVersion = minecraft
        pickedLoader = versions.value?.versions?.firstOrNull { it.minecraft == minecraft }?.loaders?.firstOrNull()
        report = null
    }

    fun pickLoader(loader: String) {
        pickedLoader = loader
        report = null
    }

    fun showSnapshots(on: Boolean) {
        snapshots = on
    }

    fun check() {
        val c = client() ?: return
        val type = pickedType ?: return
        val minecraft = pickedVersion ?: return
        report = Read(loading = true)
        scope.launch {
            report = try {
                Read(c.versionPreflight(serverId, type, minecraft, pickedLoader))
            } catch (e: AgentException) {
                noted(e)
                Read(problem = Message.of(e))
            }
        }
    }

    /** After the one confirmation: the server stops, a backup is taken,
     * and the change runs as a task. */
    fun changeVersion(strings: Strings) {
        val checked = report?.value ?: return
        val type = pickedType ?: return
        val minecraft = pickedVersion ?: return
        val c = client() ?: return
        if (busy != null) return
        busy = "version"
        said = null
        scope.launch {
            try {
                val done = c.changeVersion(serverId, type, minecraft, pickedLoader)
                val notes = listOfNotNull(
                    strings.t("version.changed", "version" to VersionChange.target(checked)),
                    strings.t("new.unverified").takeIf { done.verified == false },
                    strings.t("version.crossplay_off").takeIf { done.crossplayTurnedOff == true },
                )
                said = Said(notes.joinToString(" "), good = true)
                report = null
                onListChanged()
            } catch (e: AgentException) {
                noted(e)
                said = Said(Message.of(e).text(strings), good = false)
            } finally {
                busy = null
                task = null
            }
            loadVersion()
        }
    }

    fun rollBack(strings: Strings) = versionWork("roll_back", strings) {
        it.rollBackVersion(serverId)
        Said(strings.t("version.went_back"), good = true)
    }

    /** Only from the person's own tick. */
    fun acceptEula(strings: Strings) = versionWork("eula", strings) {
        it.acceptEula(serverId)
        Said(strings.t("version.eula_done"), good = true)
    }

    private fun versionWork(name: String, strings: Strings, call: suspend (AgentClient) -> Said) {
        val c = client() ?: return
        if (busy != null) return
        busy = name
        said = null
        scope.launch {
            try {
                said = call(c)
            } catch (e: AgentException) {
                noted(e)
                said = Said(Message.of(e).text(strings), good = false)
            } finally {
                busy = null
                task = null
            }
            loadVersion()
        }
    }

    // ------------------------------------------------------------ crossplay
    var crossplay: Read<CrossplayInfo> by mutableStateOf(Read())
        private set

    /** The port typed for Bedrock players. */
    var crossPort: String by mutableStateOf("")
        private set

    fun loadCrossplay() {
        val c = client() ?: return
        crossplay = crossplay.copy(loading = true)
        scope.launch {
            crossplay = try {
                val read = c.crossplay(serverId)
                crossPort = Crossplay.port(read)
                Read(read)
            } catch (e: AgentException) {
                noted(e)
                Read(problem = Message.of(e))
            }
        }
    }

    fun typePort(text: String) {
        crossPort = text.filter(Char::isDigit).take(5)
    }

    fun setCrossplay(on: Boolean, strings: Strings) {
        val c = client() ?: return
        if (busy != null) return
        busy = "crossplay"
        said = null
        scope.launch {
            try {
                crossplay = Read(c.setCrossplay(serverId, on, if (on) Crossplay.typedPort(crossPort) else null))
                said = Said(strings.t(if (on) "cross.on_done" else "cross.off_done"), good = true)
            } catch (e: AgentException) {
                noted(e)
                said = Said(Message.of(e).text(strings), good = false)
            } finally {
                busy = null
            }
        }
    }

    // ------------------------------------------------------------ duplicate
    var copyOptions: Read<DuplicateOptions> by mutableStateOf(Read())
        private set
    var copyName: String by mutableStateOf("")
        private set
    var copyFolder: String by mutableStateOf("")
        private set
    var copyWorld: String by mutableStateOf(Duplicate.COPY)
        private set

    /** The copy running now, from the live feed. */
    var copying: Job? by mutableStateOf(null)
        private set

    fun loadCopyOptions() {
        val c = client() ?: return
        scope.launch {
            copyOptions = try {
                val read = c.duplicateOptions(serverId)
                copyName = read.name
                copyFolder = read.directory
                copyWorld = Duplicate.worlds(read).first()
                Read(read)
            } catch (e: AgentException) {
                noted(e)
                Read(problem = Message.of(e))
            }
        }
    }

    fun nameCopy(text: String) {
        copyName = text.take(ServerForm.NAME_LIMIT)
    }

    fun placeCopy(text: String) {
        copyFolder = text
    }

    fun pickCopyWorld(world: String) {
        copyWorld = world
    }

    fun duplicate(strings: Strings) {
        val c = client() ?: return
        if (busy != null || !Duplicate.ready(copyName, copyFolder)) return
        busy = "duplicate"
        said = null
        scope.launch {
            try {
                copying = c.duplicate(serverId, copyName.trim(), copyFolder.trim(), copyWorld).job
                said = Said(strings.t("dup.started", "name" to copyName.trim()) + " " + strings.t("dup.after"), good = true)
            } catch (e: AgentException) {
                noted(e)
                said = Said(Message.of(e).text(strings), good = false)
            } finally {
                busy = null
            }
        }
    }

    /** Takes this server off the list, then [onRemoved] leaves its screens. */
    fun removeServer(strings: Strings, onRemoved: () -> Unit) {
        val c = client() ?: return
        if (busy != null) return
        busy = "remove"
        said = null
        scope.launch {
            try {
                c.removeServer(serverId)
                onListChanged()
                onRemoved()
            } catch (e: AgentException) {
                noted(e)
                said = Said(Message.of(e).text(strings), good = false)
            } finally {
                busy = null
            }
        }
    }

    /** Saves the Java options typed in Technical mode, then reads the form
     * and the memory card again so both show them. */
    fun saveJavaOptions(args: List<String>, strings: Strings) {
        val c = client() ?: return
        if (busy != null) return
        busy = "java"
        said = null
        scope.launch {
            try {
                val done = c.saveServerSettings(serverId, buildJsonObject { put("server.jvm_args", JsonArray(args.map(::JsonPrimitive))) })
                val refused = done.rejected["server.jvm_args"]
                said = Said(refused ?: strings.t("mobile.raw.args_saved"), good = refused == null)
                loadMemory()
                loadSettings()
            } catch (e: AgentException) {
                noted(e)
                said = Said(Message.of(e).text(strings), good = false)
            } finally {
                busy = null
            }
        }
    }
}

