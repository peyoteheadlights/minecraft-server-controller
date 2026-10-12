package io.github.peyoteheadlights.mcsc.core

import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

/** The owner's moderator screens and a moderator's invite (agent/api/routes/accounts.py). */
class ModeratorsTest {
    private val json = Json { ignoreUnknownKeys = true }
    private val strings = Strings(Shared.strings)
    private val token = "secret-session-token-1234567890"

    // The catalogue GET /api/accounts sends (agent/security/permissions.py).
    private val catalogue = json.decodeFromString(
        PermissionCatalogue.serializer(),
        """{"levels": [
              {"id": "start_and_stop", "permissions": ["server.control", "server.view"]},
              {"id": "look_after_it", "permissions": ["backups.create", "chat.send", "console.read", "players.manage", "server.control", "server.view"]},
              {"id": "run_it", "permissions": ["backups.create", "backups.restore", "chat.send", "console.read", "mods.manage", "players.manage", "schedules.manage", "server.control", "server.view", "settings.game", "settings.server"]}],
            "default_level": "look_after_it",
            "groups": [
              {"id": "server", "permissions": ["server.control", "console.read", "console.send"]},
              {"id": "players", "permissions": ["players.manage", "chat.send", "players.op"]},
              {"id": "addons", "permissions": ["mods.manage"]},
              {"id": "backups", "permissions": ["backups.create", "backups.restore", "backups.download", "backups.delete", "world.replace"]},
              {"id": "settings", "permissions": ["settings.game", "settings.server", "schedules.manage"]}],
            "technical": ["backups.delete", "backups.download", "console.send", "players.op", "world.replace"],
            "warn": ["console.send", "players.op"],
            "needs": {"players.op": ["players.manage"], "console.send": ["console.read"]}}""",
    )

    private val lookAfterIt = Moderators.level(Levels.LOOK_AFTER_IT, catalogue)

    @Test
    fun `a set reads as its level, or Custom`() {
        assertEquals(Levels.LOOK_AFTER_IT, Moderators.levelOf(lookAfterIt, catalogue))
        assertEquals(Levels.NONE, Moderators.levelOf(emptySet(), catalogue))
        val custom = Moderators.toggle(lookAfterIt, Permissions.CHAT_SEND, false, catalogue)
        assertEquals(Levels.CUSTOM, Moderators.levelOf(custom, catalogue))
        // Ticking it again is the level once more.
        assertEquals(Levels.LOOK_AFTER_IT, Moderators.levelOf(Moderators.toggle(custom, Permissions.CHAT_SEND, true, catalogue), catalogue))
    }

    @Test
    fun `joined switches move together`() {
        val start = Moderators.level(Levels.START_AND_STOP, catalogue)
        val op = Moderators.toggle(start, Permissions.PLAYERS_OP, true, catalogue)
        assertTrue(Permissions.PLAYERS_MANAGE in op)
        // Taking Players away takes Make ops with it.
        val noPlayers = Moderators.toggle(op, Permissions.PLAYERS_MANAGE, false, catalogue)
        assertFalse(Permissions.PLAYERS_OP in noPlayers)
        assertTrue(Permissions.CONSOLE_READ in Moderators.toggle(start, Permissions.CONSOLE_SEND, true, catalogue))
    }

    @Test
    fun `anything ticked sees the server, nothing ticked hides it`() {
        val one = Moderators.toggle(emptySet(), Permissions.CHAT_SEND, true, catalogue)
        assertEquals(setOf(Permissions.CHAT_SEND, Permissions.SERVER_VIEW), one)
        assertEquals(emptySet<String>(), Moderators.toggle(one, Permissions.CHAT_SEND, false, catalogue))
    }

    @Test
    fun `Simple mode hides the Technical-only switches and counts the ticked ones`() {
        val backups = catalogue.groups.single { it.id == "backups" }
        assertEquals(listOf("backups.create", "backups.restore"), Moderators.shown(backups, technical = false, catalogue))
        assertEquals(5, Moderators.shown(backups, technical = true, catalogue).size)
        val withConsole = Moderators.toggle(lookAfterIt, Permissions.CONSOLE_SEND, true, catalogue)
        val withDelete = Moderators.toggle(withConsole, Permissions.BACKUPS_DELETE, true, catalogue)
        assertEquals(2, Moderators.hiddenTicked(withDelete, technical = false, catalogue))
        assertEquals(0, Moderators.hiddenTicked(withDelete, technical = true, catalogue))
        assertEquals(0, Moderators.hiddenTicked(lookAfterIt, technical = false, catalogue))
    }

    @Test
    fun `Console commands and Make ops warn`() {
        assertFalse(Moderators.warns(lookAfterIt, catalogue))
        assertTrue(Moderators.warns(Moderators.toggle(lookAfterIt, Permissions.PLAYERS_OP, true, catalogue), catalogue))
    }

    @Test
    fun `the summary names the level or the first few switches`() {
        assertEquals("Look after it", Moderators.summary(lookAfterIt, catalogue, strings))
        assertEquals("No access", Moderators.summary(emptySet(), catalogue, strings))
        val few = Moderators.toggle(Moderators.level(Levels.START_AND_STOP, catalogue), Permissions.CHAT_SEND, true, catalogue)
        assertEquals("Start and stop, Chat", Moderators.summary(few, catalogue, strings))
        val many = Moderators.toggle(lookAfterIt, Permissions.CHAT_SEND, false, catalogue)
        assertEquals("Start and stop, See the Console and Activity, Players and 1 more", Moderators.summary(many, catalogue, strings))
    }

    @Test
    fun `every switch has a name`() {
        for (permission in catalogue.groups.flatMap { it.permissions }) {
            val key = Moderators.switchKey(permission)
            assertTrue(key, Shared.strings.containsKey(key))
        }
        for (level in catalogue.levels) assertTrue(Shared.strings.containsKey("mobile.mod.level_${level.id}"))
    }

    @Test
    fun `Save for and Apply to all send each server the same set`() {
        val body = Moderators.saveFor(listOf("survival", "creative"), lookAfterIt)
        val grants = body["grants"]!!.jsonObject
        assertEquals(setOf("survival", "creative"), grants.keys)
        assertEquals(lookAfterIt, grants["creative"]!!.jsonArray.map { it.jsonPrimitive.content }.toSet())
        assertNull(body["new_server"])
        val all = Moderators.applyToAll(listOf("survival"), lookAfterIt, allServers = true)
        assertEquals(lookAfterIt, all["new_server"]!!.jsonArray.map { it.jsonPrimitive.content }.toSet())
        assertNull(Moderators.applyToAll(listOf("survival"), lookAfterIt, allServers = false)["new_server"])
    }

    @Test
    fun `All servers gives new servers what most of their servers have`() {
        val sam = Moderator(
            username = "sam",
            access = listOf(
                ServerAccess("a", "A", lookAfterIt.toList()),
                ServerAccess("b", "B", lookAfterIt.toList()),
                ServerAccess("c", "C", listOf(Permissions.SERVER_VIEW, Permissions.SERVER_CONTROL)),
                ServerAccess("d", "D"),
            ),
        )
        val on = Moderators.allServers(true, sam, catalogue)
        assertEquals(lookAfterIt, on["new_server"]!!.jsonArray.map { it.jsonPrimitive.content }.toSet())
        // Nobody's servers yet: the default level.
        val fresh = Moderators.allServers(true, Moderator(username = "jo"), catalogue)
        assertEquals(lookAfterIt, fresh["new_server"]!!.jsonArray.map { it.jsonPrimitive.content }.toSet())
        val off = Moderators.allServers(false, sam, catalogue)
        assertEquals("false", off["all_servers"]!!.jsonPrimitive.content)
        assertNull(off["new_server"])
    }

    @Test
    fun `names the agent takes`() {
        assertTrue(Moderators.nameOk("sam"))
        assertTrue(Moderators.nameOk("sam.b-2"))
        assertFalse(Moderators.nameOk("s"))
        assertFalse(Moderators.nameOk("sam smith"))
        assertFalse(Moderators.nameOk("-sam"))
    }

    @Test
    fun `the moderator list reads with its catalogue`() = runBlocking {
        TestAgent().use { agent ->
            agent.server.enqueue(
                agent.json(
                    """{"owner": "admin", "helpers": [{"username": "sam", "role": "helper", "servers": null, "all_servers": true,
                        "new_server": {"permissions": ["server.control", "server.view"], "level": "start_and_stop"},
                        "access": [{"id": "survival", "name": "Survival", "permissions": ["server.control", "server.view"], "level": "start_and_stop"},
                                   {"id": "creative", "name": "Creative", "permissions": [], "level": "none"}],
                        "invite_waiting": true, "invite": {"created_at": 1.0, "expires_at": 86401.0},
                        "active_sessions": 0, "last_used": null}],
                      "permissions": {"levels": [], "groups": []}, "servers": [{"id": "survival", "name": "Survival"}]}""",
                ),
            )
            val list = client(agent).moderators()
            val sam = list.helpers.single()
            assertTrue(sam.inviteWaiting)
            assertTrue(sam.allServers)
            assertEquals(listOf("survival"), sam.seen.map { it.id })
            assertEquals(Levels.START_AND_STOP, sam.newServer.level)
        }
    }

    @Test
    fun `saving and inviting send what the agent reads`() = runBlocking {
        TestAgent().use { agent ->
            agent.server.enqueue(agent.json("""{"ok": true, "username": "sam"}"""))
            client(agent).saveModerator("sam", Moderators.saveFor(listOf("survival"), lookAfterIt))
            val put = agent.server.takeRequest()
            assertEquals("PUT", put.method)
            assertEquals("/api/accounts/sam", put.path)
            assertTrue(put.body.readUtf8().contains("\"grants\""))

            agent.server.enqueue(agent.json("""{"ok": true, "username": "sam", "expires_at": 2.0, "url": "https://pc:8765/?pair=1&invite=x&user=sam", "qr": ["101"]}"""))
            val code = client(agent).inviteModerator("sam", forgetPassword = true)
            assertEquals(listOf("101"), code.qr)
            val post = agent.server.takeRequest()
            assertEquals("/api/accounts/sam/invite", post.path)
            assertEquals("""{"forget_password":true}""", post.body.readUtf8())

            agent.server.enqueue(agent.json("""{"ok": true, "username": "jo", "invite": {"ok": true, "username": "jo", "expires_at": 3.0}}"""))
            val added = client(agent).addModerator("jo", null, lookAfterIt)
            assertEquals("jo", added.invite?.username)
            val body = json.parseToJsonElement(agent.server.takeRequest().body.readUtf8()).jsonObject
            assertNull(body["servers"])
            assertNull(body["password"])
        }
    }

    @Test
    fun `your own devices, and signing one out`() = runBlocking {
        TestAgent().use { agent ->
            agent.server.enqueue(
                agent.json(
                    """{"sessions": [{"id": "a1", "user": "sam", "label": "Command Block on Pixel 8", "last_used": 5.0, "current": true},
                                     {"id": "b2", "user": "sam", "label": "Firefox", "last_used": 3.0}], "remember_days": 30}""",
                ),
            )
            val devices = client(agent).devices().sessions
            assertEquals(listOf(true, false), devices.map { it.current })
            agent.server.takeRequest()
            agent.server.enqueue(agent.json("""{"ok": true}"""))
            client(agent).signOutDevice("b2")
            val delete = agent.server.takeRequest()
            assertEquals("DELETE", delete.method)
            assertEquals("/api/sessions/b2", delete.path)
        }
    }

    // ------------------------------------------------------------ invites
    private val link = "https://pc.tail1234.ts.net:8765/?pair=1&fp=${"ab".repeat(32)}&api=1&invite=Zx_9-abcdefghijklmnopqrstu&user=sam"

    @Test
    fun `an invite is read from a code, pasted text or a link`() {
        assertEquals(Invite("Zx_9-abcdefghijklmnopqrstu", "sam"), InviteLink.parse(link))
        // Pasted from a message: the words around it don't matter.
        assertEquals("sam", InviteLink.parse("Here it is:\n$link\nIt works once.")?.username)
        // The same link pairs with the PC.
        val pairing = PairingLink.parse(link)
        assertEquals("pc.tail1234.ts.net", pairing.host)
        assertEquals("ab".repeat(32), pairing.fingerprint)
    }

    @Test
    fun `a broken invite is refused`() {
        assertNull(InviteLink.parse("https://pc:8765/?pair=1&fp=${"ab".repeat(32)}"))
        assertNull(InviteLink.parse(link.replace("invite=Zx_9-abcdefghijklmnopqrstu", "invite=short")))
        assertNull(InviteLink.parse(link.replace("user=sam", "user=")))
        assertNull(InviteLink.parse(link.replace("user=sam", "user=a%20b")))
        assertNull(InviteLink.parse(""))
    }

    @Test
    fun `used, cancelled and run out invites say to ask for a new one`() = runBlocking {
        TestAgent().use { agent ->
            for (words in listOf(
                "This invite was already used. Ask the owner for a new one.",
                "This invite was cancelled. Ask the owner for a new one.",
                "This invite has run out. Ask the owner for a new one.",
            )) {
                agent.server.enqueue(agent.json("""{"detail": "$words"}""", code = 410))
                val e = assertThrows(AgentException.Failed::class.java) { runBlocking { client(agent, current = { null }).checkInvite("Zx_9-abcdefghijklmnopqrstu") } }
                assertEquals(words, e.reason)
            }
        }
    }

    @Test
    fun `accepting an invite needs no sign-in and returns one`() = runBlocking {
        TestAgent().use { agent ->
            agent.server.enqueue(agent.json("""{"token": "new-token-for-sam-1234567890", "user": "sam", "role": "helper", "expires_at": null}"""))
            val result = client(agent, current = { null }).acceptInvite("Zx_9-abcdefghijklmnopqrstu", "a long password", "Command Block on Pixel 8")
            assertEquals("new-token-for-sam-1234567890", result.token)
            val sent = agent.server.takeRequest()
            assertEquals("/api/invite/accept", sent.path)
            assertNull(sent.getHeader("Authorization"))
        }
    }

    private fun client(agent: TestAgent, current: () -> String? = { token }) =
        AgentClient(agent.pairing(), current, {}, AgentLog { }, systemTrust = TestAgent.trustingNothing())
}
