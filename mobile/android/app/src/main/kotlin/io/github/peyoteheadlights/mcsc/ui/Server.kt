package io.github.peyoteheadlights.mcsc.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import io.github.peyoteheadlights.mcsc.core.Display
import io.github.peyoteheadlights.mcsc.core.QuickAction
import io.github.peyoteheadlights.mcsc.core.States

/** One server, in its own color: what it's doing, who's playing, and
 * Start, Stop and Restart (the last two ask first). */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ServerScreen(vm: AppViewModel, serverId: String, onBack: () -> Unit) {
    DisposableEffect(serverId) {
        vm.watch(serverId)
        onDispose { vm.watch(null) }
    }
    val row = vm.servers.list.firstOrNull { it.id == serverId }
    val ui = vm.server[serverId] ?: ServerUi()
    val status = ui.status
    // Not current after a failed read: Unknown, with when it was last read.
    val state = if (ui.problem != null) States.UNKNOWN else status?.state ?: row?.state
    val now = rememberNow()
    var asking by rememberSaveable { mutableStateOf<String?>(null) }

    McscTheme(vm.shared, themeName(vm.theme), serverColor = row?.color) {
        val colors = LocalColors.current
        Scaffold(containerColor = colors.sheet, topBar = { Bar(row?.name ?: status?.name ?: serverId, onBack) }) { padding ->
            PullToRefreshBox(
                isRefreshing = false,
                onRefresh = { vm.refreshServer(serverId) },
                modifier = Modifier.padding(padding).fillMaxSize(),
            ) {
                LazyColumn(contentPadding = ScreenPadding, verticalArrangement = Gap, modifier = Modifier.fillMaxSize()) {
                    item {
                        Card(Modifier.padding(top = 8.dp)) {
                            Item(t(Display.state(state).key), subtitle = Display.uptime(vm.strings, state, status?.uptime))
                            if (state == States.RESTART_PENDING) Note(t("mobile.server.restart_pending"))
                            listOfNotNull(status?.serverTypeName ?: row?.typeName, status?.minecraftVersion ?: row?.minecraftVersion)
                                .joinToString(" ").takeIf { it.isNotBlank() }
                                ?.let { Note(it, color = colors.text2) }
                            Actions(
                                Display.actions(state, vm.canControl()),
                                busy = ui.busyAction,
                                onAction = { action -> if (action.confirm) asking = action.action else vm.act(serverId, action.action) },
                            )
                            if (vm.me != null && !vm.canControl()) Note(t("mobile.server.not_allowed"), color = colors.text3)
                        }
                    }
                    ui.done?.let { done ->
                        item {
                            Note(
                                done.text(),
                                color = colors.success,
                                modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite },
                            )
                        }
                    }
                    ui.problem?.let { problem -> item { ProblemNote(problem, onRetry = { vm.refreshServer(serverId) }) } }
                    item { SectionTitle(t("mobile.server.players_now")) }
                    item { Players(vm, state, status) }
                    if (status != null) {
                        items(if (ui.problem == null && state == States.ONLINE) status.players else emptyList(), key = { it.username }) { player ->
                            Card {
                                Item(
                                    player.username,
                                    subtitle = player.sessionSeconds?.let {
                                        t("mobile.server.player_since", "duration" to Display.duration(vm.strings, it))
                                    },
                                )
                            }
                        }
                    }
                    ui.checkedAt?.let { at ->
                        item { Note(t("mobile.servers.checked", "when" to Display.ago(vm.strings, at, now))) }
                    }
                }
            }
        }
        asking?.let { action ->
            Confirm(
                title = t("confirm.${action}_title"),
                body = t("confirm.${action}_body"),
                confirm = t("action.$action"),
                danger = action == "stop",
                onConfirm = {
                    asking = null
                    vm.act(serverId, action)
                },
                onDismiss = { asking = null },
            )
        }
    }
}

@Composable
private fun Players(vm: AppViewModel, state: String?, status: io.github.peyoteheadlights.mcsc.core.ServerStatus?) {
    val text = when {
        state != States.ONLINE -> null
        status?.playersOnline == null -> t("overview.players_unknown")
        status.playersOnline == 0 -> t("mobile.server.nobody")
        else -> vm.strings.tn("head.players", status.playersOnline ?: 0)
    }
    if (text != null) Note(text)
}

@Composable
private fun Actions(actions: List<QuickAction>, busy: String?, onAction: (QuickAction) -> Unit) {
    if (actions.isEmpty()) return
    val colors = LocalColors.current
    Row(
        Modifier.fillMaxWidth().padding(16.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        for (action in actions) {
            val label = t(action.labelKey)
            val modifier = Modifier.weight(1f).height(48.dp)
            if (action.danger) {
                OutlinedButton(
                    onClick = { onAction(action) },
                    enabled = busy == null,
                    modifier = modifier,
                    colors = ButtonDefaults.outlinedButtonColors(contentColor = colors.danger),
                ) { Text(label, style = MaterialTheme.typography.labelLarge) }
            } else {
                Button(onClick = { onAction(action) }, enabled = busy == null, modifier = modifier) {
                    Text(label, style = MaterialTheme.typography.labelLarge)
                }
            }
        }
    }
}
