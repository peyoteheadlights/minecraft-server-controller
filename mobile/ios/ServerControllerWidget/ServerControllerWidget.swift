import Core
import SwiftUI
import WidgetKit

/// The home-screen widget: each server's state and players, from the last
/// reading the app or this widget saved. A reading that isn't fresh reads
/// Unknown, with when the PC was last checked.
@main
struct ServerControllerWidgets: WidgetBundle {
    var body: some Widget {
        ServersWidget()
    }
}

struct ServersWidget: Widget {
    let kind = "ServersWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: ServersProvider()) { entry in
            ServersWidgetView(entry: entry)
        }
        .configurationDisplayName(Text(verbatim: WidgetWords.t("mobile.widget.name")))
        .description(Text(verbatim: WidgetWords.t("mobile.widget.description")))
        .supportedFamilies([.systemSmall, .systemMedium])
    }
}

/// The widget's words, in the wording chosen in the app.
enum WidgetWords {
    static let strings = Strings(Bundled.english)

    static func t(_ key: String, _ values: [String: CustomStringConvertible] = [:]) -> String {
        strings.technical = SharedStore().technical
        return strings.t(key, values)
    }
}

struct ServersEntry: TimelineEntry {
    let date: Date
    let paired: Bool
    let snapshot: WidgetSnapshot?
}

struct ServersProvider: TimelineProvider {
    func placeholder(in context: Context) -> ServersEntry {
        ServersEntry(date: Date(), paired: true, snapshot: nil)
    }

    func getSnapshot(in context: Context, completion: @escaping (ServersEntry) -> Void) {
        completion(ServersProvider.entry(at: Date()))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<ServersEntry>) -> Void) {
        Task {
            await WidgetRefresh.refresh()
            let now = Date()
            // Entries along the next hour and a quarter, so "Checked …" stays
            // true and an old reading turns Unknown even if no refresh comes.
            var entries: [ServersEntry] = []
            for minutes in stride(from: 0, through: 75, by: 15) {
                entries.append(ServersProvider.entry(at: now.addingTimeInterval(Double(minutes) * 60)))
            }
            completion(Timeline(entries: entries, policy: .after(now.addingTimeInterval(30 * 60))))
        }
    }

    static func entry(at date: Date) -> ServersEntry {
        let store = SharedStore()
        // Signed out (here or on the PC): nothing from before is shown.
        let signedIn = store.pairing != nil && TokenStore.read() != nil
        return ServersEntry(date: date, paired: signedIn, snapshot: store.widgetSnapshot)
    }
}

/// Reads the PC with the app's own sign-in (shared through the Keychain
/// group) and saves what it saw. Only GET /api/servers: the widget never
/// starts or stops anything.
enum WidgetRefresh {
    static func refresh() async {
        let store = SharedStore()
        guard let pairing = store.pairing, TokenStore.read() != nil else { return }
        let client = AgentClient(
            pairing: pairing,
            token: { TokenStore.read() },
            onSignedOut: { TokenStore.delete() }
        )
        let now = Date().timeIntervalSince1970
        do {
            let list = try await client.servers()
            store.widgetSnapshot = WidgetSnapshot.read(list, now: now)
        } catch let problem as AgentError {
            store.widgetSnapshot = WidgetSnapshot.failed(store.widgetSnapshot, problem: problem, now: now)
        } catch {}
    }
}

struct ServersWidgetView: View {
    let entry: ServersEntry

    @Environment(\.widgetFamily) private var family
    @Environment(\.colorScheme) private var colorScheme

    var body: some View {
        content
            .containerBackground(.background, for: .widget)
            .widgetURL(DeepLink.home)
    }

    @ViewBuilder
    private var content: some View {
        if !entry.paired {
            VStack(alignment: .leading, spacing: 8) {
                Image(systemName: "server.rack")
                    .font(.title2)
                    .accessibilityHidden(true)
                Text(WidgetWords.t("mobile.widget.not_paired"))
                    .font(.footnote)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        } else {
            let now = entry.date.timeIntervalSince1970
            let shown = entry.snapshot?.shown(now)
            let servers = Array((shown?.servers ?? []).prefix(family == .systemSmall ? 3 : 4))
            VStack(alignment: .leading, spacing: 6) {
                if servers.isEmpty {
                    Text(WidgetWords.t("value.unknown"))
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
                ForEach(servers) { server in
                    row(server)
                }
                Spacer(minLength: 0)
                if let snapshot = entry.snapshot, !snapshot.reached {
                    Text(WidgetWords.t("mobile.widget.unreachable"))
                        .font(.caption2)
                        .foregroundStyle(palette.tone(.warning))
                }
                Text(WidgetWords.t("mobile.widget.checked", ["when": Display.ago(WidgetWords.strings, entry.snapshot?.checkedAt, now: now)]))
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
    }

    private var palette: Palette {
        Palette.base(Bundled.themes, colorScheme == .dark ? "dark" : "light")
    }

    @ViewBuilder
    private func row(_ server: WidgetServer) -> some View {
        let words = Display.state(server.state)
        let line = HStack(spacing: 6) {
            ColorBadge(hex: server.color, size: 10)
            VStack(alignment: .leading, spacing: 0) {
                Text(server.name)
                    .font(.caption.weight(.semibold))
                    .lineLimit(1)
                HStack(spacing: 4) {
                    Text(WidgetWords.t(words.key))
                        .foregroundStyle(palette.tone(words.tone))
                    if family != .systemSmall {
                        Text(verbatim: "·")
                            .foregroundStyle(.secondary)
                        Text(Display.players(WidgetWords.strings, server.playersOnline, server.maxPlayers))
                            .foregroundStyle(.secondary)
                    }
                }
                .font(.caption2)
                .lineLimit(1)
            }
        }
        .accessibilityElement(children: .combine)
        if family == .systemSmall {
            line
        } else if let url = DeepLink.server(server.id) {
            Link(destination: url) {
                line
            }
        } else {
            line
        }
    }
}
