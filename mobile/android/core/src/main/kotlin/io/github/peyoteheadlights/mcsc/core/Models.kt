package io.github.peyoteheadlights.mcsc.core

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/**
 * What the agent answers, as agent/api/responses.py describes it. Only the
 * fields the app uses are listed; anything else the agent adds is ignored.
 * A value the agent hasn't measured is null here and shown as Unknown,
 * never as 0 or a guess (house rule 1).
 */
val AgentJson = Json {
    ignoreUnknownKeys = true
    explicitNulls = false
    coerceInputValues = true
}

@Serializable
data class Health(
    val ok: Boolean = false,
    @SerialName("agent_uptime") val agentUptime: Double? = null,
    @SerialName("auth_configured") val authConfigured: Boolean? = null,
    @SerialName("api_version") val apiVersion: Int? = null,
)

@Serializable
data class LoginResult(
    val token: String,
    val user: String? = null,
    @SerialName("expires_at") val expiresAt: Double? = null,
)

@Serializable
data class Me(
    val user: String,
    val role: String = "owner",
    val servers: List<String>? = null,
    /** Everything held on at least one server, plus the account's own. */
    val permissions: List<String> = emptyList(),
    /** What doesn't belong to one server. Null from an agent older than part 6. */
    @SerialName("account_permissions") val accountPermissions: List<String>? = null,
    /** What this account may do on each server it can see, by server id. */
    @SerialName("server_permissions") val serverPermissions: Map<String, List<String>>? = null,
    val preferences: Map<String, String> = emptyMap(),
) {
    val isOwner: Boolean get() = role == "owner"

    fun can(permission: String): Boolean =
        permission in permissions ||
            // An agent older than part 6 has one settings permission for all three.
            (serverPermissions == null && permission in Permissions.SPLIT_SETTINGS && Permissions.SETTINGS_EDIT in permissions)

    /**
     * This account on one server: what it may do there and nothing it may
     * only do on others. Unchanged for no server, or an agent that doesn't
     * say per server.
     */
    fun forServer(serverId: String?): Me {
        val perServer = serverPermissions ?: return this
        if (serverId == null) return this
        return copy(permissions = (accountPermissions.orEmpty() + perServer[serverId].orEmpty()).distinct())
    }

    /**
     * Whether the Console, Chat, Activity and Crashes show on this server
     * ("See the Console and Activity"). An agent older than part 6 doesn't
     * say, so they show, as before.
     */
    val readsConsole: Boolean
        get() = isOwner || serverPermissions == null || Permissions.CONSOLE_READ in permissions

    /** Whether this account can see that server now (a moderator's servers change). */
    fun sees(serverId: String?): Boolean =
        serverId == null || serverPermissions?.containsKey(serverId) ?: (servers == null || serverId in servers)
}

@Serializable
data class Capabilities(
    val addons: Boolean? = null,
    val mods: Boolean? = null,
    val bans: Boolean? = null,
    val crossplay: Boolean? = null,
    /** False for a server type that reports no game speed (Bedrock). */
    val speed: Boolean? = null,
)

@Serializable
data class ServerRow(
    val id: String,
    val name: String,
    val color: String? = null,
    val state: String = "UNKNOWN",
    @SerialName("state_verified") val stateVerified: Boolean? = null,
    val uptime: Double? = null,
    @SerialName("players_online") val playersOnline: Int? = null,
    @SerialName("players_verified") val playersVerified: Boolean? = null,
    @SerialName("max_players") val maxPlayers: Int? = null,
    @SerialName("minecraft_version") val minecraftVersion: String? = null,
    @SerialName("type_name") val typeName: String? = null,
    /** "mods" or "plugins"; null for a type that takes neither. */
    val content: String? = null,
    val edition: String? = null,
    val capabilities: Capabilities? = null,
)

@Serializable
data class ServerList(
    val servers: List<ServerRow> = emptyList(),
    val default: String? = null,
)

@Serializable
data class OnlinePlayer(
    val username: String,
    val uuid: String? = null,
    val edition: String? = null,
    @SerialName("session_seconds") val sessionSeconds: Double? = null,
    /** Null when the join wasn't seen: then [sessionSeconds] is 0, not measured. */
    @SerialName("session_started") val sessionStarted: Double? = null,
)

@Serializable
data class ServerStatus(
    @SerialName("server_id") val serverId: String? = null,
    val name: String? = null,
    val state: String = "UNKNOWN",
    @SerialName("state_verified") val stateVerified: Boolean? = null,
    val uptime: Double? = null,
    @SerialName("minecraft_version") val minecraftVersion: String? = null,
    @SerialName("server_type_name") val serverTypeName: String? = null,
    @SerialName("players_online") val playersOnline: Int? = null,
    @SerialName("players_verified") val playersVerified: Boolean? = null,
    val players: List<OnlinePlayer> = emptyList(),
    @SerialName("max_players") val maxPlayers: Int? = null,
)

@Serializable
data class ServerAction(
    val result: String,
    val detail: String? = null,
    val state: String? = null,
)

@Serializable
data class AppAlert(
    val id: Long,
    val ts: Double,
    @SerialName("server_id") val serverId: String? = null,
    val event: String,
    val title: String,
    val body: String,
    val page: String,
    val url: String,
)

@Serializable
data class AppAlerts(
    val alerts: List<AppAlert> = emptyList(),
    val latest: Long = 0,
    val more: Boolean = false,
    val enabled: Boolean = false,
)

@Serializable
data class AppPhone(
    val configured: Boolean = false,
    val registered: Boolean = false,
)

/** One line of the agent's live feed (/ws): {"type": "event", "event": {...}}. */
@Serializable
data class LiveEvent(
    val type: String,
    val ts: Double? = null,
    @SerialName("server_id") val serverId: String? = null,
)

@Serializable
data class VersionInfo(
    val version: String? = null,
    @SerialName("api_version") val apiVersion: Int? = null,
)

/** The states the agent reports (agent/minecraft/process.py). */
object States {
    const val ONLINE = "ONLINE"
    const val OFFLINE = "OFFLINE"
    const val STARTING = "STARTING"
    const val STOPPING = "STOPPING"
    const val RESTARTING = "RESTARTING"
    const val RESTART_PENDING = "RESTART_PENDING"
    const val CRASHED = "CRASHED"
    const val UNKNOWN = "UNKNOWN"
}

/** Permission names (agent/security/permissions.py). */
object Permissions {
    const val SERVER_VIEW = "server.view"
    const val SERVER_CONTROL = "server.control"
    const val CONSOLE_SEND = "console.send"
    const val PLAYERS_MANAGE = "players.manage"
    const val PLAYERS_OP = "players.op"
    const val CHAT_SEND = "chat.send"
    const val SETTINGS_VIEW = "settings.view"
    /** The one settings permission of agents older than part 6. */
    const val SETTINGS_EDIT = "settings.edit"
    const val SETTINGS_GAME = "settings.game"
    const val SETTINGS_SERVER = "settings.server"
    const val PC_SETTINGS = "pc.settings"
    const val CONSOLE_READ = "console.read"
    const val USERS_MANAGE = "users.manage"
    val SPLIT_SETTINGS = setOf(SETTINGS_GAME, SETTINGS_SERVER, PC_SETTINGS)
    const val BACKUPS_CREATE = "backups.create"
    const val BACKUPS_DOWNLOAD = "backups.download"
    const val BACKUPS_RESTORE = "backups.restore"
    const val BACKUPS_DELETE = "backups.delete"
    const val SCHEDULES_MANAGE = "schedules.manage"
    const val MODS_MANAGE = "mods.manage"
    const val SERVERS_MANAGE = "servers.manage"
    const val FILES_BROWSE = "files.browse"
    const val WORLD_REPLACE = "world.replace"
}
