package io.github.peyoteheadlights.mcsc.ui

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.History
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SmallFloatingActionButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import io.github.peyoteheadlights.mcsc.core.ConsoleBuffer
import io.github.peyoteheadlights.mcsc.core.ConsoleCommands
import io.github.peyoteheadlights.mcsc.core.LevelChip
import io.github.peyoteheadlights.mcsc.core.LineLook
import io.github.peyoteheadlights.mcsc.core.Permissions

/**
 * The server's console: the newest lines, live, with a filter and level
 * chips. The owner gets a command box (commands go to Minecraft only,
 * never Windows; risky ones ask first) and Clear. Helpers read only.
 */
@Composable
fun ConsoleScreen(vm: AppViewModel, serverId: String, onBack: () -> Unit) {
    val pages = vm.pages(serverId)
    val canSend = vm.canDo(Permissions.CONSOLE_SEND)
    var filter by rememberSaveable { mutableStateOf("") }
    var chip by rememberSaveable { mutableStateOf(LevelChip.ALL) }
    // The typed command and the Up history stay in memory only.
    var command by remember { mutableStateOf("") }
    var back by remember { mutableIntStateOf(0) }
    val sent: () -> Unit = {
        command = ""
        back = 0
    }
    LaunchedEffect(serverId) { pages.loadConsole() }

    val all = pages.console.value
    val lines = ConsoleBuffer.shown(all.orEmpty(), filter, chip)
    val list = rememberLazyListState()
    var following by remember { mutableStateOf(true) }
    val atBottom by remember {
        derivedStateOf {
            val info = list.layoutInfo
            val last = info.visibleItemsInfo.lastOrNull()
            last == null || last.index >= info.totalItemsCount - 1
        }
    }
    // Scrolling up stops following; reaching the bottom starts it again.
    LaunchedEffect(list) {
        snapshotFlow { list.isScrollInProgress && list.lastScrolledBackward }.collect { if (it) following = false }
    }
    LaunchedEffect(list) {
        snapshotFlow { atBottom }.collect { if (it) following = true }
    }
    // The filter row, and a problem note when there is one, come before the lines.
    val header = if (pages.console.problem != null) 2 else 1
    LaunchedEffect(lines.lastOrNull(), following) {
        if (following && lines.isNotEmpty()) list.scrollToItem(header + lines.size - 1)
    }

    ServerFrame(
        vm, serverId,
        title = t("page.console"),
        onBack = onBack,
        refreshing = false,
        onRefresh = pages::loadConsole,
        listState = list,
        actions = {
            if (canSend) TextButton(onClick = pages::clearConsole) { Text(t("console.clear")) }
        },
        bottomBar = {
            if (canSend) {
                CommandBox(
                    command = command,
                    onChange = { if (it.length <= ConsoleCommands.MAX_LENGTH) command = it },
                    busy = pages.sending,
                    problem = pages.commandProblem,
                    hasHistory = pages.history.isNotEmpty(),
                    onPrevious = {
                        val history = pages.history
                        if (history.isNotEmpty()) {
                            back = (back + 1).coerceAtMost(history.size)
                            command = history[history.size - back]
                        }
                    },
                    onSend = { pages.submitCommand(command, sent) },
                )
            } else {
                Surface(color = LocalColors.current.surface) {
                    Note(t("mobile.console.owner_only"), modifier = Modifier.navigationBarsPadding().padding(vertical = 8.dp))
                }
            }
        },
        overlay = {
            if (!following && lines.isNotEmpty()) {
                SmallFloatingActionButton(
                    onClick = { following = true },
                    modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 16.dp),
                    containerColor = LocalColors.current.float,
                    contentColor = LocalColors.current.accentInk,
                ) { Text(t("mobile.console.jump"), modifier = Modifier.padding(horizontal = 14.dp)) }
            }
            pages.asking?.let { step ->
                Confirm(
                    title = t("console.run_title", "command" to step.command),
                    body = step.reason,
                    confirm = t("console.run"),
                    danger = true,
                    onConfirm = { pages.confirmCommand(sent) },
                    onDismiss = pages::cancelCommand,
                )
            }
        },
    ) {
        item {
            Column {
                OutlinedTextField(
                    value = filter,
                    onValueChange = { filter = it },
                    label = { Text(t("console.filter_label")) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp),
                )
                Row(
                    Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    for (option in LevelChip.entries) {
                        FilterChip(selected = chip == option, onClick = { chip = option }, label = { Text(t(option.key)) })
                    }
                }
            }
        }
        val problem = pages.console.problem
        when {
            problem != null -> item { ProblemNote(problem, pages::loadConsole) }
            all == null -> item { Note(t("mobile.common.loading")) }
            all.isEmpty() -> item { Card { Item(t("console.empty"), subtitle = t("console.empty_hint")) } }
            lines.isEmpty() -> item {
                Card { Item(t("console.no_match"), subtitle = t("console.no_match_hint", "filter" to filter.trim())) }
            }
        }
        items(lines) { line ->
            val colors = LocalColors.current
            Text(
                line.raw,
                fontFamily = FontFamily.Monospace,
                style = MaterialTheme.typography.bodySmall,
                color = when (ConsoleBuffer.look(line)) {
                    LineLook.WARNING -> colors.warning
                    LineLook.DANGER -> colors.danger
                    LineLook.COMMAND -> colors.accentInk
                    LineLook.PLAIN -> colors.text
                },
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp),
            )
        }
    }
}

@Composable
private fun CommandBox(
    command: String,
    onChange: (String) -> Unit,
    busy: Boolean,
    problem: Message?,
    hasHistory: Boolean,
    onPrevious: () -> Unit,
    onSend: () -> Unit,
) {
    val colors = LocalColors.current
    Surface(color = colors.surface) {
        Column(Modifier.navigationBarsPadding().imePadding().padding(vertical = 6.dp)) {
            problem?.let { Note(it.text(), color = colors.danger) }
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.fillMaxWidth().padding(horizontal = 8.dp),
            ) {
                if (hasHistory) {
                    IconButton(onClick = onPrevious) {
                        Icon(Icons.Outlined.History, contentDescription = t("mobile.console.previous"), tint = colors.text2)
                    }
                }
                OutlinedTextField(
                    value = command,
                    onValueChange = onChange,
                    placeholder = { Text(t("console.command_placeholder")) },
                    label = { Text(t("console.command_label")) },
                    singleLine = true,
                    textStyle = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace),
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send, autoCorrectEnabled = false),
                    keyboardActions = KeyboardActions(onSend = { if (!busy) onSend() }),
                    modifier = Modifier.weight(1f),
                )
                Button(
                    onClick = onSend,
                    enabled = !busy && command.isNotBlank(),
                    modifier = Modifier.padding(start = 8.dp),
                ) { Text(t(if (busy) "console.sending" else "console.send")) }
            }
            Note(t("console.hint"), color = colors.text3)
        }
    }
}
