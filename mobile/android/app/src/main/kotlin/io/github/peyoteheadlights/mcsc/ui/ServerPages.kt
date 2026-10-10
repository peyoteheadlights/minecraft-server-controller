package io.github.peyoteheadlights.mcsc.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import io.github.peyoteheadlights.mcsc.core.AgentClient
import io.github.peyoteheadlights.mcsc.core.AgentException
import io.github.peyoteheadlights.mcsc.core.ChatBuffer
import io.github.peyoteheadlights.mcsc.core.ChatMessage
import io.github.peyoteheadlights.mcsc.core.Checklist
import io.github.peyoteheadlights.mcsc.core.CommandStep
import io.github.peyoteheadlights.mcsc.core.ConsoleBuffer
import io.github.peyoteheadlights.mcsc.core.ConsoleCommands
import io.github.peyoteheadlights.mcsc.core.ConsoleLine
import io.github.peyoteheadlights.mcsc.core.Crash
import io.github.peyoteheadlights.mcsc.core.EventRow
import io.github.peyoteheadlights.mcsc.core.JoinInfo
import io.github.peyoteheadlights.mcsc.core.PlayerAction
import io.github.peyoteheadlights.mcsc.core.PlayerActionWatch
import io.github.peyoteheadlights.mcsc.core.PlayerActions
import io.github.peyoteheadlights.mcsc.core.PlayersPage
import io.github.peyoteheadlights.mcsc.core.Recommendations
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch

/** A reading that can fail: what was read, when, and what went wrong
 * the last time. Screens hide [value] while [problem] is set when the
 * value is a current state (players, the cards), so nothing old is shown
 * as current. */
data class Read<T>(val value: T? = null, val problem: Message? = null, val loading: Boolean = false) {
    val loaded: Boolean get() = value != null
}

/**
 * Everything the Console, Chat, Players, Activity, Crashes and Overview
 * cards show for one server. Reads go through [client] with the person's
 * own sign-in, so the agent decides what they may see and do.
 */
class ServerPages(
    val serverId: String,
    private val scope: CoroutineScope,
    private val client: () -> AgentClient?,
    private val noted: (AgentException) -> Unit,
) {
    // ------------------------------------------------------------ console
    var console: Read<List<ConsoleLine>> by mutableStateOf(Read())
        private set
    var history: List<String> by mutableStateOf(emptyList())
        private set
    var asking: CommandStep.AskFirst? by mutableStateOf(null)
        private set
    var commandProblem: Message? by mutableStateOf(null)
        private set
    var sending: Boolean by mutableStateOf(false)
        private set

    fun loadConsole() = load({ console }, { console = it }) { ConsoleBuffer.replace(it.consoleLog(serverId).lines) }

    fun onConsoleLine(line: ConsoleLine) {
        console = console.copy(value = ConsoleBuffer.add(console.value.orEmpty(), line))
    }

    fun onConsoleTail(lines: List<ConsoleLine>) {
        console = Read(ConsoleBuffer.replace(lines))
    }

    fun clearConsole() {
        val c = client() ?: return
        scope.launch {
            try {
                c.clearConsole(serverId)
                console = Read(emptyList())
            } catch (e: AgentException) {
                noted(e)
                commandProblem = Message.of(e)
            }
        }
    }

    /** Sends [text] as the dashboard does; [sent] runs once it went, to
     * empty the box. A risky command waits in [asking]. */
    fun submitCommand(text: String, sent: () -> Unit) {
        val c = client() ?: return
        commandProblem = null
        sending = true
        scope.launch {
            try {
                when (val step = ConsoleCommands(c, serverId).submit(text)) {
                    CommandStep.Empty -> Unit
                    is CommandStep.Invalid ->
                        commandProblem = step.reason?.let { Message("mobile.error.failed", mapOf("reason" to it)) }
                            ?: Message("mobile.console.invalid")
                    is CommandStep.AskFirst -> asking = step
                    is CommandStep.Sent -> {
                        history = ConsoleCommands.remember(history, step.command)
                        sent()
                    }
                }
            } catch (e: AgentException) {
                noted(e)
                commandProblem = Message.of(e)
            }
            sending = false
        }
    }

    fun confirmCommand(sent: () -> Unit) {
        val step = asking ?: return
        asking = null
        val c = client() ?: return
        sending = true
        scope.launch {
            try {
                val done = ConsoleCommands(c, serverId).confirmed(step.command)
                history = ConsoleCommands.remember(history, done.command)
                sent()
            } catch (e: AgentException) {
                noted(e)
                commandProblem = Message.of(e)
            }
            sending = false
        }
    }

    fun cancelCommand() {
        asking = null
    }

    // ------------------------------------------------------------ chat
    var chat: Read<List<ChatMessage>> by mutableStateOf(Read())
        private set
    var chatRunning: Boolean? by mutableStateOf(null)
        private set
    var chatProblem: Message? by mutableStateOf(null)
        private set
    var chatSending: Boolean by mutableStateOf(false)
        private set

    fun loadChat() = load({ chat }, { chat = it }) {
        val log = it.chat(serverId)
        chatRunning = log.running
        ChatBuffer.replace(log.messages)
    }

    fun onChat(message: ChatMessage) {
        chat = chat.copy(value = ChatBuffer.add(chat.value.orEmpty(), message))
    }

    fun sendChat(text: String, sent: () -> Unit) {
        val message = text.trim().take(ChatBuffer.MAX_LENGTH)
        if (message.isEmpty()) return
        val c = client() ?: return
        chatProblem = null
        chatSending = true
        scope.launch {
            try {
                c.sendChat(serverId, message)
                sent()
            } catch (e: AgentException) {
                noted(e)
                chatProblem = Message.of(e)
            }
            chatSending = false
        }
    }

    // ------------------------------------------------------------ players
    var players: Read<PlayersPage> by mutableStateOf(Read())
        private set

    /** "kick:Steve" while that button is being sent. */
    var playerBusy: String? by mutableStateOf(null)
        private set
    var playerProblem: Message? by mutableStateOf(null)
        private set

    /** The buttons pressed here, newest first, as the agent last described them. */
    var pressed: List<PlayerAction> by mutableStateOf(emptyList())
        private set

    fun loadPlayers() = load({ players }, { players = it }) { it.players(serverId) }

    /** What was sent to the server: this phone's own presses first, then
     * the agent's list, each once. */
    fun recentActions(): List<PlayerAction> {
        val mine = pressed.map { it.id }.toSet()
        return (pressed + players.value?.actions.orEmpty().filter { it.id !in mine }).take(10)
    }

    fun playerAction(action: String, name: String, reason: String?) {
        val c = client() ?: return
        playerBusy = "$action:$name"
        playerProblem = null
        scope.launch {
            try {
                val result = c.playerAction(
                    serverId, action, name,
                    reason = reason?.trim()?.takeIf { it.isNotEmpty() && action in PlayerActions.CONFIRM },
                    confirm = action in PlayerActions.CONFIRM,
                )
                track(result.action)
                playerBusy = null
                PlayerActionWatch({ c.playerActionStatus(serverId, it).action }).follow(result.action, ::track)
            } catch (e: AgentException) {
                noted(e)
                playerProblem = Message.of(e)
            }
            playerBusy = null
            loadPlayers()
        }
    }

    private fun track(action: PlayerAction) {
        pressed = (listOf(action) + pressed.filter { it.id != action.id }).take(10)
    }

    // ------------------------------------------------------------ activity
    var events: Read<List<EventRow>> by mutableStateOf(Read())
        private set

    fun loadEvents() = load({ events }, { events = it }) { it.events(serverId, EVENTS).events }

    /** A live event for this server (or the PC itself), newest first. */
    fun onEvent(row: EventRow) {
        val list = events.value ?: return
        if (row.serverId != null && row.serverId != serverId) return
        events = events.copy(value = (listOf(row) + list).take(EVENTS))
    }

    // ------------------------------------------------------------ crashes
    var crashes: Read<List<Crash>> by mutableStateOf(Read())
        private set
    var crash: Read<Crash> by mutableStateOf(Read())
        private set

    fun loadCrashes() = load({ crashes }, { crashes = it }) { it.crashes(serverId).crashes }

    fun openCrash(id: Long) {
        if (crash.value?.id != id) crash = Read()
        load({ crash }, { crash = it }) { it.crash(serverId, id) }
    }

    // ------------------------------------------------------------ overview cards
    var join: Read<JoinInfo> by mutableStateOf(Read())
        private set
    var suggestions: Read<Recommendations> by mutableStateOf(Read())
        private set
    var checklist: Read<Checklist> by mutableStateOf(Read())
        private set
    var cardProblem: Message? by mutableStateOf(null)
        private set

    fun loadCards() {
        load({ join }, { join = it }) { it.join(serverId) }
        load({ suggestions }, { suggestions = it }) { it.recommendations(serverId) }
        load({ checklist }, { checklist = it }) { it.gettingStarted(serverId) }
    }

    fun suggestion(recId: String, action: String) {
        val c = client() ?: return
        cardProblem = null
        scope.launch {
            try {
                suggestions = Read(c.recommendationAction(serverId, recId, action))
            } catch (e: AgentException) {
                noted(e)
                cardProblem = Message.of(e)
            }
        }
    }

    fun hideChecklist() {
        val c = client() ?: return
        cardProblem = null
        scope.launch {
            try {
                checklist = Read(c.hideGettingStarted(serverId))
            } catch (e: AgentException) {
                noted(e)
                cardProblem = Message.of(e)
            }
        }
    }

    // ------------------------------------------------------------ reading
    /** Reads with [call] into the [Read] that [current] gives and [store]
     * keeps: loading, then the value, or the problem (keeping what was
     * there, so each screen decides whether it may still show it). */
    private fun <T> load(current: () -> Read<T>, store: (Read<T>) -> Unit, call: suspend (AgentClient) -> T) {
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

    companion object {
        const val EVENTS = 200
    }
}
