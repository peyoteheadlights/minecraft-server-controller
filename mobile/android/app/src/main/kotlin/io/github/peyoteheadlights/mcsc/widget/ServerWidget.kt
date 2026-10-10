package io.github.peyoteheadlights.mcsc.widget

import android.content.Context
import androidx.compose.runtime.Composable
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.glance.GlanceId
import androidx.glance.GlanceModifier
import androidx.glance.GlanceTheme
import androidx.glance.action.actionStartActivity
import androidx.glance.action.clickable
import androidx.glance.appwidget.GlanceAppWidget
import androidx.glance.appwidget.GlanceAppWidgetReceiver
import androidx.glance.appwidget.cornerRadius
import androidx.glance.appwidget.provideContent
import androidx.glance.background
import androidx.glance.layout.Column
import androidx.glance.layout.Row
import androidx.glance.layout.Spacer
import androidx.glance.layout.fillMaxSize
import androidx.glance.layout.fillMaxWidth
import androidx.glance.layout.height
import androidx.glance.layout.padding
import androidx.glance.layout.width
import androidx.glance.text.FontWeight
import androidx.glance.text.Text
import androidx.glance.text.TextStyle
import io.github.peyoteheadlights.mcsc.MainActivity
import io.github.peyoteheadlights.mcsc.core.Display
import io.github.peyoteheadlights.mcsc.core.Strings
import io.github.peyoteheadlights.mcsc.core.WidgetSnapshot
import io.github.peyoteheadlights.mcsc.graph
import io.github.peyoteheadlights.mcsc.ui.now

/** The home-screen widget: each server's state and players, from the last
 * background read. Anything not read recently shows as Unknown. */
class ServerWidget : GlanceAppWidget() {
    override suspend fun provideGlance(context: Context, id: GlanceId) {
        val graph = context.graph
        val paired = graph.prefs.pairing != null && graph.vault.token() != null
        val snapshot = graph.widget.read()
        val strings = graph.strings
        provideContent {
            GlanceTheme {
                Body(paired, snapshot, strings, now())
            }
        }
    }
}

@Composable
private fun Body(paired: Boolean, snapshot: WidgetSnapshot?, strings: Strings, now: Double) {
    val primary = TextStyle(color = GlanceTheme.colors.onSurface, fontSize = 14.sp, fontWeight = FontWeight.Medium)
    val secondary = TextStyle(color = GlanceTheme.colors.onSurfaceVariant, fontSize = 12.sp)
    Column(
        GlanceModifier
            .fillMaxSize()
            .background(GlanceTheme.colors.widgetBackground)
            .cornerRadius(16.dp)
            .padding(12.dp)
            .clickable(actionStartActivity<MainActivity>()),
    ) {
        if (!paired || snapshot == null) {
            Text(strings.t("mobile.widget.not_paired"), style = secondary)
            return@Column
        }
        val shown = snapshot.shown(now)
        if (!snapshot.reached) Text(strings.t("mobile.widget.unreachable"), style = primary)
        for (server in shown.servers.take(4)) {
            Row(GlanceModifier.fillMaxWidth().padding(vertical = 3.dp)) {
                Text(server.name, style = primary, maxLines = 1, modifier = GlanceModifier.defaultWeight())
                Spacer(GlanceModifier.width(8.dp))
                Text(strings.t(Display.state(server.state).key), style = secondary, maxLines = 1)
            }
            if (server.state == "ONLINE") {
                Text(
                    strings.t("servers.players") + ": " + Display.players(strings, server.playersOnline, server.maxPlayers),
                    style = secondary,
                )
            }
        }
        Spacer(GlanceModifier.height(4.dp))
        Text(strings.t("mobile.widget.checked", "when" to Display.ago(strings, snapshot.checkedAt, now)), style = secondary)
    }
}

class ServerWidgetReceiver : GlanceAppWidgetReceiver() {
    override val glanceAppWidget: GlanceAppWidget = ServerWidget()
}
