import Core
import SwiftUI

/// Every alert from the servers this account may see, newest first. Tapping
/// one about a server opens that server.
struct NotificationsView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.colorScheme) private var colorScheme

    var body: some View {
        NavigationStack {
            List {
                if model.alertState.alerts.isEmpty {
                    Section {
                        VStack(alignment: .leading, spacing: 8) {
                            Text(model.t("mobile.alerts.empty"))
                            Text(model.t("mobile.alerts.empty_hint"))
                                .font(.footnote)
                                .foregroundStyle(.secondary)
                        }
                        .padding(.vertical, 8)
                    }
                } else {
                    ForEach(model.alertState.newestFirst) { alert in
                        Button {
                            if let id = alert.serverId {
                                model.openServer(id)
                            }
                        } label: {
                            AlertRowView(alert: alert, unread: alert.id > model.alertState.readUpTo)
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
            .refreshable {
                await model.syncAlerts()
            }
            .navigationTitle(model.t("mobile.alerts.title"))
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button(model.t("mobile.alerts.mark_read")) {
                        model.markAllRead()
                    }
                    .disabled(model.alertState.unread == 0)
                }
            }
            .task {
                await model.syncAlerts()
            }
        }
    }
}

struct AlertRowView: View {
    let alert: AppAlert
    let unread: Bool

    @Environment(AppModel.self) private var model
    @Environment(\.colorScheme) private var colorScheme

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Circle()
                .fill(unread ? model.basePalette(colorScheme).accentInk : Color.clear)
                .frame(width: 10, height: 10)
                .padding(.top, 6)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 4) {
                Text(alert.title)
                    .font(.headline)
                if !alert.body.isEmpty {
                    Text(alert.body)
                        .font(.subheadline)
                } else if let words = model.feedWords(alert.event) {
                    Text(words)
                        .font(.subheadline)
                }
                HStack(spacing: 6) {
                    ColorBadge(hex: serverColor, size: 10)
                    Text(model.serverName(alert.serverId))
                    Text(verbatim: "·")
                        .accessibilityHidden(true)
                    TimelineView(.periodic(from: .now, by: 60)) { context in
                        Text(Display.ago(model.strings, alert.ts, now: context.date.timeIntervalSince1970))
                    }
                }
                .font(.footnote)
                .foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
            if alert.serverId != nil {
                Image(systemName: "chevron.right")
                    .font(.footnote)
                    .foregroundStyle(.tertiary)
                    .accessibilityHidden(true)
            }
        }
        .frame(minHeight: 44)
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityHint(unread ? model.t("mobile.alerts.new") : "")
    }

    private var serverColor: String? {
        guard let id = alert.serverId else { return nil }
        return model.servers.first(where: { $0.id == id })?.color
    }
}
