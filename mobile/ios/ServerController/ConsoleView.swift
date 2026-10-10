import Core
import SwiftUI

/// The server's console: the newest lines, live, with a filter and level
/// chips. The owner gets a command box (commands go to Minecraft only,
/// never Windows; risky ones ask first) and Clear. Helpers read only.
struct ConsoleView: View {
    let serverId: String

    @Environment(AppModel.self) private var model
    @State private var filter = ""
    @State private var chip = LevelChip.all
    // The typed command stays in memory only.
    @State private var command = ""
    @State private var atBottom = true

    private let bottom = "bottom"

    private var pages: ServerPages { model.pages(serverId) }

    var body: some View {
        let pages = self.pages
        ServerFrame(serverId: serverId, title: model.t("page.console")) { palette in
            VStack(spacing: 0) {
                header
                lineList(palette)
            }
            .safeAreaInset(edge: .bottom) { bottomBar(palette) }
            .toolbar { clearButton }
            .alert(
                model.t("console.run_title", ["command": pages.asking?.command ?? ""]),
                isPresented: asking,
                presenting: pages.asking,
                actions: { step in confirmButtons(step.command) },
                message: { step in Text(step.reason) }
            )
        }
        .task(id: serverId) { await pages.loadConsole() }
    }

    // MARK: - Parts

    private var header: some View {
        VStack(spacing: 8) {
            TextField(model.t("console.filter_label"), text: $filter)
                .textFieldStyle(.roundedBorder)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
            Picker(model.t("console.filter_label"), selection: $chip) {
                ForEach(LevelChip.allCases, id: \.self) { option in
                    Text(model.t(option.key)).tag(option)
                }
            }
            .pickerStyle(.segmented)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 8)
    }

    private func lineList(_ palette: Palette) -> some View {
        let pages = self.pages
        let lines = ConsoleBuffer.shown(pages.console.value ?? [], filter: filter, chip: chip)
        return ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 2) {
                    note(palette, shown: lines.count)
                    ForEach(Array(lines.enumerated()), id: \.offset) { _, line in
                        Text(verbatim: line.raw)
                            .font(.system(.footnote, design: .monospaced))
                            .foregroundStyle(color(ConsoleBuffer.look(line), palette))
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    // On screen while the newest line is: new lines then keep
                    // it in view; scrolling up stops that.
                    Color.clear
                        .frame(height: 1)
                        .id(bottom)
                        .onAppear { atBottom = true }
                        .onDisappear { atBottom = false }
                }
                .padding(16)
            }
            .refreshable { await pages.loadConsole() }
            .onChange(of: lines.last) {
                if atBottom { proxy.scrollTo(bottom, anchor: .bottom) }
            }
            .overlay(alignment: .bottom) {
                if !atBottom && !lines.isEmpty {
                    Button {
                        withAnimation { proxy.scrollTo(bottom, anchor: .bottom) }
                    } label: {
                        Label(model.t("mobile.console.jump"), systemImage: "arrow.down")
                            .padding(.horizontal, 14)
                            .padding(.vertical, 8)
                            .background(palette.surface, in: Capsule())
                            .foregroundStyle(palette.accentInk)
                    }
                    .buttonStyle(.plain)
                    .padding(.bottom, 12)
                }
            }
        }
    }

    /// Loading, a problem, or why no line shows.
    @ViewBuilder
    private func note(_ palette: Palette, shown: Int) -> some View {
        let pages = self.pages
        if let problem = pages.console.problem {
            ProblemCard(problem: problem, palette: palette) { await pages.loadConsole() }
        } else if let all = pages.console.value {
            if all.isEmpty {
                EmptyCard(title: model.t("console.empty"), hint: model.t("console.empty_hint"), palette: palette)
            } else if shown == 0 {
                EmptyCard(
                    title: model.t("console.no_match"),
                    hint: model.t("console.no_match_hint", ["filter": filter.trimmingCharacters(in: .whitespaces)]),
                    palette: palette
                )
            }
        } else {
            ProgressView().frame(maxWidth: .infinity)
        }
    }

    @ViewBuilder
    private func bottomBar(_ palette: Palette) -> some View {
        if model.can(Permissions.CONSOLE_SEND) {
            commandBox(palette)
        } else {
            InputBar(palette: palette, notes: [model.t("mobile.console.owner_only")]) { EmptyView() }
        }
    }

    private func commandBox(_ palette: Palette) -> some View {
        let pages = self.pages
        let busy = pages.sending
        return InputBar(palette: palette, problem: pages.commandProblem, notes: [model.t("console.hint")]) {
            if !pages.history.isEmpty {
                Menu {
                    // Newest first.
                    ForEach(pages.history.reversed(), id: \.self) { previous in
                        Button(previous) { command = previous }
                    }
                } label: {
                    Image(systemName: "clock.arrow.circlepath")
                        .frame(minWidth: 44, minHeight: 44)
                }
                .accessibilityLabel(model.t("mobile.console.previous"))
            }
            TextField(model.t("console.command_placeholder"), text: $command)
                .font(.system(.body, design: .monospaced))
                .textFieldStyle(.roundedBorder)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .submitLabel(.send)
                .accessibilityLabel(model.t("console.command_label"))
                .onSubmit { send() }
                .onChange(of: command) {
                    if command.count > ConsoleCommands.MAX_LENGTH {
                        command = String(command.prefix(ConsoleCommands.MAX_LENGTH))
                    }
                }
            Button(model.t(busy ? "console.sending" : "console.send")) { send() }
                .buttonStyle(.borderedProminent)
                .disabled(busy || command.trimmingCharacters(in: .whitespaces).isEmpty)
        }
    }

    private var clearButton: some ToolbarContent {
        ToolbarItem(placement: .topBarTrailing) {
            if model.can(Permissions.CONSOLE_SEND) {
                Button(model.t("console.clear")) {
                    let pages = self.pages
                    Task { await pages.clearConsole(model.strings) }
                }
            }
        }
    }

    // MARK: - Sending

    private var asking: Binding<Bool> {
        let pages = self.pages
        return Binding(
            get: { pages.asking != nil },
            set: { shown in
                if !shown { pages.asking = nil }
            }
        )
    }

    @ViewBuilder
    private func confirmButtons(_ asked: String) -> some View {
        Button(model.t("console.run"), role: .destructive) {
            let pages = self.pages
            Task {
                if await pages.confirmCommand(asked, model.strings) { command = "" }
            }
        }
        Button(model.t("mobile.common.cancel"), role: .cancel) {}
    }

    private func send() {
        let pages = self.pages
        guard !pages.sending else { return }
        let typed = command
        Task {
            if await pages.submitCommand(typed, model.strings) { command = "" }
        }
    }

    private func color(_ look: LineLook, _ palette: Palette) -> Color {
        switch look {
        case .warning: return palette.tone(.warning)
        case .danger: return palette.tone(.danger)
        case .command: return palette.accentInk
        case .plain: return palette.textPrimary
        }
    }
}
