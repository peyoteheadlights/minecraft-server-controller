package io.github.peyoteheadlights.mcsc.widget

import android.content.Context
import android.content.Intent
import androidx.core.content.pm.ShortcutInfoCompat
import androidx.core.content.pm.ShortcutManagerCompat
import androidx.core.graphics.drawable.IconCompat
import androidx.glance.appwidget.updateAll
import io.github.peyoteheadlights.mcsc.MainActivity
import io.github.peyoteheadlights.mcsc.R
import io.github.peyoteheadlights.mcsc.core.ServerRow

object Widgets {
    suspend fun refresh(context: Context) {
        ServerWidget().updateAll(context)
    }

    /**
     * Long-pressing the app icon lists the servers. Each opens that
     * server's screen, where Stop and Restart still ask first.
     */
    fun shortcuts(context: Context, servers: List<ServerRow>) {
        val max = ShortcutManagerCompat.getMaxShortcutCountPerActivity(context).coerceAtMost(4)
        val list = servers.take(max).map { row ->
            ShortcutInfoCompat.Builder(context, "server-${row.id}")
                .setShortLabel(row.name.take(25))
                .setLongLabel(row.name)
                .setIcon(IconCompat.createWithResource(context, R.drawable.ic_shortcut_server))
                .setIntent(
                    Intent(context, MainActivity::class.java)
                        .setAction(Intent.ACTION_VIEW)
                        .putExtra(MainActivity.EXTRA_SERVER, row.id),
                )
                .build()
        }
        ShortcutManagerCompat.setDynamicShortcuts(context, list)
    }
}
