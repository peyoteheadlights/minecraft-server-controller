package io.github.peyoteheadlights.mcsc.core

import kotlinx.serialization.Serializable

@Serializable
data class WidgetServer(
    val id: String,
    val name: String,
    val color: String? = null,
    val state: String = States.UNKNOWN,
    val playersOnline: Int? = null,
    val maxPlayers: Int? = null,
)

/**
 * What the home-screen widget shows, saved by the background refresh.
 * Only what the last read actually saw is shown as current: a PC that
 * didn't answer leaves every server Unknown, with when it was last
 * checked, and a reading older than [FRESH_FOR] seconds turns Unknown too.
 */
@Serializable
data class WidgetSnapshot(
    val checkedAt: Double,
    val reached: Boolean,
    val problemKey: String? = null,
    val servers: List<WidgetServer> = emptyList(),
) {
    /** The snapshot as it may be shown at [now]. */
    fun shown(now: Double): WidgetSnapshot =
        if (reached && now - checkedAt <= FRESH_FOR) this
        else copy(servers = servers.map { it.copy(state = States.UNKNOWN, playersOnline = null) })

    fun isFresh(now: Double): Boolean = reached && now - checkedAt <= FRESH_FOR

    companion object {
        /** Android refreshes widgets every 30 minutes at most; allow one miss. */
        const val FRESH_FOR = 60.0 * 60

        fun read(list: ServerList, now: Double): WidgetSnapshot = WidgetSnapshot(
            checkedAt = now,
            reached = true,
            servers = list.servers.map {
                WidgetServer(it.id, it.name, it.color, it.state, it.playersOnline, it.maxPlayers)
            },
        )

        /** The PC didn't answer: keep the names, not what they were doing. */
        fun failed(previous: WidgetSnapshot?, problem: AgentException, now: Double): WidgetSnapshot = WidgetSnapshot(
            checkedAt = now,
            reached = false,
            problemKey = problem.key,
            servers = previous?.servers.orEmpty().map { it.copy(state = States.UNKNOWN, playersOnline = null) },
        )
    }
}
