package io.github.peyoteheadlights.mcsc.ui

import android.net.Uri
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Dns
import androidx.compose.material.icons.outlined.Notifications
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.navigation.NavBackStackEntry
import androidx.navigation.NavDestination.Companion.hierarchy
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController

private data class Tab(val route: String, val key: String, val icon: ImageVector)

private val TABS = listOf(
    Tab("servers", "mobile.tab.servers", Icons.Outlined.Dns),
    Tab("alerts", "mobile.tab.notifications", Icons.Outlined.Notifications),
    Tab("settings", "mobile.tab.settings", Icons.Outlined.Settings),
)

/** The signed-in app: Servers, Notifications and Settings. */
@Composable
fun Main(vm: AppViewModel) {
    val nav = rememberNavController()
    val entry by nav.currentBackStackEntryAsState()
    val colors = LocalColors.current

    LaunchedEffect(vm.pendingServer) {
        val id = vm.pendingServer ?: return@LaunchedEffect
        vm.pendingServer = null
        nav.navigate("server/${android.net.Uri.encode(id)}") { launchSingleTop = true }
    }

    Scaffold(
        containerColor = colors.sheet,
        bottomBar = {
            NavigationBar(containerColor = colors.surface) {
                for (tab in TABS) {
                    val selected = entry?.destination?.hierarchy?.any { it.route == tab.route } == true
                    NavigationBarItem(
                        selected = selected,
                        onClick = { open(nav, tab.route) },
                        label = { Text(t(tab.key)) },
                        icon = {
                            val unread = if (tab.route == "alerts") vm.alerts.unread else 0
                            BadgedBox(badge = { if (unread > 0) Badge { Text(if (unread > 99) "99+" else unread.toString()) } }) {
                                Icon(tab.icon, contentDescription = null)
                            }
                        },
                        colors = NavigationBarItemDefaults.colors(
                            selectedIconColor = colors.accentInk,
                            selectedTextColor = colors.accentInk,
                            indicatorColor = colors.accentBand,
                            unselectedIconColor = colors.text2,
                            unselectedTextColor = colors.text2,
                        ),
                    )
                }
            }
        },
    ) { padding ->
        NavHost(nav, startDestination = "servers", modifier = Modifier.padding(padding)) {
            composable("servers") {
                ServersScreen(vm, onOpen = { nav.navigate("server/${android.net.Uri.encode(it)}") }, onAdd = { nav.navigate("servers/add") })
            }
            composable("servers/add") {
                AddServerScreen(vm, onBack = { nav.popBackStack() }, onOpen = { id ->
                    // The new server opens in place of the "+" screen.
                    nav.popBackStack()
                    nav.navigate("server/${Uri.encode(id)}")
                })
            }
            composable("server/{id}") { back ->
                val id = back.arguments?.getString("id").orEmpty()
                ServerScreen(vm, id, onBack = { nav.popBackStack() }, onOpen = { page -> nav.navigate("server/${Uri.encode(id)}/$page") })
            }
            composable("server/{id}/console") { back ->
                ConsoleScreen(vm, back.serverId(), onBack = { nav.popBackStack() })
            }
            composable("server/{id}/chat") { back ->
                ChatScreen(vm, back.serverId(), onBack = { nav.popBackStack() })
            }
            composable("server/{id}/players") { back ->
                PlayersScreen(vm, back.serverId(), onBack = { nav.popBackStack() })
            }
            composable("server/{id}/performance") { back ->
                PerformanceScreen(vm, back.serverId(), onBack = { nav.popBackStack() })
            }
            composable("server/{id}/backups") { back ->
                val id = back.serverId()
                BackupsScreen(vm, id, onBack = { nav.popBackStack() }, onRestoreWorld = { nav.navigate("server/${Uri.encode(id)}/world") })
            }
            composable("server/{id}/world") { back ->
                WorldRestoreScreen(vm, back.serverId(), onBack = { nav.popBackStack() })
            }
            composable("server/{id}/schedules") { back ->
                SchedulesScreen(vm, back.serverId(), onBack = { nav.popBackStack() })
            }
            composable("server/{id}/content") { back ->
                ContentScreen(vm, back.serverId(), onBack = { nav.popBackStack() })
            }
            composable("server/{id}/game") { back ->
                GameSettingsScreen(vm, back.serverId(), onBack = { nav.popBackStack() })
            }
            composable("server/{id}/settings") { back ->
                ServerSettingsScreen(
                    vm, back.serverId(),
                    onBack = { nav.popBackStack() },
                    // The server is gone: back to All servers, not to its page.
                    onRemoved = { nav.popBackStack("servers", inclusive = false) },
                )
            }
            composable("server/{id}/events") { back ->
                EventsScreen(vm, back.serverId(), onBack = { nav.popBackStack() })
            }
            composable("server/{id}/crashes") { back ->
                val id = back.serverId()
                CrashesScreen(vm, id, onBack = { nav.popBackStack() }, onOpen = { crash -> nav.navigate("server/${Uri.encode(id)}/crashes/$crash") })
            }
            composable("server/{id}/crashes/{crash}") { back ->
                val crash = back.arguments?.getString("crash")?.toLongOrNull() ?: return@composable
                CrashScreen(vm, back.serverId(), crash, onBack = { nav.popBackStack() })
            }
            composable("alerts") {
                NotificationsScreen(vm, onOpenServer = { nav.navigate("server/${android.net.Uri.encode(it)}") })
            }
            composable("settings") {
                SettingsScreen(
                    vm,
                    onAbout = { nav.navigate("about") },
                    onAccount = { nav.navigate("settings/account") },
                    onModerators = { nav.navigate("settings/moderators") },
                    onPc = { nav.navigate("settings/pc") },
                )
            }
            composable("settings/account") { AccountScreen(vm, onBack = { nav.popBackStack() }) }
            composable("settings/pc") {
                PcSettingsScreen(
                    vm,
                    onBack = { nav.popBackStack() },
                    onDevices = { nav.navigate("settings/pc/devices") },
                    onAlerts = { nav.navigate("settings/pc/alerts") },
                )
            }
            composable("settings/pc/devices") { DevicesScreen(vm, onBack = { nav.popBackStack() }) }
            composable("settings/pc/alerts") { AlertSettingsScreen(vm, onBack = { nav.popBackStack() }) }
            composable("settings/moderators") {
                ModeratorsScreen(
                    vm,
                    onBack = { nav.popBackStack() },
                    onOpen = { nav.navigate("settings/moderators/${Uri.encode(it)}") },
                    onAdd = { nav.navigate("settings/moderators-add") },
                )
            }
            composable("settings/moderators-add") {
                AddModeratorScreen(vm, onBack = { nav.popBackStack() }, onAdded = { name ->
                    // The invite opens in place of the form; back goes to the list.
                    nav.popBackStack()
                    nav.navigate("settings/moderators/${Uri.encode(name)}/invite")
                })
            }
            composable("settings/moderators/{name}") { back ->
                val name = back.arguments?.getString("name").orEmpty()
                ModeratorScreen(
                    vm, name,
                    onBack = { nav.popBackStack() },
                    onServer = { id -> nav.navigate("settings/moderators/${Uri.encode(name)}/server/${Uri.encode(id)}") },
                    onInvite = { nav.navigate("settings/moderators/${Uri.encode(name)}/invite") },
                )
            }
            composable("settings/moderators/{name}/invite") { back ->
                InviteScreen(vm, back.arguments?.getString("name").orEmpty(), onDone = { nav.popBackStack() })
            }
            composable("settings/moderators/{name}/server/{id}") { back ->
                ModeratorServerScreen(vm, back.arguments?.getString("name").orEmpty(), back.serverId(), onBack = { nav.popBackStack() })
            }
            composable("about") { AboutScreen(vm, onBack = { nav.popBackStack() }, onHelp = { nav.navigate("help") }) }
            composable("help") { HelpScreen(onBack = { nav.popBackStack() }) }
        }
    }
}

private fun NavBackStackEntry.serverId(): String = arguments?.getString("id").orEmpty()

private fun open(nav: NavHostController, route: String) {
    nav.navigate(route) {
        popUpTo(nav.graph.findStartDestination().id) { saveState = true }
        launchSingleTop = true
        restoreState = true
    }
}
