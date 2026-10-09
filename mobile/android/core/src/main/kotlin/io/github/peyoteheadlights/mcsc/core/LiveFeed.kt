package io.github.peyoteheadlights.mcsc.core

import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
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
     * the agent's event type ("state", "player_joined", ...). */
    data class Changed(val serverId: String?, val type: String) : LiveSignal()

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
 * never in a log. Console lines are ignored; the app has no console yet.
 */
class LiveFeed(private val client: AgentClient, private val token: () -> String?) {
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
                        "ready" -> trySend(LiveSignal.Ready)
                        "event" -> {
                            val event = runCatching { message.getValue("event").jsonObject }.getOrNull() ?: return
                            val type = event["type"]?.jsonPrimitive?.contentOrNull ?: return
                            if (type == "console") return
                            trySend(LiveSignal.Changed(event["server_id"]?.jsonPrimitive?.contentOrNull, type))
                        }
                        "error" -> {
                            trySend(LiveSignal.Closed(message["message"]?.jsonPrimitive?.contentOrNull))
                            webSocket.close(1000, null)
                        }
                    }
                }

                override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                    close()
                }

                override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                    val problem = if (t is java.io.IOException) client.translateFailure(t) else AgentException.Unreachable()
                    trySend(LiveSignal.Lost(problem))
                    close()
                }
            },
        )
        awaitClose { socket.close(1000, null) }
    }
}
