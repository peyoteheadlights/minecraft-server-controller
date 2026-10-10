import Core
import SwiftUI

/// What happened on this server and the PC, newest first, live. Only each
/// event's words, level and time: the details it carries are never shown.
struct EventsView: View {
    let serverId: String

    @Environment(AppModel.self) private var model

    var body: some View {
        let pages = model.pages(serverId)
        let shown = pages.events.value?.filter { Display.worthShowing($0.type, technical: model.technical) }
        ServerFrame(serverId: serverId, title: model.t("page.events")) { palette in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 8) {
                    if let problem = pages.events.problem {
                        ProblemCard(problem: problem, palette: palette) { await pages.loadEvents() }
                    } else if let shown = shown {
                        if shown.isEmpty {
                            EmptyCard(title: model.t("events.none"), palette: palette)
                        }
                        TimelineView(.periodic(from: .now, by: 30)) { context in
                            LazyVStack(alignment: .leading, spacing: 8) {
                                ForEach(Array(shown.enumerated()), id: \.offset) { _, event in
                                    row(event, palette, now: context.date.timeIntervalSince1970)
                                }
                            }
                        }
                    } else {
                        ProgressView().frame(maxWidth: .infinity)
                    }
                }
                .padding(16)
                .frame(maxWidth: 640)
                .frame(maxWidth: .infinity)
            }
            .refreshable { await pages.loadEvents() }
        }
        .task(id: serverId) { await pages.loadEvents() }
    }

    private func row(_ event: EventRow, _ palette: Palette, now: Double) -> some View {
        CardBox(palette: palette) {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Circle()
                    .fill(palette.tone(Display.eventTone(event.level)))
                    .frame(width: 10, height: 10)
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 2) {
                    Text(verbatim: event.message.isEmpty ? event.type : event.message)
                        .foregroundStyle(palette.textPrimary)
                    Text(Display.ago(model.strings, event.ts, now: now))
                        .font(.footnote)
                        .foregroundStyle(palette.textSecondary)
                }
            }
            .accessibilityElement(children: .combine)
        }
    }
}

/// The crashes the agent recorded, with its best guess at each cause.
struct CrashesView: View {
    let serverId: String

    @Environment(AppModel.self) private var model

    var body: some View {
        let pages = model.pages(serverId)
        ServerFrame(serverId: serverId, title: model.t("page.crashes")) { palette in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 8) {
                    if let problem = pages.crashes.problem {
                        ProblemCard(problem: problem, palette: palette) { await pages.loadCrashes() }
                    } else if let crashes = pages.crashes.value {
                        if crashes.isEmpty {
                            EmptyCard(title: model.t("crashes.none"), palette: palette)
                        }
                        ForEach(crashes, id: \.id) { crash in
                            NavigationLink(value: ServerRoute.crash(serverId, crash.id)) {
                                CardBox(palette: palette) {
                                    Text(crashWhen(crash, model.strings))
                                        .font(.headline)
                                        .foregroundStyle(palette.textPrimary)
                                    Text(crashLine(crash))
                                        .font(.footnote)
                                        .foregroundStyle(palette.textSecondary)
                                }
                            }
                            .buttonStyle(.plain)
                        }
                    } else {
                        ProgressView().frame(maxWidth: .infinity)
                    }
                }
                .padding(16)
                .frame(maxWidth: 640)
                .frame(maxWidth: .infinity)
            }
            .refreshable { await pages.loadCrashes() }
        }
        .task(id: serverId) { await pages.loadCrashes() }
    }

    private func crashLine(_ crash: Crash) -> String {
        [
            Display.cause(model.strings, crash.category),
            model.t(Display.confidence(crash.confidence).key),
            model.t("crashes.col_code") + " " + Display.exitCode(model.strings, crash.exitCode),
        ].joined(separator: " · ")
    }
}

/// One crash: the cause, the lines that point to it, what was known then,
/// and the end of the saved log.
struct CrashView: View {
    let serverId: String
    let crashId: Int64

    @Environment(AppModel.self) private var model

    var body: some View {
        let pages = model.pages(serverId)
        let crash = pages.crash.value.flatMap { $0.id == crashId ? $0 : nil }
        let title = crash.map { model.t("crashes.dialog_title", ["when": crashWhen($0, model.strings)]) } ?? model.t("page.crashes")
        ServerFrame(serverId: serverId, title: title) { palette in
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    if let problem = pages.crash.problem {
                        ProblemCard(problem: problem, palette: palette) { await pages.openCrash(crashId) }
                    } else if let crash = crash {
                        details(crash, palette)
                    } else {
                        ProgressView().frame(maxWidth: .infinity)
                    }
                }
                .padding(16)
                .frame(maxWidth: 640)
                .frame(maxWidth: .infinity)
            }
            .refreshable { await pages.openCrash(crashId) }
        }
        .task(id: crashId) { await pages.openCrash(crashId) }
    }

    @ViewBuilder
    private func details(_ crash: Crash, _ palette: Palette) -> some View {
        let unknown = model.t("value.unknown")
        let analysis = crash.context?.analysis
        CardBox(palette: palette) {
            field(model.t("crashes.col_cause"), Display.cause(model.strings, crash.category), palette)
            field(model.t("crashes.col_confidence"), model.t(Display.confidence(crash.confidence).key), palette)
            field(model.t("crashes.col_code"), Display.exitCode(model.strings, crash.exitCode), palette)
            if let summary = crash.summary, !summary.isEmpty {
                Text(verbatim: summary).foregroundStyle(palette.textPrimary)
            }
            if let advice = analysis?.advice, !advice.isEmpty {
                Text(verbatim: advice).foregroundStyle(palette.textPrimary)
            }
            if let mods = analysis?.suspectMods, !mods.isEmpty {
                Text(model.t("crashes.suspect_mods") + mods.joined(separator: ", ") + model.t("crashes.suspect_hint"))
                    .foregroundStyle(palette.textPrimary)
            }
            Text(model.t("crashes.rule_match"))
                .font(.footnote)
                .foregroundStyle(palette.textSecondary)
        }
        if !crash.evidence.isEmpty {
            heading(model.t("crashes.evidence"), palette)
            CardBox(palette: palette) { mono(crash.evidence, palette) }
        }
        if let context = crash.context {
            heading(model.t("crashes.context"), palette)
            CardBox(palette: palette) {
                field(model.t("crashes.f_minecraft"), context.minecraftVersion ?? unknown, palette)
                if let loader = context.fabricLoader {
                    field(model.t("crashes.f_loader"), loader, palette)
                }
                field(model.t("crashes.f_java"), context.javaVersion ?? unknown, palette)
                field(model.t("crashes.f_players"), players(context.playersOnline), palette)
                field(model.t("crashes.f_report"), context.crashReport ?? model.t("crashes.no_report"), palette)
                if let log = context.logFile {
                    field(model.t("crashes.f_log"), log, palette)
                }
            }
        }
        heading(model.t("mobile.crash.log_tail"), palette)
        CardBox(palette: palette) {
            if let tail = crash.logTail, !tail.isEmpty {
                mono(tail, palette)
            } else {
                Text(model.t("mobile.crash.log_gone")).foregroundStyle(palette.textSecondary)
            }
        }
    }

    private func players(_ names: [String]?) -> String {
        guard let names = names else { return model.t("value.unknown") }
        return names.isEmpty ? model.t("crashes.no_players") : names.joined(separator: ", ")
    }

    private func field(_ label: String, _ value: String, _ palette: Palette) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label)
                .font(.footnote)
                .foregroundStyle(palette.textSecondary)
            Text(verbatim: value)
                .foregroundStyle(palette.textPrimary)
                .textSelection(.enabled)
        }
        .accessibilityElement(children: .combine)
    }

    private func heading(_ text: String, _ palette: Palette) -> some View {
        Text(text)
            .font(.headline)
            .foregroundStyle(palette.textPrimary)
            .padding(.top, 8)
            .accessibilityAddTraits(.isHeader)
    }

    private func mono(_ lines: [String], _ palette: Palette) -> some View {
        ScrollView(.horizontal) {
            Text(verbatim: lines.joined(separator: "\n"))
                .font(.system(.footnote, design: .monospaced))
                .foregroundStyle(palette.textPrimary)
                .textSelection(.enabled)
                .fixedSize()
        }
    }
}

/// "2026-10-10 14:05:09" in the phone's time zone, or Unknown.
func crashWhen(_ crash: Crash, _ strings: Strings) -> String {
    crash.ts.map { Display.dateTime($0) } ?? strings.t("value.unknown")
}
