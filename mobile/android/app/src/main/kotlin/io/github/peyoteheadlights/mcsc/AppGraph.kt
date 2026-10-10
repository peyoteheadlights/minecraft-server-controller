package io.github.peyoteheadlights.mcsc

import android.content.Context
import android.os.Build
import androidx.core.content.pm.ShortcutManagerCompat
import io.github.peyoteheadlights.mcsc.core.AgentClient
import io.github.peyoteheadlights.mcsc.core.AlertState
import io.github.peyoteheadlights.mcsc.core.Pairer
import io.github.peyoteheadlights.mcsc.core.RequestLog
import io.github.peyoteheadlights.mcsc.core.Strings
import io.github.peyoteheadlights.mcsc.core.WidgetSnapshot
import io.github.peyoteheadlights.mcsc.data.JsonFile
import io.github.peyoteheadlights.mcsc.data.Prefs
import io.github.peyoteheadlights.mcsc.data.SharedData
import io.github.peyoteheadlights.mcsc.data.Vault
import java.io.File
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.serialization.builtins.nullable
import okhttp3.OkHttpClient

class AppGraph(private val context: Context) {
    val shared: SharedData = SharedData.load(context.assets)
    val prefs = Prefs(context)
    val vault = Vault(context)
    val log = RequestLog()
    val alerts = JsonFile(File(context.filesDir, "alerts.json"), AlertState.serializer()) { AlertState() }
    val widget = JsonFile(File(context.filesDir, "widget.json"), WidgetSnapshot.serializer().nullable) { null }

    /** The words, in the wording the person picked. */
    val strings: Strings = Strings(shared.english).also { it.technical = prefs.technical }

    private val http = OkHttpClient()
    private val signedOutEvents = MutableSharedFlow<Unit>(extraBufferCapacity = 1)

    /** Fires when the PC ends this phone's sign-in (a 401). */
    val signedOut: SharedFlow<Unit> = signedOutEvents

    @Volatile
    private var cached: AgentClient? = null

    /** The paired PC, or null before pairing. */
    fun client(): AgentClient? {
        val pairing = prefs.pairing ?: return null
        cached?.takeIf { it.pairing == pairing }?.let { return it }
        return AgentClient(pairing, token = vault::token, onSignedOut = ::signedOutByPc, log = log, baseClient = http)
            .also { cached = it }
    }

    fun pairer(): Pairer = Pairer(shared.apiRange, http, log)

    /** "Server Controller on Pixel 9": the name on the dashboard's Security page. */
    fun deviceLabel(): String =
        strings.t("mobile.signin.device", "app" to strings.t("mobile.app_name"), "model" to Build.MODEL).take(80)

    private fun signedOutByPc() {
        forgetSignIn()
        signedOutEvents.tryEmit(Unit)
    }

    /** Signed out: the token goes, and what was only for this sign-in. */
    fun forgetSignIn() {
        vault.clear()
        prefs.user = null
        prefs.lockAlerts = false
        alerts.write(AlertState())
        widget.write(null)
        ShortcutManagerCompat.removeAllDynamicShortcuts(context)
    }

    /** Forget this PC entirely: back to the welcome screen. */
    fun forgetPc() {
        forgetSignIn()
        prefs.pairing = null
        prefs.agentVersion = null
        widget.write(null)
        cached = null
    }
}
