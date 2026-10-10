package io.github.peyoteheadlights.mcsc.ui

import android.app.Application
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import io.github.peyoteheadlights.mcsc.core.AgentClient
import io.github.peyoteheadlights.mcsc.core.AgentException
import io.github.peyoteheadlights.mcsc.core.AlertState
import io.github.peyoteheadlights.mcsc.core.AlertSync
import io.github.peyoteheadlights.mcsc.core.Compatibility
import io.github.peyoteheadlights.mcsc.core.LiveFeed
import io.github.peyoteheadlights.mcsc.core.LiveSignal
import io.github.peyoteheadlights.mcsc.core.Me
import io.github.peyoteheadlights.mcsc.core.PairResult
import io.github.peyoteheadlights.mcsc.core.Pairing
import io.github.peyoteheadlights.mcsc.core.PairingLink
import io.github.peyoteheadlights.mcsc.core.PairingParseException
import io.github.peyoteheadlights.mcsc.core.Permissions
import io.github.peyoteheadlights.mcsc.core.ServerRow
import io.github.peyoteheadlights.mcsc.core.ServerStatus
import io.github.peyoteheadlights.mcsc.core.Strings
import io.github.peyoteheadlights.mcsc.core.WidgetSnapshot
import io.github.peyoteheadlights.mcsc.graph
import io.github.peyoteheadlights.mcsc.push.Push
import io.github.peyoteheadlights.mcsc.widget.Widgets
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/** Where the app is before its main screens. */
sealed interface Stage {
    data object Welcome : Stage
    data object Scan : Stage
    data class Type(val problem: Message? = null) : Stage
    data object Checking : Stage
    data class Confirm(val pairing: Pairing, val fingerprint: String) : Stage

    /** A rescanned code for another PC: switching signs out of [current]. */
    data class Switch(val pairing: Pairing, val current: Pairing) : Stage
    data class Problem(val message: Message, val retry: Pairing? = null) : Stage
    data class SignIn(val problem: Message? = null, val busy: Boolean = false) : Stage
    data object Ready : Stage
}

data class ServersUi(
    val list: List<ServerRow> = emptyList(),
    val loaded: Boolean = false,
    val checkedAt: Double? = null,
    val problem: Message? = null,
    val refreshing: Boolean = false,
)

data class ServerUi(
    val status: ServerStatus? = null,
    val checkedAt: Double? = null,
    val problem: Message? = null,
    val busyAction: String? = null,
    val done: Message? = null,
)

data class PhoneUi(
    val busy: Boolean = false,
    val problem: Message? = null,
)

fun now(): Double = System.currentTimeMillis() / 1000.0

class AppViewModel(app: Application) : AndroidViewModel(app) {
    private val graph = app.graph
    private val prefs = graph.prefs

    var stage: Stage by mutableStateOf(
        when {
            prefs.pairing == null -> Stage.Welcome
            graph.vault.token() == null -> Stage.SignIn()
            else -> Stage.Ready
        },
    )
        private set

    /** Locked behind the phone's own unlock (fingerprint, face or PIN). */
    var locked: Boolean by mutableStateOf(prefs.unlock && stage == Stage.Ready)
        private set

    var theme: String by mutableStateOf(prefs.theme)
        private set
    var technical: Boolean by mutableStateOf(prefs.technical)
        private set
    var unlock: Boolean by mutableStateOf(prefs.unlock)
        private set
    var lockAlerts: Boolean by mutableStateOf(prefs.lockAlerts)
        private set

    var me: Me? by mutableStateOf(null)
        private set
    var servers: ServersUi by mutableStateOf(ServersUi())
        private set
    var server: Map<String, ServerUi> by mutableStateOf(emptyMap())
        private set
    var alerts: AlertState by mutableStateOf(graph.alerts.read())
        private set
    var live: Boolean by mutableStateOf(false)
        private set
    var phone: PhoneUi by mutableStateOf(PhoneUi())
        private set
    var agentVersion: String? by mutableStateOf(prefs.agentVersion)
        private set

    /** A server to open (from a shortcut, the widget or an alert). */
    var pendingServer: String? by mutableStateOf(null)

    /** Scanning the code again from Settings, still signed in. */
    var rescanning: Boolean by mutableStateOf(false)
        private set

    val strings: Strings get() = graph.strings
    val shared get() = graph.shared
    val pairing: Pairing? get() = prefs.pairing
    val user: String? get() = prefs.user

    private var foreground = false
    private var watching: String? = null

    /** The server screens open now, newest last; the same server can be
     * open twice (its home and its Console) while one replaces the other. */
    private val watchers = mutableListOf<String>()
    private val pagesBy = mutableMapOf<String, ServerPages>()
    private var feed: LiveFeed? = null
    private var liveJob: Job? = null
    private var refreshJob: Job? = null

    init {
        viewModelScope.launch {
            graph.signedOut.collect {
                // The widget stops showing servers at once, not at its next refresh.
                Widgets.refresh(getApplication())
                stopLive()
                me = null
                lockAlerts = false
                pagesBy.clear()
                stage = Stage.SignIn(Message("error.session_ended"))
            }
        }
    }

    // ------------------------------------------------------------ pairing
    fun go(next: Stage) {
        stage = next
    }

    /** A scanned code or a typed address. */
    fun submit(text: String, scanned: Boolean) {
        val pairing = try {
            PairingLink.parse(text)
        } catch (e: PairingParseException) {
            stage = if (scanned) Stage.Problem(Message("mobile.scan.not_ours")) else Stage.Type(Message(e.problem.key))
            return
        }
        if (scanned && pairing.fingerprint == null) {
            stage = Stage.Problem(Message("mobile.scan.not_ours"))
            return
        }
        val current = prefs.pairing
        if (rescanning && current != null && !current.samePc(pairing)) {
            stage = Stage.Switch(pairing, current)
            return
        }
        check(pairing)
    }

    /** "Scan the code again" in Settings: for a renewed certificate. */
    fun rescan() {
        stopLive()
        rescanning = true
        stage = Stage.Scan
    }

    /** Back from a pairing screen: to the app when rescanning, else to the start. */
    fun back() {
        val signedIn = rescanning && prefs.pairing != null && graph.vault.token() != null
        rescanning = false
        stage = if (signedIn) Stage.Ready else Stage.Welcome
        if (signedIn) afterSignIn()
    }

    fun check(pairing: Pairing) {
        stage = Stage.Checking
        viewModelScope.launch { handle(pairing, graph.pairer().check(pairing)) }
    }

    fun confirmFingerprint(pairing: Pairing, fingerprint: String) {
        stage = Stage.Checking
        viewModelScope.launch { handle(pairing, graph.pairer().confirm(pairing, fingerprint)) }
    }

    private suspend fun handle(tried: Pairing, result: PairResult) {
        if (result is PairResult.Paired) {
            // A new code for the same PC (a renewed certificate) keeps the
            // sign-in; for any other address it ends here, so it is never
            // sent to another PC.
            val before = prefs.pairing
            if ((before == null || !before.samePc(result.pairing)) && graph.vault.token() != null) leaveOldPc()
            prefs.pairing = result.pairing
            rescanning = false
            if (graph.vault.token() != null) {
                stage = Stage.Ready
                afterSignIn()
            } else {
                stage = Stage.SignIn()
            }
            return
        }
        stage = when (result) {
            is PairResult.Paired -> Stage.Ready
            is PairResult.ConfirmFingerprint -> Stage.Confirm(result.pairing, result.fingerprint)
            is PairResult.Refused -> {
                prefs.lastProblem = result.problem.key
                val retry = if (result.problem is AgentException.Unreachable) tried else null
                Stage.Problem(Message.of(result.problem), retry)
            }
            is PairResult.Incompatible -> when (val c = result.compatibility) {
                is Compatibility.AgentTooOld -> Stage.Problem(Message("mobile.pair.too_old", mapOf("api" to c.agentApi.toString())))
                is Compatibility.AgentTooNew -> Stage.Problem(Message("mobile.pair.too_new", mapOf("api" to c.agentApi.toString())))
                Compatibility.Ok -> Stage.Problem(Message("mobile.error.not_agent"))
            }
        }
    }

    // ------------------------------------------------------------ sign-in
    fun signIn(username: String, password: String) {
        val client = graph.client() ?: return go(Stage.Welcome)
        stage = Stage.SignIn(busy = true)
        viewModelScope.launch {
            try {
                val result = client.login(username.trim(), password, graph.deviceLabel())
                graph.vault.save(result.token)
                prefs.user = result.user ?: username.trim()
                // A new sign-in starts the Notifications tab from now.
                graph.alerts.write(AlertState())
                alerts = AlertState()
                locked = false
                stage = Stage.Ready
                afterSignIn()
            } catch (e: AgentException) {
                prefs.lastProblem = e.key
                stage = Stage.SignIn(Message.of(e))
            }
        }
    }

    private fun afterSignIn() {
        refreshAll()
        if (foreground) startLive()
    }

    fun signOut() {
        val client = graph.client()
        viewModelScope.launch {
            if (prefs.lockAlerts) runCatching { client?.forgetPhone() }
            client?.logout()
            stopLive()
            graph.forgetSignIn()
            Widgets.refresh(getApplication())
            me = null
            lockAlerts = false
            alerts = AlertState()
            pagesBy.clear()
            stage = Stage.SignIn()
        }
    }

    /** Signs out of the paired PC before pairing with another one. */
    private suspend fun leaveOldPc() {
        val old = graph.client()
        if (prefs.lockAlerts) runCatching { old?.forgetPhone() }
        runCatching { old?.logout() }
        Push.stop(getApplication())
        graph.forgetSignIn()
        Widgets.refresh(getApplication())
        me = null
        lockAlerts = false
        alerts = AlertState()
        servers = ServersUi()
        server = emptyMap()
        pagesBy.clear()
        agentVersion = null
        prefs.agentVersion = null
    }

    fun forgetPc() {
        val client = graph.client()
        viewModelScope.launch {
            if (prefs.lockAlerts) runCatching { client?.forgetPhone() }
            client?.logout()
            stopLive()
            Push.stop(getApplication())
            graph.forgetPc()
            Widgets.refresh(getApplication())
            me = null
            lockAlerts = false
            alerts = AlertState()
            servers = ServersUi()
            server = emptyMap()
            pagesBy.clear()
            agentVersion = null
            stage = Stage.Welcome
        }
    }

    // ------------------------------------------------------------ the lock
    fun lockIfAway(awaySeconds: Double?) {
        if (!unlock || stage != Stage.Ready) return
        if (awaySeconds == null || awaySeconds > LOCK_AFTER) locked = true
    }

    fun unlocked() {
        locked = false
    }

    // ------------------------------------------------------------ reading
    fun foreground(on: Boolean) {
        foreground = on
        if (on && stage == Stage.Ready) {
            refreshAll()
            startLive()
        } else {
            stopLive()
        }
    }

    fun refreshAll() {
        refreshServers()
        watching?.let(::refreshServer)
        catchUpAlerts()
        loadMe()
    }

    private fun client(): AgentClient? = graph.client().takeIf { stage == Stage.Ready }

    fun refreshServers() {
        val client = client() ?: return
        servers = servers.copy(refreshing = true)
        viewModelScope.launch {
            try {
                val list = client.servers()
                val at = now()
                servers = ServersUi(list.servers, loaded = true, checkedAt = at)
                graph.widget.write(WidgetSnapshot.read(list, at))
                Widgets.refresh(getApplication())
                Widgets.shortcuts(getApplication(), list.servers)
            } catch (e: AgentException) {
                prefs.lastProblem = e.key
                // What was read before stays, marked with when; nothing
                // is passed off as current.
                servers = servers.copy(problem = Message.of(e), refreshing = false)
            }
        }
    }

    /** A screen of [serverId] opened: the live feed carries its console and chat. */
    fun watch(serverId: String) {
        watchers += serverId
        follow(serverId)
    }

    /** That screen closed. */
    fun unwatch(serverId: String) {
        watchers.remove(serverId)
        follow(watchers.lastOrNull())
    }

    private fun follow(serverId: String?) {
        if (watching == serverId) return
        watching = serverId
        // No server screen open: the feed can stay where it is.
        if (serverId == null) return
        refreshServer(serverId)
        // Switch the open feed to it; reconnect only if it isn't open.
        if (feed?.tail(serverId) != true && foreground && liveJob != null) startLive()
    }

    /** What the Console, Chat, Players, Activity and Crashes screens show. */
    fun pages(serverId: String): ServerPages = pagesBy.getOrPut(serverId) {
        ServerPages(serverId, viewModelScope, { client() }, { prefs.lastProblem = it.key })
    }

    fun canDo(permission: String): Boolean = me?.can(permission) == true

    fun refreshServer(serverId: String) {
        val client = client() ?: return
        viewModelScope.launch {
            try {
                val status = client.status(serverId)
                update(serverId) { it.copy(status = status, checkedAt = now(), problem = null) }
            } catch (e: AgentException) {
                prefs.lastProblem = e.key
                update(serverId) { it.copy(problem = Message.of(e)) }
            }
        }
    }

    fun act(serverId: String, action: String) {
        val client = client() ?: return
        update(serverId) { it.copy(busyAction = action, done = null, problem = null) }
        viewModelScope.launch {
            try {
                client.serverAction(serverId, action)
                update(serverId) { it.copy(busyAction = null, done = Message("mobile.server.done_$action")) }
            } catch (e: AgentException) {
                prefs.lastProblem = e.key
                update(serverId) { it.copy(busyAction = null, problem = Message.of(e)) }
            }
            refreshServer(serverId)
            refreshServers()
        }
    }

    private fun update(serverId: String, change: (ServerUi) -> ServerUi) {
        server = server + (serverId to change(server[serverId] ?: ServerUi()))
    }

    fun canControl(): Boolean = me?.can(Permissions.SERVER_CONTROL) == true

    private fun loadMe() {
        val client = client() ?: return
        viewModelScope.launch {
            runCatching { client.me() }.onSuccess {
                me = it
                prefs.user = it.user
            }
            runCatching { client.version() }.onSuccess {
                agentVersion = it.version
                prefs.agentVersion = it.version
            }
        }
    }

    // ------------------------------------------------------------ alerts
    fun catchUpAlerts() {
        val client = client() ?: return
        viewModelScope.launch {
            try {
                val next = AlertSync { after, limit -> client.alerts(after, limit) }.catchUp(graph.alerts.read())
                graph.alerts.write(next)
                alerts = next
            } catch (e: AgentException) {
                prefs.lastProblem = e.key
            }
        }
    }

    fun markAllRead() {
        alerts = graph.alerts.update { it.markAllRead() }
    }

    // ------------------------------------------------------------ live feed
    private fun startLive() {
        stopLive()
        val client = client() ?: return
        liveJob = viewModelScope.launch {
            var wait = 2_000L
            while (true) {
                val current = LiveFeed(client, graph.vault::token)
                feed = current
                current.connect(watching).collect { signal ->
                    when (signal) {
                        LiveSignal.Ready -> {
                            live = true
                            wait = 2_000L
                        }
                        is LiveSignal.Changed -> {
                            soon(signal.type in shared.feed)
                            changed(signal)
                        }
                        is LiveSignal.Console -> signal.serverId?.let { pagesBy[it] }?.onConsoleLine(signal.line)
                        is LiveSignal.Chat -> signal.serverId?.let { pagesBy[it] }?.onChat(signal.message)
                        is LiveSignal.ConsoleTail -> pagesBy[signal.serverId]?.onConsoleTail(signal.lines)
                        is LiveSignal.Closed -> {
                            live = false
                            // A 401 here signs the app out; anything else, try again.
                            runCatching { client.me() }
                        }
                        is LiveSignal.Lost -> live = false
                        LiveSignal.SignedOut -> live = false
                    }
                }
                live = false
                if (stage != Stage.Ready) break
                delay(wait)
                wait = (wait * 2).coerceAtMost(30_000L)
            }
        }
    }

    private fun stopLive() {
        liveJob?.cancel()
        liveJob = null
        feed = null
        live = false
    }

    /** An event for the Activity screens, and a fresh read of what it changed. */
    private fun changed(signal: LiveSignal.Changed) {
        val row = signal.event
        if (row != null) pagesBy.values.forEach { it.onEvent(row) }
        val pages = signal.serverId?.let { pagesBy[it] } ?: return
        when (signal.type) {
            "player_joined", "player_left", "player_action" -> if (pages.players.loaded) pages.loadPlayers()
            "server_crashed" -> if (pages.crashes.loaded) pages.loadCrashes()
        }
        // Started or stopped: Players and Chat say whether their buttons
        // work now, so they read it again rather than keep the old answer.
        if (signal.type == "state") {
            if (pages.players.loaded) pages.loadPlayers()
            if (pages.chat.loaded) pages.loadChat()
        }
    }

    /** Many events can come at once (a server starting): read once after. */
    private fun soon(alertsToo: Boolean) {
        refreshJob?.cancel()
        refreshJob = viewModelScope.launch {
            delay(800)
            refreshServers()
            watching?.let(::refreshServer)
            if (alertsToo) catchUpAlerts()
        }
    }

    // ------------------------------------------------------------ settings
    fun chooseTheme(name: String) {
        prefs.theme = name
        theme = name
    }

    fun chooseTechnical(on: Boolean) {
        prefs.technical = on
        graph.strings.technical = on
        technical = on
    }

    fun chooseUnlock(on: Boolean) {
        prefs.unlock = on
        unlock = on
    }

    /** Lock-screen alerts on or off for this phone's sign-in. */
    fun chooseLockAlerts(on: Boolean) {
        val client = client() ?: return
        phone = PhoneUi(busy = true)
        viewModelScope.launch {
            try {
                if (on) {
                    if (!client.phone().configured) {
                        phone = PhoneUi(problem = Message("mobile.settings.lock_alerts_not_set_up"))
                        return@launch
                    }
                    val token = Push.token(getApplication())
                    if (token == null) {
                        phone = PhoneUi(problem = Message("mobile.settings.lock_alerts_no_play"))
                        return@launch
                    }
                    client.registerPhone(token, "android", graph.deviceLabel())
                    prefs.notifiedUpTo = maxOf(prefs.notifiedUpTo, alerts.cursor ?: 0)
                } else {
                    client.forgetPhone()
                    Push.stop(getApplication())
                }
                prefs.lockAlerts = on
                lockAlerts = on
                phone = PhoneUi()
            } catch (e: AgentException) {
                prefs.lastProblem = e.key
                phone = PhoneUi(problem = Message.of(e))
            }
        }
    }

    fun lockAlertsBlocked() {
        phone = PhoneUi(problem = Message("mobile.settings.lock_alerts_blocked"))
    }

    companion object {
        /** Seconds away before the app asks for the unlock again. */
        const val LOCK_AFTER = 60.0
    }
}
