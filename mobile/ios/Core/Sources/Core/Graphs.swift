import Foundation

// The Performance graphs' rules, as agent/web/js/charts.js draws them and
// mobile/android/core's Charts.kt works them out. Named Graph here so it
// doesn't clash with Swift Charts' own Chart.

/// One sample on a graph: its time and value.
public struct GraphPoint: Equatable, Sendable {
    public let ts: Double
    public let value: Double

    public init(ts: Double, value: Double) {
        self.ts = ts
        self.value = value
    }
}

/// A dashed reference line, such as the memory limit.
public struct GraphGuide: Equatable, Sendable {
    public let value: Double
    public let label: String
}

/// One graph, worked out and ready to draw: time along the bottom on clock
/// ticks, the value up the side on a fixed range where one exists, and a
/// gap wherever there is no sample, never a line drawn through it or a zero.
public struct Graph: Identifiable, Sendable {
    public let title: String
    public let unit: String
    /// Runs of points with no gap between them, oldest first.
    public let runs: [[GraphPoint]]
    public let from: Double
    public let to: Double
    public let yTicks: [Double]
    public let timeTicks: [Double]
    /// Time ticks are days (a week shown) rather than clock times.
    public let days: Bool
    public let guide: GraphGuide?
    /// What to say instead of a graph when nothing was measured.
    public let empty: String?
    /// A value as text; axis = true for a tick label.
    public let format: @Sendable (Double, Bool) -> String

    public var id: String { title }
    public var top: Double { yTicks.last ?? 1 }
    public var points: [GraphPoint] { runs.flatMap { $0 } }

    /// For VoiceOver: the latest value and the lowest and highest.
    public func summary(_ strings: Strings) -> String {
        let values = points.map(\.value)
        guard let last = values.last, let low = values.min(), let high = values.max() else {
            return "\(title): \(empty ?? "")"
        }
        return strings.t("chart.aria", [
            "title": title, "latest": format(last, false), "low": format(low, false), "high": format(high, false),
        ])
    }
}

public enum Graphs {
    /// The ranges offered, in hours.
    public static let RANGES = [1, 6, 24, 168]
    public static let DEFAULT_RANGE = 6

    public static func rangeKey(_ hours: Int) -> String {
        "perf.range_\(hours)"
    }

    /// A missing bucket or two is jitter; more than that is a gap.
    public static func gap(bucketSeconds: Double, sampleInterval: Double) -> Double {
        Swift.max(bucketSeconds * 2.5, sampleInterval * 3)
    }

    /// Runs of consecutive measured points with no gap between them.
    public static func segments(_ points: [(Double, Double?)], gap: Double) -> [[GraphPoint]] {
        var runs: [[GraphPoint]] = []
        var run: [GraphPoint] = []
        var last: Double?
        for (ts, value) in points {
            guard let value = value, !value.isNaN else {
                if !run.isEmpty { runs.append(run) }
                run = []
                last = nil
                continue
            }
            if let last = last, ts - last > gap {
                runs.append(run)
                run = []
            }
            run.append(GraphPoint(ts: ts, value: value))
            last = ts
        }
        if !run.isEmpty { runs.append(run) }
        return runs
    }

    /// Round numbers for a value axis: 0 to at least `max`, in 4 or 5 steps.
    public static func niceTicks(_ max: Double) -> [Double] {
        guard max > 0 else { return [0, 1] }
        let rough = max / 4
        let power = pow(10, floor(log10(rough)))
        let step = [1, 2, 2.5, 5, 10].map { $0 * power }.first { $0 >= rough } ?? rough
        var ticks: [Double] = []
        var v = 0.0
        while v < max + step * 0.999 {
            ticks.append((v * 1e6).rounded() / 1e6)
            v += step
        }
        return ticks
    }

    /// Clock ticks on whole quarter hours, hours, 4 hours or local
    /// midnights, whichever suits the range; true when they are days.
    public static func timeTicks(from: Double, to: Double, zone: TimeZone = .current) -> (ticks: [Double], days: Bool) {
        let span = to - from
        let step: Double = span <= 2 * 3600 ? 900 : span <= 8 * 3600 ? 3600 : span <= 30 * 3600 ? 4 * 3600 : 86400
        var ticks: [Double] = []
        if step == 86400 {
            var calendar = Calendar(identifier: .gregorian)
            calendar.timeZone = zone
            var day = calendar.startOfDay(for: Date(timeIntervalSince1970: from))
            while true {
                guard let next = calendar.date(byAdding: .day, value: 1, to: day) else { break }
                day = next
                if day.timeIntervalSince1970 > to { break }
                ticks.append(day.timeIntervalSince1970)
            }
            return (ticks, true)
        }
        let offset = Double(zone.secondsFromGMT(for: Date(timeIntervalSince1970: from)))
        var tick = ceil((from + offset) / step) * step - offset
        while tick <= to {
            ticks.append(tick)
            tick += step
        }
        return (ticks, false)
    }

    /// The Performance graphs for `perf`, drawn up to `now`: CPU, the
    /// server's memory, game speed and players; with Technical words also
    /// time per tick and the PC's memory. `speedReported` is the server
    /// type's speed capability (false on Bedrock).
    public static func performance(_ strings: Strings, _ perf: Performance, now: Double, speedReported: Bool?, zone: TimeZone = .current) -> [Graph] {
        let points = perf.series.points
        let to = now
        let from = to - perf.series.hours * 3600
        let gapSeconds = gap(bucketSeconds: perf.series.bucketSeconds, sampleInterval: perf.sampleInterval)
        let time = timeTicks(from: from, to: to, zone: zone)

        func graph(
            _ pick: (SeriesPoint) -> Double?, title: String, unit: String, format: @escaping @Sendable (Double, Bool) -> String,
            max: Double?, ticks: ((Double) -> [Double])? = nil, guide: GraphGuide? = nil, empty: String? = nil
        ) -> Graph {
            let runs = segments(points.map { ($0.ts, pick($0)) }, gap: gapSeconds)
            let values = runs.flatMap { $0 }.map(\.value)
            let yMax = max ?? ((values + [guide?.value].compactMap { $0 }).max() ?? 0) * 1.1
            return Graph(
                title: title, unit: unit, runs: runs, from: from, to: to,
                yTicks: ticks?(yMax) ?? niceTicks(yMax), timeTicks: time.ticks, days: time.days, guide: guide,
                empty: values.isEmpty ? (empty ?? strings.t("chart.no_samples")) : nil, format: format
            )
        }

        let limit = perf.memoryLimitMb
        let peak = (points.compactMap(\.procRamMb) + [limit ?? 0, 0]).max() ?? 0
        let useGb = peak >= 1536
        let memory = memoryFormat(useGb: useGb)
        var graphs = [
            graph(
                { $0.cpuPercent }, title: strings.t("perf.chart_cpu"), unit: "%",
                format: { v, _ in "\(Display.fixed(v, 0))%" }, max: 100, ticks: { _ in [0, 25, 50, 75, 100] }
            ),
            graph(
                { $0.procRamMb }, title: strings.t("perf.chart_memory"), unit: useGb ? "GB" : "MB", format: memory, max: nil,
                // Round gigabytes on the axis, not round megabytes shown as GB.
                ticks: { top in useGb ? niceTicks(top / 1024).map { $0 * 1024 } : niceTicks(top) },
                guide: limit.map { GraphGuide(value: $0, label: strings.t("perf.limit", ["limit": memory($0, false)])) },
                empty: strings.t("perf.memory_empty")
            ),
            graph(
                { $0.tps }, title: strings.t("perf.chart_speed"), unit: strings.t("perf.speed_unit"),
                format: { v, axis in axis ? whole(v) : "\(Display.fixed(v, 1)) / 20" },
                max: 20, ticks: { _ in [0, 5, 10, 15, 20] },
                // Bedrock servers report no speed: said instead of an empty graph.
                empty: strings.t(speedReported == false ? "perf.speed_not_bedrock" : "perf.speed_empty")
            ),
            graph(
                { $0.players }, title: strings.t("perf.chart_players"), unit: strings.t("perf.players_unit"),
                format: { v, axis in axis ? whole(v) : whole((v * 10).rounded() / 10) },
                max: Swift.max(4, points.compactMap(\.playersMax).max() ?? 0),
                empty: strings.t("perf.players_empty")
            ),
        ]
        if strings.technical {
            graphs.append(graph(
                { $0.mspt }, title: strings.t("perf.chart_mspt"), unit: "ms",
                format: { v, axis in "\(Display.fixed(v, axis ? 0 : 1)) ms" }, max: nil,
                guide: GraphGuide(value: 50, label: strings.t("perf.mspt_budget")),
                empty: strings.t("perf.speed_empty")
            ))
            let total = points.compactMap(\.ramTotalMb).max() ?? 0
            graphs.append(graph(
                { $0.ramUsedMb }, title: strings.t("perf.chart_pc_memory"), unit: "GB",
                format: { v, axis in "\(Display.fixed(v / 1024, axis ? 0 : 1)) GB" }, max: nil,
                ticks: { top in niceTicks(Swift.max(top, total) / 1024).map { $0 * 1024 } }
            ))
        }
        return graphs
    }

    /// Memory in MB, or GB once the graph reaches 1.5 GB.
    public static func memoryFormat(useGb: Bool) -> @Sendable (Double, Bool) -> String {
        { v, axis in
            if useGb {
                let gb = v / 1024
                return "\(Display.fixed(gb, axis && gb.truncatingRemainder(dividingBy: 1) == 0 ? 0 : 1)) GB"
            }
            return "\(Display.fixed(v, 0)) MB"
        }
    }

    /// A time tick's label: "Fri 9" for days, else "2:00 PM" in the phone's way.
    public static func axisLabel(_ ts: Double, days: Bool, zone: TimeZone = .current, locale: Locale = .current) -> String {
        WorldRestore.format(Date(timeIntervalSince1970: ts), template: days ? "EEEd" : "jmm", zone: zone, locale: locale)
    }

    /// A touched point's time: with the weekday when more than a day is shown.
    public static func pointLabel(_ ts: Double, span: Double, zone: TimeZone = .current, locale: Locale = .current) -> String {
        WorldRestore.format(Date(timeIntervalSince1970: ts), template: span > 30 * 3600 ? "EEEjmm" : "jmm", zone: zone, locale: locale)
    }

    /// The point nearest in time to `ts`, for reading a graph by touch.
    public static func nearest(_ points: [GraphPoint], _ ts: Double) -> GraphPoint? {
        points.min { abs($0.ts - ts) < abs($1.ts - ts) }
    }

    /// 2 rather than 2.0; 2.5 stays 2.5.
    static func whole(_ v: Double) -> String {
        v.truncatingRemainder(dividingBy: 1) == 0 && abs(v) < 1e15 ? String(Int64(v)) : String(v)
    }
}
