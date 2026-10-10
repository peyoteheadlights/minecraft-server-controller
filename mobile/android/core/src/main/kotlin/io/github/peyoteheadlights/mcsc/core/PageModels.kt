package io.github.peyoteheadlights.mcsc.core

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/*
 * What the per-server screens read: Console, Chat, Players, Activity,
 * Crashes and the Overview's cards. As in Models.kt, only the fields the app
 * uses are listed, anything else is ignored, and a value the agent can leave
 * out is null here and shown as Unknown.
 */

/** One console line (agent/minecraft/console.py). */
@Serializable
data class ConsoleLine(
    val seq: Long = 0,
    val ts: Double = 0.0,
    val raw: String = "",
    val level: String = "INFO",
    val source: String = "stdout",
)

@Serializable
data class ConsoleLog(
    val lines: List<ConsoleLine> = emptyList(),
    val buffered: Int? = null,
    @SerialName("buffer_limit") val bufferLimit: Int? = null,
)

@Serializable
data class CommandCheck(
    val valid: Boolean = false,
    val error: String? = null,
    @SerialName("danger_reason") val dangerReason: String? = null,
)

@Serializable
data class CommandSent(
    val result: String,
    val detail: String? = null,
    val command: String? = null,
)

/** One chat line (agent/minecraft/chat.py). [name] is null for the server. */
@Serializable
data class ChatMessage(
    val seq: Long = 0,
    val ts: Double = 0.0,
    val kind: String = "player",
    val name: String? = null,
    val text: String = "",
)

@Serializable
data class ChatLog(
    val messages: List<ChatMessage> = emptyList(),
    val running: Boolean? = null,
)

@Serializable
data class ChatSent(
    val result: String,
    val detail: String? = null,
    val message: String? = null,
)

/** Someone the agent has seen join (the players table). */
@Serializable
data class KnownPlayer(
    val username: String,
    val uuid: String? = null,
    @SerialName("first_seen") val firstSeen: Double? = null,
    @SerialName("last_seen") val lastSeen: Double? = null,
    val sessions: Int? = null,
    val online: Int? = null,
    val edition: String? = null,
    @SerialName("total_seconds_live") val totalSecondsLive: Double? = null,
)

/** A name on one of Minecraft's own lists. On Bedrock an operator can have
 * no name, only the Xbox number in [uuid]. */
@Serializable
data class ListedPlayer(
    val name: String? = null,
    val uuid: String? = null,
    val reason: String? = null,
)

/** whitelist.json, ops.json or banned-players.json. [players] is null
 * when the file isn't there or can't be read; [reason] says why. */
@Serializable
data class PlayerList(
    val players: List<ListedPlayer>? = null,
    val file: String? = null,
    val reason: String? = null,
)

@Serializable
data class PlayerLists(
    val whitelist: PlayerList? = null,
    val ops: PlayerList? = null,
    val banned: PlayerList? = null,
)

/** A player button sent to the server, and what the console answered. */
@Serializable
data class PlayerAction(
    val id: String,
    val kind: String,
    val name: String,
    @SerialName("sent_at") val sentAt: Double? = null,
    val state: String = PlayerActions.SENT,
    val message: String? = null,
    @SerialName("answered_at") val answeredAt: Double? = null,
)

@Serializable
data class PlayerActionResult(val result: String, val action: PlayerAction)

@Serializable
data class PlayerActionStatus(val action: PlayerAction)

/** GET /players. [onlineCount] is null until the list is established. */
@Serializable
data class PlayersPage(
    val online: List<OnlinePlayer> = emptyList(),
    @SerialName("online_count") val onlineCount: Int? = null,
    val verified: Boolean? = null,
    val known: List<KnownPlayer> = emptyList(),
    @SerialName("max_players") val maxPlayers: Int? = null,
    val lists: PlayerLists? = null,
    val bans: Boolean? = null,
    val edition: String? = null,
    val running: Boolean? = null,
    val actions: List<PlayerAction> = emptyList(),
)

/** One row of the events table. Its data is never shown as it is (it can
 * hold sign-in names and addresses), so it isn't read at all. */
@Serializable
data class EventRow(
    val id: Long? = null,
    @SerialName("server_id") val serverId: String? = null,
    val ts: Double? = null,
    val type: String = "",
    val level: String = "info",
    val message: String = "",
)

@Serializable
data class EventList(val events: List<EventRow> = emptyList())

@Serializable
data class CrashAnalysis(
    val category: String? = null,
    val confidence: String? = null,
    val summary: String? = null,
    val advice: String? = null,
    @SerialName("suspect_mods") val suspectMods: List<String>? = null,
)

@Serializable
data class CrashContext(
    val analysis: CrashAnalysis? = null,
    @SerialName("players_online") val playersOnline: List<String>? = null,
    @SerialName("crash_report") val crashReport: String? = null,
    @SerialName("log_file") val logFile: String? = null,
    @SerialName("console_file") val consoleFile: String? = null,
    @SerialName("minecraft_version") val minecraftVersion: String? = null,
    @SerialName("fabric_loader") val fabricLoader: String? = null,
    @SerialName("java_version") val javaVersion: String? = null,
)

/** A crash. [logTail] only comes with GET /crashes/{id}, and only while
 * the saved log is still there. */
@Serializable
data class Crash(
    val id: Long,
    val ts: Double? = null,
    @SerialName("exit_code") val exitCode: Int? = null,
    val category: String? = null,
    val confidence: String? = null,
    val summary: String? = null,
    val evidence: List<String>? = null,
    val context: CrashContext? = null,
    @SerialName("log_tail") val logTail: List<String>? = null,
)

@Serializable
data class CrashList(val crashes: List<Crash> = emptyList())

/** A suggestion's fix: a dashboard page or an outside link. */
@Serializable
data class RecAction(
    val label: String? = null,
    val page: String? = null,
    val url: String? = null,
)

/** A suggestion, in the agent's own (English) words. */
@Serializable
data class Recommendation(
    val id: String,
    val title: String = "",
    val reason: String? = null,
    val evidence: String? = null,
    val action: RecAction? = null,
)

@Serializable
data class Recommendations(
    val recommendations: List<Recommendation> = emptyList(),
    val hidden: List<Recommendation> = emptyList(),
)

@Serializable
data class ChecklistEvidence(
    val name: String? = null,
    @SerialName("created_at") val createdAt: Double? = null,
)

@Serializable
data class ChecklistItem(
    val id: String,
    val done: Boolean = false,
    @SerialName("evidence_key") val evidenceKey: String? = null,
    val evidence: ChecklistEvidence? = null,
)

/** Getting started. Ticked from what the agent measured, never from a tap. */
@Serializable
data class Checklist(
    val items: List<ChecklistItem> = emptyList(),
    val done: Int? = null,
    val total: Int? = null,
    val show: Boolean = false,
)

@Serializable
data class JoinAddress(
    val address: String,
    val adapter: String? = null,
    val virtual: Boolean = false,
)

@Serializable
data class TailscaleInfo(
    val address: String? = null,
    @SerialName("dns_name") val dnsName: String? = null,
    val connected: Boolean? = null,
    val verified: Boolean? = null,
    val detail: String? = null,
)

/** How to reach one edition: home addresses, Tailscale and the port. */
@Serializable
data class JoinWay(
    val port: Int? = null,
    @SerialName("port_source") val portSource: String? = null,
    @SerialName("default_port") val defaultPort: Boolean? = null,
    val local: List<JoinAddress> = emptyList(),
    val tailscale: TailscaleInfo? = null,
    /** Bedrock crossplay only: the Tailscale address, null when unknown. */
    val address: String? = null,
    val ready: Boolean? = null,
    @SerialName("own_server") val ownServer: Boolean? = null,
)

/** GET /join. The internet is never tested, so it is never claimed. */
@Serializable
data class JoinInfo(
    val java: JoinWay? = null,
    val bedrock: JoinWay? = null,
    val running: Boolean? = null,
)

@Serializable
data class Ok(val ok: Boolean = false)

/** The player buttons (agent/minecraft/playeractions.py) and their states. */
object PlayerActions {
    const val WHITELIST_ADD = "whitelist_add"
    const val WHITELIST_REMOVE = "whitelist_remove"
    const val OP = "op"
    const val DEOP = "deop"
    const val KICK = "kick"
    const val BAN = "ban"
    const val PARDON = "pardon"
    val ALL = listOf(WHITELIST_ADD, WHITELIST_REMOVE, OP, DEOP, KICK, BAN, PARDON)

    /** Only these two ask first, with an optional reason. */
    val CONFIRM = setOf(KICK, BAN)

    const val SENT = "sent"
    const val DONE = "done"
    const val UNCHANGED = "unchanged"
    const val FAILED = "failed"
    const val NO_ANSWER = "no_answer"
}
