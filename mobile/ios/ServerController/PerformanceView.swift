import Charts
import Core
import SwiftUI

/// How the PC and the server are doing: the values now, graphs over the
/// chosen time with real axes and gaps where nothing was measured, the disk
/// use, and the health checks. A value nobody measured reads Unknown.
struct PerformanceView: View {
    let serverId: String

    @Environment(AppModel.self) private var model

    private var world: WorldPages { model.pages(serverId).world }

    var body: some View {
        let world = self.world
        ServerFrame(serverId: serverId, title: model.t("page.performance")) { palette in
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    Picker(model.t("page.performance"), selection: Binding(get: { world.range }, set: { hours in
                        Task { await world.showRange(hours) }
                    })) {
                        ForEach(Graphs.RANGES, id: \.self) { hours in
                            Text(model.t(Graphs.rangeKey(hours))).tag(hours)
                        }
                    }
                    .pickerStyle(.segmented)
                    content(world, palette)
                    health(world, palette)
                }
                .padding(16)
                .frame(maxWidth: 640)
                .frame(maxWidth: .infinity)
            }
            .refreshable { await world.loadPerformance() }
        }
        .task(id: serverId) { await world.loadPerformance() }
    }

    @ViewBuilder
    private func content(_ world: WorldPages, _ palette: Palette) -> some View {
        if let problem = world.performance.problem {
            // The values now are a current state: not shown after a failed read.
            ProblemCard(problem: problem, palette: palette) { await world.loadPerformance() }
        } else if let data = world.performance.value {
            let speed = model.servers.first(where: { $0.id == serverId })?.capabilities?.speed
            nowCard(data, palette)
            SectionTitle(text: model.t("mobile.perf.graphs"), palette: palette)
            ForEach(Graphs.performance(model.strings, data, now: world.readAt, speedReported: speed)) { graph in
                GraphCard(graph: graph, palette: palette)
            }
            Hint(text: model.t("mobile.perf.touch"), palette: palette)
            storage(data, palette)
        } else {
            ProgressView().frame(maxWidth: .infinity)
        }
    }

    @ViewBuilder
    private func nowCard(_ data: Performance, _ palette: Palette) -> some View {
        let strings = model.strings
        let c = data.current
        let serverMemory = Display.memory(c.procRamMb)
        SectionTitle(text: model.t("mobile.perf.now"), palette: palette)
        CardBox(palette: palette) {
            ValueRow(title: model.t("perf.pc_cpu"), note: model.t("perf.pc_cpu_note"), value: Display.pct(strings, c.cpuPercent), palette: palette)
            ValueRow(
                title: model.t("perf.server_cpu"), note: model.t("perf.server_cpu_note"),
                value: Display.pct(strings, c.processCpuPercent), palette: palette
            )
            ValueRow(
                title: model.t("perf.server_memory"),
                note: serverMemory == nil
                    ? model.t("perf.not_running_note")
                    : data.memoryLimitMb.flatMap { Display.memory($0) }.map { model.t("perf.of_limit", ["limit": $0]) },
                value: serverMemory ?? model.t("value.unknown"), palette: palette
            )
            ValueRow(title: model.t("perf.pc_memory"), note: model.t("perf.pc_memory_note"), value: Display.pct(strings, c.ramPercent), palette: palette)
            ValueRow(
                title: model.t("perf.disk_free"),
                note: c.diskFreeGb != nil || c.diskUnknownReason == nil ? model.t("perf.on_server_drive") : c.diskUnknownReason,
                value: Display.gb(strings, c.diskFreeGb), palette: palette
            )
        }
    }

    @ViewBuilder
    private func storage(_ data: Performance, _ palette: Palette) -> some View {
        let strings = model.strings
        if let s = data.storage {
            SectionTitle(text: model.t("perf.storage"), palette: palette)
            CardBox(palette: palette) {
                ValueRow(title: model.t("perf.storage_worlds"), value: Display.gb(strings, s.worldsGb), palette: palette)
                ValueRow(title: model.t("perf.storage_backups"), value: Display.gb(strings, s.backupsGb), palette: palette)
                ValueRow(title: model.t("perf.storage_mods"), value: Display.gb(strings, s.modsGb), palette: palette)
                ValueRow(title: model.t("perf.storage_logs"), value: Display.gb(strings, s.logsGb), palette: palette)
                ValueRow(title: model.t("perf.storage_other"), value: Display.gb(strings, s.otherGb), palette: palette)
                ValueRow(
                    title: model.t("perf.storage_free"),
                    note: s.freeGb == nil ? s.freeUnknownReason.map { model.t("perf.unknown_because", ["reason": $0]) } : nil,
                    value: Display.gb(strings, s.freeGb), palette: palette
                )
            }
        }
        if model.technical {
            let c = data.current
            SectionTitle(text: model.t("perf.network"), palette: palette)
            CardBox(palette: palette) {
                ValueRow(
                    title: model.t("perf.net_in"),
                    value: c.netRecvMbS.map { "\(Display.fixed($0, 2)) MB/s" } ?? model.t("value.unknown"), palette: palette
                )
                ValueRow(
                    title: model.t("perf.net_out"),
                    value: c.netSentMbS.map { "\(Display.fixed($0, 2)) MB/s" } ?? model.t("value.unknown"), palette: palette
                )
            }
        }
    }

    @ViewBuilder
    private func health(_ world: WorldPages, _ palette: Palette) -> some View {
        SectionTitle(text: model.t("perf.health"), palette: palette)
        if let problem = world.health.problem {
            ProblemCard(problem: problem, palette: palette) { await world.loadPerformance() }
        } else if let health = world.health.value {
            let overall = HealthChecks.overall(health.overall)
            CardBox(palette: palette) {
                ValueRow(
                    title: overall.map { model.t($0.key) } ?? health.overall,
                    note: health.note.flatMap { $0.trimmingCharacters(in: .whitespaces).isEmpty ? nil : $0 },
                    dot: palette.tone(overall?.tone ?? .neutral), palette: palette
                )
                ForEach(health.checks) { check in
                    let detail = HealthChecks.detail(model.strings, check)
                    ValueRow(
                        title: check.name, note: detail.isEmpty ? nil : detail,
                        value: HealthChecks.value(model.strings, check),
                        dot: palette.tone(HealthChecks.tone(check.status)), palette: palette
                    )
                }
            }
        } else {
            ProgressView().frame(maxWidth: .infinity)
        }
    }
}

/// A name with a note under it and its value on the right.
private struct ValueRow: View {
    let title: String
    var note: String? = nil
    var value: String? = nil
    var dot: Color? = nil
    let palette: Palette

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            if let dot = dot {
                Circle()
                    .fill(dot)
                    .frame(width: 10, height: 10)
                    .accessibilityHidden(true)
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(verbatim: title)
                    .foregroundStyle(palette.textPrimary)
                if let note = note {
                    Text(verbatim: note)
                        .font(.footnote)
                        .foregroundStyle(palette.textSecondary)
                }
            }
            Spacer(minLength: 8)
            if let value = value {
                Text(verbatim: value)
                    .fontWeight(.medium)
                    .foregroundStyle(palette.textPrimary)
                    .multilineTextAlignment(.trailing)
            }
        }
        .frame(minHeight: 44)
        .accessibilityElement(children: .combine)
    }
}

/// One graph, drawn as the dashboard draws it: value ticks up the side,
/// clock ticks along the bottom, a dashed guide for a limit, a line broken
/// wherever there was no sample. Touch or drag along it to read a point.
private struct GraphCard: View {
    let graph: Graph
    let palette: Palette

    @Environment(AppModel.self) private var model
    @State private var touched: Date?

    var body: some View {
        CardBox(palette: palette) {
            HStack(alignment: .firstTextBaseline) {
                Text(graph.title)
                    .fontWeight(.medium)
                    .foregroundStyle(palette.textPrimary)
                Spacer()
                Text(verbatim: graph.unit)
                    .font(.caption)
                    .foregroundStyle(palette.textSecondary)
            }
            if let empty = graph.empty {
                Hint(text: empty, palette: palette)
            } else {
                let point = touched.flatMap { Graphs.nearest(graph.points, $0.timeIntervalSince1970) }
                Text(verbatim: point.map(reading) ?? " ")
                    .font(.footnote)
                    .foregroundStyle(palette.textSecondary)
                chart(point)
            }
        }
    }

    private func reading(_ point: GraphPoint) -> String {
        model.t("mobile.perf.point", [
            "value": graph.format(point.value, false),
            "time": Graphs.pointLabel(point.ts, span: graph.to - graph.from),
        ])
    }

    /// Up to five time labels, so they never run into each other.
    private var timeTicks: [Date] {
        let every = Swift.max(1, Int((Double(graph.timeTicks.count) / 5).rounded(.up)))
        return graph.timeTicks.enumerated().filter { $0.offset % every == 0 }.map { Date(timeIntervalSince1970: $0.element) }
    }

    private func chart(_ point: GraphPoint?) -> some View {
        let line = palette.accentInk
        return Chart {
            ForEach(Array(graph.runs.enumerated()), id: \.offset) { index, run in
                if run.count == 1, let only = run.first {
                    PointMark(x: .value("Time", Date(timeIntervalSince1970: only.ts)), y: .value("Value", only.value))
                        .symbolSize(20)
                        .foregroundStyle(line)
                } else {
                    ForEach(run, id: \.ts) { p in
                        LineMark(
                            x: .value("Time", Date(timeIntervalSince1970: p.ts)),
                            y: .value("Value", Swift.min(Swift.max(p.value, 0), graph.top)),
                            series: .value("Run", index)
                        )
                        .lineStyle(StrokeStyle(lineWidth: 2))
                        .foregroundStyle(line)
                    }
                }
            }
            if let guide = graph.guide, guide.value <= graph.top {
                RuleMark(y: .value("Guide", guide.value))
                    .lineStyle(StrokeStyle(lineWidth: 1.5, dash: [5, 4]))
                    .foregroundStyle(palette.textSecondary)
                    .annotation(position: .top, alignment: .trailing) {
                        Text(verbatim: guide.label)
                            .font(.caption2)
                            .foregroundStyle(palette.textSecondary)
                    }
            }
            if let point = point {
                RuleMark(x: .value("Time", Date(timeIntervalSince1970: point.ts)))
                    .lineStyle(StrokeStyle(lineWidth: 1))
                    .foregroundStyle(palette.textSecondary)
                PointMark(x: .value("Time", Date(timeIntervalSince1970: point.ts)), y: .value("Value", Swift.min(point.value, graph.top)))
                    .symbolSize(60)
                    .foregroundStyle(line)
            }
        }
        .chartXScale(domain: Date(timeIntervalSince1970: graph.from)...Date(timeIntervalSince1970: graph.to))
        .chartYScale(domain: 0...graph.top)
        .chartYAxis {
            AxisMarks(position: .leading, values: graph.yTicks) { value in
                AxisGridLine()
                AxisValueLabel {
                    if let v = value.as(Double.self) {
                        Text(verbatim: graph.format(v, true))
                    }
                }
            }
        }
        .chartXAxis {
            AxisMarks(values: timeTicks) { value in
                AxisGridLine()
                AxisValueLabel {
                    if let date = value.as(Date.self) {
                        Text(verbatim: Graphs.axisLabel(date.timeIntervalSince1970, days: graph.days))
                    }
                }
            }
        }
        .chartXSelection(value: $touched)
        .frame(height: 180)
        .accessibilityLabel(graph.summary(model.strings))
    }
}
