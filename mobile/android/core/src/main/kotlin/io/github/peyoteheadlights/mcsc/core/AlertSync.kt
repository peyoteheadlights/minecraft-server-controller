package io.github.peyoteheadlights.mcsc.core

import kotlinx.serialization.Serializable

/**
 * The Notifications tab's list as the phone keeps it: the alerts read so
 * far (newest [KEPT]), where to carry on reading ([cursor]) and how far the
 * person has looked ([readUpTo]). Saved on the phone between launches.
 */
@Serializable
data class AlertState(
    val cursor: Long? = null,
    val readUpTo: Long = 0,
    val alerts: List<AppAlert> = emptyList(),
) {
    /** Newest first, for the list. */
    val newestFirst: List<AppAlert> get() = alerts.sortedByDescending { it.id }

    val unread: Int get() = alerts.count { it.id > readUpTo }

    fun markAllRead(): AlertState = copy(readUpTo = maxOf(readUpTo, alerts.maxOfOrNull { it.id } ?: 0))

    companion object {
        /** The agent keeps its newest 200 (APP_ALERTS_KEPT); so does the phone. */
        const val KEPT = 200
    }
}

/**
 * Catches the list up with the agent's (GET /api/alerts). A newly paired
 * phone starts from "now": it learns where the list is and shows nothing
 * old. After that, every alert since the last read is fetched, page by
 * page. Called when the app opens, on a live-feed event, from the push
 * wake-up and from the widget's refresh.
 */
class AlertSync(private val fetch: suspend (after: Long?, limit: Int) -> AppAlerts) {
    suspend fun catchUp(state: AlertState, pageSize: Int = 50, maxPages: Int = 10): AlertState {
        val cursor = state.cursor
        if (cursor == null) {
            val now = fetch(null, pageSize)
            return state.copy(cursor = now.latest, readUpTo = now.latest)
        }
        var after: Long = cursor
        val found = mutableListOf<AppAlert>()
        for (page in 0 until maxPages) {
            val answer = fetch(after, pageSize)
            if (answer.latest < after) {
                // The agent's list started again (a new data folder): its
                // numbers mean other alerts now, so start from where it is.
                return AlertState(cursor = answer.latest, readUpTo = answer.latest)
            }
            found += answer.alerts
            after = answer.latest
            if (!answer.more) break
        }
        val byId = LinkedHashMap<Long, AppAlert>()
        for (alert in state.alerts + found) byId[alert.id] = alert
        val kept = byId.values.sortedBy { it.id }.takeLast(AlertState.KEPT)
        return state.copy(cursor = after, alerts = kept)
    }
}
