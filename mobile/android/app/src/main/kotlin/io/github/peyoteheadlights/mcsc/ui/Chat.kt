package io.github.peyoteheadlights.mcsc.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import io.github.peyoteheadlights.mcsc.core.ChatBuffer
import io.github.peyoteheadlights.mcsc.core.ChatMessage
import io.github.peyoteheadlights.mcsc.core.Display
import io.github.peyoteheadlights.mcsc.core.Permissions

/** What players say in the game, live, and a box to answer as Server
 * (for anyone allowed to chat, helpers included). */
@Composable
fun ChatScreen(vm: AppViewModel, serverId: String, onBack: () -> Unit) {
    val pages = vm.pages(serverId)
    val canSend = vm.canDo(Permissions.CHAT_SEND)
    var text by remember { mutableStateOf("") }
    LaunchedEffect(serverId) { pages.loadChat() }
    val messages = pages.chat.value
    val list = rememberLazyListState()
    val header = if (pages.chat.problem != null) 1 else 0
    LaunchedEffect(messages?.lastOrNull()) {
        if (!messages.isNullOrEmpty()) list.scrollToItem(header + messages.size - 1)
    }

    ServerFrame(
        vm, serverId,
        title = t("page.chat"),
        onBack = onBack,
        refreshing = false,
        onRefresh = pages::loadChat,
        listState = list,
        bottomBar = {
            if (canSend) {
                ChatBox(
                    text = text,
                    onChange = { if (it.length <= ChatBuffer.MAX_LENGTH) text = it },
                    busy = pages.chatSending,
                    problem = pages.chatProblem,
                    offline = pages.chatRunning == false,
                    onSend = { pages.sendChat(text) { text = "" } },
                )
            }
        },
    ) {
        val problem = pages.chat.problem
        when {
            problem != null -> item { ProblemNote(problem, pages::loadChat) }
            messages == null -> item { Note(t("mobile.common.loading")) }
            messages.isEmpty() -> item { Card { Item(t("chat.empty"), subtitle = t("chat.empty_hint")) } }
        }
        items(messages.orEmpty()) { message -> ChatLine(message) }
    }
}

@Composable
private fun ChatLine(message: ChatMessage) {
    val colors = LocalColors.current
    val who = if (message.kind == "server") t("chat.server") else message.name.orEmpty()
    val words = if (message.kind == "action") "• ${message.text}" else message.text
    Text(
        buildAnnotatedString {
            withStyle(SpanStyle(color = colors.text3)) { append(Display.clock(message.ts)) }
            append("  ")
            withStyle(SpanStyle(fontWeight = FontWeight.SemiBold, color = if (message.kind == "server") colors.accentInk else colors.text)) {
                append(who)
            }
            append("  ")
            append(words)
        },
        style = MaterialTheme.typography.bodyMedium,
        color = colors.text,
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 2.dp),
    )
}

@Composable
private fun ChatBox(
    text: String,
    onChange: (String) -> Unit,
    busy: Boolean,
    problem: Message?,
    offline: Boolean,
    onSend: () -> Unit,
) {
    val colors = LocalColors.current
    Surface(color = colors.surface) {
        Column(Modifier.navigationBarsPadding().imePadding().padding(vertical = 6.dp)) {
            problem?.let { Note(it.text(), color = colors.danger) }
            if (offline) Note(t("chat.offline"), color = colors.text3)
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp),
            ) {
                OutlinedTextField(
                    value = text,
                    onValueChange = onChange,
                    placeholder = { Text(t("chat.placeholder")) },
                    label = { Text(t("chat.input_label")) },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                    keyboardActions = KeyboardActions(onSend = { if (!busy) onSend() }),
                    modifier = Modifier.weight(1f),
                )
                Button(
                    onClick = onSend,
                    enabled = !busy && text.isNotBlank(),
                    modifier = Modifier.padding(start = 8.dp),
                ) { Text(t("chat.send")) }
            }
            Note(t("chat.hint"), color = colors.text3)
        }
    }
}
