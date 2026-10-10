package io.github.peyoteheadlights.mcsc.core

import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class AlertSyncTest {
    private fun alert(id: Long) = AppAlert(id, id.toDouble(), "survival", "server_crashed", "Crashed $id", "", "overview", "/#overview")

    /** A pretend agent holding alerts 1..[last], answering like phoneapp.py. */
    private class Agent(var last: Long) {
        val asked = mutableListOf<Long?>()
        fun answer(after: Long?, limit: Int): AppAlerts {
            asked += after
            if (after == null) return AppAlerts(latest = last)
            val ids = ((after + 1)..last).take(limit)
            val more = ids.size == limit && ids.last() < last
            return AppAlerts(alerts = ids.map { AppAlert(it, it.toDouble(), null, "e", "t$it", "", "p", "/") }, latest = if (more) ids.last() else last, more = more)
        }
    }

    @Test
    fun `a newly paired phone starts from now`() = runBlocking {
        val agent = Agent(last = 40)
        val state = AlertSync(agent::answer).catchUp(AlertState())
        assertEquals(40L, state.cursor)
        assertEquals(0, state.alerts.size)
        assertEquals(0, state.unread)
    }

    @Test
    fun `new alerts arrive page by page and count as unread`() = runBlocking {
        val agent = Agent(last = 40)
        val sync = AlertSync(agent::answer)
        var state = sync.catchUp(AlertState())
        agent.last = 165
        state = sync.catchUp(state, pageSize = 50)
        assertEquals((41L..165L).toList(), state.alerts.map { it.id })
        assertEquals(listOf(null, 40L, 90L, 140L), agent.asked)
        assertEquals(125, state.unread)
        assertEquals(165L, state.newestFirst.first().id)
        state = state.markAllRead()
        assertEquals(0, state.unread)
        agent.last = 166
        assertEquals(1, sync.catchUp(state).unread)
    }

    @Test
    fun `the phone keeps the newest 200`() = runBlocking {
        val agent = Agent(last = 0)
        val sync = AlertSync(agent::answer)
        var state = sync.catchUp(AlertState())
        agent.last = 450
        state = sync.catchUp(state, pageSize = 200)
        assertEquals(AlertState.KEPT, state.alerts.size)
        assertEquals(251L, state.alerts.first().id)
    }

    @Test
    fun `a fresh list on the PC starts the phone's list again`() = runBlocking {
        val agent = Agent(last = 0)
        val sync = AlertSync(agent::answer)
        var state = sync.catchUp(AlertState())
        agent.last = 30
        state = sync.catchUp(state)
        agent.last = 2
        state = sync.catchUp(state)
        assertEquals(2L, state.cursor)
        assertEquals(0, state.alerts.size)
        assertNull(AlertState().cursor)
        assertEquals(alert(1).id, 1L)
    }
}
