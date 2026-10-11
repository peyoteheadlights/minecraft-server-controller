package io.github.peyoteheadlights.mcsc.core

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
