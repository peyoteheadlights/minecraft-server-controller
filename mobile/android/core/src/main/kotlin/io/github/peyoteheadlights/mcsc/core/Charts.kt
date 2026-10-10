package io.github.peyoteheadlights.mcsc.core

import kotlin.math.ceil
import kotlin.math.floor
import kotlin.math.log10
import kotlin.math.pow
import kotlin.math.roundToLong

/** One sample on a graph: its time and value. */
data class ChartPoint(val ts: Double, val value: Double)

/** A dashed reference line, such as the memory limit. */
data class ChartGuide(val value: Double, val label: String)

/**
 * One graph, worked out and ready to draw, with the dashboard's rules
 * (agent/web/js/charts.js): time along the bottom on clock ticks, the
 * value up the side on a fixed range where one exists, and a gap wherever
 * there is no sample, never a line drawn through it or a zero.
 */
data class Chart(
    val title: String,
    val unit: String,
    /** Runs of points with no gap between them, oldest first. */
    val runs: List<List<ChartPoint>>,
    val from: Double,
    val to: Double,
    val yTicks: List<Double>,
    val timeTicks: List<Double>,
    /** Time ticks are days (a week shown) rather than clock times. */
    val days: Boolean,
    val guide: ChartGuide?,
    /** What to say instead of a graph when nothing was measured. */
    val empty: String?,
    /** A value as text; axis = true for a tick label. */
    val format: (Double, Boolean) -> String,
) {
    val top: Double get() = yTicks.last()
    val points: List<ChartPoint> get() = runs.flatten()

    /** For screen readers: the latest value and the lowest and highest. */
    fun summary(strings: Strings): String {
        val values = points.map { it.value }
        if (values.isEmpty()) return "$title: ${empty.orEmpty()}"
        return strings.t(
            "chart.aria",
            "title" to title,
            "latest" to format(values.last(), false),
            "low" to format(values.min(), false),
            "high" to format(values.max(), false),
        )
    }
}

object Charts {
    /** The ranges offered, in hours. */
    val RANGES = listOf(1, 6, 24, 168)
    const val DEFAULT_RANGE = 6

    fun rangeKey(hours: Int): String = "perf.range_$hours"

    /** A missing bucket or two is jitter; more than that is a gap. */
    fun gap(bucketSeconds: Double, sampleInterval: Double): Double = maxOf(bucketSeconds * 2.5, sampleInterval * 3)

    /** Runs of consecutive measured points with no gap between them. */
    fun segments(points: List<Pair<Double, Double?>>, gap: Double): List<List<ChartPoint>> {
        val runs = mutableListOf<List<ChartPoint>>()
        var run = mutableListOf<ChartPoint>()
        var last: Double? = null
        for ((ts, value) in points) {
            if (value == null || value.isNaN()) {
                if (run.isNotEmpty()) runs += run
                run = mutableListOf()
                last = null
                continue
            }
            if (last != null && ts - last > gap) {
                runs += run
                run = mutableListOf()
            }
            run += ChartPoint(ts, value)
            last = ts
        }
        if (run.isNotEmpty()) runs += run
        return runs
    }

    /** Round numbers for a value axis: 0 to at least [max], in 4 or 5 steps. */
    fun niceTicks(max: Double): List<Double> {
        if (!(max > 0)) return listOf(0.0, 1.0)
        val rough = max / 4
        val power = 10.0.pow(floor(log10(rough)))
        val step = listOf(1.0, 2.0, 2.5, 5.0, 10.0).map { it * power }.first { it >= rough }
        val ticks = mutableListOf<Double>()
        var v = 0.0
        while (v < max + step * 0.999) {
            ticks += (v * 1e6).roundToLong() / 1e6
            v += step
        }
        return ticks
    }

    /** Clock ticks on whole quarter hours, hours, 4 hours or local
     * midnights, whichever suits the range; true when they are days. */
    fun timeTicks(from: Double, to: Double, zone: java.time.ZoneId = java.time.ZoneId.systemDefault()): Pair<List<Double>, Boolean> {
        val span = to - from
        val step = when {
            span <= 2 * 3600 -> 900L
            span <= 8 * 3600 -> 3600L
            span <= 30 * 3600 -> 4 * 3600L
            else -> 86400L
        }
        val ticks = mutableListOf<Double>()
        val start = java.time.Instant.ofEpochMilli((from * 1000).toLong()).atZone(zone)
        if (step == 86400L) {
            var day = start.toLocalDate().plusDays(1).atStartOfDay(zone)
            while (day.toEpochSecond() <= to) {
                ticks += day.toEpochSecond().toDouble()
                day = day.toLocalDate().plusDays(1).atStartOfDay(zone)
            }
            return ticks to true
        }
        val offset = start.offset.totalSeconds
        var tick = ceil((from + offset) / step) * step - offset
        while (tick <= to) {
            ticks += tick
            tick += step
        }
        return ticks to false
    }

    /**
     * The Performance graphs for [perf], drawn up to [now]: CPU, the
     * server's memory, game speed and players; with Technical words also
     * time per tick and the PC's memory. [speedReported] is the server
     * type's speed capability (false on Bedrock).
     */
    fun performance(
        strings: Strings,
        perf: Performance,
        now: Double,
        speedReported: Boolean?,
        zone: java.time.ZoneId = java.time.ZoneId.systemDefault(),
    ): List<Chart> {
        val points = perf.series.points
        val to = now
        val from = to - perf.series.hours * 3600
        val gap = gap(perf.series.bucketSeconds, perf.sampleInterval)
        val (tTicks, days) = timeTicks(from, to, zone)

        fun chart(
            pick: (SeriesPoint) -> Double?,
            title: String,
            unit: String,
            format: (Double, Boolean) -> String,
            max: Double?,
            ticks: ((Double) -> List<Double>)? = null,
            guide: ChartGuide? = null,
            empty: String? = null,
        ): Chart {
            val runs = segments(points.map { it.ts to pick(it) }, gap)
            val values = runs.flatten().map { it.value }
            val yMax = max ?: ((values + listOfNotNull(guide?.value)).maxOrNull() ?: 0.0) * 1.1
            return Chart(
                title = title,
                unit = unit,
                runs = runs,
                from = from,
                to = to,
                yTicks = ticks?.invoke(yMax) ?: niceTicks(yMax),
                timeTicks = tTicks,
                days = days,
                guide = guide,
                empty = if (values.isEmpty()) empty ?: strings.t("chart.no_samples") else null,
                format = format,
            )
        }

        val limit = perf.memoryLimitMb
        val peak = (points.mapNotNull { it.procRamMb } + listOfNotNull(limit, 0.0)).max()
        val useGb = peak >= 1536
        val memory = memoryFormat(useGb)
        val charts = mutableListOf(
            chart(
                { it.cpuPercent }, strings.t("perf.chart_cpu"), "%",
                { v, _ -> "${Display.fixed(v, 0)}%" }, max = 100.0, ticks = { listOf(0.0, 25.0, 50.0, 75.0, 100.0) },
            ),
            chart(
                { it.procRamMb }, strings.t("perf.chart_memory"), if (useGb) "GB" else "MB", memory, max = null,
                // Round gigabytes on the axis, not round megabytes shown as GB.
                ticks = { top -> if (useGb) niceTicks(top / 1024).map { it * 1024 } else niceTicks(top) },
                guide = limit?.let { ChartGuide(it, strings.t("perf.limit", "limit" to memory(it, false))) },
                empty = strings.t("perf.memory_empty"),
            ),
            chart(
                { it.tps }, strings.t("perf.chart_speed"), strings.t("perf.speed_unit"),
                { v, axis -> if (axis) whole(v) else "${Display.fixed(v, 1)} / 20" },
                max = 20.0, ticks = { listOf(0.0, 5.0, 10.0, 15.0, 20.0) },
                // Bedrock servers report no speed: said instead of an empty graph.
                empty = strings.t(if (speedReported == false) "perf.speed_not_bedrock" else "perf.speed_empty"),
            ),
            chart(
                { it.players }, strings.t("perf.chart_players"), strings.t("perf.players_unit"),
                { v, axis -> if (axis) whole(v) else whole((v * 10).roundToLong() / 10.0) },
                max = maxOf(4.0, points.mapNotNull { it.playersMax }.maxOrNull() ?: 0.0),
                empty = strings.t("perf.players_empty"),
            ),
        )
        if (strings.technical) {
            charts += chart(
                { it.mspt }, strings.t("perf.chart_mspt"), "ms",
                { v, axis -> "${if (axis) Display.fixed(v, 0) else Display.fixed(v, 1)} ms" }, max = null,
                guide = ChartGuide(50.0, strings.t("perf.mspt_budget")),
                empty = strings.t("perf.speed_empty"),
            )
            val total = points.mapNotNull { it.ramTotalMb }.maxOrNull() ?: 0.0
            charts += chart(
                { it.ramUsedMb }, strings.t("perf.chart_pc_memory"), "GB",
                { v, axis -> "${Display.fixed(v / 1024, if (axis) 0 else 1)} GB" }, max = null,
                ticks = { top -> niceTicks(maxOf(top, total) / 1024).map { it * 1024 } },
            )
        }
        return charts
    }

    /** A time tick's label: "Fri 9" for days, else "2:00 PM" in the phone's way. */
    fun axisLabel(
        ts: Double,
        days: Boolean,
        zone: java.time.ZoneId = java.time.ZoneId.systemDefault(),
        locale: java.util.Locale = java.util.Locale.getDefault(),
    ): String {
        val at = java.time.Instant.ofEpochMilli((ts * 1000).toLong()).atZone(zone)
        val format = if (days) java.time.format.DateTimeFormatter.ofPattern("EEE d", locale)
        else java.time.format.DateTimeFormatter.ofLocalizedTime(java.time.format.FormatStyle.SHORT).withLocale(locale)
        return at.format(format)
    }

    /** A touched point's time: with the weekday when more than a day is shown. */
    fun pointLabel(
        ts: Double,
        span: Double,
        zone: java.time.ZoneId = java.time.ZoneId.systemDefault(),
        locale: java.util.Locale = java.util.Locale.getDefault(),
    ): String {
        val at = java.time.Instant.ofEpochMilli((ts * 1000).toLong()).atZone(zone)
        val clock = at.format(java.time.format.DateTimeFormatter.ofLocalizedTime(java.time.format.FormatStyle.SHORT).withLocale(locale))
        return if (span > 30 * 3600) at.format(java.time.format.DateTimeFormatter.ofPattern("EEE", locale)) + " " + clock else clock
    }

    /** The point nearest in time to [ts], for reading a graph by touch. */
    fun nearest(points: List<ChartPoint>, ts: Double): ChartPoint? = points.minByOrNull { kotlin.math.abs(it.ts - ts) }

    /** Memory in MB, or GB once the graph reaches 1.5 GB. */
    fun memoryFormat(useGb: Boolean): (Double, Boolean) -> String = { v, axis ->
        if (useGb) {
            val gb = v / 1024
            "${Display.fixed(gb, if (axis && gb % 1 == 0.0) 0 else 1)} GB"
        } else {
            "${Display.fixed(v, 0)} MB"
        }
    }

    /** 2 rather than 2.0; 2.5 stays 2.5. */
    private fun whole(v: Double): String = if (v % 1 == 0.0) v.toLong().toString() else v.toString()
}
