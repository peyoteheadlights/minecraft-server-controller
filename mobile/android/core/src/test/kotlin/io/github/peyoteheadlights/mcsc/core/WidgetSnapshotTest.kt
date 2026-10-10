package io.github.peyoteheadlights.mcsc.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class WidgetSnapshotTest {
    private val list = ServerList(listOf(ServerRow("survival", "Survival", "#1967D4", "ONLINE", playersOnline = 3, maxPlayers = 20)))

    @Test
    fun `a fresh read is shown as it is`() {
        val snap = WidgetSnapshot.read(list, now = 1000.0)
        assertEquals("ONLINE", snap.shown(1100.0).servers.single().state)
        assertEquals(3, snap.shown(1100.0).servers.single().playersOnline)
        assertTrue(snap.isFresh(1100.0))
    }

    @Test
    fun `an old read turns Unknown instead of looking current`() {
        val snap = WidgetSnapshot.read(list, now = 1000.0)
        val later = snap.shown(1000.0 + WidgetSnapshot.FRESH_FOR + 1)
        assertEquals("UNKNOWN", later.servers.single().state)
        assertNull(later.servers.single().playersOnline)
        assertEquals(1000.0, later.checkedAt, 0.0)
    }

    @Test
    fun `an unreachable PC keeps the names, not what they were doing`() {
        val before = WidgetSnapshot.read(list, now = 1000.0)
        val snap = WidgetSnapshot.failed(before, AgentException.Unreachable(), now = 2000.0)
        assertFalse(snap.reached)
        assertEquals("mobile.error.unreachable", snap.problemKey)
        assertEquals("Survival", snap.servers.single().name)
        assertEquals("UNKNOWN", snap.shown(2000.0).servers.single().state)
        assertNull(snap.servers.single().playersOnline)
        assertEquals(emptyList<WidgetServer>(), WidgetSnapshot.failed(null, AgentException.Unreachable(), 1.0).servers)
    }
}
