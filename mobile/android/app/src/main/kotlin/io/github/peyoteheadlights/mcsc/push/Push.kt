package io.github.peyoteheadlights.mcsc.push

import android.content.Context
import com.google.firebase.FirebaseApp
import com.google.firebase.messaging.FirebaseMessaging
import io.github.peyoteheadlights.mcsc.BuildConfig
import kotlinx.coroutines.tasks.await

/**
 * This phone's address on Google's push service (FCM). The agent sends
 * only a wake-up with an alert number to it; the words are read from the
 * PC over Tailscale. Builds without the Firebase file (mobile/README.md)
 * have no address, and lock-screen alerts stay off.
 */
object Push {
    private fun ready(context: Context): Boolean =
        BuildConfig.HAS_FIREBASE && FirebaseApp.getApps(context).isNotEmpty()

    /** Null when this build or this phone can't get one (no Google Play services). */
    suspend fun token(context: Context): String? {
        if (!ready(context)) return null
        return try {
            FirebaseMessaging.getInstance().isAutoInitEnabled = true
            FirebaseMessaging.getInstance().token.await()
        } catch (e: Exception) {
            null
        }
    }

    /** Lock-screen alerts off: drop the address, so Google has none. */
    suspend fun stop(context: Context) {
        if (!ready(context)) return
        try {
            FirebaseMessaging.getInstance().isAutoInitEnabled = false
            FirebaseMessaging.getInstance().deleteToken().await()
        } catch (e: Exception) {
            // No Google Play services: there was no address to drop.
        }
    }
}
