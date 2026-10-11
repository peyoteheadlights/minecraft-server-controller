package io.github.peyoteheadlights.mcsc.core

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject

/*
 * What the Setup screens read (Phase 9 part 5): Server settings, version
 * and type changes, the raw editors, new servers and the PC folder picker.
 * As in PageModels.kt, only the fields the app uses are listed.
 */

@Serializable
data class PaletteColor(val id: String, val name: String = "", val hex: String)

@Serializable
data class CpuStatus(
    /** Null: every core. */
    val configured: List<Int>? = null,
    /** Read from the running server; null when it couldn't be. */
    val applied: List<Int>? = null,
    @SerialName("applied_reason") val appliedReason: String? = null,
    val problems: List<String> = emptyList(),
)

@Serializable
data class CpuOther(val id: String, val name: String = "", val cores: List<Int> = emptyList())

@Serializable
data class CpuOverview(
    @SerialName("logical_cores") val logicalCores: Int? = null,
    val supported: Boolean = false,
    @SerialName("unsupported_reason") val unsupportedReason: String? = null,
    val others: List<CpuOther> = emptyList(),
    val status: CpuStatus = CpuStatus(),
)

/** Sleep when empty, as measured now. */
@Serializable
data class SleepStatus(
    val enabled: Boolean = false,
    val minutes: Int = 0,
    @SerialName("players_online") val playersOnline: Int? = null,
    @SerialName("stops_in") val stopsIn: Double? = null,
    @SerialName("list_answered") val listAnswered: Boolean? = null,
)

/** One server's own settings: "server" holds its name and launch settings,
 * then its crash, backup and mod settings with its own values applied. */
@Serializable
data class ServerSettings(
    @SerialName("server_id") val serverId: String = "",
    val server: JsonObject = JsonObject(emptyMap()),
    val color: String? = null,
    val palette: List<PaletteColor> = emptyList(),
    val monitor: JsonObject = JsonObject(emptyMap()),
    val backups: JsonObject = JsonObject(emptyMap()),
    val mods: JsonObject = JsonObject(emptyMap()),
    val cpu: CpuOverview = CpuOverview(),
    val sleep: SleepStatus? = null,
)

@Serializable
data class ServerSettingsSaved(
    val applied: Map<String, JsonElement> = emptyMap(),
    /** Each refused key with the agent's reason. */
    val rejected: Map<String, String> = emptyMap(),
    @SerialName("cpu_cores") val cpuCores: JsonObject? = null,
)

@Serializable
data class ColorSaved(val color: String)
