import Core
import SwiftUI

/// Every server this account may see: its color, what it's doing and who's
/// playing, with when the PC was last read. If the last read failed, the
/// names stay but what they were doing reads Unknown.
struct ServersListView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.colorScheme) private var colorScheme

    var body: some View {
        @Bindable var model = model
        NavigationStack(path: $model.serversPath) {
            List {
                Section {
                    statusLine
                }
                if model.serversLoaded && model.servers.isEmpty {
                    Section {
                        Text(model.me?.isOwner == false ? model.t("mobile.servers.helper_none") : model.t("mobile.servers.none"))
                            .foregroundStyle(.secondary)
                    }
                } else if !model.serversLoaded {
                    Section {
                        HStack(spacing: 12) {
                            ProgressView()
                            Text(model.t("mobile.common.loading"))
                        }
                        .frame(minHeight: 44)
                    }
                }
                Section {
                    ForEach(model.servers) { row in
                        NavigationLink(value: row.id) {
                            ServerRowView(row: row, fresh: model.serversFresh)
                        }
                    }
                } footer: {
                    if !model.servers.isEmpty {
                        Text(model.t("mobile.servers.more_on_pc"))
                    }
                }
            }
            .refreshable {
                await model.refreshServers()
            }
            .navigationTitle(model.t("mobile.servers.title"))
            .navigationDestination(for: String.self) { id in
                ServerView(serverId: id)
            }
        }
    }

    private var statusLine: some View {
        VStack(alignment: .leading, spacing: 6) {
            if let problem = model.serversProblem {
                Label(problem.message(model.strings), systemImage: "exclamationmark.triangle")
                    .foregroundStyle(model.basePalette(colorScheme).tone(.warning))
            }
            TimelineView(.periodic(from: .now, by: 30)) { context in
                HStack(spacing: 8) {
                    if model.live {
                        Image(systemName: "dot.radiowaves.left.and.right")
                            .foregroundStyle(model.basePalette(colorScheme).tone(.success))
                            .accessibilityHidden(true)
                        Text(model.t("mobile.servers.live"))
                        Text(verbatim: "·")
                            .accessibilityHidden(true)
                    }
                    Text(model.t("mobile.servers.checked", [
                        "when": Display.ago(model.strings, model.serversCheckedAt, now: context.date.timeIntervalSince1970),
                    ]))
                }
                .font(.footnote)
                .foregroundStyle(.secondary)
                .accessibilityElement(children: .combine)
            }
        }
    }
}

/// One server in the list.
struct ServerRowView: View {
    let row: ServerRow
    /// The last read worked; otherwise state and players read Unknown.
    let fresh: Bool

    @Environment(AppModel.self) private var model
    @Environment(\.colorScheme) private var colorScheme

    var body: some View {
        let state = fresh ? row.state : States.UNKNOWN
        let players: Int? = fresh ? row.playersOnline : nil
        let words = Display.state(state)
        HStack(spacing: 12) {
            ColorBadge(hex: row.color, size: 16)
            VStack(alignment: .leading, spacing: 4) {
                Text(row.name)
                    .font(.headline)
                HStack(spacing: 6) {
                    Text(model.t(words.key))
                        .foregroundStyle(model.basePalette(colorScheme).tone(words.tone))
                    Text(verbatim: "·")
                        .foregroundStyle(.secondary)
                        .accessibilityHidden(true)
                    Image(systemName: "person.2")
                        .foregroundStyle(.secondary)
                        .accessibilityHidden(true)
                    Text(Display.players(model.strings, players, row.maxPlayers))
                        .foregroundStyle(.secondary)
                }
                .font(.subheadline)
            }
        }
        .frame(minHeight: 44)
        .accessibilityElement(children: .combine)
    }
}
