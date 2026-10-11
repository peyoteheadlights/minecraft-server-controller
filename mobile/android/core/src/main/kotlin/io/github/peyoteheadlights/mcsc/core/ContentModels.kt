package io.github.peyoteheadlights.mcsc.core

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

/*
 * What the Mods / Plugins / Packs and Game settings screens read. As in
 * PageModels.kt, only the fields the app uses are listed, and a value the
 * agent can leave out is null here and shown as Unknown.
 */

/** Something wrong with one mod, in the agent's words. */
@Serializable
data class ModIssue(
    val kind: String = "",
    val severity: String = "info",
    val detail: String = "",
)

/** A newer version found on Modrinth at the agent's last check. */
@Serializable
data class ModUpdate(
    @SerialName("latest_version") val latestVersion: String = "",
    @SerialName("version_id") val versionId: String? = null,
)

/** One mod or plugin in the server's folder. */
@Serializable
data class Mod(
    val filename: String,
    @SerialName("mod_id") val modId: String = "",
    val name: String = "",
    val version: String = "",
    val enabled: Boolean = true,
    val description: String? = null,
    @SerialName("minecraft_range") val minecraftRange: String? = null,
    /** ok, warn or error while on; disabled while off. */
    val status: String? = null,
    val issues: List<ModIssue> = emptyList(),
    @SerialName("update_available") val updateAvailable: ModUpdate? = null,
)

@Serializable
data class ModList(
    val mods: List<Mod> = emptyList(),
    /** Null until the server has started once. */
    @SerialName("minecraft_version") val minecraftVersion: String? = null,
    @SerialName("server_state") val serverState: String = "UNKNOWN",
)

@Serializable
data class ModChanged(val mod: Mod? = null)

@Serializable
data class ModDependent(
    val name: String = "",
    val requires: String? = null,
)

/** What else needs a mod, asked before it is removed. */
@Serializable
data class ModImpact(
    val dependents: List<ModDependent> = emptyList(),
    val warning: String? = null,
)

@Serializable
data class ModRef(
    val filename: String = "",
    val name: String = "",
    val version: String = "",
)

@Serializable
data class ModRemoved(val removed: ModRef? = null)

@Serializable
data class ModUpdated(
    val updated: ModRef? = null,
    @SerialName("previous_version") val previousVersion: String? = null,
)

/** A copy of a mod kept on this server, which it can roll back to. */
@Serializable
data class ModVersion(
    val version: String? = null,
    val filename: String = "",
    @SerialName("archive_path") val archivePath: String,
    @SerialName("created_at") val createdAt: Double = 0.0,
    @SerialName("is_current") val isCurrent: Boolean = false,
    /** False when the kept file has gone. */
    val exists: Boolean = false,
)

@Serializable
data class ModVersions(val versions: List<ModVersion> = emptyList())

@Serializable
data class ModRolledBack(
    val restored: ModRef? = null,
    @SerialName("previous_version") val previousVersion: String? = null,
)

/** One change in the history: what, when, who, and whether it worked. */
@Serializable
data class ModHistoryRow(
    val ts: Double = 0.0,
    val user: String? = null,
    val action: String = "",
    @SerialName("mod_id") val modId: String? = null,
    @SerialName("mod_name") val modName: String? = null,
    @SerialName("old_version") val oldVersion: String? = null,
    @SerialName("new_version") val newVersion: String? = null,
    val result: String = "",
    val detail: String? = null,
)

@Serializable
data class ModHistory(val history: List<ModHistoryRow> = emptyList())

/** A Modrinth search result. [iconUrl] is loaded straight from Modrinth. */
@Serializable
data class ModrinthHit(
    @SerialName("project_id") val projectId: String? = null,
    val slug: String = "",
    val title: String = "",
    val description: String? = null,
    val downloads: Long? = null,
    @SerialName("icon_url") val iconUrl: String? = null,
    val page: String? = null,
)

@Serializable
data class ModSearch(
    val hits: List<ModrinthHit> = emptyList(),
    val total: Int? = null,
)

@Serializable
data class ModrinthFile(val filename: String? = null, val size: Long? = null)

@Serializable
data class ModrinthDependency(
    @SerialName("project_id") val projectId: String? = null,
    val type: String? = null,
)

@Serializable
data class ModrinthVersion(
    @SerialName("version_id") val versionId: String? = null,
    @SerialName("version_number") val versionNumber: String? = null,
    @SerialName("game_versions") val gameVersions: List<String> = emptyList(),
    val dependencies: List<ModrinthDependency> = emptyList(),
    val file: ModrinthFile? = null,
)

@Serializable
data class ModrinthProject(
    val slug: String = "",
    val title: String = "",
    val description: String? = null,
    val license: String? = null,
    @SerialName("server_side") val serverSide: String? = null,
    @SerialName("client_side") val clientSide: String? = null,
    @SerialName("icon_url") val iconUrl: String? = null,
    val page: String? = null,
)

/** A Modrinth project and its versions that fit this server, newest first. */
@Serializable
data class ModProject(
    val project: ModrinthProject = ModrinthProject(),
    val versions: List<ModrinthVersion> = emptyList(),
)

@Serializable
data class DependencyNeeded(
    @SerialName("mod_id") val modId: String = "",
    val title: String? = null,
    val installed: Boolean = false,
)

@Serializable
data class ModInstalled(
    val installed: ModRef? = null,
    @SerialName("dependencies_required") val dependenciesRequired: List<DependencyNeeded> = emptyList(),
)

/** A link to a mod's page, when Modrinth has one. */
@Serializable
data class DependencyPage(val page: String? = null)

@Serializable
data class DependencyItem(
    @SerialName("mod_id") val modId: String,
    val name: String = "",
    val kind: String = "",
    /** Minecraft, the loader or Java rather than a mod. */
    val platform: Boolean = false,
    val status: String? = null,
    @SerialName("range_text") val rangeText: String? = null,
    val reason: String? = null,
    val modrinth: DependencyPage? = null,
)

@Serializable
data class DependencyReport(
    val items: List<DependencyItem> = emptyList(),
    @SerialName("missing_required") val missingRequired: List<String> = emptyList(),
)

@Serializable
data class PlannedDependency(
    @SerialName("mod_id") val modId: String = "",
    val title: String? = null,
    @SerialName("version_number") val versionNumber: String? = null,
    val size: Long? = null,
)

/** One the app can't install by itself, with a page to get it by hand. */
@Serializable
data class UnresolvableDependency(
    @SerialName("mod_id") val modId: String = "",
    val name: String? = null,
    val reason: String = "",
    val page: String? = null,
)

/** What "Install the missing ones" would download. Nothing is yet. */
@Serializable
data class DependencyPlan(
    val items: List<PlannedDependency> = emptyList(),
    val unresolvable: List<UnresolvableDependency> = emptyList(),
)

@Serializable
data class DependencyResult(
    val title: String = "",
    val result: String = "",
    val detail: String? = null,
)

@Serializable
data class DependencyInstall(val results: List<DependencyResult> = emptyList())

@Serializable
data class ModUploaded(val installed: ModRef? = null)

/** A mod Update all would change. Turned-off ones are listed, not ticked. */
@Serializable
data class UpdateAllRow(
    @SerialName("mod_id") val modId: String = "",
    val name: String = "",
    val filename: String,
    val enabled: Boolean = true,
    @SerialName("installed_version") val installedVersion: String = "",
    @SerialName("latest_version") val latestVersion: String = "",
    @SerialName("version_id") val versionId: String? = null,
)

/** One Modrinth couldn't be asked about, with the reason. */
@Serializable
data class UpdateAllUnchecked(
    val name: String = "",
    val reason: String = "",
)

@Serializable
data class UpdateAllPlan(
    val updates: List<UpdateAllRow> = emptyList(),
    val unchecked: List<UpdateAllUnchecked> = emptyList(),
    @SerialName("server_running") val serverRunning: Boolean = false,
    @SerialName("blocked_by") val blockedBy: String? = null,
)

@Serializable
data class UpdateAllDone(
    val name: String = "",
    @SerialName("previous_version") val previousVersion: String = "",
    val version: String = "",
)

@Serializable
data class UpdateAllResult(
    val updated: List<UpdateAllDone> = emptyList(),
    @SerialName("safety_backup") val safetyBackup: SafetyBackup? = null,
    val undo: Undo? = null,
)

@Serializable
data class ModpackFile(
    val name: String = "",
    val size: Long? = null,
    /** download, client_only or refused. */
    val status: String = "",
    val reason: String? = null,
)

/** What a modpack holds, read before anything changes. */
@Serializable
data class Modpack(
    val name: String = "",
    val version: String? = null,
    val summary: String? = null,
    @SerialName("minecraft_version") val minecraftVersion: String? = null,
    @SerialName("type_name") val typeName: String? = null,
    @SerialName("loader_version") val loaderVersion: String? = null,
    val files: List<ModpackFile> = emptyList(),
    @SerialName("download_count") val downloadCount: Int = 0,
    @SerialName("download_bytes") val downloadBytes: Long = 0,
    @SerialName("client_only") val clientOnly: List<String> = emptyList(),
    @SerialName("skipped_overrides") val skippedOverrides: List<String> = emptyList(),
    val problems: List<String> = emptyList(),
    @SerialName("can_import") val canImport: Boolean = false,
)

@Serializable
data class ModpackInto(@SerialName("version_change") val versionChange: Boolean = false)

@Serializable
data class ModpackInspected(
    val token: String,
    val pack: Modpack = Modpack(),
    val into: ModpackInto? = null,
)

@Serializable
data class ModpackSummary(val name: String = "")

@Serializable
data class ModpackImported(
    val modpack: ModpackSummary = ModpackSummary(),
    val undo: Undo? = null,
)

/** One Bedrock behavior or resource pack. */
@Serializable
data class Addon(
    val uuid: String,
    val name: String = "",
    val version: String = "",
    val description: String? = null,
    /** behavior or resource. */
    val kind: String = "",
    val folder: String = "",
    val enabled: Boolean = false,
)

@Serializable
data class AddonList(
    val addons: List<Addon> = emptyList(),
    /** The world the packs are on; null before the server made one. */
    val world: String? = null,
    val running: Boolean = false,
    @SerialName("restart_needed") val restartNeeded: Boolean? = null,
)

@Serializable
data class AddonResult(
    val installed: List<Addon> = emptyList(),
    @SerialName("restart_needed") val restartNeeded: Boolean? = null,
)

/** One setting from server.properties. [value] is typed (a word, a number,
 * true or false); null when the file doesn't set it or can't be read. */
@Serializable
data class GameSetting(
    val key: String,
    /** choice, bool, int, text, port or seed. */
    val kind: String = "text",
    val value: JsonElement? = null,
    val set: Boolean = false,
    val problem: String? = null,
    /** The file's own text for it, as written (shown when it can't be read as a value). */
    val raw: String? = null,
    @SerialName("minecraft_default") val minecraftDefault: String = "",
    val choices: List<String> = emptyList(),
    val min: Int? = null,
    val max: Int? = null,
    @SerialName("max_length") val maxLength: Int? = null,
    /** "world_exists" for the seed once the world is made. */
    @SerialName("read_only") val readOnly: String? = null,
)

@Serializable
data class GameSettings(
    val file: String = "",
    val exists: Boolean = false,
    val fields: List<GameSetting> = emptyList(),
    val running: Boolean = false,
    @SerialName("restart_needed") val restartNeeded: Boolean = false,
    /** The whole file as it is now, for the Technical mode editor. */
    val text: String = "",
)

@Serializable
data class GameSettingsSaved(
    val keys: List<String> = emptyList(),
    @SerialName("nothing_changed") val nothingChanged: Boolean? = null,
    val running: Boolean = false,
    @SerialName("restart_needed") val restartNeeded: Boolean = false,
)
