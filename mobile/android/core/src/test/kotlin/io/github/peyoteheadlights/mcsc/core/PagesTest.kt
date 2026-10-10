package io.github.peyoteheadlights.mcsc.core

import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PagesTest {
    private val token = "secret-session-token-1234567890"

    private fun client(agent: TestAgent) = AgentClient(agent.pairing(), { token }, systemTrust = TestAgent.trustingNothing())

    private fun line(seq: Long, raw: String = "line $seq", level: String = "INFO", source: String = "stdout") =
        ConsoleLine(seq = seq, ts = 1000.0 + seq, raw = raw, level = level, source = source)

    @Test
    fun `the console keeps the newest thousand lines, once each`() {
        var lines = ConsoleBuffer.replace((1L..1200L).map { line(it) })
        assertEquals(1000, lines.size)
        assertEquals(201L, lines.first().seq)
        lines = ConsoleBuffer.add(lines, line(1201))
        assertEquals(1000, lines.size)
        assertEquals(202L, lines.first().seq)
        assertEquals(1201L, lines.last().seq)
        // The same line from GET /logs and from the feed shows once.
        assertEquals(lines, ConsoleBuffer.add(lines, line(1201)))
    }

    @Test
    fun `the filter and chips work on the loaded lines`() {
        val lines = listOf(
            line(1, "[10:00:00] [Server thread/INFO]: Done (3.2s)!"),
            line(2, "[10:00:01] [Server thread/WARN]: Can't keep up!", "WARN"),
            line(3, "[10:00:02] [Server thread/ERROR]: Exception ticking world", "ERROR"),
            line(4, "[10:00:03] [Server thread/FATAL]: Stopping", "FATAL"),
            line(5, "> say hi", source = "command"),
        )
        assertEquals(lines, ConsoleBuffer.shown(lines, "  ", LevelChip.ALL))
        assertEquals(listOf(1L), ConsoleBuffer.shown(lines, "done", LevelChip.ALL).map { it.seq })
        assertEquals(listOf(2L), ConsoleBuffer.shown(lines, "", LevelChip.WARNINGS).map { it.seq })
        assertEquals(listOf(3L, 4L), ConsoleBuffer.shown(lines, "", LevelChip.ERRORS).map { it.seq })
        assertEquals(listOf(4L), ConsoleBuffer.shown(lines, "STOPPING", LevelChip.ERRORS).map { it.seq })
        assertEquals(
            listOf(LineLook.PLAIN, LineLook.WARNING, LineLook.DANGER, LineLook.DANGER, LineLook.COMMAND),
            lines.map(ConsoleBuffer::look),
        )
    }

    @Test
    fun `chat keeps three hundred and never adds a message twice`() {
        val messages = (1L..320L).map { ChatMessage(seq = it, ts = it.toDouble(), name = "Alex", text = "hi $it") }
        var kept = ChatBuffer.replace(messages)
        assertEquals(300, kept.size)
        assertEquals(21L, kept.first().seq)
        kept = ChatBuffer.add(kept, ChatMessage(seq = 320, ts = 320.0, name = "Alex", text = "hi 320"))
        assertEquals(300, kept.size)
        kept = ChatBuffer.add(kept, ChatMessage(seq = 321, ts = 321.0, kind = "server", text = "hello"))
        assertEquals(321L, kept.last().seq)
        assertEquals(22L, kept.first().seq)
    }

    @Test
    fun `a command is checked, risky ones ask first, then it is sent`() = runBlocking {
        TestAgent().use { agent ->
            val commands = ConsoleCommands(client(agent), "survival")
            assertEquals(CommandStep.Empty, commands.submit("   "))
            assertEquals(0, agent.server.requestCount)

            agent.server.enqueue(agent.json("""{"valid": false, "error": "Unknown characters", "danger_reason": null}"""))
            assertEquals(CommandStep.Invalid("Unknown characters"), commands.submit("say \$HOME"))
            assertEquals(1, agent.server.requestCount)
            val check = agent.server.takeRequest()
            assertEquals("/api/servers/survival/server/command/check", check.requestUrl!!.encodedPath)
            assertEquals("say \$HOME", check.requestUrl!!.queryParameter("command"))

            agent.server.enqueue(agent.json("""{"valid": true, "error": null, "danger_reason": "Stops the server for everyone."}"""))
            val ask = commands.submit(" stop ")
            assertEquals(CommandStep.AskFirst("stop", "Stops the server for everyone."), ask)
            agent.server.takeRequest()
            // Nothing sent until the person says yes.
            assertEquals(2, agent.server.requestCount)
            agent.server.enqueue(agent.json("""{"result": "SENT", "detail": "Sent", "command": "stop", "dangerous": true}"""))
            assertEquals("SENT", commands.confirmed("stop").answer.result)
            val sent = agent.server.takeRequest()
            assertEquals("/api/servers/survival/server/command", sent.path)
            val body = sent.body.readUtf8()
            assertTrue(body, body.contains("\"confirm\":true"))

            agent.server.enqueue(agent.json("""{"valid": true, "error": null, "danger_reason": null}"""))
            agent.server.enqueue(agent.json("""{"result": "SENT", "command": "list"}"""))
            val step = commands.submit("list")
            assertTrue(step is CommandStep.Sent)
            agent.server.takeRequest()
            assertTrue(agent.server.takeRequest().body.readUtf8().contains("\"confirm\":false"))
        }
    }

    @Test
    fun `the server not running comes back in the agent's words`() {
        TestAgent().use { agent ->
            agent.server.enqueue(agent.json("""{"valid": true, "danger_reason": null}"""))
            agent.server.enqueue(agent.json("""{"detail": "The server isn't running.", "request_id": "r1"}""", code = 409))
            val e = org.junit.Assert.assertThrows(AgentException.Failed::class.java) {
                runBlocking { ConsoleCommands(client(agent), "survival").submit("list") }
            }
            assertEquals(409, e.status)
            assertEquals("The server isn't running.", e.reason)
        }
    }

    @Test
    fun `only the last twenty commands are kept, newest last`() {
        var history = emptyList<String>()
        for (i in 1..25) history = ConsoleCommands.remember(history, "say $i")
        assertEquals(20, history.size)
        assertEquals("say 25", history.last())
        history = ConsoleCommands.remember(history, "say 10")
        assertEquals("say 10", history.last())
        assertEquals(1, history.count { it == "say 10" })
    }

    private fun action(state: String) = PlayerAction(id = "abc123def456", kind = "kick", name = "Alex", state = state)

    /** A clock that only moves when the watch waits. */
    private class FakeTime {
        var now = 0L
        val waits = mutableListOf<Long>()
        fun clock() = now
        suspend fun sleep(ms: Long) {
            waits += ms
            now += ms
        }
    }

    @Test
    fun `a player button is followed every second until it is answered`() = runBlocking {
        val time = FakeTime()
        val answers = ArrayDeque(listOf(action("sent"), action("sent"), action("done")))
        val seen = mutableListOf<String>()
        val last = PlayerActionWatch({ answers.removeFirst() }, clock = time::clock, sleep = time::sleep)
            .follow(action("sent")) { seen += it.state }
        assertEquals("done", last.state)
        assertEquals(listOf(1000L, 1000L, 1000L), time.waits)
        assertEquals(listOf("done"), seen)
        assertEquals("players.state_done", Display.actionState(last.state).key)
    }

    @Test
    fun `sent but not confirmed is said honestly`() = runBlocking {
        val time = FakeTime()
        // The agent gives up after 20 s and says so.
        val last = PlayerActionWatch({ if (time.now >= 20_000) action("no_answer") else action("sent") }, clock = time::clock, sleep = time::sleep)
            .follow(action("sent"))
        assertEquals("no_answer", last.state)
        assertEquals("Sent, not confirmed", Strings(Shared.strings).t(Display.actionState(last.state).key))

        // No answer at all within 22 s: still "Sent", never "Done".
        val quiet = FakeTime()
        val still = PlayerActionWatch({ action("sent") }, clock = quiet::clock, sleep = quiet::sleep).follow(action("sent"))
        assertEquals("sent", still.state)
        assertEquals(22, quiet.waits.size)
        assertEquals("Sent", Strings(Shared.strings).t(Display.actionState(still.state).key))

        // The PC stops answering: the last thing it said stands.
        val lost = PlayerActionWatch({ throw AgentException.Unreachable() }, clock = FakeTime()::clock, sleep = { }).follow(action("sent"))
        assertEquals("sent", lost.state)
    }

    @Test
    fun `the poll goes to the server the action was sent to`() = runBlocking {
        TestAgent().use { agent ->
            val c = client(agent)
            agent.server.enqueue(agent.json("""{"result": "SENT", "action": {"id": "abc123def456", "kind": "ban", "name": "Alex", "command": "ban Alex", "sent_at": 1, "state": "sent", "message": null}}"""))
            agent.server.enqueue(agent.json("""{"action": {"id": "abc123def456", "kind": "ban", "name": "Alex", "state": "done", "message": "Banned Alex"}}"""))
            val sent = c.playerAction("creative", PlayerActions.BAN, "Alex", reason = "griefing", confirm = true)
            val done = PlayerActionWatch({ c.playerActionStatus("creative", it).action }, sleep = { }).follow(sent.action)
            assertEquals("done", done.state)
            val first = agent.server.takeRequest()
            assertEquals("/api/servers/creative/players/actions", first.path)
            val body = first.body.readUtf8()
            assertTrue(body, body.contains("\"reason\":\"griefing\"") && body.contains("\"confirm\":true"))
            assertEquals("/api/servers/creative/players/actions/abc123def456", agent.server.takeRequest().path)
        }
    }

    @Test
    fun `player buttons follow the lists and the permissions`() {
        val page = PlayersPage(
            lists = PlayerLists(
                whitelist = PlayerList(listOf(ListedPlayer(name = "Alex"))),
                ops = PlayerList(listOf(ListedPlayer(name = "steve"))),
                banned = PlayerList(listOf(ListedPlayer(name = "Griefer"))),
            ),
            bans = true,
        )
        assertEquals(
            listOf("whitelist_remove", "op", "kick", "ban"),
            PlayerButtons.forPlayer("alex", online = true, page = page, canManage = true, canOp = true),
        )
        // A helper: no operator buttons.
        assertEquals(listOf("whitelist_add", "pardon"), PlayerButtons.forPlayer("Griefer", false, page, canManage = true, canOp = false))
        assertEquals(listOf("whitelist_add", "deop"), PlayerButtons.forPlayer("Steve", false, page.copy(bans = false), true, true))
        assertEquals(emptyList<String>(), PlayerButtons.forPlayer("Alex", true, page, canManage = false, canOp = true))
        assertEquals(listOf("players.tag_whitelisted"), PlayerButtons.tags("ALEX", page))
        assertEquals("deop", PlayerButtons.removeFrom("ops"))
    }

    @Test
    fun `names are checked as the agent checks them`() {
        assertTrue(PlayerButtons.validName("Alex_99", "java"))
        assertTrue(PlayerButtons.validName(".BedrockGuy", null))
        assertFalse(PlayerButtons.validName("way_too_long_name_x", "java"))
        assertFalse(PlayerButtons.validName("has space", "java"))
        assertTrue(PlayerButtons.validName("Cool Gamer 7", "bedrock"))
        assertFalse(PlayerButtons.validName("double  space", "bedrock"))
        assertFalse(PlayerButtons.validName("trailing ", "bedrock"))
    }
}
