package io.github.peyoteheadlights.mcsc.push

import android.Manifest
import android.annotation.SuppressLint
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import io.github.peyoteheadlights.mcsc.MainActivity
import io.github.peyoteheadlights.mcsc.R
import io.github.peyoteheadlights.mcsc.core.AgentException
import io.github.peyoteheadlights.mcsc.core.AlertSync
import io.github.peyoteheadlights.mcsc.core.AppAlert
import io.github.peyoteheadlights.mcsc.graph

/** Alerts on the lock screen: read from the PC, then shown by the phone. */
object Alerts {
    private const val CHANNEL = "alerts"
    private const val MAX_SHOWN = 5

    fun createChannel(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java)
        val strings = context.graph.strings
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL, strings.t("mobile.tab.notifications"), NotificationManager.IMPORTANCE_HIGH),
        )
    }

    /**
     * Woken by a push: catch the Notifications tab up from the PC and show
     * what's new. If the PC can't be reached (this phone off Tailscale,
     * say) a plain "New alert" is shown, with no guess at what it was.
     */
    suspend fun check(context: Context) {
        val graph = context.graph
        val client = graph.client() ?: return
        if (graph.vault.token() == null) return
        val fresh: List<AppAlert> = try {
            val next = AlertSync { after, limit -> client.alerts(after, limit) }.catchUp(graph.alerts.read())
            graph.alerts.write(next)
            next.alerts.filter { it.id > graph.prefs.notifiedUpTo }
        } catch (e: AgentException) {
            graph.prefs.lastProblem = e.key
            show(context, 0, graph.strings.t("mobile.alerts.new"), graph.strings.t("mobile.alerts.open_to_read"), null)
            return
        }
        for (alert in fresh.takeLast(MAX_SHOWN)) show(context, alert.id.toInt(), alert.title, alert.body, alert.serverId)
        fresh.maxOfOrNull { it.id }?.let { graph.prefs.notifiedUpTo = it }
    }

    @SuppressLint("MissingPermission") // checked just below
    private fun show(context: Context, id: Int, title: String, body: String, serverId: String?) {
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            return
        }
        val strings = context.graph.strings
        val open = Intent(context, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            .apply { if (serverId != null) putExtra(MainActivity.EXTRA_SERVER, serverId) }
        val tap = PendingIntent.getActivity(
            context,
            id,
            open,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        // On a locked screen only "New alert" shows until the phone is unlocked.
        val public = NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(strings.t("mobile.alerts.new"))
            .build()
        val notification = NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(title)
            .setContentText(body.ifBlank { null })
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_STATUS)
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
            .setPublicVersion(public)
            .setContentIntent(tap)
            .setAutoCancel(true)
            .build()
        NotificationManagerCompat.from(context).notify(id, notification)
    }
}
