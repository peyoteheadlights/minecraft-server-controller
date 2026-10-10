package io.github.peyoteheadlights.mcsc.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.RadioButtonUnchecked
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import io.github.peyoteheadlights.mcsc.core.Display
import io.github.peyoteheadlights.mcsc.core.JoinAddress
import io.github.peyoteheadlights.mcsc.core.JoinInfo
import io.github.peyoteheadlights.mcsc.core.JoinWay
import io.github.peyoteheadlights.mcsc.core.Recommendation

/*
 * The Overview's three cards under a server's state, as the dashboard
 * shows them: how friends join, suggestions, and getting started. Each
 * reads what the agent measured; a value it couldn't read says so.
 */

/** "How friends join": every address to share, each with Copy. */
fun LazyListScope.joinCard(vm: AppViewModel, pages: ServerPages) {
    item { SectionTitle(t("join.title")) }
    val problem = pages.join.problem
    val info = pages.join.value
    when {
        problem != null -> item { ProblemNote(problem) { pages.loadCards() } }
        info == null -> item { Note(t("mobile.common.loading")) }
        else -> item { JoinCard(vm, info) }
    }
}

@Composable
private fun JoinCard(vm: AppViewModel, info: JoinInfo) {
    val colors = LocalColors.current
    val java = info.java
    val bedrock = info.bedrock
    Card {
        when {
            java != null -> {
                JavaWays(vm, java)
                if (bedrock != null) BedrockCrossplay(vm, bedrock)
            }
            bedrock != null -> BedrockServer(vm, bedrock)
            else -> Item(t("value.unknown"))
        }
        Note(t("join.internet"), color = colors.text3, modifier = Modifier.padding(bottom = 10.dp))
    }
}

@Composable
private fun JavaWays(vm: AppViewModel, java: JoinWay) {
    val colors = LocalColors.current
    val port = java.port
    fun withPort(host: String) = if (port == null) host else "$host:$port"
    Group(t("join.home"), t("join.home_hint"))
    val home = homeAddresses(vm, java.local)
    if (home.isEmpty()) Note(t("join.no_local"), color = colors.text3)
    for (address in home) Address(withPort(address.address), adapterNote(vm, address, home.size))
    Group(t("join.tailscale"), t("join.tailscale_hint"))
    TailscaleWays(java, ::withPort)
    Note(
        t("join.port", "port" to (port?.toString() ?: t("value.unknown")), "source" to (java.portSource ?: t("value.unknown"))) +
            if (java.defaultPort == true) " " + t("join.default_port") else "",
    )
}

@Composable
private fun TailscaleWays(way: JoinWay, withPort: (String) -> String) {
    val colors = LocalColors.current
    val ts = way.tailscale
    val address = ts?.address
    if (ts == null || address == null) {
        Note(t("join.no_tailscale"), color = colors.text3)
        return
    }
    Address(withPort(address))
    ts.dnsName?.let { Address(withPort(it)) }
    when {
        ts.verified != true -> Note(t("join.ts_unconfirmed"), color = colors.warning)
        ts.connected == false -> Note(t("join.ts_off"), color = colors.warning)
    }
}

/** Crossplay: Bedrock players type the address and the port apart. */
@Composable
private fun BedrockCrossplay(vm: AppViewModel, bedrock: JoinWay) {
    val colors = LocalColors.current
    Group(t("join.bedrock"), t("join.bedrock_hint"))
    val port = bedrock.port
    if (port == null) {
        Note(t("join.no_bedrock_port"), color = colors.text3)
    } else {
        val portWords = t("join.bedrock_port", "port" to port)
        for (address in homeAddresses(vm, bedrock.local)) Address(address.address, "$portWords · ${t("join.home")}")
        val ts = bedrock.address
        if (ts != null) Address(ts, "$portWords · ${t("join.tailscale")}") else Note(t("join.no_tailscale"), color = colors.text3)
    }
    if (bedrock.ready == false) Note(t("cross.files_missing"), color = colors.warning)
    Note(t("join.consoles"), color = colors.text3)
}

/** A Bedrock server of its own. */
@Composable
private fun BedrockServer(vm: AppViewModel, bedrock: JoinWay) {
    val colors = LocalColors.current
    Group(t("join.home"), t("join.home_hint"))
    val home = homeAddresses(vm, bedrock.local)
    if (home.isEmpty()) Note(t("join.no_local"), color = colors.text3)
    for (address in home) Address(address.address, adapterNote(vm, address, home.size))
    Group(t("join.tailscale"), t("join.bedrock_tailscale_hint"))
    TailscaleWays(bedrock) { it }
    val unknown = t("value.unknown")
    Note(
        t("join.bedrock_server_port", "port" to (bedrock.port?.toString() ?: unknown), "source" to (bedrock.portSource ?: unknown)) +
            if (bedrock.defaultPort == true) " " + t("join.default_port") else "",
    )
    Note(t("join.consoles"), color = colors.text3)
}

/** Virtual adapters (VPNs, virtual machines) only in Technical words. */
private fun homeAddresses(vm: AppViewModel, all: List<JoinAddress>): List<JoinAddress> =
    all.filter { vm.technical || !it.virtual }

private fun adapterNote(vm: AppViewModel, address: JoinAddress, count: Int): String? {
    val adapter = address.adapter ?: return null
    return if (vm.technical || count > 1) vm.strings.t("join.adapter", "adapter" to adapter) else null
}

@Composable
private fun Group(title: String, hint: String) {
    Item(title, subtitle = hint)
}

@Composable
private fun Address(text: String, note: String? = null) {
    Item(text, subtitle = note, trailing = { CopyButton(text) })
}

/** Suggestions, in the agent's own words. Not now / Don't show again /
 * Show again only for someone who may change settings. */
fun LazyListScope.suggestionsCard(vm: AppViewModel, pages: ServerPages, canEdit: Boolean) {
    val read = pages.suggestions
    val value = read.value
    if (read.problem != null || value == null) return
    item { SectionTitle(t("overview.recommendations")) }
    item {
        Card {
            if (value.recommendations.isEmpty()) Item(t("rec.none"))
            for (rec in value.recommendations) Suggestion(rec, canEdit) { action -> pages.suggestion(rec.id, action) }
            if (value.hidden.isNotEmpty()) {
                Note(vm.strings.tn("rec.hidden", value.hidden.size), color = LocalColors.current.text3)
                for (rec in value.hidden) {
                    Item(
                        rec.title,
                        trailing = {
                            if (canEdit) TextButton(onClick = { pages.suggestion(rec.id, "restore") }) { Text(t("rec.show_again")) }
                        },
                    )
                }
            }
        }
    }
}

@Composable
private fun Suggestion(rec: Recommendation, canEdit: Boolean, onAction: (String) -> Unit) {
    val colors = LocalColors.current
    val context = LocalContext.current
    Item(rec.title, subtitle = rec.reason)
    rec.evidence?.takeIf { it.isNotBlank() }?.let { Note(it, color = colors.text3) }
    val url = rec.action?.url
    val label = rec.action?.label
    Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
        if (url != null && label != null && url.startsWith("https://")) {
            TextButton(onClick = { openLink(context, url) }) { Text(label) }
        }
        if (canEdit) {
            TextButton(onClick = { onAction("snooze") }) { Text(t("rec.snooze")) }
            TextButton(onClick = { onAction("dismiss") }) { Text(t("rec.dismiss")) }
        }
    }
}

/** Getting started: ticked from what the agent measured, never by a tap.
 * Gone once hidden or finished. Hide only for someone who may change settings. */
fun LazyListScope.checklistCard(vm: AppViewModel, pages: ServerPages, canEdit: Boolean) {
    val list = pages.checklist.value ?: return
    if (!list.show || pages.checklist.problem != null) return
    item { SectionTitle(t("start.title")) }
    item {
        val colors = LocalColors.current
        val now = rememberNow()
        Card {
            val done = list.done
            val total = list.total
            Item(
                if (done != null && total != null) t("start.progress", "done" to done, "total" to total) else t("value.unknown"),
                subtitle = t("start.lead"),
                trailing = {
                    if (canEdit) TextButton(onClick = pages::hideChecklist) { Text(t("start.hide")) }
                },
            )
            for (entry in list.items) {
                val found = entry.evidence
                val evidence = entry.evidenceKey?.let { key ->
                    t(
                        "start.$key",
                        "when" to (found?.createdAt?.let { Display.ago(vm.strings, it, now) } ?: ""),
                        "name" to (found?.name ?: ""),
                    )
                }
                Item(
                    t("start.${entry.id}"),
                    subtitle = evidence,
                    leading = {
                        Icon(
                            if (entry.done) Icons.Outlined.CheckCircle else Icons.Outlined.RadioButtonUnchecked,
                            contentDescription = if (entry.done) t("start.done") else null,
                            tint = if (entry.done) colors.success else colors.text3,
                        )
                    },
                )
            }
        }
    }
}
