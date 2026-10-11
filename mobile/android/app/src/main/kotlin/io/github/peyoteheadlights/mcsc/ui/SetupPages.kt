package io.github.peyoteheadlights.mcsc.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import io.github.peyoteheadlights.mcsc.core.AgentClient
import io.github.peyoteheadlights.mcsc.core.AgentException
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
}
