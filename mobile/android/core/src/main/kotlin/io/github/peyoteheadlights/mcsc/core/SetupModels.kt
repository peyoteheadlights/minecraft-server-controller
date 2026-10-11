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

/** The cores a running server got, read back from it. */
@Serializable
data class CpuApplied(val ok: Boolean = false, val applied: List<Int>? = null, val reason: String? = null)

@Serializable
data class ServerSettingsSaved(
    val applied: Map<String, JsonElement> = emptyMap(),
    /** Each refused key with the agent's reason. */
    val rejected: Map<String, String> = emptyMap(),
    /** Only when the server is running. */
    @SerialName("cpu_cores") val cpuCores: CpuApplied? = null,
)

@Serializable
data class ColorSaved(val color: String)

@Serializable
data class MemoryServer(
    val id: String,
    val name: String = "",
    @SerialName("limit_mb") val limitMb: Int? = null,
    val running: Boolean = false,
    val `this`: Boolean = false,
)

/** The memory slider: bounded by the PC's measured memory. */
@Serializable
data class MemoryOverview(
    /** Null when it couldn't be measured: the slider is off then. */
    @SerialName("total_mb") val totalMb: Int? = null,
    @SerialName("limit_mb") val limitMb: Int? = null,
    @SerialName("jvm_args") val jvmArgs: List<String> = emptyList(),
    @SerialName("takes_memory_limit") val takesMemoryLimit: Boolean = false,
    @SerialName("min_mb") val minMb: Int = 1024,
    @SerialName("step_mb") val stepMb: Int = 512,
    val servers: List<MemoryServer> = emptyList(),
    val running: Boolean = false,
)

/** One kind of server, with what it can do (agent/servertypes). */
@Serializable
data class ServerTypeInfo(
    val id: String,
    val name: String = "",
    val edition: String = "java",
    /** mods, plugins or null. */
    val content: String? = null,
    /** easy, medium or hard to set up. */
    val ease: String? = null,
    val snapshots: Boolean = false,
    @SerialName("picks_loader") val picksLoader: Boolean = false,
    @SerialName("loader_name") val loaderName: String? = null,
    @SerialName("latest_only") val latestOnly: Boolean = false,
    @SerialName("takes_memory_limit") val takesMemoryLimit: Boolean = true,
    val crossplay: Boolean = false,
    val recommended: Boolean = false,
)

@Serializable
data class ServerTypes(
    val types: List<ServerTypeInfo> = emptyList(),
    val recommended: String = "",
    val default: String = "",
)

/** One Minecraft version a type offers. */
@Serializable
data class OfferedVersion(
    val minecraft: String,
    val stable: Boolean = true,
    val loaders: List<String> = emptyList(),
    @SerialName("java_required") val javaRequired: Int? = null,
    val kept: Boolean = false,
    val latest: Boolean = false,
)

@Serializable
data class TypeVersions(
    val type: String = "",
    @SerialName("type_name") val typeName: String = "",
    @SerialName("latest_only") val latestOnly: Boolean = false,
    val snapshots: Boolean = false,
    @SerialName("picks_loader") val picksLoader: Boolean = false,
    @SerialName("loader_name") val loaderName: String? = null,
    @SerialName("latest_stable") val latestStable: String? = null,
    val versions: List<OfferedVersion> = emptyList(),
    @SerialName("source_problem") val sourceProblem: String? = null,
)

@Serializable
data class LastVersionChange(
    val at: Double? = null,
    val type: String? = null,
    @SerialName("minecraft_version") val minecraftVersion: String? = null,
    @SerialName("can_roll_back") val canRollBack: Boolean = false,
)

/** A server's type and version as its console reported them; null is Unknown. */
@Serializable
data class ServerVersion(
    val type: String = "",
    val capabilities: ServerTypeInfo = ServerTypeInfo(id = ""),
    @SerialName("minecraft_version") val minecraftVersion: String? = null,
    @SerialName("minecraft_version_source") val minecraftVersionSource: String? = null,
    @SerialName("loader_version") val loaderVersion: String? = null,
    @SerialName("loader_name") val loaderName: String? = null,
    @SerialName("detected_type") val detectedType: String? = null,
    @SerialName("pending_version") val pendingVersion: JsonObject? = null,
    @SerialName("eula_required") val eulaRequired: Boolean = false,
    @SerialName("eula_url") val eulaUrl: String = "",
    @SerialName("last_change") val lastChange: LastVersionChange? = null,
)

@Serializable
data class PreflightSide(
    val type: String = "",
    @SerialName("type_name") val typeName: String = "",
    @SerialName("minecraft_version") val minecraftVersion: String? = null,
    @SerialName("loader_version") val loaderVersion: String? = null,
)

@Serializable
data class JavaCheck(
    /** ok, incompatible, unknown or not_needed. */
    val verdict: String = "unknown",
    val detail: String? = null,
)

/** What a version or type change would do, before anything happens. */
@Serializable
data class VersionPreflight(
    val current: PreflightSide = PreflightSide(),
    val target: PreflightSide = PreflightSide(),
    @SerialName("type_change") val typeChange: Boolean = false,
    @SerialName("gentle_type_change") val gentleTypeChange: Boolean = false,
    @SerialName("downgrade_warning") val downgradeWarning: Boolean = false,
    val java: JavaCheck = JavaCheck(),
    @SerialName("java_required") val javaRequired: Int? = null,
    @SerialName("moved_aside") val movedAside: List<String> = emptyList(),
    @SerialName("unknown_support") val unknownSupport: List<String> = emptyList(),
    @SerialName("not_supporting") val notSupporting: List<String> = emptyList(),
    val crossplay: Boolean = false,
    @SerialName("crossplay_available") val crossplayAvailable: Boolean = false,
)

@Serializable
data class VersionChanged(
    @SerialName("job_id") val jobId: String = "",
    val verified: Boolean? = null,
    @SerialName("crossplay_turned_off") val crossplayTurnedOff: Boolean? = null,
)

@Serializable
data class VersionRolledBack(@SerialName("job_id") val jobId: String = "", val type: String = "")

@Serializable
data class EulaAccepted(val url: String = "")

/** Whether Bedrock players can join this Java server (Geyser). */
@Serializable
data class CrossplayInfo(
    val available: Boolean = false,
    @SerialName("unavailable_reason") val unavailableReason: String? = null,
    val enabled: Boolean = false,
    val port: Int? = null,
    @SerialName("default_port") val defaultPort: Int = 19132,
    @SerialName("suggested_port") val suggestedPort: Int? = null,
    @SerialName("username_prefix") val usernamePrefix: String = "",
    @SerialName("missing_mod") val missingMod: String? = null,
    val ready: Boolean = false,
    val differences: List<String> = emptyList(),
    /** Only from a measured Tailscale address. */
    val address: String? = null,
    @SerialName("address_unknown") val addressUnknown: String? = null,
)

/** A suggested name and folder for a copy of this server. */
@Serializable
data class DuplicateOptions(
    val name: String = "",
    val directory: String = "",
    val running: Boolean = false,
    val crossplay: Boolean = false,
    @SerialName("world_folders") val worldFolders: List<String> = emptyList(),
)

@Serializable
data class DuplicateStarted(val job: Job)

/** A server taken off the list; its folder stays where it is. */
@Serializable
data class ServerRemoved(val removed: String, val name: String = "", val directory: String = "")

@Serializable
data class PcDrive(val name: String, val path: String)

@Serializable
data class PcShortcut(val key: String, val path: String)

@Serializable
data class PcFolder(val name: String, val path: String, val world: Boolean = false)

/** The folders inside one folder on the PC, names only. [path] is null for
 * the top: the drives and the usual shortcuts. */
@Serializable
data class FolderListing(
    val path: String? = null,
    val parent: String? = null,
    val folders: List<PcFolder> = emptyList(),
    val drives: List<PcDrive> = emptyList(),
    val shortcuts: List<PcShortcut> = emptyList(),
    val truncated: Boolean = false,
    val world: Boolean = false,
)

@Serializable
data class OffsiteSaved(val directory: String = "")

