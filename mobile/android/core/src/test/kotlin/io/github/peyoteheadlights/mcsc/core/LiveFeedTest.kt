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
                listOf(LiveSignal.Ready, LiveSignal.Changed("survival", "state"), LiveSignal.Closed("Your session ended")),
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
    fun `without a sign-in it doesn't connect`() = runBlocking {
        TestAgent().use { agent ->
            val client = AgentClient(agent.pairing(), { null }, systemTrust = TestAgent.trustingNothing())
            assertEquals(listOf(LiveSignal.SignedOut), LiveFeed(client) { null }.connect(null).toList())
            assertEquals(0, agent.server.requestCount)
        }
    }
}
