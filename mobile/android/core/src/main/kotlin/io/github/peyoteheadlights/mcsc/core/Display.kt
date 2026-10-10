package io.github.peyoteheadlights.mcsc.core

/** How a state reads: the same words and tones as the dashboard's STATES
 * (agent/web/js/state.js). */
enum class Tone { SUCCESS, WARNING, DANGER, NEUTRAL }

data class StateWords(val key: String, val tone: Tone, val busy: Boolean = false)

/** What the server screen offers, and which need a second tap. */
data class QuickAction(val action: String, val labelKey: String, val confirm: Boolean, val danger: Boolean = false)

/**
 * Turning what the agent said into words, with the dashboard's own rules:
 * a value the agent didn't measure reads "Unknown", never 0 or a guess, and
 * nothing is shown as current when it came from an earlier read.
 */
object Display {
    private val STATES = mapOf(
        States.ONLINE to StateWords("state.online", Tone.SUCCESS),
        States.OFFLINE to StateWords("state.offline", Tone.NEUTRAL),
        States.STARTING to StateWords("state.starting", Tone.WARNING, busy = true),
        States.STOPPING to StateWords("state.stopping", Tone.WARNING, busy = true),
        States.RESTARTING to StateWords("state.restarting", Tone.WARNING, busy = true),
        // Crashed, with an automatic restart counting down.
        States.RESTART_PENDING to StateWords("state.crashed", Tone.DANGER),
        States.CRASHED to StateWords("state.crashed", Tone.DANGER),
        States.UNKNOWN to StateWords("state.unknown", Tone.NEUTRAL),
    )

    fun state(name: String?): StateWords = STATES[name] ?: STATES.getValue(States.UNKNOWN)

    /** "3d 4h", "2h 10m", "5m", "40s": fmt.duration in agent/web/js/ui.js. */
    fun duration(strings: Strings, seconds: Double): String {
        val s = maxOf(0L, kotlin.math.floor(seconds).toLong())
        val d = s / 86400
        val h = (s % 86400) / 3600
        val m = (s % 3600) / 60
        return when {
            d > 0 -> strings.t("time.days_hours", "d" to d, "h" to h)
            h > 0 -> strings.t("time.hours_minutes", "h" to h, "m" to m)
            m > 0 -> strings.t("time.minutes", "m" to m)
            else -> strings.t("time.seconds", "s" to s)
        }
    }

    /** "5m ago", or "Never" when there is no time. */
    fun ago(strings: Strings, ts: Double?, now: Double): String =
        if (ts == null || ts <= 0) strings.t("time.never")
        else strings.t("time.ago", "duration" to duration(strings, now - ts))

    /** "3 of 20", "3", or Unknown when the player list wasn't read. */
    fun players(strings: Strings, online: Int?, max: Int?): String = when {
        online == null -> strings.t("value.unknown")
        max != null -> strings.t("servers.players_of", "n" to online, "max" to max)
        else -> online.toString()
    }

    /** "Up for 2h 10m" while online; nothing for other states. */
    fun uptime(strings: Strings, state: String?, uptime: Double?): String? =
        if (state == States.ONLINE && uptime != null) strings.t("hero.up_for", "duration" to duration(strings, uptime))
        else null

    /** "Online now (3 of 20)"; without "of" when the maximum isn't known,
     * and "Players not known" until the agent has established the list
     * (never the length of a list that may be old). */
    fun onlineNow(strings: Strings, count: Int?, max: Int?): String = when {
        count == null -> strings.t("overview.players_unknown")
        max == null -> strings.t("mobile.players.online_count", "count" to count)
        else -> strings.t("players.online", "count" to count, "max" to max)
    }

    /** How long someone has been playing; Unknown when the join wasn't
     * seen (the agent then says 0, which wasn't measured). */
    fun playingFor(strings: Strings, player: OnlinePlayer): String {
        val seconds = player.sessionSeconds
        return if (player.sessionStarted == null || seconds == null) strings.t("value.unknown") else duration(strings, seconds)
    }

    /** A crash's exit code, or Unknown (never "null"). */
    fun exitCode(strings: Strings, code: Int?): String = code?.toString() ?: strings.t("value.unknown")

    /** The likely cause in words; the analyzer's own name in Technical
     * words or when the app has no words for it (causeText in crashes.js). */
    fun cause(strings: Strings, category: String?): String {
        if (category.isNullOrBlank() || category == "Unknown") return strings.t("crashes.cause_unknown")
        val key = "cause.$category"
        if (strings.technical || !strings.has(key)) return category
        return strings.t(key).replaceFirstChar { it.uppercaseChar() }
    }

    private val CONFIDENCE = mapOf(
        "confirmed" to StateWords("crashes.conf_confirmed", Tone.DANGER),
        "likely" to StateWords("crashes.conf_likely", Tone.WARNING),
        "possible" to StateWords("crashes.conf_possible", Tone.NEUTRAL),
    )

    fun confidence(name: String?): StateWords = CONFIDENCE[name] ?: StateWords("crashes.conf_unknown", Tone.NEUTRAL)

    private val ACTION_STATES = mapOf(
        PlayerActions.SENT to StateWords("players.state_sent", Tone.WARNING, busy = true),
        PlayerActions.DONE to StateWords("players.state_done", Tone.SUCCESS),
        PlayerActions.UNCHANGED to StateWords("players.state_unchanged", Tone.NEUTRAL),
        PlayerActions.FAILED to StateWords("players.state_failed", Tone.DANGER),
        PlayerActions.NO_ANSWER to StateWords("players.state_no_answer", Tone.WARNING),
    )

    /** What became of a player button. "Sent, not confirmed" is said as
     * such; an unknown state reads Unknown, never "Done". */
    fun actionState(state: String?): StateWords = ACTION_STATES[state] ?: StateWords("value.unknown", Tone.NEUTRAL)

    fun eventTone(level: String?): Tone = when (level) {
        "error" -> Tone.DANGER
        "warn" -> Tone.WARNING
        "success" -> Tone.SUCCESS
        else -> Tone.NEUTRAL
    }

    /** Events Simple words leave out (INTERNAL in agent/web/js/feed.js). */
    private val INTERNAL = setOf(
        "state", "console", "metrics", "job", "chat", "plain", "text",
        "server_start_requested", "server_stop_requested",
        "backup_started", "restore_stopping", "backup_retention",
        "tps_detection_started", "tps_command_detected", "tps_detection_failed",
        "server_changed", "data_folder_moved", "data_folder_not_moved",
    )

    fun worthShowing(type: String, technical: Boolean): Boolean = technical || type !in INTERNAL

    /** 24-hour "14:05:09" in the phone's time zone (fmt.clock). */
    fun clock(ts: Double, zone: java.time.ZoneId = java.time.ZoneId.systemDefault()): String =
        java.time.Instant.ofEpochMilli((ts * 1000).toLong()).atZone(zone).toLocalTime()
            .format(java.time.format.DateTimeFormatter.ofPattern("HH:mm:ss"))

    /**
     * The buttons the dashboard's server page shows for this state
     * (heroActions in overview.js). Starting asks nothing; stopping and
     * restarting ask first, because players are thrown off. Nothing is
     * offered while the agent is busy, or to an account that may not
     * control the server. A crash with a restart counting down offers no
     * Start: the agent starts it itself.
     */
    fun actions(state: String?, canControl: Boolean): List<QuickAction> {
        if (!canControl) return emptyList()
        return when (state) {
            States.ONLINE -> listOf(
                QuickAction("restart", "action.restart", confirm = true),
                QuickAction("stop", "action.stop", confirm = true, danger = true),
            )
            States.OFFLINE, States.CRASHED -> listOf(QuickAction("start", "action.start", confirm = false))
            else -> emptyList()
        }
    }
}
