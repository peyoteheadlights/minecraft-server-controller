package io.github.peyoteheadlights.mcsc.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import io.github.peyoteheadlights.mcsc.core.AgentClient
import io.github.peyoteheadlights.mcsc.core.AgentException
import io.github.peyoteheadlights.mcsc.core.CpuCores
import io.github.peyoteheadlights.mcsc.core.Memory
import io.github.peyoteheadlights.mcsc.core.MemoryOverview
import io.github.peyoteheadlights.mcsc.core.ServerForm
import io.github.peyoteheadlights.mcsc.core.ServerSettings
import io.github.peyoteheadlights.mcsc.core.ServerSettingsSaved
import io.github.peyoteheadlights.mcsc.core.Strings
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch

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
}
