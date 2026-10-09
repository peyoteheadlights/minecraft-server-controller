package io.github.peyoteheadlights.mcsc.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class DisplayTest {
    private val s = Strings(Shared.strings)

    @Test
    fun `states read as in the dashboard`() {
        assertEquals("Online", s.t(Display.state("ONLINE").key))
        assertEquals("Crashed", s.t(Display.state("RESTART_PENDING").key))
        assertEquals("Unknown", s.t(Display.state("SOMETHING_NEW").key))
        assertEquals("Unknown", s.t(Display.state(null).key))
        assertTrue(Display.state("STARTING").busy)
    }

    @Test
    fun `durations and players`() {
        assertEquals("40s", Display.duration(s, 40.9))
        assertEquals("5m", Display.duration(s, 300.0))
        assertEquals("2h 10m", Display.duration(s, 7800.0))
        assertEquals("3d 4h", Display.duration(s, 3 * 86400.0 + 4 * 3600))
        assertEquals("5m ago", Display.ago(s, 1000.0, 1300.0))
        assertEquals("Never", Display.ago(s, null, 1300.0))
        assertEquals("3 of 20", Display.players(s, 3, 20))
        assertEquals("Unknown", Display.players(s, null, 20))
        assertEquals("Up for 5m", Display.uptime(s, "ONLINE", 300.0))
        assertNull(Display.uptime(s, "ONLINE", null))
        assertNull(Display.uptime(s, "OFFLINE", 300.0))
    }

    @Test
    fun `starting asks nothing, stopping and restarting ask first`() {
        assertEquals(listOf("start"), Display.actions("OFFLINE", true).map { it.action })
        assertEquals(false, Display.actions("CRASHED", true).single().confirm)
        val online = Display.actions("ONLINE", true)
        assertEquals(listOf("restart", "stop"), online.map { it.action })
        assertTrue(online.all { it.confirm })
        for (busy in listOf("STARTING", "STOPPING", "RESTARTING", "RESTART_PENDING", "UNKNOWN")) {
            assertEquals(busy, emptyList<QuickAction>(), Display.actions(busy, true))
        }
        assertEquals(emptyList<QuickAction>(), Display.actions("OFFLINE", canControl = false))
    }
}
