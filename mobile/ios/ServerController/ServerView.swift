import Core
import SwiftUI

/// One server, tinted with its color as the dashboard tints its pages: what
/// it's doing, for how long, who's playing, and Start, Stop or Restart.
struct ServerView: View {
    let serverId: String

    @Environment(AppModel.self) private var model
    @Environment(\.colorScheme) private var colorScheme
    @State private var status: ServerStatus?
    @State private var problem: AgentError?
    @State private var loaded = false
    @State private var working = false
    @State private var result: String?
    @State private var pending: QuickAction?

    private var row: ServerRow? {
        model.servers.first(where: { $0.id == serverId })
    }

    var body: some View {
        let palette = model.serverPalette(row?.color, colorScheme)
        let pages = model.pages(serverId)
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                header(palette)
                if let problem = problem {
                    card(palette) {
                        Label(problem.message(model.strings), systemImage: "exclamationmark.triangle")
                            .foregroundStyle(palette.tone(.warning))
                    }
                }
                actions(palette)
                players(palette)
                screens(palette)
                JoinCard(pages: pages, palette: palette)
                SuggestionsCard(pages: pages, palette: palette)
                ChecklistCard(pages: pages, palette: palette)
            }
            .padding(16)
            .frame(maxWidth: 640)
            .frame(maxWidth: .infinity)
        }
        .background(palette.sheet.ignoresSafeArea())
        .navigationTitle(row?.name ?? status?.name ?? serverId)
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(palette.sheet, for: .navigationBar)
        .refreshable {
            await load()
            await pages.loadCards()
        }
        .task(id: model.liveTick) {
            await load()
        }
        .task(id: serverId) {
            await pages.loadCards()
        }
        .onAppear { model.watch(serverId) }
        .onDisappear { model.unwatch(serverId) }
        .alert(confirmTitle, isPresented: confirming, presenting: pending) { action in
            Button(model.t(action.labelKey), role: action.danger ? .destructive : nil) {
                run(action)
            }
            Button(model.t("mobile.common.cancel"), role: .cancel) {}
        } message: { action in
            Text(confirmBody(action))
        }
    }

    // MARK: - Parts

    private func header(_ palette: Palette) -> some View {
        // Nothing old is shown as current: without a fresh read, Unknown.
        let state = status?.state ?? States.UNKNOWN
        let words = Display.state(state)
        return card(palette) {
            HStack(alignment: .center, spacing: 12) {
                ColorBadge(hex: row?.color, size: 18)
                Text(row?.name ?? status?.name ?? serverId)
                    .font(.title2.weight(.bold))
                    .foregroundStyle(palette.textPrimary)
            }
            HStack(spacing: 8) {
                Circle()
                    .fill(palette.tone(words.tone))
                    .frame(width: 10, height: 10)
                    .accessibilityHidden(true)
                Text(model.t(words.key))
                    .font(.headline)
                    .foregroundStyle(palette.tone(words.tone))
                if words.busy {
                    ProgressView()
                        .controlSize(.small)
                }
            }
            .accessibilityElement(children: .combine)
            if let uptime = Display.uptime(model.strings, state, status?.uptime) {
                Text(uptime)
                    .foregroundStyle(palette.textSecondary)
            }
            if state == States.RESTART_PENDING {
                Text(model.t("mobile.server.restart_pending"))
                    .foregroundStyle(palette.textSecondary)
            }
            if !loaded {
                ProgressView()
            }
        }
    }

    @ViewBuilder
    private func actions(_ palette: Palette) -> some View {
        let available = Display.actions(status?.state, canControl: model.canControl)
        if model.me != nil && !model.canControl {
            card(palette) {
                Text(model.t("mobile.server.not_allowed"))
                    .foregroundStyle(palette.textSecondary)
            }
        } else if !available.isEmpty || result != nil {
            card(palette) {
                ForEach(available, id: \.action) { action in
                    Button {
                        if action.confirm {
                            pending = action
                        } else {
                            run(action)
                        }
                    } label: {
                        Text(model.t(action.labelKey))
                            .font(.headline)
                            .frame(maxWidth: .infinity, minHeight: 44)
                            .foregroundStyle(action.danger ? palette.danger : palette.accentText)
                            .background(
                                action.danger ? palette.sunken : palette.accent,
                                in: RoundedRectangle(cornerRadius: 10)
                            )
                    }
                    .buttonStyle(.plain)
                    .disabled(working)
                }
                if working {
                    ProgressView()
                        .frame(maxWidth: .infinity)
                }
                if let result = result {
                    Text(result)
                        .foregroundStyle(palette.textPrimary)
                        .accessibilityAddTraits(.updatesFrequently)
                }
            }
        }
    }

    private func players(_ palette: Palette) -> some View {
        let online = status?.playersOnline
        let list = status?.players ?? []
        return card(palette) {
            HStack {
                Text(model.t("mobile.server.players_now"))
                    .font(.headline)
                    .foregroundStyle(palette.textPrimary)
                Spacer()
                Text(Display.players(model.strings, online, status?.maxPlayers))
                    .foregroundStyle(palette.textSecondary)
            }
            .accessibilityElement(children: .combine)
            if online == nil {
                Text(model.t("overview.players_unknown"))
                    .foregroundStyle(palette.textSecondary)
            } else if list.isEmpty {
                Text(model.t("mobile.server.nobody"))
                    .foregroundStyle(palette.textSecondary)
            } else {
                ForEach(list, id: \.username) { player in
                    HStack {
                        Image(systemName: "person.fill")
                            .foregroundStyle(palette.accentInk)
                            .accessibilityHidden(true)
                        Text(player.username)
                            .foregroundStyle(palette.textPrimary)
                        Spacer()
                        // The agent says 0 when it didn't see the join: not measured.
                        if player.sessionStarted != nil, let seconds = player.sessionSeconds {
                            Text(model.t("mobile.server.player_since", ["duration": Display.duration(model.strings, seconds)]))
                                .font(.footnote)
                                .foregroundStyle(palette.textSecondary)
                        }
                    }
                    .frame(minHeight: 44)
                    .accessibilityElement(children: .combine)
                }
            }
        }
    }

    /// Console, Chat, Players, Activity and Crashes.
    private func screens(_ palette: Palette) -> some View {
        card(palette) {
            ForEach(ServerPage.allCases, id: \.self) { page in
                NavigationLink(value: ServerRoute.page(serverId, page)) {
                    HStack {
                        Text(model.t(page.titleKey))
                            .foregroundStyle(palette.textPrimary)
                        Spacer()
                        Image(systemName: "chevron.right")
                            .font(.footnote.weight(.semibold))
                            .foregroundStyle(palette.textSecondary)
                            .accessibilityHidden(true)
                    }
                    .frame(minHeight: 44)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
        }
    }

    private func card<Content: View>(_ palette: Palette, @ViewBuilder _ content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            content()
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(palette.surface, in: RoundedRectangle(cornerRadius: 14))
        .overlay(
            RoundedRectangle(cornerRadius: 14)
                .strokeBorder(palette.accentEdge.opacity(0.35), lineWidth: 1)
        )
    }

    // MARK: - Confirming

    private var confirming: Binding<Bool> {
        Binding(
            get: { pending != nil },
            set: { shown in
                if !shown { pending = nil }
            }
        )
    }

    private var confirmTitle: String {
        switch pending?.action ?? "" {
        case "stop": return model.t("confirm.stop_title")
        case "restart": return model.t("confirm.restart_title")
        default: return ""
        }
    }

    private func confirmBody(_ action: QuickAction) -> String {
        switch action.action {
        case "stop": return model.t("confirm.stop_body")
        case "restart": return model.t("confirm.restart_body")
        default: return ""
        }
    }

    // MARK: - Reading and acting

    private func load() async {
        guard let client = model.client else { return }
        do {
            status = try await client.status(serverId: serverId)
            problem = nil
        } catch let error as AgentError {
            // Never keep showing an earlier reading as current.
            status = nil
            problem = error
        } catch {
            return
        }
        loaded = true
    }

    private func run(_ action: QuickAction) {
        pending = nil
        working = true
        result = nil
        Task {
            result = await model.perform(action.action, serverId: serverId)
            working = false
            await load()
        }
    }
}
