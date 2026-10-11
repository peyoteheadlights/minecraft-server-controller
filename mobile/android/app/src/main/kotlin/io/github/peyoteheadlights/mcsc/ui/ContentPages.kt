package io.github.peyoteheadlights.mcsc.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import io.github.peyoteheadlights.mcsc.core.AddonList
import io.github.peyoteheadlights.mcsc.core.Addon
import io.github.peyoteheadlights.mcsc.core.AgentClient
import io.github.peyoteheadlights.mcsc.core.AgentException
import io.github.peyoteheadlights.mcsc.core.Content
import io.github.peyoteheadlights.mcsc.core.DependencyPlan
import io.github.peyoteheadlights.mcsc.core.DependencyReport
import io.github.peyoteheadlights.mcsc.core.GameForm
import io.github.peyoteheadlights.mcsc.core.GameSettings
import io.github.peyoteheadlights.mcsc.core.Install
import io.github.peyoteheadlights.mcsc.core.Job
import io.github.peyoteheadlights.mcsc.core.Mod
import io.github.peyoteheadlights.mcsc.core.ModHistory
import io.github.peyoteheadlights.mcsc.core.ModImpact
import io.github.peyoteheadlights.mcsc.core.ModList
import io.github.peyoteheadlights.mcsc.core.ModProject
import io.github.peyoteheadlights.mcsc.core.ModVersion
import io.github.peyoteheadlights.mcsc.core.ModVersions
import io.github.peyoteheadlights.mcsc.core.ModpackInspected
import io.github.peyoteheadlights.mcsc.core.ModrinthHit
import io.github.peyoteheadlights.mcsc.core.PickedFile
import io.github.peyoteheadlights.mcsc.core.Strings
import io.github.peyoteheadlights.mcsc.core.UpdateAll
import io.github.peyoteheadlights.mcsc.core.UpdateAllPlan
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch

/** A remove waiting for "yes", with what else needs the mod. */
data class RemoveAsk(val mod: Mod, val impact: ModImpact)

/** The kept versions of one mod, shown to roll back to. */
data class VersionsAsk(val mod: Mod, val versions: Read<ModVersions>)

/** Search results so far, and whether more can be asked for. */
data class Found(val query: String, val hits: List<ModrinthHit>, val total: Int?) {
    val more: Boolean get() = total != null && hits.size < total
}

/**
 * Everything the Mods / Plugins / Packs and Game settings screens show for
 * one server. Every button is the dashboard's own route with the person's
 * own sign-in, so the agent decides what they may do and explains a refusal.
 */
class ContentPages(
    val serverId: String,
    private val scope: CoroutineScope,
    private val client: () -> AgentClient?,
    private val noted: (AgentException) -> Unit,
) {
    /** "toggle:file", "remove:file", "update:file", "update_all", ... while that button works. */
    var busy: String? by mutableStateOf(null)
        private set
    var said: Said? by mutableStateOf(null)
        private set

    fun clearSaid() {
        said = null
    }

    /** Something the phone itself says, like a file of the wrong kind. */
    fun tell(words: Said) {
        said = words
    }

    // ------------------------------------------------------------ installed
    var mods: Read<ModList> by mutableStateOf(Read())
        private set
    var history: Read<ModHistory> by mutableStateOf(Read())
        private set
    var dependencies: DependencyReport? by mutableStateOf(null)
        private set
    var removing: RemoveAsk? by mutableStateOf(null)
        private set
    var updating: Mod? by mutableStateOf(null)
        private set
    var versions: VersionsAsk? by mutableStateOf(null)
        private set

    fun loadMods() {
        val c = client() ?: return
        mods = mods.copy(loading = true)
        scope.launch {
            try {
                mods = Read(c.mods(serverId))
            } catch (e: AgentException) {
                noted(e)
                // Never the old list as if current: Unknown until the PC answers.
                mods = Read(problem = Message.of(e))
                dependencies = null
                return@launch
            }
            // As the dashboard: the list still shows without these.
            dependencies = try { c.dependencies(serverId) } catch (e: AgentException) { null }
            history = try { Read(c.modHistory(serverId)) } catch (e: AgentException) { Read(problem = Message.of(e)) }
        }
    }

    fun setEnabled(mod: Mod, on: Boolean, strings: Strings) = work("toggle:${mod.filename}", strings, reload = ::loadMods) {
        it.setModEnabled(serverId, mod.filename, on)
        Said(strings.t(if (on) "mods.turned_on" else "mods.turned_off", "name" to mod.name), good = true)
    }

    /** Asks the agent what else needs [mod]; nothing changes yet. */
    fun askRemove(mod: Mod, strings: Strings) = work("remove:${mod.filename}", strings) {
        removing = RemoveAsk(mod, it.modImpact(serverId, mod.filename))
        null
    }

    fun cancelRemove() {
        removing = null
    }

    fun remove(strings: Strings) {
        val ask = removing ?: return
        removing = null
        work("remove:${ask.mod.filename}", strings, reload = ::loadMods) {
            it.removeMod(serverId, ask.mod.filename)
            Said(strings.t("mods.removed_toast", "name" to ask.mod.name), good = true)
        }
    }

    fun askUpdate(mod: Mod) {
        updating = mod
    }

    fun cancelUpdate() {
        updating = null
    }

    fun update(strings: Strings) {
        val mod = updating ?: return
        updating = null
        work("update:${mod.filename}", strings, reload = ::loadMods) {
            val done = it.updateMod(serverId, mod.filename, mod.updateAvailable?.versionId)
            Said(strings.t("mods.updated_toast", "version" to (done.updated?.version ?: strings.t("value.unknown"))), good = true)
        }
    }

    fun showVersions(mod: Mod) {
        val c = client() ?: return
        versions = VersionsAsk(mod, Read(loading = true))
        scope.launch {
            val read = try {
                Read(c.modVersions(serverId, mod.modId))
            } catch (e: AgentException) {
                noted(e)
                Read(problem = Message.of(e))
            }
            if (versions?.mod == mod) versions = VersionsAsk(mod, read)
        }
    }

    fun closeVersions() {
        versions = null
    }

    fun rollBack(version: ModVersion, strings: Strings) {
        val ask = versions ?: return
        if (!Content.canRollBack(version)) return
        versions = null
        work("rollback:${ask.mod.filename}", strings, reload = ::loadMods) {
            val done = it.rollBackMod(serverId, ask.mod.modId, version.archivePath)
            Said(strings.t("mods.rolled_back", "version" to (done.restored?.version ?: version.version ?: strings.t("value.unknown"))), good = true)
        }
    }

    // ------------------------------------------------------------ update all
    var plan: Read<UpdateAllPlan>? by mutableStateOf(null)
        private set
    var ticked: Set<String> by mutableStateOf(emptySet())
        private set

    /** The live feed's latest word on a task of this server. */
    var task: Job? by mutableStateOf(null)
        private set

    fun onTask(job: Job) {
        task = job
    }

    /** Asks Modrinth (through the PC) what Update all would change. */
    fun openUpdateAll() {
        val c = client() ?: return
        plan = Read(loading = true)
        scope.launch {
            plan = try {
                val read = c.updateAllPlan(serverId)
                ticked = UpdateAll.ticked(read)
                Read(read)
            } catch (e: AgentException) {
                noted(e)
                Read(problem = Message.of(e))
            }
        }
    }

    fun tick(filename: String, on: Boolean) {
        ticked = if (on) ticked + filename else ticked - filename
    }

    fun closeUpdateAll() {
        plan = null
    }

    fun updateAll(strings: Strings) {
        val read = plan?.value ?: return
        val body = UpdateAll.body(read, ticked)
        plan = null
        task = null
        work("update_all", strings, reload = ::loadMods) {
            Said(UpdateAll.done(strings, it.updateAll(serverId, body)), good = true)
        }
    }

    // ------------------------------------------------------------ Modrinth
    var found: Read<Found>? by mutableStateOf(null)
        private set
    var project: Read<ModProject>? by mutableStateOf(null)
        private set
    var missingPlan: Read<DependencyPlan>? by mutableStateOf(null)
        private set

    /** Counts searches, so an answer for an older query is dropped. */
    private var searchRead = 0

    fun search(query: String) {
        val c = client() ?: return
        val q = query.trim()
        if (q.isEmpty()) return
        val mine = ++searchRead
        found = Read(loading = true)
        scope.launch {
            val read = try {
                val page = c.searchMods(serverId, q)
                Read(Found(q, page.hits, page.total))
            } catch (e: AgentException) {
                noted(e)
                Read(problem = Message.of(e))
            }
            if (mine == searchRead) found = read
        }
    }

    fun searchMore() {
        val c = client() ?: return
        val now = found?.value ?: return
        if (!now.more || found?.loading == true) return
        val mine = ++searchRead
        found = Read(now, loading = true)
        scope.launch {
            val read = try {
                val page = c.searchMods(serverId, now.query, offset = now.hits.size)
                Read(Found(now.query, now.hits + page.hits.filter { hit -> now.hits.none { it.slug == hit.slug } }, page.total))
            } catch (e: AgentException) {
                noted(e)
                Read(now, problem = Message.of(e))
            }
            if (mine == searchRead) found = read
        }
    }

    /** Reads a project's versions that fit this server, for the install question. */
    fun openProject(hit: ModrinthHit) {
        val c = client() ?: return
        project = Read(loading = true)
        scope.launch {
            project = try {
                Read(c.modProject(serverId, hit.slug))
            } catch (e: AgentException) {
                noted(e)
                Read(problem = Message.of(e))
            }
        }
    }

    fun closeProject() {
        project = null
    }

    fun install(withDependencies: Boolean, strings: Strings) {
        val read = project?.value ?: return
        val version = Install.latest(read) ?: return
        project = null
        work("install:${read.project.slug}", strings, reload = ::loadMods) {
            val done = it.installMod(serverId, read.project.slug, version.versionId, withDependencies)
            val name = done.installed?.name ?: read.project.title
            Said(strings.t("mobile.content.installed", "name" to name, "version" to (done.installed?.version ?: version.versionNumber ?: strings.t("value.unknown"))), good = true)
        }
    }

    /** What "Install the missing ones" would download; nothing is yet. */
    fun planMissing() {
        val c = client() ?: return
        missingPlan = Read(loading = true)
        scope.launch {
            missingPlan = try {
                Read(c.planDependencies(serverId))
            } catch (e: AgentException) {
                noted(e)
                Read(problem = Message.of(e))
            }
        }
    }

    fun closeMissing() {
        missingPlan = null
    }

    fun installMissing(strings: Strings) {
        missingPlan = null
        work("missing", strings, reload = ::loadMods) {
            val results = it.installDependencies(serverId).results
            val words = results.joinToString(", ") { r -> "${r.title} (${strings.t(if (r.result == "ok") "mobile.content.result_ok" else "mobile.content.result_failed")})" }
            Said(strings.t("mobile.content.missing_done", "results" to words), good = results.all { r -> r.result == "ok" })
        }
    }

    // ------------------------------------------------------------ files
    var modpack: ModpackInspected? by mutableStateOf(null)
        private set

    fun uploadMod(file: PickedFile, strings: Strings) = work("upload", strings, reload = ::loadMods) {
        val done = it.uploadMod(serverId, file)
        Said(strings.t("mobile.content.added", "name" to (done.installed?.name ?: file.name)), good = true)
    }

    /** Reads the modpack on the PC; nothing changes until Import. */
    fun inspectModpack(file: PickedFile, strings: Strings) = work("modpack", strings) {
        modpack = it.inspectModpack(serverId, file)
        null
    }

    /** No import after all: the PC forgets the pack it read. */
    fun cancelModpack() {
        val token = modpack?.token ?: return
        modpack = null
        val c = client() ?: return
        scope.launch {
            try { c.forgetModpack(token) } catch (e: AgentException) { /* The PC drops it later itself. */ }
        }
    }

    fun importModpack(strings: Strings) {
        val read = modpack ?: return
        modpack = null
        task = null
        work("modpack", strings, reload = ::loadMods) {
            val done = it.importModpack(serverId, read.token)
            Said(strings.t("mobile.content.modpack_done", "name" to done.modpack.name.ifBlank { read.pack.name }), good = true)
        }
    }

    // ------------------------------------------------------------ Bedrock packs
    var addons: Read<AddonList> by mutableStateOf(Read())
        private set

    /** Set after a pack change while the server runs: "Restart now" shows. */
    var restartOffered: Boolean by mutableStateOf(false)
        private set

    fun loadAddons() {
        val c = client() ?: return
        addons = addons.copy(loading = true)
        scope.launch {
            addons = try {
                Read(c.addons(serverId))
            } catch (e: AgentException) {
                noted(e)
                Read(problem = Message.of(e))
            }
        }
    }

    fun setAddon(addon: Addon, on: Boolean, strings: Strings) = work("pack:${addon.uuid}", strings, reload = ::loadAddons) {
        restartOffered = it.setAddonEnabled(serverId, addon.uuid, on).restartNeeded == true
        Said(strings.t(if (on) "addons.turned_on" else "addons.turned_off", "name" to addon.name), good = true)
    }

    fun removeAddon(addon: Addon, strings: Strings) = work("pack:${addon.uuid}", strings, reload = ::loadAddons) {
        restartOffered = it.removeAddon(serverId, addon.uuid).restartNeeded == true
        Said(strings.t("addons.removed", "name" to addon.name), good = true)
    }

    fun uploadAddon(file: PickedFile, strings: Strings) = work("upload", strings, reload = ::loadAddons) {
        val done = it.uploadAddon(serverId, file)
        restartOffered = done.restartNeeded == true
        Said(strings.t("addons.installed_done", "name" to done.installed.joinToString(", ") { a -> a.name }.ifBlank { file.name }), good = true)
    }

    fun restarted() {
        restartOffered = false
    }

    // ------------------------------------------------------------ game settings
    var game: Read<GameSettings> by mutableStateOf(Read())
        private set

    /** What the person typed or picked, by key, as text. */
    var edits: Map<String, String> by mutableStateOf(emptyMap())
        private set

    /** Each refused value's reason, by key, from the last Save. */
    var fieldProblems: Map<String, String> by mutableStateOf(emptyMap())
        private set

    /** Saved while running: "Restart now" shows next to the words. */
    var gameRestart: Boolean by mutableStateOf(false)
        private set

    fun loadGame() {
        val c = client() ?: return
        game = game.copy(loading = true)
        scope.launch {
            game = try {
                Read(c.gameSettings(serverId)).also {
                    edits = emptyMap()
                    fieldProblems = emptyMap()
                }
            } catch (e: AgentException) {
                noted(e)
                Read(problem = Message.of(e))
            }
        }
    }

    fun edit(key: String, value: String) {
        edits = edits + (key to value)
        fieldProblems = fieldProblems - key
    }

    /** True when Save would send something. */
    fun gameChanged(): Boolean {
        val settings = game.value ?: return false
        return GameForm.changed(settings, edits).isNotEmpty()
    }

    fun saveGame(strings: Strings) {
        val settings = game.value ?: return
        val values = GameForm.changed(settings, edits)
        val c = client() ?: return
        if (busy != null) return
        busy = "game"
        said = null
        scope.launch {
            try {
                val done = c.saveGameSettings(serverId, values)
                said = Said(GameForm.saved(strings, done), good = true)
                gameRestart = done.running && done.nothingChanged != true
                loadGame()
            } catch (e: AgentException.Failed) {
                noted(e)
                fieldProblems = e.problems
                said = Said(if (e.problems.isNotEmpty()) strings.t("mobile.game.fix_marked") else Message.of(e).text(strings), good = false)
            } catch (e: AgentException) {
                noted(e)
                said = Said(Message.of(e).text(strings), good = false)
            } finally {
                busy = null
            }
        }
    }

    fun gameRestarted() {
        gameRestart = false
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
                // Reading the picked file on the phone failed: said as such.
                said = Said(strings.t("mobile.error.failed", "reason" to (e.message ?: strings.t("value.unknown"))), good = false)
            } finally {
                busy = null
            }
            reload?.invoke()
        }
    }
}
