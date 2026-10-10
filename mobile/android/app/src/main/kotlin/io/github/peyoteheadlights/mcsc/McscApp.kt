package io.github.peyoteheadlights.mcsc

import android.app.Application
import android.content.Context
import io.github.peyoteheadlights.mcsc.push.Alerts
import io.github.peyoteheadlights.mcsc.widget.RefreshWorker

class McscApp : Application() {
    lateinit var graph: AppGraph
        private set

    override fun onCreate() {
        super.onCreate()
        graph = AppGraph(this)
        Alerts.createChannel(this)
        RefreshWorker.schedule(this)
    }
}

/** Everything the app keeps, shared by its screens, the widget and alerts. */
val Context.graph: AppGraph
    get() = (applicationContext as McscApp).graph
