package io.github.peyoteheadlights.mcsc.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import io.github.peyoteheadlights.mcsc.core.Display
import io.github.peyoteheadlights.mcsc.core.ServerRow
import io.github.peyoteheadlights.mcsc.core.States

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ServersScreen(vm: AppViewModel, onOpen: (String) -> Unit) {
    val ui = vm.servers
    val colors = LocalColors.current
    val now = rememberNow()
    Scaffold(
        containerColor = colors.sheet,
        topBar = {
            Bar(t("mobile.servers.title"), actions = {
                if (vm.live) {
                    Text(t("mobile.servers.live"), color = colors.success, modifier = Modifier.padding(end = 16.dp))
                }
            })
        },
    ) { padding ->
        PullToRefreshBox(
            isRefreshing = ui.refreshing,
            onRefresh = { vm.refreshAll() },
            modifier = Modifier.padding(padding).fillMaxSize(),
        ) {
            LazyColumn(contentPadding = ScreenPadding, verticalArrangement = Gap, modifier = Modifier.fillMaxSize()) {
                ui.problem?.let { problem -> item { ProblemNote(problem, onRetry = { vm.refreshServers() }) } }
                if (ui.loaded && ui.list.isEmpty()) {
                    item {
                        Note(t(if (vm.me?.isOwner == false) "mobile.servers.helper_none" else "servers.none"))
                    }
                }
                items(ui.list, key = { it.id }) { row ->
                    // Read before the last failed attempt: not current, so not shown as if it were.
                    ServerCard(if (ui.problem != null) row.copy(state = States.UNKNOWN, playersOnline = null) else row) {
                        onOpen(row.id)
                    }
                }
                ui.checkedAt?.let { at ->
                    item { Note(t("mobile.servers.checked", "when" to Display.ago(vm.strings, at, now))) }
                }
                if (ui.loaded) item { Note(t("mobile.servers.more_on_pc"), color = colors.text3) }
            }
        }
    }
}

@Composable
private fun ServerCard(row: ServerRow, onClick: () -> Unit) {
    val colors = LocalColors.current
    Card {
        Item(
            title = row.name,
            subtitle = listOfNotNull(row.typeName, row.minecraftVersion).joinToString(" ").ifBlank { null },
            onClick = onClick,
            leading = { ServerDot(row.color) },
        )
        Row(
            Modifier.fillMaxWidth().padding(start = 42.dp, end = 16.dp, bottom = 14.dp),
            horizontalArrangement = Arrangement.spacedBy(16.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            StateText(row.state)
            if (row.state == States.ONLINE) {
                Text(
                    t("servers.players") + ": " + Display.players(LocalStrings.current, row.playersOnline, row.maxPlayers),
                    color = colors.text2,
                    style = MaterialTheme.typography.bodyMedium,
                )
            }
        }
    }
}

