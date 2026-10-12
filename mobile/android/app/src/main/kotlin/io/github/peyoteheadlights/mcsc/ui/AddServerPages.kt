package io.github.peyoteheadlights.mcsc.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import io.github.peyoteheadlights.mcsc.core.AddServer
import io.github.peyoteheadlights.mcsc.core.AgentClient
import io.github.peyoteheadlights.mcsc.core.AgentException
import io.github.peyoteheadlights.mcsc.core.Job
import io.github.peyoteheadlights.mcsc.core.ModpackInspected
import io.github.peyoteheadlights.mcsc.core.NewServerOptions
import io.github.peyoteheadlights.mcsc.core.NewServerRequest
import io.github.peyoteheadlights.mcsc.core.OfferedVersion
import io.github.peyoteheadlights.mcsc.core.PickedFile
import io.github.peyoteheadlights.mcsc.core.ServerAdded
import io.github.peyoteheadlights.mcsc.core.ServerTypeInfo
import io.github.peyoteheadlights.mcsc.core.Strings
import io.github.peyoteheadlights.mcsc.core.TypeVersions
import io.github.peyoteheadlights.mcsc.core.VersionChange
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch

/**
 * The "+" on All servers: a new server, one from a modpack, or one already
 * on the PC. Kept for the whole app, so a server being set up still shows
 * its progress when the screen is opened again. [opened] is the server to
 * open once it exists; the screen opens it and calls [openedShown].
 */
class AddServerPages(
    private val scope: CoroutineScope,
    private val client: () -> AgentClient?,
    private val noted: (AgentException) -> Unit,
    private val onListChanged: () -> Unit,
) {
    var way: String? by mutableStateOf(null)
        private set
    var options: Read<NewServerOptions> by mutableStateOf(Read())
        private set
    var edition: String by mutableStateOf("java")
        private set
    var type: ServerTypeInfo? by mutableStateOf(null)
        private set
    var versions: Read<TypeVersions> by mutableStateOf(Read())
        private set
    var snapshots: Boolean by mutableStateOf(false)
        private set
    var version: OfferedVersion? by mutableStateOf(null)
        private set
    var loader: String? by mutableStateOf(null)
        private set
    var name: String by mutableStateOf("")
    var color: String? by mutableStateOf(null)
    var memoryMb: Int? by mutableStateOf(null)
    /** The folder picked on the PC; the server's own folder goes inside it. */
    var parent: String? by mutableStateOf(null)
    /** Technical mode's typed folder, used as it is. */
    var typedFolder: String? by mutableStateOf(null)
    var ruled: Boolean by mutableStateOf(false)
    var jar: String by mutableStateOf("")
    var pack: ModpackInspected? by mutableStateOf(null)
        private set
    var task: Job? by mutableStateOf(null)
        private set
    var busy: String? by mutableStateOf(null)
        private set
    var said: Said? by mutableStateOf(null)
        private set
    /** Lines shown after adding a server already on the PC: its name and the agent's warnings. */
    var addedLines: List<String> by mutableStateOf(emptyList())
        private set
    var opened: String? by mutableStateOf(null)
        private set
    /** A server already on the PC that came with warnings: it opens when the person is ready. */
    var added: ServerAdded? by mutableStateOf(null)
        private set

    /** The folder that will be sent: the typed one, or a new one inside the picked one. */
    val folder: String
        get() = typedFolder ?: parent?.let { if (way == AddServer.HAVE) it else AddServer.folderFor(it, name) }.orEmpty()

    fun begin(chosen: String) {
        way = chosen
        said = null
        addedLines = emptyList()
        added = null
        if (options.value == null) loadOptions()
    }

    /** Back to the three ways; a pack read but not used is thrown away. */
    fun startOver() {
        dropPack()
        way = null
        type = null
        version = null
        loader = null
        versions = Read()
        name = ""
        parent = null
        typedFolder = null
        ruled = false
        jar = ""
        said = null
        addedLines = emptyList()
        added = null
    }

    /** Leaving the screen: a pack read but not used is thrown away, unless it is being made into a server now. */
    fun leave() {
        if (busy != "create") dropPack()
    }

    /** Opens the server added with warnings, once they've been read. */
    fun openAdded() {
        opened = added?.server?.id
    }

    fun loadOptions() {
        val c = client() ?: return
        options = options.copy(loading = true)
        scope.launch {
            options = try {
                val read = c.newServerOptions()
                color = color ?: read.color
                memoryMb = memoryMb ?: read.memoryMb
                Read(read)
            } catch (e: AgentException) {
                noted(e)
                Read(problem = Message.of(e))
            }
        }
        resume()
    }

    /** A new server still being set up after the app was closed shows its progress again. */
    fun resume() {
        val c = client() ?: return
        scope.launch {
            try {
                AddServer.creating(c.runningJobs().jobs)?.let { task = it }
            } catch (e: AgentException) {
                noted(e)
            }
        }
    }

    fun pickEdition(chosen: String) {
        edition = chosen
        ruled = false
        val read = options.value ?: return
        if (chosen == "bedrock") AddServer.bedrockType(read)?.let(::pickType) else {
            type = null
            version = null
            versions = Read()
        }
    }

    fun pickType(chosen: ServerTypeInfo) {
        type = chosen
        if (way == AddServer.HAVE) return
        version = null
        loader = null
        val c = client() ?: return
        versions = Read(loading = true)
        scope.launch {
            val answer: Read<TypeVersions> = try {
                Read(c.typeVersions(chosen.id))
            } catch (e: AgentException) {
                noted(e)
                Read(problem = Message.of(e))
            }
            // Another kind was tapped meanwhile: its own answer is the one shown.
            if (type?.id != chosen.id) return@launch
            versions = answer
            version = answer.value?.let(AddServer::firstVersion)
            loader = version?.loaders?.firstOrNull()
        }
    }

    fun showSnapshots(on: Boolean) {
        snapshots = on
    }

    fun choices(): List<OfferedVersion> = versions.value?.let { VersionChange.choices(it, snapshots) }.orEmpty()

    fun pickVersion(minecraft: String) {
        version = versions.value?.versions?.firstOrNull { it.minecraft == minecraft }
        loader = version?.loaders?.firstOrNull()
    }

    fun pickLoader(chosen: String) {
        loader = chosen
    }

    fun nudgeMemory(stepMb: Int) {
        val now = memoryMb ?: return
        memoryMb = AddServer.nudged(now, stepMb, options.value?.totalMb)
    }

    fun create(strings: Strings) {
        val c = client() ?: return
        val kind = type ?: return
        val chosen = version ?: return
        if (busy != null) return
        busy = "create"
        said = null
        val request = NewServerRequest(
            name.trim(), folder, kind.id, chosen.minecraft, loader.takeIf { kind.picksLoader },
            memoryMb.takeIf { AddServer.memoryShown(kind) }, color, eulaAccepted = ruled,
        )
        scope.launch {
            try {
                val made = c.createServer(request)
                done(strings, made.serverId, made.name)
            } catch (e: AgentException) {
                noted(e)
                said = Said(Message.of(e).text(strings), good = false)
            } finally {
                busy = null
                task = null
            }
        }
    }

    fun add(strings: Strings) {
        val c = client() ?: return
        val kind = type ?: return
        if (busy != null) return
        busy = "add"
        said = null
        scope.launch {
            try {
                val result = c.addServer(name.trim(), folder, kind.id, jar.trim())
                addedLines = AddServer.addedLines(strings, result)
                onListChanged()
                // Warnings stay on screen so they can be fixed before starting.
                if (result.warnings.isEmpty()) opened = result.server.id else added = result
            } catch (e: AgentException) {
                noted(e)
                said = Said(Message.of(e).text(strings), good = false)
            } finally {
                busy = null
            }
        }
    }

    fun inspect(file: PickedFile, strings: Strings) {
        val c = client() ?: return
        if (busy != null) return
        busy = "inspect"
        said = null
        scope.launch {
            try {
                dropPack()
                pack = c.inspectModpack(null, file).also { if (name.isBlank()) name = it.pack.name }
            } catch (e: AgentException) {
                noted(e)
                said = Said(Message.of(e).text(strings), good = false)
            } finally {
                busy = null
            }
        }
    }

    fun createFromPack(strings: Strings) {
        val c = client() ?: return
        val read = pack ?: return
        if (busy != null) return
        busy = "create"
        said = null
        scope.launch {
            try {
                val made = c.modpackServer(read.token, name.trim(), folder, memoryMb, color, eulaAccepted = ruled)
                pack = null
                done(strings, made.serverId, made.name)
            } catch (e: AgentException) {
                noted(e)
                said = Said(Message.of(e).text(strings), good = false)
            } finally {
                busy = null
                task = null
            }
        }
    }

    /** Throws an uploaded pack away on the agent. */
    fun dropPack() {
        val token = pack?.token ?: return
        pack = null
        val c = client() ?: return
        scope.launch {
            try {
                c.forgetModpack(token)
            } catch (e: AgentException) {
                noted(e)
            }
        }
    }

    fun onTask(job: Job) {
        if (job.kind != "server_create") return
        task = job.takeIf { it.state == "running" }
        if (job.state == "succeeded") onListChanged()
    }

    fun openedShown() {
        opened = null
        startOver()
    }

    private fun done(strings: Strings, serverId: String, made: String) {
        said = Said(strings.t("new.created", "name" to made), good = true)
        onListChanged()
        opened = serverId
    }
}
