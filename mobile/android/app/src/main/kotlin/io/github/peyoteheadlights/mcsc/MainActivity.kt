package io.github.peyoteheadlights.mcsc

import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.os.SystemClock
import android.view.WindowManager
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricManager.Authenticators.BIOMETRIC_STRONG
import androidx.biometric.BiometricManager.Authenticators.BIOMETRIC_WEAK
import androidx.biometric.BiometricManager.Authenticators.DEVICE_CREDENTIAL
import androidx.biometric.BiometricPrompt
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import io.github.peyoteheadlights.mcsc.core.Strings
import io.github.peyoteheadlights.mcsc.ui.AppViewModel
import io.github.peyoteheadlights.mcsc.ui.LocalStrings
import io.github.peyoteheadlights.mcsc.ui.LockScreen
import io.github.peyoteheadlights.mcsc.ui.Main
import io.github.peyoteheadlights.mcsc.ui.McscTheme
import io.github.peyoteheadlights.mcsc.ui.Onboarding
import io.github.peyoteheadlights.mcsc.ui.Stage
import io.github.peyoteheadlights.mcsc.ui.themeName

class MainActivity : FragmentActivity() {
    private val vm: AppViewModel by viewModels()
    private var stoppedAt: Long? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        // No screenshots, and a blank card in the app switcher.
        window.setFlags(WindowManager.LayoutParams.FLAG_SECURE, WindowManager.LayoutParams.FLAG_SECURE)
        open(intent)
        setContent {
            val shared = vm.shared
            val technical = vm.technical
            val strings = remember(technical) { Strings(shared.english).also { it.technical = technical } }
            CompositionLocalProvider(LocalStrings provides strings) {
                McscTheme(shared, themeName(vm.theme)) {
                    when {
                        vm.stage != Stage.Ready -> Onboarding(vm)
                        vm.locked -> {
                            val available = canUnlock()
                            LaunchedEffect(Unit) { if (available) askToUnlock() }
                            LockScreen(available) { if (available) askToUnlock() else vm.unlocked() }
                        }
                        else -> Main(vm)
                    }
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        open(intent)
    }

    override fun onStart() {
        super.onStart()
        val away = stoppedAt?.let { (SystemClock.elapsedRealtime() - it) / 1000.0 }
        if (stoppedAt != null) vm.lockIfAway(away)
        stoppedAt = null
        vm.foreground(true)
    }

    override fun onStop() {
        super.onStop()
        stoppedAt = SystemClock.elapsedRealtime()
        vm.foreground(false)
    }

    /** A shortcut, the widget or an alert can name a server to open. */
    private fun open(intent: Intent?) {
        intent?.getStringExtra(EXTRA_SERVER)?.let { vm.pendingServer = it }
    }

    private val authenticators: Int
        get() = if (Build.VERSION.SDK_INT >= 30) BIOMETRIC_STRONG or DEVICE_CREDENTIAL else BIOMETRIC_WEAK or DEVICE_CREDENTIAL

    private fun canUnlock(): Boolean =
        BiometricManager.from(this).canAuthenticate(authenticators) == BiometricManager.BIOMETRIC_SUCCESS

    private fun askToUnlock() {
        val prompt = BiometricPrompt(
            this,
            ContextCompat.getMainExecutor(this),
            object : BiometricPrompt.AuthenticationCallback() {
                override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                    vm.unlocked()
                }
            },
        )
        val info = BiometricPrompt.PromptInfo.Builder()
            .setTitle(graph.strings.t("mobile.lock.reason"))
            .setAllowedAuthenticators(authenticators)
            .build()
        prompt.authenticate(info)
    }

    companion object {
        const val EXTRA_SERVER = "server"
    }
}
