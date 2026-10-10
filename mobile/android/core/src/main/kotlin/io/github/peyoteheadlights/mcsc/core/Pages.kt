package io.github.peyoteheadlights.mcsc.core

import kotlinx.coroutines.delay

/** The Console's level chips. */
enum class LevelChip(val key: String) {
    ALL("mobile.console.level_all"),
    WARNINGS("mobile.console.level_warnings"),
    ERRORS("mobile.console.level_errors"),
    ;

    fun matches(level: String): Boolean = when (this) {
        ALL -> true
        WARNINGS -> level == "WARN"
        ERRORS -> level == "ERROR" || level == "FATAL"
    }
}

/** How a console line is colored: warnings amber, errors red, and the
 * agent's echo of a sent command in the accent color. */
enum class LineLook { PLAIN, WARNING, DANGER, COMMAND }

/**
 * The lines the Console keeps: the newest [LIMIT], as the dashboard keeps.
 * The same line can arrive both from GET /logs and live, so a line already
 * here is not added twice.
 */
object ConsoleBuffer {
    const val LIMIT = 1000

    fun add(lines: List<ConsoleLine>, line: ConsoleLine): List<ConsoleLine> {
        if (lines.asReversed().take(RECENT).any { it.seq == line.seq && it.raw == line.raw }) return lines
        return (lines + line).takeLast(LIMIT)
    }

    fun replace(lines: List<ConsoleLine>): List<ConsoleLine> = lines.takeLast(LIMIT)

    /** What the filter box and chips leave: a case-insensitive match on the
     * line as printed, among the lines already loaded. */
    fun shown(lines: List<ConsoleLine>, filter: String, chip: LevelChip): List<ConsoleLine> {
        val needle = filter.trim()
        if (needle.isEmpty() && chip == LevelChip.ALL) return lines
        return lines.filter { chip.matches(it.level) && (needle.isEmpty() || it.raw.contains(needle, ignoreCase = true)) }
    }

    fun look(line: ConsoleLine): LineLook = when {
        line.source == "command" -> LineLook.COMMAND
        line.level == "ERROR" || line.level == "FATAL" -> LineLook.DANGER
        line.level == "WARN" -> LineLook.WARNING
        else -> LineLook.PLAIN
    }

    private const val RECENT = 50
}

/** The chat the Chat screen keeps: the newest [LIMIT] messages. */
object ChatBuffer {
    const val LIMIT = 300

    /** The most a message can be (the agent's own limit). */
    const val MAX_LENGTH = 220

    fun add(messages: List<ChatMessage>, message: ChatMessage): List<ChatMessage> {
        if (messages.asReversed().take(RECENT).any { it.seq == message.seq && it.text == message.text }) return messages
        return (messages + message).takeLast(LIMIT)
    }

    fun replace(messages: List<ChatMessage>): List<ChatMessage> = messages.takeLast(LIMIT)

    private const val RECENT = 50
}

/** What happened to a typed console command. */
sealed class CommandStep {
    /** Nothing typed: nothing sent. */
    data object Empty : CommandStep()

    /** The agent says it can't be sent; [reason] in its words, if it gave some. */
    data class Invalid(val reason: String?) : CommandStep()

    /** Risky: ask first with the agent's [reason], then [ConsoleCommands.confirmed]. */
    data class AskFirst(val command: String, val reason: String) : CommandStep()

    data class Sent(val command: String, val answer: CommandSent) : CommandStep()
}

/**
 * Sending a console command as the dashboard does: check it first; a risky
 * one is only sent with confirm after the person said yes to the agent's
 * reason. Commands go to Minecraft's console only, never a shell.
 */
class ConsoleCommands(private val client: AgentClient, private val serverId: String) {
    suspend fun submit(text: String): CommandStep {
        val command = text.trim()
        if (command.isEmpty()) return CommandStep.Empty
        if (command.length > MAX_LENGTH) return CommandStep.Invalid(null)
        val check = client.checkCommand(serverId, command)
        val danger = check.dangerReason
        if (!check.valid) return CommandStep.Invalid(check.error)
        if (danger != null) return CommandStep.AskFirst(command, danger)
        return CommandStep.Sent(command, client.sendCommand(serverId, command, confirm = false))
    }

    /** After the person said yes to [CommandStep.AskFirst]. */
    suspend fun confirmed(command: String): CommandStep.Sent =
        CommandStep.Sent(command, client.sendCommand(serverId, command, confirm = true))

    companion object {
        const val MAX_LENGTH = 512
        const val HISTORY = 20

        /** The commands sent this time, newest last, for the Up button.
         * Kept in memory only, never written down. */
        fun remember(history: List<String>, command: String): List<String> =
            (history.filter { it != command } + command).takeLast(HISTORY)
    }
}

/**
 * Following a player button after it was sent: ask the agent every second,
 * for up to 22 seconds, until the console answered. The result is the last
 * thing the agent said; still "sent" when time ran out or the PC stopped
 * answering, so the app never claims it worked.
 */
class PlayerActionWatch(
    private val poll: suspend (String) -> PlayerAction,
    private val every: Long = 1_000,
    private val upTo: Long = 22_000,
    private val clock: () -> Long = System::currentTimeMillis,
    private val sleep: suspend (Long) -> Unit = { delay(it) },
) {
    suspend fun follow(action: PlayerAction, onChange: (PlayerAction) -> Unit = {}): PlayerAction {
        var current = action
        val start = clock()
        while (current.state == PlayerActions.SENT && clock() - start < upTo) {
            sleep(every)
            val next = try {
                poll(current.id)
            } catch (e: AgentException) {
                return current
            }
            if (next != current) {
                current = next
                onChange(next)
            }
        }
        return current
    }
}

/** Which player buttons show, as the dashboard's Players page decides. */
object PlayerButtons {
    /**
     * The buttons for [name]: whitelist add or remove, operator (only with
     * players.op), kick (only while online) and ban or unban (not on
     * Bedrock). None without players.manage.
     */
    fun forPlayer(name: String, online: Boolean, page: PlayersPage, canManage: Boolean, canOp: Boolean): List<String> {
        if (!canManage) return emptyList()
        val buttons = mutableListOf<String>()
        buttons += if (on(page.lists?.whitelist, name)) PlayerActions.WHITELIST_REMOVE else PlayerActions.WHITELIST_ADD
        if (canOp) buttons += if (on(page.lists?.ops, name)) PlayerActions.DEOP else PlayerActions.OP
        if (online) buttons += PlayerActions.KICK
        if (page.bans != false) buttons += if (on(page.lists?.banned, name)) PlayerActions.PARDON else PlayerActions.BAN
        return buttons
    }

    /** "Whitelisted", "Operator", "Banned" tags for [name]. */
    fun tags(name: String, page: PlayersPage): List<String> = listOfNotNull(
        "players.tag_whitelisted".takeIf { on(page.lists?.whitelist, name) },
        "players.tag_op".takeIf { on(page.lists?.ops, name) },
        "players.tag_banned".takeIf { on(page.lists?.banned, name) },
    )

    /** The remove button on a list card. */
    fun removeFrom(list: String): String = when (list) {
        "ops" -> PlayerActions.DEOP
        "banned" -> PlayerActions.PARDON
        else -> PlayerActions.WHITELIST_REMOVE
    }

    private val JAVA_NAME = Regex("^\\.?[A-Za-z0-9_]{1,16}$")
    private val GAMERTAG = Regex("^[A-Za-z0-9](?:[A-Za-z0-9]| (?! )){0,19}(?<! )$")

    /** A typed name the agent would take, checked first so the person gets
     * the dashboard's own hint; the agent checks again. */
    fun validName(name: String, edition: String?): Boolean =
        if (edition == "bedrock") GAMERTAG.matches(name) else JAVA_NAME.matches(name)

    /** The most a reason for kick or ban can be. */
    const val REASON_LENGTH = 100

    private fun on(list: PlayerList?, name: String): Boolean =
        list?.players?.any { it.name?.lowercase() == name.lowercase() } == true
}
