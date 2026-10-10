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

    @Test
    fun `the server's pages read what the agent sends, missing stays missing`() = runBlocking {
        TestAgent().use { agent ->
            val c = client(agent)
            agent.server.enqueue(agent.json("""{"online": [{"username": "Alex", "uuid": null, "session_started": null, "session_seconds": 0, "edition": null}],
                "online_count": null, "verified": false, "source": null, "known": [{"username": "Alex", "first_seen": 1.0, "last_seen": null, "sessions": 2, "online": 1, "total_seconds_live": 60.5, "server_id": "s"}],
                "lists": {"whitelist": {"players": null, "file": "whitelist.json", "reason": "Can't read it"}, "ops": {"players": [{"name": null, "uuid": "2535", "level": 4}], "file": null, "reason": null},
                "banned": {"players": [], "file": "banned-players.json", "reason": null, "not_applicable": true}},
                "bans": false, "edition": "bedrock", "running": true, "actions": []}"""))
            val players = c.players("s")
            assertNull(players.onlineCount)
            assertNull(players.maxPlayers)
            assertNull(players.online.single().sessionStarted)
            assertNull(players.lists?.whitelist?.players)
            assertEquals("Can't read it", players.lists?.whitelist?.reason)
            assertNull(players.lists?.ops?.players?.single()?.name)
            assertEquals(false, players.bans)
            assertNull(players.known.single().lastSeen)

            agent.server.enqueue(agent.json("""{"crashes": [{"id": 4, "server_id": "s", "ts": 5.0, "exit_code": null, "category": null, "confidence": null, "summary": null, "evidence": [], "report_path": null, "log_path": null, "context": {}, "restarted": 0}]}"""))
            val crash = c.crashes("s").crashes.single()
            assertNull(crash.exitCode)
            assertEquals("Unknown", Display.exitCode(Strings(Shared.strings), crash.exitCode))

            agent.server.enqueue(agent.json("""{"java": {"port": 25565, "port_source": "server.properties", "default_port": true, "local": [{"address": "192.168.1.5", "adapter": "Ethernet", "virtual": false}],
                "tailscale": {"address": null, "dns_name": null, "connected": null, "verified": false, "source": null, "detail": null}}, "bedrock": null, "internet": {"known": false, "reason": "not_tested"}, "running": true}"""))
            val join = c.join("s")
            assertEquals(25565, join.java?.port)
            assertNull(join.java?.tailscale?.address)
            assertNull(join.bedrock)

            agent.server.enqueue(agent.json("""{"items": [{"id": "backup_taken", "done": true, "page": "backups", "evidence_key": "backup_done", "evidence": {"name": "b1", "created_at": 9.0}},
                {"id": "alerts_on", "done": false, "page": "app-settings", "evidence_key": "alerts_none", "evidence": {"channels": []}}], "done": 1, "total": 4, "show": true, "dismissed": false, "finished": false}"""))
            val checklist = c.gettingStarted("s")
            assertEquals(9.0, checklist.items.first().evidence?.createdAt)
            assertTrue(checklist.show)

            agent.server.enqueue(agent.json("""{"recommendations": [], "hidden": [{"id": "java", "title": "Update Java", "reason": "Old", "evidence": "17", "action": {"label": "Get Java", "url": "https://adoptium.net"}, "details": {"a": 1}, "dismissed": true}]}"""))
            assertEquals("Update Java", c.recommendationAction("s", "java", "restore").hidden.single().title)
            repeat(4) { agent.server.takeRequest() }
            val rec = agent.server.takeRequest()
            assertEquals("/api/servers/s/recommendations/java", rec.path)
            assertEquals("""{"action":"restore"}""", rec.body.readUtf8())
        }
    }

    @Test
    fun `routes ask for the dashboard's amounts`() = runBlocking {
        TestAgent().use { agent ->
            val c = client(agent)
            agent.server.enqueue(agent.json("""{"lines": [], "buffered": 0, "buffer_limit": 2000}"""))
            agent.server.enqueue(agent.json("""{"messages": [], "running": false, "kept": 0}"""))
            agent.server.enqueue(agent.json("""{"events": [{"id": 1, "server_id": "_agent", "ts": 1.0, "type": "auth_failure", "level": "warn", "message": "Failed sign-in", "data": "{\"source_ip\": \"1.2.3.4\"}"}]}"""))
            agent.server.enqueue(agent.json("""{"ok": true}"""))
            agent.server.enqueue(agent.json("""{"result": "SENT", "detail": "Sent", "message": "hi"}"""))
            c.consoleLog("s")
            c.chat("s")
            assertEquals("Failed sign-in", c.events("s").events.single().message)
            assertTrue(c.clearConsole("s").ok)
            assertEquals("hi", c.sendChat("s", "hi").message)
            assertEquals("/api/servers/s/logs?lines=500", agent.server.takeRequest().path)
            assertEquals("/api/servers/s/chat?lines=200", agent.server.takeRequest().path)
            assertEquals("/api/servers/s/events?limit=200", agent.server.takeRequest().path)
            assertEquals("/api/servers/s/logs/clear", agent.server.takeRequest().path)
            assertEquals("""{"message":"hi"}""", agent.server.takeRequest().body.readUtf8())
        }
    }

    @Test
    fun `a refusal whose detail isn't words gives the error number`() {
        TestAgent().use { agent ->
            agent.server.enqueue(agent.json("""{"detail": [{"loc": ["body", "name"], "msg": "too long"}]}""", code = 422))
            val e = assertThrows(AgentException.Failed::class.java) {
                runBlocking { client(agent).playerAction("s", PlayerActions.WHITELIST_ADD, "x".repeat(40), null, confirm = false) }
            }
            assertEquals(422, e.status)
            assertNull(e.reason)
            assertThrows(IllegalArgumentException::class.java) {
                runBlocking { client(agent).playerAction("s", "run", "Alex", null, confirm = false) }
            }
            assertThrows(IllegalArgumentException::class.java) {
                runBlocking { client(agent).recommendationAction("s", "java", "apply") }
            }
        }
    }
}
