package io.github.peyoteheadlights.mcsc.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import io.github.peyoteheadlights.mcsc.core.Display
import io.github.peyoteheadlights.mcsc.core.PlayerActions
import io.github.peyoteheadlights.mcsc.core.PlayerButtons
import io.github.peyoteheadlights.mcsc.core.PlayerList
import io.github.peyoteheadlights.mcsc.core.PlayersPage
import io.github.peyoteheadlights.mcsc.core.Permissions

/** A kick or ban waiting for "yes", with its optional reason. */
private data class Asking(val action: String, val name: String)

/**
 * Who is online, everyone seen, and Minecraft's whitelist, operators and
 * bans, with the dashboard's buttons. Each button is a console command;
 * the app says what the console answered, never that it worked when the
 * console didn't confirm it.
 */
@Composable
fun PlayersScreen(vm: AppViewModel, serverId: String, onBack: () -> Unit) {
    val pages = vm.pages(serverId)
    val canManage = vm.canDo(Permissions.PLAYERS_MANAGE)
    val canOp = vm.canDo(Permissions.PLAYERS_OP)
    var asking by remember { mutableStateOf<Asking?>(null) }
    LaunchedEffect(serverId) { pages.loadPlayers() }
    val press: (String, String) -> Unit = { action, name ->
        if (action in PlayerActions.CONFIRM) {
            asking = Asking(action, name)
        } else {
            pages.playerAction(action, name, null)
        }
    }

    ServerFrame(
        vm, serverId,
        title = t("page.players"),
        onBack = onBack,
        refreshing = false,
        onRefresh = pages::loadPlayers,
        overlay = {
            asking?.let { ask ->
                AskWithReason(ask, onDismiss = { asking = null }) { reason ->
                    asking = null
                    pages.playerAction(ask.action, ask.name, reason)
                }
            }
        },
    ) {
        val problem = pages.players.problem
        val page = pages.players.value
        pages.playerProblem?.let { item { ProblemNote(it) } }
        when {
            // What's online now is a current state: not shown after a failed read.
            problem != null -> item { ProblemNote(problem, pages::loadPlayers) }
            page == null -> item { Note(t("mobile.common.loading")) }
            else -> playersPage(vm, pages, page, canManage, canOp, press)
        }
    }
}

private fun LazyListScope.playersPage(
    vm: AppViewModel,
    pages: ServerPages,
    page: PlayersPage,
    canManage: Boolean,
    canOp: Boolean,
    press: (String, String) -> Unit,
) {
    val busy = pages.playerBusy
    item { SectionTitle(Display.onlineNow(vm.strings, page.onlineCount, page.maxPlayers)) }
    if (canManage && page.running == false) item { Note(t("players.start_first"), color = LocalColors.current.text3) }
    if (page.onlineCount == null) {
        item { Note(t("overview.players_unknown_hint")) }
    } else if (page.online.isEmpty()) {
        item { Card { Item(t("players.nobody")) } }
    }
    if (page.onlineCount != null) {
        items(page.online) { player ->
            Card {
                val bedrock = if (player.edition == "bedrock") " · " + t("players.bedrock") else ""
                Item(player.username, subtitle = t("players.col_session") + ": " + Display.playingFor(vm.strings, player) + bedrock)
                Buttons(PlayerButtons.forPlayer(player.username, true, page, canManage, canOp), player.username, busy, press)
            }
        }
    }

    val recent = pages.recentActions()
    if (recent.isNotEmpty()) {
        item { SectionTitle(t("players.recent_actions")) }
        item {
            Card {
                for (action in recent) {
                    val state = Display.actionState(action.state)
                    Item(
                        t("players.do_${action.kind}") + " · " + action.name,
                        subtitle = listOfNotNull(t(state.key), action.message).joinToString(" · "),
                        trailing = { Text(t(state.key), color = LocalColors.current.tone(state.tone)) },
                    )
                }
            }
        }
    }

    if (canManage) item { AddByName(page, canOp, busy, press) }

    page.lists?.let { lists ->
        listCard("players.whitelist", "players.whitelist_empty", lists.whitelist, "whitelist", canManage, busy, press)
        listCard("players.ops", "players.ops_empty", lists.ops, "ops", canManage && canOp, busy, press)
        listCard("players.banned", "players.banned_empty", lists.banned, "banned", canManage, busy, press)
        item { Note(t("players.whitelist_note"), color = LocalColors.current.text3) }
    }

    item { SectionTitle(t("players.everyone")) }
    if (page.known.isEmpty()) item { Card { Item(t("players.none"), subtitle = t("players.none_hint")) } }
    items(page.known) { known ->
        val now = rememberNow()
        Card {
            val tags = PlayerButtons.tags(known.username, page).map { t(it) }
            val seen = t("players.col_last") + ": " + Display.ago(vm.strings, known.lastSeen, now)
            Item(known.username, subtitle = (listOf(seen) + tags).joinToString(" · "))
            val online = page.online.any { it.username.equals(known.username, ignoreCase = true) }
            Buttons(PlayerButtons.forPlayer(known.username, online, page, canManage, canOp), known.username, busy, press)
        }
    }
    item { Note(t("players.no_ip"), color = LocalColors.current.text3) }
}

/** One of Minecraft's lists, with Remove on each name for someone allowed. */
private fun LazyListScope.listCard(
    titleKey: String,
    emptyKey: String,
    list: PlayerList?,
    kind: String,
    canRemove: Boolean,
    busy: String?,
    press: (String, String) -> Unit,
) {
    item { SectionTitle(t(titleKey)) }
    item {
        val colors = LocalColors.current
        Card {
            val players = list?.players
            when {
                players == null -> Item(list?.reason ?: t("value.unknown"))
                players.isEmpty() -> Item(t(emptyKey))
                else -> players.forEach { entry ->
                    val name = entry.name
                    val reason = entry.reason?.takeIf { kind == "banned" && it.isNotBlank() }
                    if (name == null) {
                        // Bedrock: an operator known only by Xbox number.
                        Item(entry.uuid ?: t("value.unknown"), subtitle = t("players.xuid_only"))
                    } else {
                        val action = PlayerButtons.removeFrom(kind)
                        Item(
                            name,
                            subtitle = reason?.let { t("players.col_reason") + ": " + it },
                            trailing = {
                                if (canRemove) {
                                    TextButton(onClick = { press(action, name) }, enabled = busy == null) {
                                        Text(t("players.do_$action"), color = colors.accentInk)
                                    }
                                }
                            },
                        )
                    }
                }
            }
            list?.file?.let { Note(t("players.from_file", "file" to it), color = colors.text3) }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Buttons(actions: List<String>, name: String, busy: String?, press: (String, String) -> Unit) {
    if (actions.isEmpty()) return
    val colors = LocalColors.current
    FlowRow(
        Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, bottom = 10.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        for (action in actions) {
            val danger = action == PlayerActions.KICK || action == PlayerActions.BAN
            OutlinedButton(
                onClick = { press(action, name) },
                enabled = busy == null,
                colors = ButtonDefaults.outlinedButtonColors(contentColor = if (danger) colors.danger else colors.accentInk),
            ) { Text(t(if (busy == "$action:$name") "players.sending" else "players.do_$action")) }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun AddByName(page: PlayersPage, canOp: Boolean, busy: String?, press: (String, String) -> Unit) {
    val colors = LocalColors.current
    var name by rememberSaveable { mutableStateOf("") }
    val typed = name.trim()
    val bad = typed.isNotEmpty() && !PlayerButtons.validName(typed, page.edition)
    Column {
        SectionTitle(t("players.add_title"))
        Card {
            OutlinedTextField(
                value = name,
                onValueChange = { name = it.take(32) },
                label = { Text(t("players.add_name")) },
                singleLine = true,
                isError = bad,
                supportingText = {
                    Text(
                        if (!bad) t("players.add_hint")
                        else t(if (page.edition == "bedrock") "players.bad_gamertag" else "players.bad_name"),
                    )
                },
                modifier = Modifier.fillMaxWidth().padding(16.dp),
            )
            val actions = listOfNotNull(
                PlayerActions.WHITELIST_ADD,
                PlayerActions.OP.takeIf { canOp && page.edition != "bedrock" },
                PlayerActions.BAN.takeIf { page.bans != false },
            )
            FlowRow(
                Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, bottom = 12.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                for (action in actions) {
                    OutlinedButton(
                        onClick = {
                            press(action, typed)
                            if (action !in PlayerActions.CONFIRM) name = ""
                        },
                        enabled = busy == null && typed.isNotEmpty() && !bad,
                        colors = ButtonDefaults.outlinedButtonColors(
                            contentColor = if (action == PlayerActions.BAN) colors.danger else colors.accentInk,
                        ),
                    ) { Text(t("players.do_$action")) }
                }
            }
            if (page.edition == "bedrock" && canOp) Note(t("players.bedrock_op_online"), color = colors.text3)
        }
    }
}

/** Kick or ban: asks first, with an optional reason the player sees. */
@Composable
private fun AskWithReason(ask: Asking, onDismiss: () -> Unit, onConfirm: (String) -> Unit) {
    val colors = LocalColors.current
    var reason by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(t("players.${ask.action}_title", "name" to ask.name)) },
        text = {
            Column {
                Text(t("players.${ask.action}_body", "name" to ask.name))
                OutlinedTextField(
                    value = reason,
                    onValueChange = { reason = it.take(PlayerButtons.REASON_LENGTH) },
                    label = { Text(t("players.reason")) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
                )
            }
        },
        confirmButton = {
            TextButton(
                onClick = { onConfirm(reason) },
                colors = ButtonDefaults.textButtonColors(contentColor = colors.danger),
            ) { Text(t("players.do_${ask.action}")) }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text(t("mobile.common.cancel")) } },
        containerColor = colors.float,
        titleContentColor = colors.text,
        textContentColor = colors.text2,
    )
}
