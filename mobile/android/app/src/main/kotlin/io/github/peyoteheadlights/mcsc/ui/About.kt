package io.github.peyoteheadlights.mcsc.ui

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.os.Build
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import io.github.peyoteheadlights.mcsc.core.AgentJson
import io.github.peyoteheadlights.mcsc.core.Diagnostics
import io.github.peyoteheadlights.mcsc.graph
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer

/** Help & About, all in the app: help topics, privacy, licenses, and the
 * two GitHub forms (which open in the browser, with a warning first). */
@Composable
fun AboutScreen(vm: AppViewModel, onBack: () -> Unit, onHelp: () -> Unit) {
    val colors = LocalColors.current
    val context = LocalContext.current
    var copied by rememberSaveable { mutableStateOf(false) }
    var showing by rememberSaveable { mutableStateOf<String?>(null) }
    if (showing == "privacy") return PrivacyScreen(onBack = { showing = null })
    if (showing == "licenses") return LicensesScreen(onBack = { showing = null })

    Scaffold(containerColor = colors.sheet, topBar = { Bar(t("mobile.about.title"), onBack) }) { padding ->
        LazyColumn(contentPadding = ScreenPadding, modifier = Modifier.padding(padding).fillMaxSize()) {
            item {
                Text(
                    t("mobile.app_name"),
                    style = MaterialTheme.typography.headlineSmall,
                    color = colors.text,
                    modifier = Modifier.padding(horizontal = 20.dp, vertical = 12.dp),
                )
            }
            item { Note(t("mobile.about.version", "version" to vm.shared.appVersion)) }
            item { Note(t("mobile.about.free")) }
            item { SectionTitle(t("mobile.about.help")) }
            item {
                Card {
                    Item(t("mobile.about.help"), onClick = onHelp)
                    Item(t("mobile.about.whats_new"), onClick = { openLink(context, Links.RELEASES) }, external = true)
                    Item(t("mobile.about.privacy"), onClick = { showing = "privacy" })
                    Item(t("mobile.about.licenses"), onClick = { showing = "licenses" })
                }
            }
            item { SectionTitle(t("mobile.about.report")) }
            item {
                Card {
                    Note(t("mobile.about.forms_hint"), color = colors.warning, modifier = Modifier.padding(top = 8.dp))
                    Item(t("mobile.about.report"), onClick = { openLink(context, Links.REPORT) }, external = true)
                    Item(t("mobile.about.suggest"), onClick = { openLink(context, Links.SUGGEST) }, external = true)
                    Item(
                        t("mobile.about.copy_diagnostics"),
                        subtitle = if (copied) t("mobile.about.copied") else null,
                        onClick = {
                            copy(context, diagnostics(context, vm))
                            copied = true
                        },
                    )
                    Item(t("mobile.about.source"), onClick = { openLink(context, Links.REPO) }, external = true)
                }
            }
            item {
                Text(
                    t("mobile.about.disclaimer"),
                    style = MaterialTheme.typography.bodySmall,
                    fontWeight = FontWeight.Medium,
                    color = colors.text2,
                    modifier = Modifier.padding(20.dp),
                )
            }
        }
    }
}

private fun diagnostics(context: Context, vm: AppViewModel): String {
    val graph = context.graph
    val facts = Diagnostics.Facts(
        appVersion = vm.shared.appVersion,
        platform = "Android",
        osVersion = Build.VERSION.RELEASE,
        device = Build.MODEL,
        agentVersion = vm.agentVersion,
        agentApi = vm.pairing?.apiVersion,
        paired = vm.pairing != null,
        pinned = vm.pairing?.fingerprint != null,
        signedIn = graph.vault.token() != null,
        lockScreenAlerts = vm.lockAlerts,
        lastProblem = graph.prefs.lastProblem,
    )
    return Diagnostics.text(facts, graph.log.recent())
}

private fun copy(context: Context, text: String) {
    val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    clipboard.setPrimaryClip(ClipData.newPlainText("Diagnostics", text))
}

private val HELP = listOf("pairing", "unreachable", "certificate", "alerts", "signout")

@Composable
fun HelpScreen(onBack: () -> Unit) {
    val colors = LocalColors.current
    Scaffold(containerColor = colors.sheet, topBar = { Bar(t("mobile.about.help"), onBack) }) { padding ->
        LazyColumn(contentPadding = ScreenPadding, modifier = Modifier.padding(padding).fillMaxSize()) {
            items(HELP) { topic ->
                SectionTitle(t("mobile.help.${topic}_title"))
                Card { Text(t("mobile.help.${topic}_body"), color = colors.text, modifier = Modifier.padding(16.dp)) }
            }
        }
    }
}

@Composable
private fun PrivacyScreen(onBack: () -> Unit) {
    val colors = LocalColors.current
    val context = LocalContext.current
    Scaffold(containerColor = colors.sheet, topBar = { Bar(t("mobile.about.privacy"), onBack) }) { padding ->
        LazyColumn(contentPadding = ScreenPadding, modifier = Modifier.padding(padding).fillMaxSize()) {
            item { Card(Modifier.padding(top = 8.dp)) { Text(t("mobile.privacy.body"), color = colors.text, modifier = Modifier.padding(16.dp)) } }
            item { Card(Modifier.padding(top = 8.dp)) { Item(t("mobile.privacy.full"), onClick = { openLink(context, Links.PRIVACY) }, external = true) } }
        }
    }
}

/** The free libraries inside the app (app/src/main/assets/licenses.json;
 * tests/test_phone_app.py checks every library the app uses is listed). */
@Serializable
private data class License(val name: String, val group: String, val license: String, val url: String)

@Composable
private fun LicensesScreen(onBack: () -> Unit) {
    val colors = LocalColors.current
    val context = LocalContext.current
    val licenses = remember {
        val text = context.assets.open("licenses.json").bufferedReader().use { it.readText() }
        AgentJson.decodeFromString(ListSerializer(License.serializer()), text)
    }
    Scaffold(containerColor = colors.sheet, topBar = { Bar(t("mobile.about.licenses"), onBack) }) { padding ->
        LazyColumn(contentPadding = ScreenPadding, modifier = Modifier.padding(padding).fillMaxSize()) {
            item { Note(t("mobile.about.licenses_lead")) }
            item {
                Card {
                    for (entry in licenses) {
                        Item(entry.name, subtitle = entry.license, onClick = { openLink(context, entry.url) }, external = true)
                    }
                }
            }
        }
    }
}
