package io.github.peyoteheadlights.mcsc.core

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/** Backups' words, and which buttons each row offers (backups.js). */
object Backups {
    private val KINDS = mapOf(
        "manual" to StateWords("backups.kind_manual", Tone.SUCCESS),
        "scheduled" to StateWords("backups.kind_scheduled", Tone.NEUTRAL),
        "safety" to StateWords("backups.kind_safety", Tone.WARNING),
    )

    /** Manual, Scheduled or the one made before a change; null for a kind
     * the app has no words for (then its own name is shown). */
    fun kind(kind: String?): StateWords? = KINDS[kind]

    private val STATUS = mapOf(
        "ok" to StateWords("backup.checked", Tone.SUCCESS),
        "unverified" to StateWords("backup.unchecked", Tone.WARNING),
        "failed" to StateWords("backup.failed", Tone.DANGER),
    )

    /** Whether the backup was checked when it was made; Unknown otherwise. */
    fun status(status: String?): StateWords = STATUS[status] ?: StateWords("value.unknown", Tone.NEUTRAL)

    /** The second copy's state, as the agent found it just now. */
    fun copy(strings: Strings, copy: BackupCopy?): Pair<String, Tone> {
        val reason = copy?.reason ?: strings.t("value.unknown")
        return when (copy?.state ?: "none") {
            "ok" -> strings.t("offsite.copied") to Tone.SUCCESS
            "failed" -> strings.t("offsite.failed", "reason" to reason) to Tone.DANGER
            "unreachable" -> strings.t("offsite.unreachable", "reason" to reason) to Tone.WARNING
            "missing" -> strings.t("offsite.missing") to Tone.WARNING
            "none" -> strings.t("offsite.not_copied") to Tone.NEUTRAL
            else -> strings.t("value.unknown") to Tone.NEUTRAL
        }
    }

    /** "Copy" is offered for a checked backup without a good second copy,
     * while second copies are on. */
    fun canCopyAgain(backup: Backup, offsite: Offsite?, canCreate: Boolean): Boolean =
        canCreate && !offsite?.directory.isNullOrEmpty() && backup.status == "ok" && backup.copy?.state != "ok"

    /** A backup whose file is gone can't be downloaded or restored. */
    fun onDisk(backup: Backup): Boolean = backup.exists != false

    /** A task's states once it is over. */
    val FINISHED = setOf("succeeded", "failed", "interrupted")

    /** "Kept: last 7 days, 4 weeks, 3 months"; null when the agent didn't say. */
    fun keeping(strings: Strings, retention: Retention?): String? {
        val r = retention ?: return null
        if (r.daily == null || r.weekly == null || r.monthly == null) return null
        return strings.t("backups.keeping", "daily" to r.daily, "weekly" to r.weekly, "monthly" to r.monthly)
    }

    /** What to say once Back up now finished. */
    fun made(strings: Strings, made: BackupMade): String {
        val entries = made.verification?.entries
        return if (made.verification?.ok == true && entries != null) {
            strings.t("backups.verified_toast", "name" to made.name, "entries" to entries)
        } else {
            strings.t("backup.done", "name" to made.name)
        }
    }

    /** What Check found. */
    fun checked(strings: Strings, check: BackupCheck): String =
        if (check.ok) strings.t("backups.verify_ok")
        else strings.t("backups.verify_failed", "reason" to (check.reason ?: strings.t("value.unknown")))

    /** What a restore did, with the backup made just before it. */
    fun restored(strings: Strings, result: Restored): String {
        val name = result.restored ?: ""
        val safety = result.safetyBackup?.name ?: return strings.t("mobile.backups.restored", "name" to name)
        return strings.t("mobile.backups.restored_backup", "name" to name, "safety" to safety)
    }

    /** The body a restore is confirmed with. The backup made first is
     * always asked for, as the dashboard does. */
    fun restoreBody(confirm: Boolean, startAfter: Boolean): JsonObject = buildJsonObject {
        put("confirm", confirm)
        put("start_after", startAfter)
        put("safety_backup", true)
    }
}

/** Schedules' words and what is sent (schedules.js). */
object Schedules {
    val KINDS = listOf("daily", "weekly", "interval")

    fun kindKey(kind: String): String = "schedules.kind_$kind"

    /** "Every day at 04:00"; the agent's own words for a kind the app doesn't know. */
    fun whenText(strings: Strings, schedule: Schedule): String =
        if (schedule.kind in KINDS) strings.t("schedules.every_${schedule.kind}", "expr" to schedule.expr)
        else "${schedule.kind} ${schedule.expr}"

    /** "Back up the world"; its own name in Technical words or when the app has none. */
    fun taskName(strings: Strings, task: String, tasks: List<String>): String =
        if (!strings.technical && task in tasks && strings.has("task.$task")) strings.t("task.$task") else task

    /** The next run's time, or Off. */
    fun next(strings: Strings, schedule: Schedule): String =
        if (schedule.enabled) Display.dateTime(strings, schedule.nextRun) else strings.t("schedules.off")

    /** A new schedule; with no name it is called after its task. */
    fun newBody(strings: Strings, name: String, task: String, kind: String, expr: String, tasks: List<String>): JsonObject =
        body(name.trim().ifEmpty { taskName(strings, task, tasks) }, task, kind, expr.trim(), JsonObject(emptyMap()), enabled = true)

    /** The whole schedule again with only on or off changed (PUT replaces it). */
    fun toggled(schedule: Schedule): JsonObject =
        body(schedule.name, schedule.task, schedule.kind, schedule.expr, schedule.payload, !schedule.enabled)

    private fun body(name: String, task: String, kind: String, expr: String, payload: JsonObject, enabled: Boolean) =
        buildJsonObject {
            put("name", name)
            put("task", task)
            put("kind", kind)
            put("expr", expr)
            put("payload", payload)
            put("enabled", enabled)
        }

    /** The most the agent takes for a name and a time. */
    const val NAME_LENGTH = 80
    const val EXPR_LENGTH = 32
}

/** Restore world's words (world.js). */
object WorldRestore {
    /** "Yesterday, 9:00 PM": the words a person would use for a moment. */
    fun whenLabel(
        strings: Strings,
        ts: Double,
        now: Double,
        zone: java.time.ZoneId = java.time.ZoneId.systemDefault(),
        locale: java.util.Locale = java.util.Locale.getDefault(),
    ): String {
        val then = java.time.Instant.ofEpochMilli((ts * 1000).toLong()).atZone(zone)
        val today = java.time.Instant.ofEpochMilli((now * 1000).toLong()).atZone(zone).toLocalDate()
        val days = java.time.temporal.ChronoUnit.DAYS.between(then.toLocalDate(), today)
        val clock = then.format(java.time.format.DateTimeFormatter.ofLocalizedTime(java.time.format.FormatStyle.SHORT).withLocale(locale))
        return when {
            days <= 0 -> strings.t("world.today_at", "time" to clock)
            days == 1L -> strings.t("world.yesterday_at", "time" to clock)
            days < 7 -> strings.t(
                "world.day_at",
                "day" to then.dayOfWeek.getDisplayName(java.time.format.TextStyle.FULL, locale),
                "time" to clock,
            )
            else -> strings.t(
                "world.date_at",
                "date" to then.format(java.time.format.DateTimeFormatter.ofPattern("MMM d", locale)),
                "time" to clock,
            )
        }
    }

    /** "2h 10m ago · about 1h 30m of play would be lost"; play not known
     * when no sessions were recorded (never "no play"). */
    fun lossLine(strings: Strings, point: WorldPoint): String = lossLine(strings, point.ageSeconds, point.playedSeconds)

    /** The same line for a backup made [ageSeconds] ago (Undo and Redo use it too). */
    fun lossLine(strings: Strings, ageSeconds: Double, playedSeconds: Double?): String {
        val since = strings.t("world.since", "duration" to Display.duration(strings, ageSeconds))
        val play = when {
            playedSeconds == null -> strings.t("world.play_unknown")
            playedSeconds < 60 -> strings.t("world.no_play")
            else -> strings.t("world.play_lost", "duration" to Display.duration(strings, playedSeconds))
        }
        return "$since · $play"
    }

    /** Why nothing can be put back now, or null when it can. */
    fun blocked(strings: Strings, timeline: WorldTimeline): String? = when {
        timeline.serverRunning -> strings.t("world.stop_first")
        timeline.blockedBy != null -> strings.t("world.busy", "job" to timeline.blockedBy)
        else -> null
    }

    fun done(strings: Strings, result: Restored): String =
        result.safetyBackup?.name?.let { strings.t("world.done_with_undo", "name" to it) } ?: strings.t("world.done")
}

/** Undo and Redo: the two lists of changes (changesCard and moveChange in backups.js). */
object ChangeList {
    /** How many changes past the newest the screen lists ("Pressing Undo again goes on to"). */
    const val LATER = 3

    /** Whether the Undo ("undo") or Redo ("redo") button works now: the
     * person may restore, there is something to move and no task holds the server. */
    fun canMove(changes: UndoRedo, direction: String, canRestore: Boolean): Boolean {
        val list = if (direction == "undo") changes.undo else changes.redo
        return canRestore && list.isNotEmpty() && changes.blockedBy == null
    }

    /** The first line: the newest change, or that nothing is left to undo. */
    fun next(strings: Strings, changes: UndoRedo, now: Double): String {
        val change = changes.undo.firstOrNull() ?: return strings.t("changes.nothing_to_undo")
        return strings.t(
            "changes.next_undo",
            "title" to change.title,
            "when" to Display.ago(strings, change.madeAt, now),
            "who" to (change.user ?: strings.t("value.unknown")),
        )
    }

    /** The change Redo would put back, or null when nothing was undone. */
    fun nextRedo(strings: Strings, changes: UndoRedo, now: Double): String? {
        val change = changes.redo.firstOrNull() ?: return null
        return strings.t("changes.next_redo", "title" to change.title, "when" to Display.ago(strings, change.undoneAt, now))
    }

    /** The changes after the newest, for "Pressing Undo again goes on to". */
    fun later(strings: Strings, changes: UndoRedo, now: Double): List<String> =
        changes.undo.drop(1).take(LATER).map {
            strings.t("changes.later_item", "title" to it.title, "when" to Display.ago(strings, it.madeAt, now))
        }

    /** The question before Undo or Redo: what goes back, and what would be lost. */
    fun ask(strings: Strings, direction: String, change: Change, now: Double): Pair<String, String> {
        val what = change.scope?.joinToString(", ") ?: strings.t("changes.everything")
        val body = strings.t("changes.${direction}_body", "what" to what, "when" to Display.dateTime(strings, change.backupAt))
        val loss = WorldRestore.lossLine(strings, (now - change.backupAt).coerceAtLeast(0.0), change.playedSeconds)
        return strings.t("changes.${direction}_title", "title" to change.title) to
            listOf(body, loss, strings.t("changes.server_stops")).joinToString("\n\n")
    }

    fun done(strings: Strings, direction: String, moved: ChangeMoved): String =
        strings.t("changes.${direction}_done", "title" to moved.change.title)
}

/** The health checks' words (healthCard in performance.js). */
object HealthChecks {
    private val OVERALL = mapOf(
        "ALL CHECKS VERIFIED" to StateWords("health.all_ok", Tone.SUCCESS),
        "PARTIALLY VERIFIED" to StateWords("health.partial", Tone.NEUTRAL),
        "ATTENTION NEEDED" to StateWords("health.attention", Tone.DANGER),
    )

    /** null for a verdict the app has no words for (then it is shown as sent). */
    fun overall(overall: String): StateWords? = OVERALL[overall]

    fun tone(status: String): Tone = when (status) {
        "ok" -> Tone.SUCCESS
        "unknown" -> Tone.NEUTRAL
        else -> Tone.WARNING
    }

    /** The measured value as the agent sent it, or Unknown. */
    fun value(strings: Strings, check: HealthCheck): String = text(check.value) ?: strings.t("value.unknown")

    /** "detail (limit 90) [source]". */
    fun detail(strings: Strings, check: HealthCheck): String = buildString {
        append(check.detail.orEmpty())
        text(check.threshold)?.let { append(" (").append(strings.t("health.limit", "limit" to it)).append(")") }
        check.source?.takeIf { it.isNotEmpty() }?.let { append(" [").append(it).append("]") }
    }.trim()

    private fun text(value: kotlinx.serialization.json.JsonElement?): String? = when (value) {
        null, JsonNull -> null
        is JsonPrimitive -> value.content
        is JsonArray, is JsonObject -> value.toString()
    }
}
