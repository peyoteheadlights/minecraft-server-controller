package io.github.peyoteheadlights.mcsc.core

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put

// PC settings, owner only (agent/api/routes/settings.py, system.py,
// updates.py, transfer.py, helpdesk.py; the dashboard's app-settings.js).

@Serializable
data class SettingsSecrets(
    @SerialName("discord_webhook_configured") val discord: Boolean = false,
    @SerialName("smtp_configured") val email: Boolean = false,
)

@Serializable
data class PcSettingsView(val config: JsonObject = JsonObject(emptyMap()), val secrets: SettingsSecrets = SettingsSecrets())

@Serializable
data class SettingsSaved(
    val ok: Boolean = false,
    val applied: JsonObject = JsonObject(emptyMap()),
    val rejected: Map<String, String> = emptyMap(),
)

@Serializable
data class MaintenanceSet(val ok: Boolean = false, val maintenance: Boolean = false)

@Serializable
data class TestAlert(val channel: String = "", val sent: Boolean = false)

@Serializable
data class Battery(val present: Boolean = false, val percent: Int? = null, @SerialName("plugged_in") val pluggedIn: Boolean? = null)

@Serializable
data class PowerStatus(
    val supported: Boolean = false,
    val enabled: Boolean = false,
    val active: Boolean = false,
    val running: List<String> = emptyList(),
    val problem: String? = null,
    val battery: Battery? = null,
    @SerialName("still_sleeps") val stillSleeps: List<String> = emptyList(),
)

@Serializable
data class StartupTask(val mode: String? = null, val command: String? = null, @SerialName("working_directory") val folder: String? = null)

@Serializable
data class StartupRuntime(@SerialName("last_run_time") val lastRun: String? = null, @SerialName("last_result") val lastResult: String? = null)

@Serializable
data class StartupStep(val event: String = "")

@Serializable
data class LastStartup(
    @SerialName("started_at") val startedAt: String? = null,
    @SerialName("launched_by") val launchedBy: String? = null,
    val events: List<StartupStep> = emptyList(),
)

@Serializable
data class StartupReport(
    val supported: Boolean = false,
    val verdict: String = "",
    val registered: Boolean? = null,
    @SerialName("points_to_current_app") val pointsHere: Boolean? = null,
    val mechanism: String? = null,
    val problems: List<String> = emptyList(),
    val task: StartupTask? = null,
    val runtime: StartupRuntime? = null,
    @SerialName("last_startup") val lastStartup: LastStartup? = null,
)

@Serializable
data class ExportServerSizes(val id: String = "", val name: String = "", val files: Long = 0, val worlds: Long = 0, val backups: Long = 0)

@Serializable
data class ExportSizes(val servers: List<ExportServerSizes> = emptyList())

@Serializable
data class ExportStarted(val ok: Boolean = false, @SerialName("job_id") val jobId: String)

@Serializable
data class ExportResult(
    val token: String = "",
    val filename: String = "",
    @SerialName("size_bytes") val sizeBytes: Long? = null,
    @SerialName("saved_to") val savedTo: String? = null,
)

/** The export task as GET /api/jobs/{id} reports it. */
@Serializable
data class ExportJob(
    val id: String,
    val state: String = "",
    val step: String? = null,
    val progress: Double? = null,
    val message: String? = null,
    val result: ExportResult? = null,
)

@Serializable
data class HelpFile(val name: String, val size: Long? = null)

@Serializable
data class HelpFiles(val files: List<HelpFile> = emptyList())

@Serializable
data class HelpFileMade(val ok: Boolean = false, val token: String, val filename: String)

@Serializable
data class SessionsRevoked(val ok: Boolean = false, val revoked: Int = 0)

@Serializable
data class Release(val version: String, val page: String? = null, val notes: String? = null)

@Serializable
data class UpdateResult(
    val ok: Boolean? = null,
    val version: String? = null,
    val message: String? = null,
    @SerialName("rolled_back") val rolledBack: Boolean? = null,
)

@Serializable
data class UpdateStatus(
    val current: String,
    val latest: Release? = null,
    val available: Boolean = false,
    @SerialName("checked_at") val checkedAt: Double? = null,
    val error: String? = null,
    val checking: Boolean = false,
    @SerialName("can_install") val canInstall: Boolean = false,
    @SerialName("cannot_install_reason") val cannotInstallReason: String? = null,
    @SerialName("last_result") val lastResult: UpdateResult? = null,
    /** Only in the checks before installing: null when it couldn't tell. */
    @SerialName("players_online") val playersOnline: Int? = null,
)

@Serializable
data class UpdateStarted(val ok: Boolean = false, val job: Job)

@Serializable
data class OldCopy(val path: String, val offer: Boolean = false, val problems: List<String> = emptyList())

@Serializable
data class OldCopyStatus(@SerialName("old_copy") val oldCopy: OldCopy? = null)

@Serializable
data class OldCopyRemoved(val ok: Boolean = false, val kept: List<String> = emptyList(), @SerialName("folder_removed") val folderRemoved: Boolean = false)

/** The alert settings as the owner edits them, with the agent's key for each. */
data class AlertSettings(
    val discord: Boolean = false,
    val email: Boolean = false,
    val phone: Boolean = false,
    /** Every event the PC can alert about, in the PC's order. */
    val events: Map<String, Boolean> = emptyMap(),
    val thresholds: Map<String, Double> = emptyMap(),
    val repeatSeconds: Double = 300.0,
)

object PcSettings {
    /** Each limit the PC alerts at, with the dashboard's words for it. */
    val THRESHOLDS = listOf(
        "cpu_percent" to "appset.cpu_alert",
        "ram_percent" to "appset.ram_alert",
        "disk_free_gb" to "appset.disk_alert",
        "tps_min" to "appset.tps_alert",
        "mspt_max" to "appset.mspt_alert",
    )

    /**
     * Every PC-wide setting the dashboard's App settings page changes. The
     * phones have a screen for each (tests/test_phone_app.py checks this
     * list against the dashboard).
     */
    val KEYS = listOf(
        "notifications.discord_enabled",
        "notifications.email_enabled",
        "notifications.push_enabled",
        "notifications.events.",
        "notifications.min_interval_seconds",
        "thresholds.",
        "power.keep_awake",
        "updates.check",
    )

    private fun JsonObject.section(name: String): JsonObject? = (get(name) as? JsonObject)
    private fun JsonElement?.bool(): Boolean? = (this as? JsonPrimitive)?.booleanOrNull
    private fun JsonElement?.number(): Double? = (this as? JsonPrimitive)?.doubleOrNull

    fun alerts(view: PcSettingsView): AlertSettings {
        val notifications = view.config.section("notifications") ?: JsonObject(emptyMap())
        val thresholds = view.config.section("thresholds") ?: JsonObject(emptyMap())
        return AlertSettings(
            discord = notifications["discord_enabled"].bool() ?: false,
            email = notifications["email_enabled"].bool() ?: false,
            phone = notifications["push_enabled"].bool() ?: false,
            events = notifications.section("events").orEmpty().mapNotNull { (k, v) -> v.bool()?.let { k to it } }.toMap(),
            thresholds = THRESHOLDS.mapNotNull { (key, _) -> thresholds[key].number()?.let { key to it } }.toMap(),
            repeatSeconds = notifications["min_interval_seconds"].number() ?: 300.0,
        )
    }

    fun keepAwake(view: PcSettingsView): Boolean = view.config.section("power")?.get("keep_awake").bool() ?: false
    fun dailyCheck(view: PcSettingsView): Boolean = view.config.section("updates")?.get("check").bool() ?: false
    fun maintenance(view: PcSettingsView): Boolean = view.config.section("maintenance")?.get("enabled").bool() ?: false

    /** Who the email alerts go to, for Technical mode; addresses aren't secret. */
    fun emailTo(view: PcSettingsView): List<String> =
        view.config.section("notifications")?.section("email")?.get("to_addresses")
            ?.let { runCatching { it.jsonArray.map { a -> a.jsonPrimitive.content } }.getOrNull() }.orEmpty()

    /** Only what changed, as PUT /api/settings takes it. */
    fun changes(before: AlertSettings, after: AlertSettings): JsonObject = buildJsonObject {
        if (after.discord != before.discord) put("notifications.discord_enabled", after.discord)
        if (after.email != before.email) put("notifications.email_enabled", after.email)
        if (after.phone != before.phone) put("notifications.push_enabled", after.phone)
        for ((key, on) in after.events) if (before.events[key] != on) put("notifications.events.$key", on)
        for ((key, value) in after.thresholds) if (before.thresholds[key] != value) put("thresholds.$key", value)
        if (after.repeatSeconds != before.repeatSeconds) put("notifications.min_interval_seconds", after.repeatSeconds)
    }

    /** A typed number, or null when it isn't one (the field shows it as wrong). */
    fun number(text: String): Double? = text.trim().replace(',', '.').toDoubleOrNull()?.takeIf { it.isFinite() && it >= 0 }

    /** What saving said: the PC's reason for each setting it refused, or saved. */
    fun saved(strings: Strings, result: SettingsSaved): Pair<String, Boolean> = when {
        result.rejected.isNotEmpty() -> result.rejected.values.joinToString(" ") to false
        else -> strings.t("settings.saved") to true
    }

    /** The line under "Keep the PC awake": what Windows does now. */
    fun awake(strings: Strings, power: PowerStatus): String = when {
        !power.supported -> strings.t("awake.unsupported")
        !power.enabled -> strings.t("awake.off_now")
        power.active -> strings.t("awake.active", "names" to power.running.joinToString(", "))
        else -> strings.t("awake.idle")
    }

    /** Why Windows can still sleep, only for reasons the dashboard has words for. */
    fun stillSleeps(strings: Strings, power: PowerStatus): List<String> =
        power.stillSleeps.map { "awake.still_$it" }.filter(strings::has).map(strings::t)

    // ------------------------------------------------------------ start with Windows
    fun verdict(report: StartupReport): String = "startup.${report.verdict.replace(' ', '_')}"

    fun verdictGood(report: StartupReport): Boolean? = when (report.verdict) {
        "registered correctly" -> true
        "unsupported" -> null
        else -> false
    }

    /** The check's rows, as the dashboard shows them; nothing is guessed. */
    fun startupRows(strings: Strings, report: StartupReport, technical: Boolean): List<Pair<String, String>> {
        fun yesNo(v: Boolean?) = strings.t(if (v == true) "value.yes" else if (v == false) "value.no" else "value.unknown")
        val task = report.task ?: StartupTask()
        val last = report.lastStartup ?: LastStartup()
        val started = last.events.any { it.event == "controller_initialized" }
        val rows = mutableListOf(
            strings.t("startup.registered") to strings.t(
                when (report.registered) { true -> "startup.found"; false -> "startup.not_found"; null -> "value.unknown" },
            ),
            strings.t("startup.mode") to when (task.mode) {
                "boot" -> strings.t("startup.at_boot")
                "logon" -> strings.t("startup.at_logon")
                else -> "—"
            },
            strings.t("startup.points_here") to yesNo(report.pointsHere),
            strings.t("startup.last_run") to (report.runtime?.lastRun ?: strings.t("value.unknown")),
            strings.t("startup.last_start") to (
                last.startedAt?.let { strings.t("startup.last_start_value", "when" to it, "by" to (last.launchedBy ?: "")) }
                    ?: strings.t("startup.none")
                ),
            strings.t("startup.initialised") to if (last.startedAt != null) yesNo(started) else "—",
        )
        if (technical) {
            rows += strings.t("startup.mechanism") to (report.mechanism ?: "—")
            rows += strings.t("startup.command") to (task.command ?: "—")
            rows += strings.t("startup.folder") to (task.folder ?: "—")
            rows += strings.t("startup.last_result") to (report.runtime?.lastResult ?: strings.t("value.unknown"))
        }
        return rows
    }

    // ------------------------------------------------------------ export everything
    data class Totals(val files: Long, val worlds: Long, val backups: Long)

    fun totals(sizes: ExportSizes) = Totals(
        sizes.servers.sumOf { it.files },
        sizes.servers.sumOf { it.worlds },
        sizes.servers.sumOf { it.backups },
    )

    const val MIN_PASSPHRASE = 10

    /** Whether Export can start: a folder picked, and a long enough passphrase when passwords go too. */
    fun canExport(folder: String?, secrets: Boolean, passphrase: String): Boolean =
        !folder.isNullOrBlank() && (!secrets || passphrase.length >= MIN_PASSPHRASE)

    fun exportBody(worlds: Boolean, backups: Boolean, secrets: Boolean, passphrase: String, folder: String): JsonObject = buildJsonObject {
        put("worlds", worlds)
        put("backups", backups)
        put("secrets", secrets)
        if (secrets) put("passphrase", passphrase)
        put("folder", folder)
    }

    /** Where an export is: still running, saved on the PC, or failed. */
    sealed interface Exporting {
        data class Running(val step: String?, val progress: Double?) : Exporting
        data class Saved(val path: String, val size: Long?) : Exporting
        data class Failed(val reason: String?) : Exporting
    }

    fun exporting(job: ExportJob): Exporting = when (job.state) {
        "running", "queued" -> Exporting.Running(job.step, job.progress)
        "succeeded" -> job.result?.savedTo?.let { Exporting.Saved(it, job.result.sizeBytes) } ?: Exporting.Failed(job.message)
        else -> Exporting.Failed(job.message)
    }

    fun exportSaid(strings: Strings, state: Exporting): String? = when (state) {
        is Exporting.Running -> null
        is Exporting.Saved -> strings.t("mobile.pc.export_saved", "path" to state.path, "size" to Display.bytes(strings, state.size))
        is Exporting.Failed -> state.reason ?: strings.t("export.failed")
    }

    // ------------------------------------------------------------ signed-in devices
    /** Every account's devices, this account first, then by name; this phone first in its list. */
    fun byAccount(devices: List<Device>, me: String?): List<Pair<String, List<Device>>> =
        devices.groupBy { it.user }
            .toList()
            .sortedWith(compareBy<Pair<String, List<Device>>> { it.first != me }.thenBy { it.first.lowercase() })
            .map { (user, list) -> user to list.sortedWith(compareBy<Device> { !it.current }.thenByDescending { it.lastUsed ?: 0.0 }) }
}

/**
 * The app update as PC settings shows it, from GET /api/updates, and
 * while the PC is updating itself.
 */
object PcUpdate {
    enum class Shows { UP_TO_DATE, READY, CANT_INSTALL, UPDATING, UPDATED, FAILED }

    /** [updating] is the version asked for, while the phone waits for the PC to come back. */
    fun shows(status: UpdateStatus, updating: String? = null): Shows = when {
        updating != null -> Shows.UPDATING
        status.lastResult?.ok == false && !status.available -> Shows.FAILED
        status.available && status.canInstall -> Shows.READY
        status.available -> Shows.CANT_INSTALL
        status.lastResult?.ok == true && status.lastResult.version == status.current -> Shows.UPDATED
        else -> Shows.UP_TO_DATE
    }

    /**
     * Whether the PC is back after an update to [target]: on the new
     * version, or saying how the update went. Before that it doesn't answer
     * at all, or still says the old version.
     */
    fun back(before: UpdateStatus, now: UpdateStatus, target: String): Boolean =
        now.current != before.current ||
            (now.lastResult != null && now.lastResult != before.lastResult && now.lastResult.version == target)

    /** How long the phone waits for the PC to come back before saying so. */
    const val WAIT_SECONDS = 600

    /** The confirmation's words: who will be disconnected, if the PC could tell. */
    fun confirmBody(strings: Strings, check: UpdateStatus): String {
        val players = check.playersOnline
        val parts = mutableListOf(strings.t("update.confirm_body"))
        when {
            players == null -> parts += strings.t("update.confirm_players_unknown")
            players > 0 -> parts += strings.t("update.confirm_players", "count" to players)
        }
        return parts.joinToString(" ")
    }

    fun confirmLabel(strings: Strings, check: UpdateStatus): String =
        strings.t(if ((check.playersOnline ?: 0) > 0) "update.install_anyway" else "update.install")

    /** "What's new", one line per change, at most 30. */
    fun notes(release: Release?): List<String> =
        release?.notes.orEmpty().lines().map { it.trim() }.filter { it.isNotEmpty() }.take(30)
            .map { it.trimStart('-', '*', '#', ' ') }

    fun lastResult(strings: Strings, result: UpdateResult?): String? {
        if (result?.ok == null) return null
        val version = result.version.orEmpty()
        if (result.ok) return strings.t("update.last_ok", "version" to version)
        val back = when (result.rolledBack) {
            true -> " " + strings.t("update.rolled_back")
            false -> " " + strings.t("update.not_rolled_back")
            null -> ""
        }
        return strings.t("update.last_failed", "version" to version) + back
    }

    fun oldCopyRemoved(strings: Strings, result: OldCopyRemoved): String =
        if (result.folderRemoved) strings.t("oldcopy.removed") else strings.t("oldcopy.removed_kept", "count" to result.kept.size)
}
