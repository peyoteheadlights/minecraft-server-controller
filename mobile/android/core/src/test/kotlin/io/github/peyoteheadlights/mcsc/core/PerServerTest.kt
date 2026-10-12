package io.github.peyoteheadlights.mcsc.core

import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** What an account may do on each server (agent/security/permissions.py). */
class PerServerTest {
    private val json = Json { ignoreUnknownKeys = true }

    private val moderator = json.decodeFromString(
        Me.serializer(),
        """{"user": "sam", "kind": "session", "role": "helper", "servers": ["survival", "creative"],
            "permissions": ["account.self", "server.view", "server.control", "console.read", "mods.manage", "settings.edit"],
            "account_permissions": ["account.self", "settings.view"],
            "server_permissions": {"survival": ["server.control", "server.view"],
                "creative": ["console.read", "mods.manage", "server.control", "server.view", "settings.game"]},
            "preferences": {}}""",
    )

    @Test
    fun `each server has its own permissions`() {
        val survival = moderator.forServer("survival")
        assertTrue(survival.can(Permissions.SERVER_CONTROL))
        assertFalse(survival.can(Permissions.CONSOLE_READ))
        assertFalse(survival.can(Permissions.MODS_MANAGE))
        assertTrue(survival.can(Permissions.SETTINGS_VIEW))
        val creative = moderator.forServer("creative")
        assertTrue(creative.can(Permissions.MODS_MANAGE))
        assertTrue(creative.can(Permissions.SETTINGS_GAME))
        assertFalse(creative.can(Permissions.SETTINGS_SERVER))
    }

    @Test
    fun `a server that isn't listed allows nothing and isn't seen`() {
        assertFalse(moderator.forServer("hidden").can(Permissions.SERVER_VIEW))
        assertFalse(moderator.sees("hidden"))
        assertTrue(moderator.sees("survival"))
        assertTrue(moderator.sees(null))
    }

    @Test
    fun `an older agent's one settings permission covers all three`() {
        val old = Me(user = "x", permissions = listOf(Permissions.SETTINGS_EDIT))
        assertTrue(old.can(Permissions.SETTINGS_GAME))
        assertTrue(old.can(Permissions.PC_SETTINGS))
        assertEquals(old, old.forServer("survival"))
        // A part 6 agent's list is read as it is.
        assertFalse(moderator.forServer("survival").can(Permissions.SETTINGS_SERVER))
    }

    @Test
    fun `alerts of a server taken away go with it`() {
        fun alert(id: Long, server: String?) = AppAlert(id, 1.0, server, "e", "t", "", "p", "/")
        val state = AlertState(alerts = listOf(alert(1, "survival"), alert(2, "hidden"), alert(3, null)))
        assertEquals(listOf(1L, 3L), state.onlyFor(moderator).alerts.map { it.id })
        val owner = Me(user = "admin", serverPermissions = mapOf("survival" to emptyList()))
        assertEquals(3, state.onlyFor(owner).alerts.size)
    }
}
