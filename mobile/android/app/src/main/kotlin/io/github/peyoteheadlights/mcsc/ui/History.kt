package io.github.peyoteheadlights.mcsc.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import io.github.peyoteheadlights.mcsc.core.Crash
import io.github.peyoteheadlights.mcsc.core.Display

/** What happened on this server and the PC, newest first, live. Only each
 * event's words, level and time: the details it carries are never shown. */
@Composable
fun EventsScreen(vm: AppViewModel, serverId: String, onBack: () -> Unit) {
    val pages = vm.pages(serverId)
    LaunchedEffect(serverId) { pages.loadEvents() }
    val now = rememberNow()
    val shown = pages.events.value?.filter { Display.worthShowing(it.type, vm.technical) }
    ServerFrame(vm, serverId, t("page.events"), onBack, refreshing = false, onRefresh = pages::loadEvents) {
        emptyOrProblem(pages.events.copy(value = shown), "events.none", onRetry = pages::loadEvents)
        items(shown.orEmpty()) { event ->
            val colors = LocalColors.current
            Card {
                Item(
                    event.message.ifBlank { event.type },
                    subtitle = Display.ago(vm.strings, event.ts, now),
                    leading = { LevelDot(colors.tone(Display.eventTone(event.level))) },
                )
            }
        }
    }
}

@Composable
private fun LevelDot(color: Color) {
    Box(Modifier.size(10.dp).background(color, CircleShape))
}

/** The crashes the agent recorded, with its best guess at each cause. */
@Composable
fun CrashesScreen(vm: AppViewModel, serverId: String, onBack: () -> Unit, onOpen: (Long) -> Unit) {
    val pages = vm.pages(serverId)
    LaunchedEffect(serverId) { pages.loadCrashes() }
    ServerFrame(vm, serverId, t("page.crashes"), onBack, refreshing = false, onRefresh = pages::loadCrashes) {
        emptyOrProblem(pages.crashes, "crashes.none", onRetry = pages::loadCrashes)
        items(pages.crashes.value.orEmpty()) { crash ->
            Card { Item(crashWhen(crash), subtitle = crashLine(vm, crash), onClick = { onOpen(crash.id) }) }
        }
    }
}

/** One crash: the cause, the lines that point to it, what was known then,
 * and the end of the saved log. */
@Composable
fun CrashScreen(vm: AppViewModel, serverId: String, crashId: Long, onBack: () -> Unit) {
    val pages = vm.pages(serverId)
    LaunchedEffect(serverId, crashId) { pages.openCrash(crashId) }
    val read = pages.crash
    val crash = read.value?.takeIf { it.id == crashId }
    ServerFrame(
        vm, serverId,
        title = crash?.let { t("crashes.dialog_title", "when" to crashWhen(it)) } ?: t("page.crashes"),
        onBack = onBack,
        refreshing = false,
        onRefresh = { pages.openCrash(crashId) },
    ) {
        val problem = read.problem
        when {
            problem != null -> item { ProblemNote(problem) { pages.openCrash(crashId) } }
            crash == null -> item { Note(t("mobile.common.loading")) }
            else -> crashDetails(vm, crash)
        }
    }
}

private fun LazyListScope.crashDetails(vm: AppViewModel, crash: Crash) {
    val unknown = vm.strings.t("value.unknown")
    val analysis = crash.context?.analysis
    item {
        Card(Modifier.padding(top = 8.dp)) {
            Item(t("crashes.col_cause"), subtitle = Display.cause(vm.strings, crash.category))
            Item(t("crashes.col_confidence"), subtitle = t(Display.confidence(crash.confidence).key))
            Item(t("crashes.col_code"), subtitle = Display.exitCode(vm.strings, crash.exitCode))
            crash.summary?.takeIf { it.isNotBlank() }?.let { Note(it) }
            analysis?.advice?.takeIf { it.isNotBlank() }?.let { Note(it) }
            analysis?.suspectMods?.takeIf { it.isNotEmpty() }?.let { mods ->
                Note(t("crashes.suspect_mods") + mods.joinToString(", ") + t("crashes.suspect_hint"))
            }
            Note(t("crashes.rule_match"), color = LocalColors.current.text3, modifier = Modifier.padding(bottom = 8.dp))
        }
    }
    val evidence = crash.evidence.orEmpty()
    if (evidence.isNotEmpty()) {
        item { SectionTitle(t("crashes.evidence")) }
        item { Card { Mono(evidence) } }
    }
    val context = crash.context
    if (context != null) {
        item { SectionTitle(t("crashes.context")) }
        item {
            Card {
                Item(t("crashes.f_minecraft"), subtitle = context.minecraftVersion ?: unknown)
                context.fabricLoader?.let { Item(t("crashes.f_loader"), subtitle = it) }
                Item(t("crashes.f_java"), subtitle = context.javaVersion ?: unknown)
                Item(
                    t("crashes.f_players"),
                    subtitle = context.playersOnline?.let { if (it.isEmpty()) t("crashes.no_players") else it.joinToString(", ") } ?: unknown,
                )
                Item(t("crashes.f_report"), subtitle = context.crashReport ?: t("crashes.no_report"))
                context.logFile?.let { Item(t("crashes.f_log"), subtitle = it) }
            }
        }
    }
    item { SectionTitle(t("mobile.crash.log_tail")) }
    item {
        val tail = crash.logTail
        Card { if (tail.isNullOrEmpty()) Item(t("mobile.crash.log_gone")) else Mono(tail) }
    }
}

@Composable
private fun Mono(lines: List<String>) {
    Text(
        lines.joinToString("\n"),
        fontFamily = FontFamily.Monospace,
        style = MaterialTheme.typography.bodySmall,
        color = LocalColors.current.text,
        modifier = Modifier.fillMaxWidth().padding(16.dp),
    )
}

/** "2026-10-10 14:05:09" in the phone's time zone, or Unknown. */
@Composable
private fun crashWhen(crash: Crash): String {
    val ts = crash.ts ?: return t("value.unknown")
    val zone = java.time.ZoneId.systemDefault()
    val day = java.time.Instant.ofEpochMilli((ts * 1000).toLong()).atZone(zone).toLocalDate().toString()
    return "$day ${Display.clock(ts, zone)}"
}

@Composable
private fun crashLine(vm: AppViewModel, crash: Crash): String = listOf(
    Display.cause(vm.strings, crash.category),
    t(Display.confidence(crash.confidence).key),
    t("crashes.col_code") + " " + Display.exitCode(vm.strings, crash.exitCode),
).joinToString(" · ")
