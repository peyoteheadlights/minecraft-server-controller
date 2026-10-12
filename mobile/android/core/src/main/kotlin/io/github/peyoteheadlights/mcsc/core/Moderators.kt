package io.github.peyoteheadlights.mcsc.core

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

// Moderators and their permissions on each server (agent/api/routes/accounts.py,
// agent/security/permissions.py). "helper" in the agent's names until Phase 12.

@Serializable
data class Described(val permissions: List<String> = emptyList(), val level: String = Levels.NONE)

@Serializable
data class ServerAccess(
    val id: String,
    val name: String,
    val permissions: List<String> = emptyList(),
    val level: String = Levels.NONE,
)

@Serializable
data class OpenInvite(@SerialName("created_at") val createdAt: Double, @SerialName("expires_at") val expiresAt: Double)

@Serializable
data class Moderator(
    val username: String,
    val servers: List<String>? = null,
    @SerialName("all_servers") val allServers: Boolean = false,
    @SerialName("new_server") val newServer: Described = Described(),
    val access: List<ServerAccess> = emptyList(),
    @SerialName("invite_waiting") val inviteWaiting: Boolean = false,
    val invite: OpenInvite? = null,
    @SerialName("active_sessions") val activeSessions: Int = 0,
    @SerialName("last_used") val lastUsed: Double? = null,
    @SerialName("last_sign_in") val lastSignIn: Double? = null,
) {
    /** The servers they can see, with what they may do on each. */
    val seen: List<ServerAccess> get() = access.filter { it.permissions.isNotEmpty() }
}

@Serializable
data class PermissionLevel(val id: String, val permissions: List<String>)

@Serializable
data class PermissionGroup(val id: String, val permissions: List<String>)

@Serializable
data class PermissionCatalogue(
    val levels: List<PermissionLevel> = emptyList(),
    @SerialName("default_level") val defaultLevel: String = Levels.LOOK_AFTER_IT,
    val groups: List<PermissionGroup> = emptyList(),
    val technical: List<String> = emptyList(),
    val warn: List<String> = emptyList(),
    val needs: Map<String, List<String>> = emptyMap(),
)

@Serializable
data class ServerName(val id: String, val name: String)

@Serializable
data class ModeratorList(
    val owner: String,
    val helpers: List<Moderator> = emptyList(),
    val permissions: PermissionCatalogue = PermissionCatalogue(),
    val servers: List<ServerName> = emptyList(),
)

@Serializable
data class InviteCode(
    val ok: Boolean,
    val username: String,
    @SerialName("expires_at") val expiresAt: Double,
    val url: String? = null,
    val qr: List<String>? = null,
    val reason: String? = null,
)

@Serializable
data class ModeratorAdded(val ok: Boolean, val username: String, val invite: InviteCode? = null)

@Serializable
data class ModeratorChanged(val ok: Boolean, val username: String)

@Serializable
data class ModeratorRemoved(val ok: Boolean, val removed: String)

@Serializable
data class InviteCheck(val username: String, @SerialName("expires_at") val expiresAt: Double)

@Serializable
data class Device(
    val id: String,
    val user: String,
    val label: String? = null,
    @SerialName("last_used") val lastUsed: Double? = null,
    @SerialName("created_at") val createdAt: Double? = null,
    val current: Boolean = false,
)

@Serializable
data class DeviceList(val sessions: List<Device> = emptyList())

object Levels {
    const val START_AND_STOP = "start_and_stop"
    const val LOOK_AFTER_IT = "look_after_it"
    const val RUN_IT = "run_it"
    const val CUSTOM = "custom"
    const val NONE = "none"
}

/** The owner's moderator screens: levels, switches and what gets saved. */
object Moderators {
    /** The level a set matches, [Levels.CUSTOM] if none, [Levels.NONE] when empty. */
    fun levelOf(permissions: Set<String>, catalogue: PermissionCatalogue): String {
        if (permissions.isEmpty()) return Levels.NONE
        return catalogue.levels.firstOrNull { it.permissions.toSet() == permissions }?.id ?: Levels.CUSTOM
    }

    fun level(id: String, catalogue: PermissionCatalogue): Set<String> =
        catalogue.levels.firstOrNull { it.id == id }?.permissions?.toSet().orEmpty()

    /**
     * Ticking a switch brings what it needs (Make ops needs Players);
     * unticking one takes away what needs it. Anything ticked brings seeing
     * the server; nothing left ticked hides the server.
     */
    fun toggle(permissions: Set<String>, permission: String, on: Boolean, catalogue: PermissionCatalogue): Set<String> {
        val next = permissions.toMutableSet()
        if (on) {
            next += permission
            next += catalogue.needs[permission].orEmpty()
        } else {
            next -= permission
            next -= catalogue.needs.filterValues { permission in it }.keys
        }
        next -= Permissions.SERVER_VIEW
        return if (next.isEmpty()) emptySet() else next + Permissions.SERVER_VIEW
    }

    /** The switches a group shows: the Technical-only ones only in Technical mode. */
    fun shown(group: PermissionGroup, technical: Boolean, catalogue: PermissionCatalogue): List<String> =
        group.permissions.filter { technical || it !in catalogue.technical }

    /** "N more permissions in Technical mode": ticked switches Simple mode doesn't show. */
    fun hiddenTicked(permissions: Set<String>, technical: Boolean, catalogue: PermissionCatalogue): Int =
        if (technical) 0 else permissions.count { it in catalogue.technical }

    /** Console commands or Make ops: they let someone do anything in the game. */
    fun warns(permissions: Set<String>, catalogue: PermissionCatalogue): Boolean =
        permissions.any { it in catalogue.warn }

    /**
     * The short line under a server: the level's name, or the ticked
     * switches' names ("Start and stop, Players, Chat") for a custom set.
     */
    fun summary(permissions: Set<String>, catalogue: PermissionCatalogue, strings: Strings): String {
        val level = levelOf(permissions, catalogue)
        if (level != Levels.CUSTOM) return strings.t("mobile.mod.level_$level")
        val names = catalogue.groups.flatMap { it.permissions }.filter { it in permissions }.map { strings.t(switchKey(it)) }
        val shown = names.take(3).joinToString(", ")
        return if (names.size > 3) strings.t("mobile.mod.summary_more", "list" to shown, "count" to names.size - 3) else shown
    }

    fun switchKey(permission: String): String = "mobile.mod.switch_${permission.replace('.', '_')}"

    /** "Save for this server" and "Save for…": the same set on each server named. */
    fun saveFor(servers: Collection<String>, permissions: Set<String>): JsonObject = buildJsonObject {
        put("grants", JsonObject(servers.associateWith { list(permissions) }))
    }

    /** "Apply to all": every server now, and each new one for an "All servers" moderator. */
    fun applyToAll(servers: Collection<String>, permissions: Set<String>, allServers: Boolean): JsonObject = buildJsonObject {
        put("grants", JsonObject(servers.associateWith { list(permissions) }))
        if (allServers) put("new_server", list(permissions))
    }

    /** The "New servers" set of an "All servers" moderator. */
    fun newServers(permissions: Set<String>): JsonObject = buildJsonObject { put("new_server", list(permissions)) }

    /**
     * "All servers" on: each new server gives what most of their servers
     * have now (the default level if none). Off: they keep the servers
     * they have, and new ones aren't theirs.
     */
    fun allServers(on: Boolean, moderator: Moderator, catalogue: PermissionCatalogue): JsonObject = buildJsonObject {
        put("all_servers", on)
        if (on) {
            val usual = moderator.seen.groupingBy { it.permissions.toSet() }.eachCount().maxByOrNull { it.value }?.key
            put("new_server", list(usual ?: level(catalogue.defaultLevel, catalogue)))
        }
    }

    private fun list(permissions: Set<String>) = JsonArray(permissions.sorted().map(::JsonPrimitive))

    /** A name the agent accepts (USERNAME_RE in agent/security/auth.py). */
    fun nameOk(name: String): Boolean = USERNAME.matches(name.trim())

    private val USERNAME = Regex("^[A-Za-z0-9][A-Za-z0-9_.-]{1,31}$")
}

/** A moderator's invite: the pairing link plus a one-time token and their name (agent/pairing.py). */
data class Invite(val token: String, val username: String)

object InviteLink {
    private val TOKEN = Regex("^[A-Za-z0-9_-]{20,128}$")
    private val URL = Regex("""https://\S+""", RegexOption.IGNORE_CASE)

    /** The invite link in a scanned code or pasted text (a whole message
     * with words around it), or null when there is none. */
    fun url(input: String): String? {
        val text = input.trim()
        return URL.findAll(text).map { it.value }.firstOrNull { "invite=" in it }
            ?: text.takeIf { "invite=" in it && it.none(Char::isWhitespace) }
    }

    /** The invite in [input], or null when it has none or it is broken. */
    fun parse(input: String): Invite? {
        val query = url(input)?.substringAfter('?', "")?.substringBefore('#')
        if (query.isNullOrEmpty()) return null
        val values = query.split('&').mapNotNull { part ->
            val eq = part.indexOf('=')
            if (eq <= 0) null else part.substring(0, eq) to runCatching { java.net.URLDecoder.decode(part.substring(eq + 1), "UTF-8") }.getOrNull()
        }.toMap()
        val token = values["invite"] ?: return null
        val user = values["user"] ?: return null
        if (!TOKEN.matches(token) || !Moderators.nameOk(user)) return null
        return Invite(token, user)
    }
}
