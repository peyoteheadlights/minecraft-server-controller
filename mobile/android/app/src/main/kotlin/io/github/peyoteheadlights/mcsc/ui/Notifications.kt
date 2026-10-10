package io.github.peyoteheadlights.mcsc.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import io.github.peyoteheadlights.mcsc.core.AppAlert
import io.github.peyoteheadlights.mcsc.core.Display

/**
 * The alerts the PC sent since this phone signed in, newest first: the
 * same ones as Discord, email and the lock screen, kept whether or not
 * any of those is on. New ones are marked until the tab is next opened.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun NotificationsScreen(vm: AppViewModel, onOpenServer: (String) -> Unit) {
    val colors = LocalColors.current
    val now = rememberNow()
    // What was new when the tab opened stays marked while it is open.
    val newAbove = remember { vm.alerts.readUpTo }
    LaunchedEffect(Unit) {
        vm.catchUpAlerts()
        vm.markAllRead()
    }
    val list = vm.alerts.newestFirst
    val names = vm.servers.list.associate { it.id to it.name }
    Scaffold(
        containerColor = colors.sheet,
        topBar = {
            Bar(t("mobile.alerts.title"), actions = {
                if (vm.alerts.unread > 0) {
                    TextButton(onClick = { vm.markAllRead() }) { Text(t("mobile.alerts.mark_read")) }
                }
            })
        },
    ) { padding ->
        PullToRefreshBox(
            isRefreshing = false,
            onRefresh = { vm.catchUpAlerts() },
            modifier = Modifier.padding(padding).fillMaxSize(),
        ) {
            LazyColumn(contentPadding = ScreenPadding, verticalArrangement = Gap, modifier = Modifier.fillMaxSize()) {
                if (list.isEmpty()) {
                    item { Note(t("mobile.alerts.empty")) }
                    item { Note(t("mobile.alerts.empty_hint"), color = colors.text3) }
                }
                items(list, key = { it.id }) { alert ->
                    AlertRow(alert, isNew = alert.id > newAbove, server = alert.serverId?.let { names[it] ?: it }, now = now) {
                        alert.serverId?.let(onOpenServer)
                    }
                }
            }
        }
    }
}

@Composable
private fun AlertRow(alert: AppAlert, isNew: Boolean, server: String?, now: Double, onClick: () -> Unit) {
    val colors = LocalColors.current
    val strings = LocalStrings.current
    val subtitle = listOfNotNull(
        alert.body.takeIf { it.isNotBlank() },
        (server ?: t("mobile.alerts.pc")) + " · " + Display.ago(strings, alert.ts, now),
    ).joinToString("\n")
    Card {
        Item(
            title = alert.title,
            subtitle = subtitle,
            onClick = if (alert.serverId != null) onClick else null,
            leading = {
                Box(Modifier.size(10.dp).background(if (isNew) colors.accent else colors.sheet, CircleShape))
            },
        )
    }
}
