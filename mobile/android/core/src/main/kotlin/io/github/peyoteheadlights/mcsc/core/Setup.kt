package io.github.peyoteheadlights.mcsc.core

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.put

/**
 * The Server settings screen: how Command Block runs one server (not the
 * game's own rules, which are Game settings). Each field is a key the
 * agent's PUT /settings takes; Save sends only what changed, and the
 * agent says why it refused any of them.
 */
object ServerForm {
    /** bool, int, number (seconds, may have a fraction) or text. */
    data class Field(val key: String, val kind: String, val labelKey: String, val hintKey: String? = null)

    data class Group(val titleKey: String, val fields: List<Field>, val noteKey: String? = null)

    val GROUPS = listOf(
        Group("serverset.crashes", listOf(
            Field("monitor.auto_restart", "bool", "serverset.auto_restart"),
            Field("monitor.restart_delay", "number", "serverset.restart_delay"),
            Field("monitor.max_crashes", "int", "serverset.max_crashes", "serverset.max_crashes_hint"),
        )),
        Group("serverset.sleep", listOf(
            Field("server.autosleep", "bool", "serverset.sleep_label"),
            Field("server.autosleep_minutes", "int", "serverset.sleep_minutes", "serverset.sleep_minutes_hint"),
        ), noteKey = "serverset.sleep_restart_note"),
        Group("serverset.keep_label", listOf(
            Field("backups.keep_daily", "int", "serverset.keep_daily"),
            Field("backups.keep_weekly", "int", "serverset.keep_weekly"),
            Field("backups.keep_monthly", "int", "serverset.keep_monthly"),
        )),
        Group("serverset.timing", listOf(
            Field("server.start_timeout", "number", "serverset.start_timeout"),
            Field("server.stop_timeout", "number", "serverset.stop_timeout", "serverset.stop_timeout_hint"),
            Field("server.autostart_minecraft", "bool", "mobile.serverset.autostart", "mobile.serverset.autostart_hint"),
        )),
    )

    const val NAME = "server.name"
    const val NAME_LIMIT = 60

    val FIELDS: List<Field> = GROUPS.flatMap { it.fields }

    /** The saved value, as the agent has it. */
    fun value(settings: ServerSettings, key: String): JsonElement? {
        val (section, name) = key.split(".", limit = 2)
        val from = when (section) {
            "server" -> settings.server
            "monitor" -> settings.monitor
            "backups" -> settings.backups
            "mods" -> settings.mods
            else -> return null
        }
        return from[name]
    }

    /** The form's starting text: "true"/"false", a number without a
     * pointless ".0", or the words. Empty when the agent didn't say. */
    fun initial(settings: ServerSettings, key: String): String {
        val primitive = value(settings, key) as? JsonPrimitive ?: return ""
        primitive.booleanOrNull?.let { if (!primitive.isString) return it.toString() }
        val text = primitive.contentOrNull ?: return ""
        if (!primitive.isString) text.toDoubleOrNull()?.let { if (it == kotlin.math.floor(it) && !it.isInfinite()) return it.toLong().toString() }
        return text
    }

    /** View it: everyone the agent lets read settings. */
    fun visible(me: Me?): Boolean = me?.can(Permissions.SETTINGS_VIEW) == true

    /** Change it: only with settings.edit; anyone else sees it read-only. */
    fun editable(me: Me?): Boolean = me?.can(Permissions.SETTINGS_EDIT) == true

    /**
     * Only what changed, typed as the agent takes it: on and off as true
     * or false, numbers as numbers when they read as one (the agent checks
     * the rest and says why), the name trimmed. A blank name is not sent.
     */
    fun changed(settings: ServerSettings, edits: Map<String, String>): JsonObject = buildJsonObject {
        edits[NAME]?.trim()?.let { name ->
            if (name.isNotEmpty() && name != initial(settings, NAME)) put(NAME, name)
        }
        for (field in FIELDS) {
            val edit = edits[field.key] ?: continue
            if (edit.trim() == initial(settings, field.key)) continue
            when (field.kind) {
                "bool" -> put(field.key, edit == "true")
                "int" -> {
                    val number = edit.trim().toLongOrNull()
                    if (number != null) put(field.key, number) else put(field.key, edit.trim())
                }
                "number" -> {
                    val number = edit.trim().toDoubleOrNull()
                    if (number != null) put(field.key, number) else put(field.key, edit.trim())
                }
                else -> put(field.key, edit)
            }
        }
    }

    /** The color as it will be sent: a palette color as is, a typed one
     * as "#RRGGBB" in capitals. Null when it isn't a color. */
    fun color(text: String): String? {
        val typed = text.trim().let { if (it.startsWith("#")) it else "#$it" }
        return if (Regex("^#[0-9a-fA-F]{6}$").matches(typed)) typed.uppercase() else null
    }

    /** What to say after Save: "Nothing changed", saved, or that some
     * fields were refused (each says why under it). */
    fun saved(strings: Strings, sent: Boolean, result: ServerSettingsSaved?): String = when {
        !sent -> strings.t("settings.nothing_changed")
        result != null && result.rejected.isNotEmpty() -> strings.t("mobile.game.fix_marked")
        else -> strings.t("settings.saved")
    }

    /** Sleep when empty, as measured now; never a guess. */
    fun sleepLine(strings: Strings, settings: ServerSettings): String {
        val on = (value(settings, "server.autosleep") as? JsonPrimitive)?.booleanOrNull == true
        val sleep = settings.sleep
        return when {
            !on -> strings.t("serverset.sleep_off")
            sleep == null -> strings.t("value.unknown")
            sleep.listAnswered == false -> strings.t("serverset.sleep_no_answer")
            sleep.playersOnline == null -> strings.t("serverset.sleep_unknown_players")
            sleep.playersOnline > 0 -> strings.t("serverset.sleep_players", "count" to sleep.playersOnline)
            sleep.stopsIn != null -> strings.t("serverset.sleep_countdown", "duration" to Display.duration(strings, sleep.stopsIn))
            else -> strings.t("serverset.sleep_waiting")
        }
    }
}

/** Which CPU cores a server may use. What it really uses is read back from
 * the running server; the boxes are only the setting. Cores are counted
 * from 0 here and shown from 1. */
object CpuCores {
    /** The other servers set to use each core, by core. */
    fun sharedBy(cpu: CpuOverview): Map<Int, List<String>> {
        val used = mutableMapOf<Int, MutableList<String>>()
        for (other in cpu.others) for (core in other.cores) used.getOrPut(core) { mutableListOf() } += other.name
        return used
    }

    /** "1-4, 7": cores as people count them, runs shortened. */
    fun describe(cores: List<Int>): String {
        val numbers = cores.sorted().map { it + 1 }
        if (numbers.isEmpty()) return ""
        val runs = mutableListOf<String>()
        var start = numbers[0]
        var prev = numbers[0]
        for (n in numbers.drop(1) + listOf<Int?>(null)) {
            if (n != null && n == prev + 1) {
                prev = n
                continue
            }
            runs += if (start == prev) "$start" else "$start-$prev"
            if (n != null) {
                start = n
                prev = n
            }
        }
        return runs.joinToString(", ")
    }

    /** The first half of the cores, rounded up. */
    fun half(count: Int): Set<Int> = (0 until (count + 1) / 2).toSet()

    /** What the running server uses now, or why that isn't known. */
    fun nowLine(strings: Strings, cpu: CpuOverview): String {
        val applied = cpu.status.applied
        return if (applied != null) {
            strings.t("serverset.cores_now", "cores" to if (applied.size == cpu.logicalCores) strings.t("serverset.every_core") else describe(applied))
        } else {
            strings.t("serverset.cores_unknown", "reason" to (cpu.status.appliedReason ?: strings.t("value.unknown")))
        }
    }

    /** What to send: empty for every core. Null when no core is picked. */
    fun toSave(all: Boolean, picked: Set<Int>): List<Int>? = when {
        all -> emptyList()
        picked.isEmpty() -> null
        else -> picked.sorted()
    }

    fun update(cores: List<Int>): JsonObject = buildJsonObject { put("server.cpu_cores", JsonArray(cores.map(::JsonPrimitive))) }

    /** After Save: used now, from the next start, or not applied and why. */
    fun saved(strings: Strings, result: ServerSettingsSaved): String {
        val live = result.cpuCores
        return when {
            live == null -> strings.t("serverset.cores_next_start")
            !live.ok -> strings.t("serverset.cores_not_applied", "reason" to (live.reason ?: strings.t("value.unknown")))
            else -> strings.t("serverset.cores_applied")
        }
    }
}

/** The memory slider: only the -Xmx limit, bounded by the PC's memory as
 * measured; every other Java option stays as it is. */
object Memory {
    /** "6 GB", "1.5 GB". */
    fun gb(mb: Int): String = if (mb % 1024 == 0) "${mb / 1024} GB" else "${Display.fixed(mb / 1024.0, 1)} GB"

    /** No slider when the PC's memory couldn't be read, or the server type
     * takes no limit (Bedrock). */
    fun slider(memory: MemoryOverview): Boolean = memory.takesMemoryLimit && memory.totalMb != null

    /** Where the slider starts: the current limit, else 2 GB, kept inside the bounds. */
    fun start(memory: MemoryOverview): Int {
        val total = memory.totalMb ?: return memory.limitMb ?: 2048
        return minOf(total, maxOf(memory.minMb, memory.limitMb ?: 2048))
    }

    /** A slider position, snapped to the step and kept inside the bounds. */
    fun snap(memory: MemoryOverview, mb: Float): Int {
        val total = memory.totalMb ?: return memory.minMb
        val step = maxOf(1, memory.stepMb)
        val snapped = memory.minMb + Math.round((mb - memory.minMb) / step) * step
        return minOf(total, maxOf(memory.minMb, snapped))
    }

    /** The warning when this server, with the others running, may use more
     * than the PC has. Null when it fits or the PC's memory isn't known. */
    fun warning(strings: Strings, memory: MemoryOverview, chosen: Int): String? {
        val total = memory.totalMb ?: return null
        val others = memory.servers.filter { !it.`this` && it.running }
        val together = others.sumOf { it.limitMb ?: 0 } + chosen
        if (together <= total) return null
        return if (others.isNotEmpty()) {
            strings.t("memory.over_together", "names" to others.joinToString(", ") { it.name }, "total" to gb(together), "pc" to gb(total))
        } else {
            strings.t("memory.over_alone", "total" to gb(together), "pc" to gb(total))
        }
    }

    /** Under the slider: what is set now. */
    fun nowLine(strings: Strings, memory: MemoryOverview): String =
        memory.limitMb?.let { strings.t("memory.now", "limit" to gb(it)) } ?: strings.t("memory.unset")

    /** Why there is no slider. */
    fun noSlider(strings: Strings, memory: MemoryOverview, bedrock: Boolean): String = when {
        !memory.takesMemoryLimit -> strings.t(if (bedrock) "memory.not_bedrock" else "memory.not_used")
        else -> strings.t("memory.pc_unknown")
    }
}

/**
 * Changing a server's version or type: checked first (what might break),
 * one confirmation (the server stops and a backup is taken first), then a
 * task with progress. Roll back puts the previous software back.
 */
object VersionChange {
    /** A line of the check's report, and how loud it is. */
    data class Line(val text: String, val tone: Tone)

    val KINDS = setOf("version_change", "version_rollback")

    /** Java and Bedrock worlds differ, so only this edition's kinds are offered. */
    fun sameEdition(types: List<ServerTypeInfo>, current: ServerVersion): List<ServerTypeInfo> =
        types.filter { it.edition == current.capabilities.edition }

    /** The versions to pick from: snapshots only when asked for. */
    fun choices(versions: TypeVersions, snapshots: Boolean): List<OfferedVersion> =
        if (snapshots) versions.versions else versions.versions.filter { it.stable }

    /** What the server is now: "Fabric 1.21.1", or that it isn't known yet. */
    fun now(strings: Strings, version: ServerVersion): String =
        version.minecraftVersion?.let { "${version.capabilities.name} $it" } ?: strings.t("version.not_seen_yet")

    /** "Fabric 1.21.4", for the check and the confirmation. */
    fun target(report: VersionPreflight): String = "${report.target.typeName} ${report.target.minecraftVersion.orEmpty()}".trim()

    /** What the check found, loudest first; then that a backup comes first. */
    fun lines(strings: Strings, report: VersionPreflight): List<Line> {
        val out = mutableListOf<Line>()
        if (report.java.verdict == "incompatible") out += Line(report.java.detail ?: strings.t("value.unknown"), Tone.DANGER)
        if (report.downgradeWarning) out += Line(strings.t("version.downgrade"), Tone.WARNING)
        if (report.typeChange) {
            out += if (report.gentleTypeChange) Line(strings.t("version.type_change_gentle"), Tone.NEUTRAL)
            else Line(strings.t("version.type_change", "from" to report.current.typeName, "to" to report.target.typeName), Tone.WARNING)
        }
        if (report.crossplay && !report.crossplayAvailable) out += Line(strings.t("version.crossplay_lost"), Tone.WARNING)
        if (report.notSupporting.isNotEmpty()) {
            out += Line(strings.t("version.not_supporting", "count" to report.notSupporting.size, "version" to report.target.minecraftVersion) +
                " " + report.notSupporting.take(8).joinToString(", "), Tone.WARNING)
        }
        if (report.movedAside.isNotEmpty()) {
            out += Line(strings.t("version.moved_aside", "count" to report.movedAside.size) + " " + strings.t("version.moved_aside_note"), Tone.WARNING)
        }
        if (report.unknownSupport.isNotEmpty()) {
            out += Line(strings.t("version.unknown_support", "count" to report.unknownSupport.size) + " " + strings.t("version.unknown_support_note"), Tone.NEUTRAL)
        }
        if (report.java.verdict == "unknown") out += Line(strings.t("version.java_unknown"), Tone.NEUTRAL)
        out += Line(strings.t("version.backup_first"), Tone.NEUTRAL)
        return out
    }

    /** The confirmation's button is red for a downgrade or a hard type change. */
    fun danger(report: VersionPreflight): Boolean = report.downgradeWarning || (report.typeChange && !report.gentleTypeChange)

    /** The server won't start until Minecraft's EULA is agreed to. */
    fun eulaNeeded(version: ServerVersion): Boolean = version.eulaRequired

    /** The version set up but not yet confirmed by the console. */
    fun pending(version: ServerVersion): String? =
        (version.pendingVersion?.get("minecraft_version") as? JsonPrimitive)?.contentOrNull

    fun canRollBack(version: ServerVersion): Boolean = version.lastChange?.canRollBack == true

    /** A version change or roll back running on this server now, to show
     * its progress when the screen is opened again. */
    fun running(jobs: List<Job>, serverId: String): Job? =
        jobs.firstOrNull { it.kind in KINDS && it.state == "running" && (it.serverId == null || it.serverId == serverId) }
}
