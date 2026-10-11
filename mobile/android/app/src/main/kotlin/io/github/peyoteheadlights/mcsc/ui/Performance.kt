package io.github.peyoteheadlights.mcsc.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.foundation.background
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextMeasurer
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.github.peyoteheadlights.mcsc.core.Chart
import io.github.peyoteheadlights.mcsc.core.ChartPoint
import io.github.peyoteheadlights.mcsc.core.Charts
import io.github.peyoteheadlights.mcsc.core.Display
import io.github.peyoteheadlights.mcsc.core.HealthChecks
import io.github.peyoteheadlights.mcsc.core.Performance
import io.github.peyoteheadlights.mcsc.core.ServerHealth
import io.github.peyoteheadlights.mcsc.core.Tone

/**
 * How the PC and the server are doing: the values now, graphs over the
 * chosen time with real axes and gaps where nothing was measured, the disk
 * use, and the health checks. A value nobody measured reads Unknown.
 */
@Composable
fun PerformanceScreen(vm: AppViewModel, serverId: String, onBack: () -> Unit) {
    val world = vm.pages(serverId).world
    LaunchedEffect(serverId) { world.loadPerformance() }
    val speed = vm.servers.list.firstOrNull { it.id == serverId }?.capabilities?.speed

    ServerFrame(
        vm, serverId,
        title = t("page.performance"),
        onBack = onBack,
        refreshing = false,
        onRefresh = world::loadPerformance,
    ) {
        item { RangePicker(world.range, world::showRange) }
        val read = world.performance
        val data = read.value
        val problem = read.problem
        when {
            problem != null -> item { ProblemNote(problem, world::loadPerformance) }
            data == null -> item { Note(t("mobile.common.loading")) }
            else -> {
                nowCard(vm, data)
                item { SectionTitle(t("mobile.perf.graphs")) }
                val charts = Charts.performance(vm.strings, data, world.readAt, speed)
                items(charts, key = { it.title }) { chart -> LineChart(chart) }
                item { Note(t("mobile.perf.touch"), color = LocalColors.current.text3) }
                storageCard(vm, data)
            }
        }
        healthCard(vm, world.health.value, world.health.problem?.let { { ProblemNote(it, world::loadPerformance) } })
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun RangePicker(range: Int, onPick: (Int) -> Unit) {
    FlowRow(
        Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        for (hours in Charts.RANGES) {
            FilterChip(selected = range == hours, onClick = { onPick(hours) }, label = { Text(t(Charts.rangeKey(hours))) })
        }
    }
}

private fun LazyListScope.nowCard(vm: AppViewModel, data: Performance) {
    item { SectionTitle(t("mobile.perf.now")) }
    item {
        val strings = vm.strings
        val c = data.current
        val limit = data.memoryLimitMb
        val serverMemory = Display.memory(c.procRamMb)
        Card {
            Item(t("perf.pc_cpu"), subtitle = t("perf.pc_cpu_note"), trailing = { Value(Display.pct(strings, c.cpuPercent)) })
            Item(t("perf.server_cpu"), subtitle = t("perf.server_cpu_note"), trailing = { Value(Display.pct(strings, c.processCpuPercent)) })
            Item(
                t("perf.server_memory"),
                subtitle = when {
                    serverMemory == null -> t("perf.not_running_note")
                    limit != null -> t("perf.of_limit", "limit" to Display.memory(limit))
                    else -> null
                },
                trailing = { Value(serverMemory ?: t("value.unknown")) },
            )
            Item(t("perf.pc_memory"), subtitle = t("perf.pc_memory_note"), trailing = { Value(Display.pct(strings, c.ramPercent)) })
            Item(
                t("perf.disk_free"),
                subtitle = if (c.diskFreeGb != null || c.diskUnknownReason == null) t("perf.on_server_drive") else c.diskUnknownReason,
                trailing = { Value(Display.gb(strings, c.diskFreeGb)) },
            )
        }
    }
}

@Composable
private fun Value(text: String) {
    Text(text, color = LocalColors.current.text, fontWeight = FontWeight.Medium, style = MaterialTheme.typography.bodyLarge)
}

private fun LazyListScope.storageCard(vm: AppViewModel, data: Performance) {
    val strings = vm.strings
    data.storage?.let { s ->
        item { SectionTitle(t("perf.storage")) }
        item {
            Card {
                Item(t("perf.storage_worlds"), trailing = { Value(Display.gb(strings, s.worldsGb)) })
                Item(t("perf.storage_backups"), trailing = { Value(Display.gb(strings, s.backupsGb)) })
                Item(t("perf.storage_mods"), trailing = { Value(Display.gb(strings, s.modsGb)) })
                Item(t("perf.storage_logs"), trailing = { Value(Display.gb(strings, s.logsGb)) })
                Item(t("perf.storage_other"), trailing = { Value(Display.gb(strings, s.otherGb)) })
                val free = s.freeUnknownReason
                Item(
                    t("perf.storage_free"),
                    subtitle = if (s.freeGb == null && free != null) t("perf.unknown_because", "reason" to free) else null,
                    trailing = { Value(Display.gb(strings, s.freeGb)) },
                )
            }
        }
    }
    if (vm.technical) {
        val c = data.current
        item { SectionTitle(t("perf.network")) }
        item {
            Card {
                Item(t("perf.net_in"), trailing = { Value(c.netRecvMbS?.let { "${Display.fixed(it, 2)} MB/s" } ?: t("value.unknown")) })
                Item(t("perf.net_out"), trailing = { Value(c.netSentMbS?.let { "${Display.fixed(it, 2)} MB/s" } ?: t("value.unknown")) })
            }
        }
    }
}

private fun LazyListScope.healthCard(vm: AppViewModel, health: ServerHealth?, problem: (@Composable () -> Unit)?) {
    item { SectionTitle(t("perf.health")) }
    if (problem != null) {
        item { problem() }
        return
    }
    if (health == null) {
        item { Note(t("mobile.common.loading")) }
        return
    }
    item {
        val colors = LocalColors.current
        val overall = HealthChecks.overall(health.overall)
        Card {
            Item(
                overall?.let { t(it.key) } ?: health.overall,
                subtitle = health.note?.takeIf { it.isNotBlank() },
                leading = { Dot(colors.tone(overall?.tone ?: Tone.NEUTRAL)) },
            )
            for (check in health.checks) {
                Item(
                    check.name,
                    subtitle = HealthChecks.detail(vm.strings, check).takeIf { it.isNotEmpty() },
                    leading = { Dot(colors.tone(HealthChecks.tone(check.status))) },
                    trailing = { Value(HealthChecks.value(vm.strings, check)) },
                )
            }
        }
    }
}

@Composable
private fun Dot(color: androidx.compose.ui.graphics.Color) {
    Box(Modifier.size(10.dp).clip(CircleShape).background(color))
}

/**
 * One graph, drawn as the dashboard draws it: value ticks up the side,
 * clock ticks along the bottom, a dashed guide for a limit, a line broken
 * wherever there was no sample. Touch or drag along it to read a point.
 */
@Composable
fun LineChart(chart: Chart) {
    val colors = LocalColors.current
    val strings = LocalStrings.current
    val measurer = rememberTextMeasurer()
    var cursor by remember(chart) { mutableStateOf<ChartPoint?>(null) }
    val points = remember(chart) { chart.points }
    Card {
        Row(Modifier.padding(start = 16.dp, end = 16.dp, top = 12.dp)) {
            Text(chart.title, color = colors.text, fontWeight = FontWeight.Medium, modifier = Modifier.weight(1f))
            Text(chart.unit, color = colors.text3, style = MaterialTheme.typography.bodySmall)
        }
        val empty = chart.empty
        if (empty != null) {
            Note(empty, modifier = Modifier.padding(bottom = 12.dp))
            return@Card
        }
        val reading = cursor?.let {
            strings.t("mobile.perf.point", "value" to chart.format(it.value, false), "time" to Charts.pointLabel(it.ts, chart.to - chart.from))
        }
        Note(reading ?: " ", color = colors.text2)
        val tick = TextStyle(color = colors.text3, fontSize = 11.sp)
        val guideStyle = TextStyle(color = colors.text2, fontSize = 11.sp)
        Canvas(
            Modifier
                .fillMaxWidth()
                .height(180.dp)
                .padding(bottom = 8.dp)
                .semantics { contentDescription = chart.summary(strings) }
                .pointerInput(chart) {
                    detectTapGestures { cursor = touched(chart, points, it.x, size.width.toFloat(), density) }
                }
                .pointerInput(chart) {
                    detectHorizontalDragGestures { change, _ ->
                        cursor = touched(chart, points, change.position.x, size.width.toFloat(), density)
                    }
                },
        ) {
            drawChart(chart, measurer, tick, guideStyle, cursor, colors)
        }
    }
}

private const val LEFT = 48f
private const val RIGHT = 14f
private const val TOP = 10f
private const val BOTTOM = 26f

private fun touched(chart: Chart, points: List<ChartPoint>, x: Float, width: Float, density: Float): ChartPoint? {
    val left = LEFT * density
    val w = width - left - RIGHT * density
    if (w <= 0) return null
    val ts = chart.from + ((x - left) / w) * (chart.to - chart.from)
    return Charts.nearest(points, ts)
}

private fun DrawScope.drawChart(
    chart: Chart,
    measurer: TextMeasurer,
    tick: TextStyle,
    guideStyle: TextStyle,
    cursor: ChartPoint?,
    colors: McscColors,
) {
    val left = LEFT.dp.toPx()
    val right = RIGHT.dp.toPx()
    val top = TOP.dp.toPx()
    val bottom = BOTTOM.dp.toPx()
    val w = size.width - left - right
    val h = size.height - top - bottom
    if (w <= 0 || h <= 0) return
    val span = (chart.to - chart.from).takeIf { it > 0 } ?: 1.0
    val x = { ts: Double -> (left + ((ts - chart.from) / span) * w).toFloat() }
    val y = { v: Double -> (top + h - (v.coerceIn(0.0, chart.top) / chart.top) * h).toFloat() }
    val grid = colors.text3.copy(alpha = 0.25f)

    for (v in chart.yTicks) {
        drawLine(grid, Offset(left, y(v)), Offset(size.width - right, y(v)), strokeWidth = 1f)
        val label = measurer.measure(chart.format(v, true), tick)
        drawText(label, topLeft = Offset(left - 8.dp.toPx() - label.size.width, y(v) - label.size.height / 2f))
    }
    val every = maxOf(1, kotlin.math.ceil(chart.timeTicks.size / maxOf(2.0, kotlin.math.floor(w / 80.dp.toPx().toDouble()))).toInt())
    chart.timeTicks.forEachIndexed { i, ts ->
        if (i % every != 0) return@forEachIndexed
        drawLine(grid, Offset(x(ts), top), Offset(x(ts), top + h), strokeWidth = 1f)
        val label = measurer.measure(Charts.axisLabel(ts, chart.days), tick)
        drawText(label, topLeft = Offset(x(ts) - label.size.width / 2f, size.height - label.size.height))
    }
    chart.guide?.takeIf { it.value <= chart.top }?.let { guide ->
        drawLine(
            colors.text2, Offset(left, y(guide.value)), Offset(size.width - right, y(guide.value)),
            strokeWidth = 1.5f, pathEffect = PathEffect.dashPathEffect(floatArrayOf(10f, 8f)),
        )
        val label = measurer.measure(guide.label, guideStyle)
        drawText(label, topLeft = Offset(size.width - right - 4.dp.toPx() - label.size.width, y(guide.value) - label.size.height - 2.dp.toPx()))
    }
    val line = colors.accentInk
    for (run in chart.runs) {
        if (run.size == 1) {
            drawCircle(line, radius = 2.2.dp.toPx(), center = Offset(x(run[0].ts), y(run[0].value)))
            continue
        }
        val path = Path().apply {
            run.forEachIndexed { i, p -> if (i == 0) moveTo(x(p.ts), y(p.value)) else lineTo(x(p.ts), y(p.value)) }
        }
        val area = Path().apply {
            addPath(path)
            lineTo(x(run.last().ts), top + h)
            lineTo(x(run.first().ts), top + h)
            close()
        }
        drawPath(area, line.copy(alpha = 0.14f))
        drawPath(path, line, style = Stroke(width = 2.dp.toPx()))
    }
    cursor?.let { p ->
        drawLine(colors.text2, Offset(x(p.ts), top), Offset(x(p.ts), top + h), strokeWidth = 1f)
        drawCircle(line, radius = 4.dp.toPx(), center = Offset(x(p.ts), y(p.value)))
    }
}
