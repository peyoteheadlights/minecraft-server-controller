package io.github.peyoteheadlights.mcsc.ui

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.core.content.ContextCompat
import io.github.peyoteheadlights.mcsc.BuildConfig

private val THEMES = listOf("system", "light", "dark", "graphite", "contrast")

@Composable
fun SettingsScreen(vm: AppViewModel, onAbout: () -> Unit) {
    val colors = LocalColors.current
    val context = LocalContext.current
    var asking by rememberSaveable { mutableStateOf<String?>(null) }
    val notifications = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) vm.chooseLockAlerts(true) else vm.lockAlertsBlocked()
    }
    fun turnOnLockAlerts() {
        val needsAsking = Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        if (needsAsking) notifications.launch(Manifest.permission.POST_NOTIFICATIONS) else vm.chooseLockAlerts(true)
    }

    Scaffold(containerColor = colors.sheet, topBar = { Bar(t("mobile.settings.title")) }) { padding ->
        LazyColumn(contentPadding = ScreenPadding, modifier = Modifier.padding(padding).fillMaxSize()) {
            item { SectionTitle(t("mobile.settings.theme")) }
            item {
                Card(Modifier.selectableGroup()) {
                    for (name in THEMES) {
                        Choice(t("theme.$name"), selected = vm.theme == name) { vm.chooseTheme(name) }
                    }
                }
            }
            item { SectionTitle(t("mobile.settings.words")) }
            item {
                Card(Modifier.selectableGroup()) {
                    Choice(t("mode.simple"), t("mode.simple_hint"), selected = !vm.technical) { vm.chooseTechnical(false) }
                    Choice(t("mode.technical"), t("mode.technical_hint"), selected = vm.technical) { vm.chooseTechnical(true) }
                }
            }
            item { SectionTitle(t("mobile.settings.unlock")) }
            item {
                Card {
                    Item(
                        t("mobile.settings.unlock_on"),
                        subtitle = t("mobile.settings.unlock_hint"),
                        trailing = { Switch(checked = vm.unlock, onCheckedChange = vm::chooseUnlock) },
                    )
                }
            }
            item { SectionTitle(t("mobile.settings.lock_alerts")) }
            item {
                Card {
                    Item(
                        t("mobile.settings.lock_alerts_on"),
                        subtitle = t("mobile.settings.lock_alerts_hint"),
                        trailing = {
                            Switch(
                                checked = vm.lockAlerts,
                                enabled = !vm.phone.busy && BuildConfig.HAS_FIREBASE,
                                onCheckedChange = { on -> if (on) turnOnLockAlerts() else vm.chooseLockAlerts(false) },
                            )
                        },
                    )
                    if (!BuildConfig.HAS_FIREBASE) Note(t("mobile.settings.lock_alerts_not_in_build"), color = colors.text3)
                    vm.phone.problem?.let { Note(it.text(), color = colors.danger) }
                }
            }
            item { SectionTitle(t("mobile.settings.this_pc")) }
            item {
                Card {
                    Item(t("mobile.settings.pc_address"), subtitle = vm.pairing?.let { "${it.host}:${it.port}" } ?: t("value.unknown"))
                    Item(t("mobile.settings.pc_version"), subtitle = vm.agentVersion ?: t("value.unknown"))
                    Item(t("mobile.settings.signed_in_as"), subtitle = vm.me?.user ?: vm.user ?: t("value.unknown"))
                    Item(t("mobile.settings.rescan"), subtitle = t("mobile.settings.rescan_hint"), onClick = vm::rescan)
                    Item(t("mobile.settings.sign_out"), onClick = { asking = "sign_out" })
                    Item(t("mobile.settings.forget_pc"), onClick = { asking = "forget_pc" })
                }
            }
            item { SectionTitle(t("mobile.settings.help")) }
            item { Card { Item(t("mobile.about.title"), onClick = onAbout) } }
        }
    }

    when (asking) {
        "sign_out" -> Confirm(
            title = t("mobile.settings.sign_out_title"),
            body = t("mobile.settings.sign_out_body"),
            confirm = t("mobile.settings.sign_out"),
            danger = true,
            onConfirm = {
                asking = null
                vm.signOut()
            },
            onDismiss = { asking = null },
        )
        "forget_pc" -> Confirm(
            title = t("mobile.settings.forget_pc_title"),
            body = t("mobile.settings.forget_pc_body"),
            confirm = t("mobile.settings.forget_pc"),
            danger = true,
            onConfirm = {
                asking = null
                vm.forgetPc()
            },
            onDismiss = { asking = null },
        )
    }
}

@Composable
private fun Choice(title: String, subtitle: String? = null, selected: Boolean, onSelect: () -> Unit) {
    androidx.compose.foundation.layout.Box(
        Modifier.selectable(selected = selected, role = Role.RadioButton, onClick = onSelect),
    ) {
        Item(title, subtitle = subtitle, trailing = { RadioButton(selected = selected, onClick = null) })
    }
}
