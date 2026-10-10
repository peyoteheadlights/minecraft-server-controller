package io.github.peyoteheadlights.mcsc.ui

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
            composable("servers") { ServersScreen(vm, onOpen = { nav.navigate("server/${android.net.Uri.encode(it)}") }) }
            composable("server/{id}") { back ->
                val id = back.arguments?.getString("id").orEmpty()
                ServerScreen(vm, id, onBack = { nav.popBackStack() })
            }
            composable("alerts") {
                NotificationsScreen(vm, onOpenServer = { nav.navigate("server/${android.net.Uri.encode(it)}") })
            }
            composable("settings") { SettingsScreen(vm, onAbout = { nav.navigate("about") }) }
            composable("about") { AboutScreen(vm, onBack = { nav.popBackStack() }, onHelp = { nav.navigate("help") }) }
            composable("help") { HelpScreen(onBack = { nav.popBackStack() }) }
        }
    }
}

private fun open(nav: NavHostController, route: String) {
    nav.navigate(route) {
        popUpTo(nav.graph.findStartDestination().id) { saveState = true }
        launchSingleTop = true
        restoreState = true
    }
}
