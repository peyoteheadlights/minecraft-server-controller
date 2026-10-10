import Core
import SwiftUI

/// A kick or ban waiting for "yes", with its optional reason.
private struct Asking {
    let action: String
    let name: String
}

/// Who is online, everyone seen, and Minecraft's whitelist, operators and
/// bans, with the dashboard's buttons. Each button is a console command;
/// the app says what the console answered, never that it worked when the
/// console didn't confirm it.
struct PlayersView: View {
    let serverId: String

    @Environment(AppModel.self) private var model
    @State private var asking: Asking?
    @State private var reason = ""
    @State private var typedName = ""

    private var pages: ServerPages { model.pages(serverId) }
    private var canManage: Bool { model.can(Permissions.PLAYERS_MANAGE) }
    private var canOp: Bool { model.can(Permissions.PLAYERS_OP) }

    var body: some View {
        let pages = self.pages
        ServerFrame(serverId: serverId, title: model.t("page.players")) { palette in
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    if let problem = pages.playerProblem {
                        ProblemRow(text: problem, palette: palette)
                    }
                    if let problem = pages.players.problem {
                        // What's online now is a current state: not shown after a failed read.
                        ProblemCard(problem: problem, palette: palette) { await pages.loadPlayers() }
                    } else if let page = pages.players.value {
                        content(page, palette)
                    } else {
                        ProgressView().frame(maxWidth: .infinity)
                    }
                }
                .padding(16)
                .frame(maxWidth: 640)
                .frame(maxWidth: .infinity)
            }
            .refreshable { await pages.loadPlayers() }
            .alert(
                askTitle,
                isPresented: Binding(get: { asking != nil }, set: { if !$0 { asking = nil } }),
                presenting: asking,
                actions: { ask in askButtons(ask) },
                message: { ask in Text(model.t("players.\(ask.action)_body", ["name": ask.name])) }
            )
        }
        .task(id: serverId) { await pages.loadPlayers() }
    }

    // MARK: - The page

    @ViewBuilder
    private func content(_ page: PlayersPage, _ palette: Palette) -> some View {
        online(page, palette)
        recent(palette)
        if canManage {
            addByName(page, palette)
        }
        if let lists = page.lists {
            listCard("players.whitelist", "players.whitelist_empty", lists.whitelist, "whitelist", canRemove: canManage, palette)
            listCard("players.ops", "players.ops_empty", lists.ops, "ops", canRemove: canManage && canOp, palette)
            listCard("players.banned", "players.banned_empty", lists.banned, "banned", canRemove: canManage, palette)
            hint(model.t("players.whitelist_note"), palette)
        }
        everyone(page, palette)
        hint(model.t("players.no_ip"), palette)
    }

    @ViewBuilder
    private func online(_ page: PlayersPage, _ palette: Palette) -> some View {
        section(Display.onlineNow(model.strings, page.onlineCount, page.maxPlayers), palette)
        if canManage && page.running == false {
            hint(model.t("players.start_first"), palette)
        }
        if page.onlineCount == nil {
            hint(model.t("overview.players_unknown_hint"), palette)
        } else if page.online.isEmpty {
            EmptyCard(title: model.t("players.nobody"), palette: palette)
        } else {
            ForEach(page.online, id: \.username) { player in
                CardBox(palette: palette) {
                    Text(verbatim: player.username)
                        .font(.headline)
                        .foregroundStyle(palette.textPrimary)
                    Text(
                        model.t("players.col_session") + ": " + Display.playingFor(model.strings, player)
                            + (player.edition == "bedrock" ? " · " + model.t("players.bedrock") : "")
                    )
                    .font(.footnote)
                    .foregroundStyle(palette.textSecondary)
                    buttons(
                        PlayerButtons.forPlayer(player.username, online: true, page: page, canManage: canManage, canOp: canOp),
                        player.username, palette
                    )
                }
            }
        }
    }

    @ViewBuilder
    private func recent(_ palette: Palette) -> some View {
        let actions = pages.recentActions
        if !actions.isEmpty {
            section(model.t("players.recent_actions"), palette)
            CardBox(palette: palette) {
                ForEach(actions, id: \.id) { action in
                    let state = Display.actionState(action.state)
                    HStack(alignment: .firstTextBaseline) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(model.t("players.do_\(action.kind)") + " · " + action.name)
                                .foregroundStyle(palette.textPrimary)
                            if let message = action.message, !message.isEmpty {
                                Text(verbatim: message)
                                    .font(.footnote)
                                    .foregroundStyle(palette.textSecondary)
                            }
                        }
                        Spacer()
                        if state.busy {
                            ProgressView().controlSize(.small)
                        }
                        Text(model.t(state.key))
                            .font(.footnote)
                            .foregroundStyle(palette.tone(state.tone))
                    }
                    .accessibilityElement(children: .combine)
                }
            }
        }
    }

    private func addByName(_ page: PlayersPage, _ palette: Palette) -> some View {
        let typed = typedName.trimmingCharacters(in: .whitespaces)
        let bad = !typed.isEmpty && !PlayerButtons.validName(typed, edition: page.edition)
        let bedrock = page.edition == "bedrock"
        var actions = [PlayerActions.WHITELIST_ADD]
        if canOp && !bedrock { actions.append(PlayerActions.OP) }
        if page.bans != false { actions.append(PlayerActions.BAN) }
        let busy = pages.playerBusy != nil
        return VStack(alignment: .leading, spacing: 12) {
            section(model.t("players.add_title"), palette)
            CardBox(palette: palette) {
                TextField(model.t("players.add_name"), text: $typedName)
                    .textFieldStyle(.roundedBorder)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .onChange(of: typedName) {
                        if typedName.count > 32 { typedName = String(typedName.prefix(32)) }
                    }
                Text(model.t(!bad ? "players.add_hint" : (bedrock ? "players.bad_gamertag" : "players.bad_name")))
                    .font(.footnote)
                    .foregroundStyle(bad ? palette.danger : palette.textSecondary)
                FlowLayout(spacing: 8) {
                    ForEach(actions, id: \.self) { action in
                        Button(model.t("players.do_\(action)")) {
                            press(action, typed)
                            if !PlayerActions.CONFIRM.contains(action) { typedName = "" }
                        }
                        .buttonStyle(.bordered)
                        .tint(action == PlayerActions.BAN ? palette.danger : palette.accentInk)
                        .disabled(busy || typed.isEmpty || bad)
                    }
                }
                if bedrock && canOp {
                    hint(model.t("players.bedrock_op_online"), palette)
                }
            }
        }
    }

    /// One of Minecraft's lists, with Remove on each name for someone allowed.
    @ViewBuilder
    private func listCard(
        _ titleKey: String, _ emptyKey: String, _ list: PlayerList?, _ kind: String,
        canRemove: Bool, _ palette: Palette
    ) -> some View {
        section(model.t(titleKey), palette)
        CardBox(palette: palette) {
            if let players = list?.players {
                if players.isEmpty {
                    Text(model.t(emptyKey)).foregroundStyle(palette.textSecondary)
                }
                ForEach(Array(players.enumerated()), id: \.offset) { _, entry in
                    listed(entry, kind, canRemove: canRemove, palette)
                }
            } else {
                Text(verbatim: list?.reason ?? model.t("value.unknown"))
                    .foregroundStyle(palette.textSecondary)
            }
            if let file = list?.file {
                hint(model.t("players.from_file", ["file": file]), palette)
            }
        }
    }

    @ViewBuilder
    private func listed(_ entry: ListedPlayer, _ kind: String, canRemove: Bool, _ palette: Palette) -> some View {
        if let name = entry.name {
            let action = PlayerButtons.removeFrom(kind)
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(verbatim: name).foregroundStyle(palette.textPrimary)
                    if kind == "banned", let reason = entry.reason, !reason.isEmpty {
                        Text(model.t("players.col_reason") + ": " + reason)
                            .font(.footnote)
                            .foregroundStyle(palette.textSecondary)
                    }
                }
                Spacer()
                if canRemove {
                    Button(model.t("players.do_\(action)")) { press(action, name) }
                        .buttonStyle(.borderless)
                        .disabled(pages.playerBusy != nil)
                }
            }
            .frame(minHeight: 44)
        } else {
            // Bedrock: an operator known only by Xbox number.
            VStack(alignment: .leading, spacing: 2) {
                Text(verbatim: entry.uuid ?? model.t("value.unknown")).foregroundStyle(palette.textPrimary)
                hint(model.t("players.xuid_only"), palette)
            }
        }
    }

    @ViewBuilder
    private func everyone(_ page: PlayersPage, _ palette: Palette) -> some View {
        section(model.t("players.everyone"), palette)
        if page.known.isEmpty {
            EmptyCard(title: model.t("players.none"), hint: model.t("players.none_hint"), palette: palette)
        }
        TimelineView(.periodic(from: .now, by: 30)) { context in
            VStack(spacing: 12) {
                ForEach(page.known, id: \.username) { known in
                    let online = page.online.contains { $0.username.lowercased() == known.username.lowercased() }
                    let seen = model.t("players.col_last") + ": "
                        + Display.ago(model.strings, known.lastSeen, now: context.date.timeIntervalSince1970)
                    let tags = PlayerButtons.tags(known.username, page: page).map { model.t($0) }
                    CardBox(palette: palette) {
                        Text(verbatim: known.username)
                            .font(.headline)
                            .foregroundStyle(palette.textPrimary)
                        Text(([seen] + tags).joined(separator: " · "))
                            .font(.footnote)
                            .foregroundStyle(palette.textSecondary)
                        buttons(
                            PlayerButtons.forPlayer(known.username, online: online, page: page, canManage: canManage, canOp: canOp),
                            known.username, palette
                        )
                    }
                }
            }
        }
    }

    // MARK: - Small parts

    @ViewBuilder
    private func buttons(_ actions: [String], _ name: String, _ palette: Palette) -> some View {
        if !actions.isEmpty {
            let busy = pages.playerBusy
            FlowLayout(spacing: 8) {
                ForEach(actions, id: \.self) { action in
                    let danger = action == PlayerActions.KICK || action == PlayerActions.BAN
                    Button(model.t(busy == "\(action):\(name)" ? "players.sending" : "players.do_\(action)")) {
                        press(action, name)
                    }
                    .buttonStyle(.bordered)
                    .tint(danger ? palette.danger : palette.accentInk)
                    .disabled(busy != nil)
                }
            }
        }
    }

    private func section(_ text: String, _ palette: Palette) -> some View {
        Text(text)
            .font(.headline)
            .foregroundStyle(palette.textPrimary)
            .padding(.top, 8)
            .accessibilityAddTraits(.isHeader)
    }

    private func hint(_ text: String, _ palette: Palette) -> some View {
        Text(text)
            .font(.footnote)
            .foregroundStyle(palette.textSecondary)
    }

    // MARK: - Pressing

    private func press(_ action: String, _ name: String) {
        if PlayerActions.CONFIRM.contains(action) {
            reason = ""
            asking = Asking(action: action, name: name)
        } else {
            let pages = self.pages
            Task { await pages.playerAction(action, name: name, reason: nil, model.strings) }
        }
    }

    private var askTitle: String {
        guard let ask = asking else { return "" }
        return model.t("players.\(ask.action)_title", ["name": ask.name])
    }

    /// Kick or ban: asks first, with an optional reason the player sees.
    @ViewBuilder
    private func askButtons(_ ask: Asking) -> some View {
        TextField(model.t("players.reason"), text: $reason)
            .onChange(of: reason) {
                if reason.count > PlayerButtons.REASON_LENGTH {
                    reason = String(reason.prefix(PlayerButtons.REASON_LENGTH))
                }
            }
        Button(model.t("players.do_\(ask.action)"), role: .destructive) {
            let pages = self.pages
            let given = reason
            Task { await pages.playerAction(ask.action, name: ask.name, reason: given, model.strings) }
        }
        Button(model.t("mobile.common.cancel"), role: .cancel) {}
    }
}

/// Buttons in rows, wrapping onto the next row when they don't fit.
struct FlowLayout: Layout {
    var spacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let rows = arrange(subviews, width: proposal.width ?? .infinity)
        let width = rows.map(\.width).max() ?? 0
        let height = rows.map(\.height).reduce(0, +) + spacing * CGFloat(max(rows.count - 1, 0))
        return CGSize(width: proposal.width ?? width, height: height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var y = bounds.minY
        for row in arrange(subviews, width: bounds.width) {
            var x = bounds.minX
            for index in row.items {
                let size = subviews[index].sizeThatFits(.unspecified)
                subviews[index].place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
                x += size.width + spacing
            }
            y += row.height + spacing
        }
    }

    private struct Row {
        var items: [Int] = []
        var width: CGFloat = 0
        var height: CGFloat = 0
    }

    private func arrange(_ subviews: Subviews, width: CGFloat) -> [Row] {
        var rows: [Row] = []
        var row = Row()
        for index in subviews.indices {
            let size = subviews[index].sizeThatFits(.unspecified)
            let needed = row.items.isEmpty ? size.width : row.width + spacing + size.width
            if needed > width && !row.items.isEmpty {
                rows.append(row)
                row = Row()
            }
            row.width = row.items.isEmpty ? size.width : row.width + spacing + size.width
            row.height = max(row.height, size.height)
            row.items.append(index)
        }
        if !row.items.isEmpty { rows.append(row) }
        return rows
    }
}
