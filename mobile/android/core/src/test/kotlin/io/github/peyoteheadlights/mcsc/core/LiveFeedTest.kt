package io.github.peyoteheadlights.mcsc.core

import kotlinx.coroutines.flow.take
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okhttp3.mockwebserver.MockResponse
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LiveFeedTest {
    private val token = "secret-session-token-1234567890"

    @Test
    fun `the token goes in the first message and events come through`() = runBlocking {
        TestAgent().use { agent ->
            val first = java.util.concurrent.LinkedBlockingQueue<String>()
            agent.server.enqueue(MockResponse().withWebSocketUpgrade(object : WebSocketListener() {
                override fun onMessage(webSocket: WebSocket, text: String) {
                    first.add(text)
                    webSocket.send("""{"type": "ready", "servers": []}""")
                    webSocket.send("""{"type": "event", "event": {"type": "console", "server_id": "survival", "line": "x"}}""")
                    webSocket.send("""{"type": "ping", "ts": 1}""")
                    webSocket.send("""{"type": "event", "event": {"type": "state", "server_id": "survival", "state": "ONLINE"}}""")
                    webSocket.send("""{"type": "error", "message": "Your session ended"}""")
                }

                override fun onOpen(webSocket: WebSocket, response: Response) {}

                override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                    webSocket.close(1000, null)
                }
            }))
            val client = AgentClient(agent.pairing(), { token }, systemTrust = TestAgent.trustingNothing())
            val signals = withTimeout(10_000) { LiveFeed(client) { token }.connect("survival").take(3).toList() }
            assertEquals(
                listOf(
                    LiveSignal.Ready,
                    LiveSignal.Changed("survival", "state", EventRow(serverId = "survival", type = "state")),
                    LiveSignal.Closed("Your session ended"),
                ),
                signals,
            )
            val request = agent.server.takeRequest()
            assertEquals("/ws", request.path)
            assertFalse(request.requestUrl.toString().contains(token))
            val auth = first.take()
            assertTrue(auth, auth.contains("\"token\":\"$token\""))
            assertTrue(auth, auth.contains("\"server_id\":\"survival\""))
        }
    }

    @Test
    fun `console lines and chat come through, and tail switches the server`() = runBlocking {
        TestAgent().use { agent ->
            val received = java.util.concurrent.LinkedBlockingQueue<String>()
            val line = """{"seq": 7, "ts": 1700000000.5, "raw": "[10:00:00] [Server thread/WARN]: Can't keep up!", "level": "WARN", "thread": "Server thread", "message": "Can't keep up!", "source": "stdout"}"""
            agent.server.enqueue(MockResponse().withWebSocketUpgrade(object : WebSocketListener() {
                override fun onMessage(webSocket: WebSocket, text: String) {
                    received.add(text)
                    if (text.contains("\"auth\"")) {
                        webSocket.send("""{"type": "ready", "server_id": "survival", "servers": [], "console": [$line]}""")
                        webSocket.send("""{"type": "event", "event": {"type": "console", "message": "x", "level": "info", "data": $line, "ts": 1, "server_id": "survival"}}""")
                        webSocket.send("""{"type": "event", "event": {"type": "chat", "message": "hi", "level": "info", "data": {"seq": 3, "ts": 2.0, "kind": "player", "name": "Alex", "text": "hi"}, "ts": 2, "server_id": "survival"}}""")
                        webSocket.send("""{"type": "event", "event": {"type": "metrics", "message": "", "level": "info", "data": {"cpu": 3}, "ts": 3, "server_id": "survival"}}""")
                        webSocket.send("""{"type": "event", "event": {"type": "player_joined", "message": "Alex joined", "level": "success", "data": {"username": "Alex"}, "ts": 3.5, "server_id": "survival"}}""")
                    } else {
                        webSocket.send("""{"type": "console_tail", "server_id": "creative", "lines": []}""")
                    }
                }

                override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                    webSocket.close(1000, null)
                }
            }))
            val client = AgentClient(agent.pairing(), { token }, systemTrust = TestAgent.trustingNothing())
            val feed = LiveFeed(client) { token }
            assertFalse(feed.tail("creative"))
            val signals = mutableListOf<LiveSignal>()
            withTimeout(10_000) {
                feed.connect("survival").take(7).collect {
                    signals += it
                    if (it is LiveSignal.Changed && it.type == "player_joined") assertTrue(feed.tail("creative", lines = 900))
                }
            }
            val warn = ConsoleLine(7, 1700000000.5, "[10:00:00] [Server thread/WARN]: Can't keep up!", "WARN", "stdout")
            assertEquals(
                listOf(
                    LiveSignal.Ready,
                    LiveSignal.ConsoleTail("survival", listOf(warn)),
                    LiveSignal.Console("survival", warn),
                    LiveSignal.Chat("survival", ChatMessage(3, 2.0, "player", "Alex", "hi")),
                    // A reading, not history: it refreshes, but is no line for Activity.
                    LiveSignal.Changed("survival", "metrics", null),
                    LiveSignal.Changed("survival", "player_joined", EventRow(serverId = "survival", ts = 3.5, type = "player_joined", level = "success", message = "Alex joined")),
                    LiveSignal.ConsoleTail("creative", emptyList()),
                ),
                signals,
            )
            received.take()
            val tail = received.take()
            assertEquals("""{"type":"tail","server_id":"creative","lines":500}""", tail)
        }
    }

    @Test
    fun `without a sign-in it doesn't connect`() = runBlocking {
        TestAgent().use { agent ->
            val client = AgentClient(agent.pairing(), { null }, systemTrust = TestAgent.trustingNothing())
            assertEquals(listOf(LiveSignal.SignedOut), LiveFeed(client) { null }.connect(null).toList())
            assertEquals(0, agent.server.requestCount)
        }
    }
}
