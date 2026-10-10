package io.github.peyoteheadlights.mcsc.core

import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.serialization.KSerializer
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener

/** What the live feed tells the app. Screens refetch what they show. */
sealed class LiveSignal {
    /** Connected and signed in. */
    data object Ready : LiveSignal()

    /** Something happened on [serverId] (null: the PC itself). [type] is
     * the agent's event type ("state", "player_joined", ...); [event] is
     * the line for the Activity screen (its data is never kept), null for
     * an event the agent doesn't keep in its history ([LiveFeed.NOT_STORED]). */
    data class Changed(val serverId: String?, val type: String, val event: EventRow? = null) : LiveSignal()

    /** A new console line of the watched server. */
    data class Console(val serverId: String?, val line: ConsoleLine) : LiveSignal()

    /** Someone said something in the watched server's game. */
    data class Chat(val serverId: String?, val message: ChatMessage) : LiveSignal()

    /** The watched server's latest console lines, which replace what the
     * Console shows: on connecting, and after [LiveFeed.tail]. */
    data class ConsoleTail(val serverId: String, val lines: List<ConsoleLine>) : LiveSignal()

    /** No sign-in to connect with. */
    data object SignedOut : LiveSignal()

    /** The agent closed the feed: the sign-in ended, or the account may no
     * longer use any server. The app asks /api/auth/me which (a 401 there
     * signs the app out). [message] is the agent's own words. */
    data class Closed(val message: String?) : LiveSignal()

    /** The connection dropped; the app reconnects when it is next shown. */
    data class Lost(val problem: AgentException) : LiveSignal()
}

/**
 * The agent's live stream (/ws, agent/api/ws.py), as the dashboard uses it:
 * the token goes in the first message, never in the address, so it is
 * never in a log. One feed watches one server's console and chat at a time:
 * the one named on connecting, until [tail] names another.
 */
class LiveFeed(private val client: AgentClient, private val token: () -> String?) {
    @Volatile
    private var open: WebSocket? = null

    /**
     * Watch [serverId]'s console and chat from now on; the agent answers
     * with its latest [lines] lines ([LiveSignal.ConsoleTail]). False when
     * the feed isn't connected: the next connect names the server instead.
     */
    fun tail(serverId: String, lines: Int = 200): Boolean {
        val message = buildJsonObject {
            put("type", "tail")
            put("server_id", serverId)
            put("lines", lines.coerceIn(1, 500))
        }
        return open?.send(message.toString()) ?: false
    }

    fun connect(serverId: String?): Flow<LiveSignal> = callbackFlow {
        val current = token()
        if (current == null) {
            trySend(LiveSignal.SignedOut)
            close()
            return@callbackFlow
        }
        val url = client.pairing.origin.replaceFirst("https://", "wss://") + "/ws"
        val socket = client.http.newWebSocket(
            Request.Builder().url(url).build(),
            object : WebSocketListener() {
                override fun onOpen(webSocket: WebSocket, response: Response) {
                    open = webSocket
                    val auth = buildJsonObject {
                        put("type", "auth")
                        put("token", current)
                        if (serverId != null) put("server_id", serverId)
                    }
                    webSocket.send(auth.toString())
                }

                override fun onMessage(webSocket: WebSocket, text: String) {
                    val message = runCatching { AgentJson.parseToJsonElement(text) as JsonObject }.getOrNull() ?: return
                    when (message["type"]?.jsonPrimitive?.contentOrNull) {
                        "ready" -> {
                            trySend(LiveSignal.Ready)
                            val watched = message.field("server_id") ?: return
                            trySend(LiveSignal.ConsoleTail(watched, lines(message["console"])))
                        }
                        "console_tail" -> {
                            val watched = message.field("server_id") ?: return
                            trySend(LiveSignal.ConsoleTail(watched, lines(message["lines"])))
                        }
                        "event" -> {
                            val event = runCatching { message.getValue("event").jsonObject }.getOrNull() ?: return
                            val type = event.field("type") ?: return
                            val server = event.field("server_id")
                            val data = event["data"]
                            when (type) {
                                "console" -> decode(ConsoleLine.serializer(), data)?.let { trySend(LiveSignal.Console(server, it)) }
                                "chat" -> decode(ChatMessage.serializer(), data)?.let { trySend(LiveSignal.Chat(server, it)) }
                                else -> trySend(LiveSignal.Changed(server, type, row(event, type, server).takeIf { type !in NOT_STORED }))
                            }
                        }
                        "error" -> {
                            trySend(LiveSignal.Closed(message["message"]?.jsonPrimitive?.contentOrNull))
                            webSocket.close(1000, null)
                        }
                    }
                }

                override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                    open = null
                    close()
                }

                override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                    open = null
                    val problem = if (t is java.io.IOException) client.translateFailure(t) else AgentException.Unreachable()
                    trySend(LiveSignal.Lost(problem))
                    close()
                }
            },
        )
        awaitClose {
            open = null
            socket.close(1000, null)
        }
    }

    private fun JsonObject.field(key: String): String? =
        (this[key] as? JsonPrimitive)?.takeIf { it !is JsonNull }?.contentOrNull

    private fun <T> decode(serializer: KSerializer<T>, element: JsonElement?): T? =
        if (element !is JsonObject) null else runCatching { AgentJson.decodeFromJsonElement(serializer, element) }.getOrNull()

    private fun lines(element: JsonElement?): List<ConsoleLine> =
        (element as? JsonArray)?.mapNotNull { decode(ConsoleLine.serializer(), it) }.orEmpty()

    companion object {
        /** Events the agent doesn't keep in its history (_persist_event in
         * agent/core.py): live-only readings, not lines for the Activity
         * screen. "metrics" comes every few seconds and would push the
         * history off the screen. */
        val NOT_STORED = setOf("console", "metrics", "job", "chat")
    }

    /** The event as the Activity screen shows it: words, level and time only. */
    private fun row(event: JsonObject, type: String, server: String?): EventRow = EventRow(
        serverId = server,
        ts = (event["ts"] as? JsonPrimitive)?.doubleOrNull,
        type = type,
        level = event.field("level") ?: "info",
        message = event.field("message").orEmpty(),
    )
}
