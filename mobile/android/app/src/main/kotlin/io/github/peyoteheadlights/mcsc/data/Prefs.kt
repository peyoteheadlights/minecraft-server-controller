package io.github.peyoteheadlights.mcsc.data

import android.content.Context
import androidx.core.content.edit
import io.github.peyoteheadlights.mcsc.core.DEFAULT_PORT
import io.github.peyoteheadlights.mcsc.core.Pairing

/** The app's settings and the paired PC. Nothing secret: the token is in [Vault]. */
class Prefs(context: Context) {
    private val p = context.getSharedPreferences("settings", Context.MODE_PRIVATE)

    var pairing: Pairing?
        get() {
            val host = p.getString("host", null) ?: return null
            return Pairing(
                host = host,
                port = p.getInt("port", DEFAULT_PORT),
                fingerprint = p.getString("fingerprint", null),
                apiVersion = p.getInt("api", 0).takeIf { it > 0 },
            )
        }
        set(value) = p.edit {
            if (value == null) {
                for (key in listOf("host", "port", "fingerprint", "api")) remove(key)
            } else {
                putString("host", value.host)
                putInt("port", value.port)
                putString("fingerprint", value.fingerprint)
                putInt("api", value.apiVersion ?: 0)
            }
        }

    /** "system", "light", "dark", "graphite" or "contrast", as in the dashboard. */
    var theme: String
        get() = p.getString("theme", "system") ?: "system"
        set(value) = p.edit { putString("theme", value) }

    var technical: Boolean
        get() = p.getBoolean("technical", false)
        set(value) = p.edit { putBoolean("technical", value) }

    /** Ask for the phone's unlock when opening the app. On by default. */
    var unlock: Boolean
        get() = p.getBoolean("unlock", true)
        set(value) = p.edit { putBoolean("unlock", value) }

    var lockAlerts: Boolean
        get() = p.getBoolean("lock_alerts", false)
        set(value) = p.edit { putBoolean("lock_alerts", value) }

    /** The account signed in, as the agent named it. */
    var user: String?
        get() = p.getString("user", null)
        set(value) = p.edit { putString("user", value) }

    var agentVersion: String?
        get() = p.getString("agent_version", null)
        set(value) = p.edit { putString("agent_version", value) }

    /** The newest alert already shown on the lock screen. */
    var notifiedUpTo: Long
        get() = p.getLong("notified_up_to", 0)
        set(value) = p.edit { putLong("notified_up_to", value) }

    /** The strings key of the last thing that went wrong, for diagnostics. */
    var lastProblem: String?
        get() = p.getString("last_problem", null)
        set(value) = p.edit { putString("last_problem", value) }
}
