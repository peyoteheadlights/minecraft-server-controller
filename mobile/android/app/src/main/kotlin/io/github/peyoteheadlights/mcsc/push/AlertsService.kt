package io.github.peyoteheadlights.mcsc.push

import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import io.github.peyoteheadlights.mcsc.core.AgentException
import io.github.peyoteheadlights.mcsc.graph
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeoutOrNull

/** Receives the agent's wake-ups. A message carries no words: only
 * {"kind": "alert", "alert": "<number>"} (agent/notifications/fcm.py). */
class AlertsService : FirebaseMessagingService() {
    override fun onMessageReceived(message: RemoteMessage) {
        if (message.data["kind"] != "alert") return
        if (!applicationContext.graph.prefs.lockAlerts) return
        // Runs on Firebase's own thread, which allows a few seconds of work.
        runBlocking { withTimeoutOrNull(9_000) { Alerts.check(applicationContext) } }
    }

    /** Google gave this phone a new address: tell the PC. */
    override fun onNewToken(token: String) {
        val app = applicationContext.graph
        if (!app.prefs.lockAlerts) return
        val client = app.client() ?: return
        runBlocking {
            withTimeoutOrNull(9_000) {
                try {
                    client.registerPhone(token, "android", app.deviceLabel())
                } catch (e: AgentException) {
                    app.prefs.lastProblem = e.key
                }
            }
        }
    }
}
