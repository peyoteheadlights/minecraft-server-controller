package io.github.peyoteheadlights.mcsc.widget

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import io.github.peyoteheadlights.mcsc.core.AgentException
import io.github.peyoteheadlights.mcsc.core.WidgetSnapshot
import io.github.peyoteheadlights.mcsc.graph
import io.github.peyoteheadlights.mcsc.ui.now
import java.util.concurrent.TimeUnit

/** Reads the server list for the widget every 30 minutes or so, when the
 * phone has a connection. A PC that doesn't answer leaves it Unknown. */
class RefreshWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val graph = applicationContext.graph
        val client = graph.client() ?: return Result.success()
        if (graph.vault.token() == null) return Result.success()
        val at = now()
        val snapshot = try {
            WidgetSnapshot.read(client.servers(), at)
        } catch (e: AgentException) {
            WidgetSnapshot.failed(graph.widget.read(), e, at)
        }
        graph.widget.write(snapshot)
        Widgets.refresh(applicationContext)
        return Result.success()
    }

    companion object {
        fun schedule(context: Context) {
            val request = PeriodicWorkRequestBuilder<RefreshWorker>(30, TimeUnit.MINUTES)
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build()
            WorkManager.getInstance(context)
                .enqueueUniquePeriodicWork("widget-refresh", ExistingPeriodicWorkPolicy.KEEP, request)
        }
    }
}
