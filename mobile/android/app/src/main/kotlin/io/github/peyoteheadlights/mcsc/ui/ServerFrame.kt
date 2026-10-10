package io.github.peyoteheadlights.mcsc.ui

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.os.Build
import android.widget.Toast
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.ContentCopy
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext

/** While a screen of [serverId] is open, the live feed carries its console and chat. */
@Composable
fun WatchServer(vm: AppViewModel, serverId: String) {
    DisposableEffect(serverId) {
        vm.watch(serverId)
        onDispose { vm.unwatch(serverId) }
    }
}

/** The server's name, as the list or its status last said, else its id. */
fun serverName(vm: AppViewModel, serverId: String): String =
    vm.servers.list.firstOrNull { it.id == serverId }?.name ?: vm.server[serverId]?.status?.name ?: serverId

/**
 * One of a server's screens: in the server's color, pull to refresh, a
 * list of [content], and an optional [bottomBar] (the Console's and Chat's
 * box).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ServerFrame(
    vm: AppViewModel,
    serverId: String,
    title: String,
    onBack: () -> Unit,
    refreshing: Boolean,
    onRefresh: () -> Unit,
    listState: LazyListState = rememberLazyListState(),
    actions: @Composable () -> Unit = {},
    bottomBar: @Composable () -> Unit = {},
    overlay: @Composable BoxScope.() -> Unit = {},
    content: LazyListScope.() -> Unit,
) {
    WatchServer(vm, serverId)
    val color = vm.servers.list.firstOrNull { it.id == serverId }?.color
    McscTheme(vm.shared, themeName(vm.theme), serverColor = color) {
        val colors = LocalColors.current
        Scaffold(
            containerColor = colors.sheet,
            topBar = { Bar(title, onBack, actions) },
            bottomBar = bottomBar,
        ) { padding ->
            PullToRefreshBox(
                isRefreshing = refreshing,
                onRefresh = onRefresh,
                modifier = Modifier.padding(padding).fillMaxSize(),
            ) {
                Box(Modifier.fillMaxSize()) {
                    LazyColumn(
                        state = listState,
                        contentPadding = ScreenPadding,
                        verticalArrangement = Gap,
                        modifier = Modifier.fillMaxSize(),
                        content = content,
                    )
                    overlay()
                }
            }
        }
    }
}

/** Copies [text]; Android 13 and later say so themselves. */
fun copyText(context: Context, text: String, said: String) {
    val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    clipboard.setPrimaryClip(ClipData.newPlainText(text, text))
    if (Build.VERSION.SDK_INT < 33) Toast.makeText(context, said, Toast.LENGTH_SHORT).show()
}

@Composable
fun CopyButton(text: String) {
    val context = LocalContext.current
    val said = t("join.copied", "text" to text)
    IconButton(onClick = { copyText(context, text, said) }) {
        Icon(Icons.Outlined.ContentCopy, contentDescription = t("join.copy_label", "text" to text), tint = LocalColors.current.accentInk)
    }
}

/** Loading, nothing yet, or what went wrong: the line a list shows when
 * it has no rows to show. Nothing when there are rows. */
fun <T> LazyListScope.emptyOrProblem(
    read: Read<List<T>>,
    emptyKey: String,
    emptyHint: String? = null,
    onRetry: () -> Unit,
) {
    read.problem?.let { problem -> item { ProblemNote(problem, onRetry) } }
    val rows = read.value
    when {
        rows == null && read.problem == null -> item { Note(t("mobile.common.loading")) }
        rows != null && rows.isEmpty() -> item {
            Card {
                Item(t(emptyKey), subtitle = emptyHint?.let { t(it) })
            }
        }
    }
}
