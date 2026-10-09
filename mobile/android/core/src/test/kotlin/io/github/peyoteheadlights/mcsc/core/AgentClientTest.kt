package io.github.peyoteheadlights.mcsc.core

import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class AgentClientTest {
    private val token = "secret-session-token-1234567890"

    private fun client(agent: TestAgent, current: () -> String? = { token }, onSignedOut: () -> Unit = {}, log: AgentLog = AgentLog { }) =
        AgentClient(agent.pairing(), current, onSignedOut, log, systemTrust = TestAgent.trustingNothing())

    @Test
    fun `requests carry the token and read the answer`() = runBlocking {
        TestAgent().use { agent ->
            agent.server.enqueue(agent.json("""{"servers": [{"id": "survival", "name": "Survival", "state": "ONLINE", "players_online": 2, "max_players": 20, "new_field": 1}], "default": "survival"}"""))
            val list = client(agent).servers()
            assertEquals("Survival", list.servers.single().name)
            assertEquals(2, list.servers.single().playersOnline)
            assertEquals("Bearer $token", agent.server.takeRequest().getHeader("Authorization"))
        }
    }

    @Test
    fun `a value the agent didn't measure stays unknown`() = runBlocking {
        TestAgent().use { agent ->
            agent.server.enqueue(agent.json("""{"servers": [{"id": "s", "name": "S", "state": "ONLINE", "players_online": null}]}"""))
            val row = client(agent).servers().servers.single()
            assertNull(row.playersOnline)
            assertEquals("Unknown", Strings(Shared.strings).let { Display.players(it, row.playersOnline, row.maxPlayers) })
        }
    }

    @Test
    fun `signing the phone out on the PC signs the app out`() = runBlocking {
        TestAgent().use { agent ->
            agent.server.enqueue(agent.json("""{"detail": "Not signed in"}""", code = 401))
            var signedOut = false
            assertThrows(AgentException.SignedOut::class.java) {
                runBlocking { client(agent, onSignedOut = { signedOut = true }).servers() }
            }
            assertTrue(signedOut)
        }
    }

    @Test
    fun `without a token nothing is sent`() = runBlocking {
        TestAgent().use { agent ->
            assertThrows(AgentException.SignedOut::class.java) { runBlocking { client(agent, current = { null }).me() } }
            assertEquals(0, agent.server.requestCount)
        }
    }

    @Test
    fun `refusals carry the agent's own words`() = runBlocking {
        TestAgent().use { agent ->
            agent.server.enqueue(agent.json("""{"detail": "Wrong username or password"}""", code = 401))
            val e = assertThrows(AgentException.SignInRefused::class.java) {
                runBlocking { client(agent).login("admin", "hunter2-password", "Server Controller on Pixel") }
            }
            assertEquals("Wrong username or password", e.reason)

            agent.server.enqueue(agent.json("""{"detail": "Helpers can't do that"}""", code = 403))
            val no = assertThrows(AgentException.NotAllowed::class.java) {
                runBlocking { client(agent).serverAction("survival", "stop") }
            }
            assertEquals("Helpers can't do that", no.reason)

            agent.server.enqueue(agent.json("""{"detail": "Busy"}""", code = 409).setHeader("X-Request-ID", "abc123"))
            val failed = assertThrows(AgentException.Failed::class.java) {
                runBlocking { client(agent).serverAction("survival", "start") }
            }
            assertEquals(409, failed.status)
            assertEquals("Busy", failed.reason)
            assertEquals("abc123", failed.requestId)
        }
    }

    @Test
    fun `only start, stop and restart can be sent`() {
        TestAgent().use { agent ->
            assertThrows(IllegalArgumentException::class.java) {
                runBlocking { client(agent).serverAction("survival", "command") }
            }
        }
    }

    @Test
    fun `server names are sent safely in the path`() = runBlocking {
        TestAgent().use { agent ->
            agent.server.enqueue(agent.json("""{"state": "OFFLINE"}"""))
            client(agent).status("my world/../x")
            assertEquals("/api/servers/my%20world%2F..%2Fx/status", agent.server.takeRequest().path)
        }
    }

    @Test
    fun `the log never has the token or the password`() = runBlocking {
        TestAgent().use { agent ->
            val log = RequestLog()
            agent.server.enqueue(agent.json("""{"token": "$token", "user": "admin"}"""))
            agent.server.enqueue(agent.json("""{"alerts": [], "latest": 3}"""))
            val c = client(agent, log = log)
            c.login("admin", "hunter2-password", "Phone")
            c.alerts(after = 1)
            val lines = log.recent().joinToString("\n")
            assertTrue(lines, lines.contains("POST /api/auth/login -> 200"))
            assertTrue(lines, lines.contains("GET /api/alerts -> 200"))
            assertFalse(lines.contains(token))
            assertFalse(lines.contains("hunter2"))
            assertFalse(lines.contains("Bearer"))
        }
    }

    @Test
    fun `the sign-in asks to be remembered with the phone's name`() = runBlocking {
        TestAgent().use { agent ->
            agent.server.enqueue(agent.json("""{"token": "$token"}"""))
            assertEquals(token, client(agent).login("admin", "pw", "Server Controller on Pixel 9").token)
            val body = agent.server.takeRequest().body.readUtf8()
            assertTrue(body, body.contains("\"remember\":true"))
            assertTrue(body, body.contains("\"device\":\"Server Controller on Pixel 9\""))
        }
    }
}
