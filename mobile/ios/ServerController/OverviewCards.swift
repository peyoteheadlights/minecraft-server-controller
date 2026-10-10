import Core
import SwiftUI

// The Overview's three cards under a server's state, as the dashboard shows
// them: how friends join, suggestions, and getting started. Each reads what
// the agent measured; a value it couldn't read says so.

/// "How friends join": every address to share, each with Copy.
struct JoinCard: View {
    let pages: ServerPages
    let palette: Palette

    @Environment(AppModel.self) private var model

    var body: some View {
        CardBox(palette: palette) {
            Text(model.t("join.title"))
                .font(.headline)
                .foregroundStyle(palette.textPrimary)
            if let problem = pages.join.problem {
                ProblemRow(text: problem.message(model.strings), palette: palette)
            } else if let info = pages.join.value {
                if let java = info.java {
                    javaWays(java)
                    if let bedrock = info.bedrock {
                        crossplay(bedrock)
                    }
                } else if let bedrock = info.bedrock {
                    bedrockServer(bedrock)
                } else {
                    hint(model.t("value.unknown"))
                }
                hint(model.t("join.internet"))
            } else {
                ProgressView()
            }
        }
    }

    @ViewBuilder
    private func javaWays(_ java: JoinWay) -> some View {
        let home = homeAddresses(java.local)
        group("join.home", "join.home_hint")
        if home.isEmpty { hint(model.t("join.no_local")) }
        ForEach(home, id: \.address) { address in
            CopyRow(text: withPort(address.address, java.port), note: adapterNote(address, home.count), palette: palette)
        }
        group("join.tailscale", "join.tailscale_hint")
        tailscale(java) { withPort($0, java.port) }
        let unknown = model.t("value.unknown")
        let port: String = java.port.map { String($0) } ?? unknown
        let source: String = java.portSource ?? unknown
        let note: String = java.defaultPort == true ? " " + model.t("join.default_port") : ""
        hint(model.t("join.port", ["port": port, "source": source]) + note)
    }

    /// Crossplay: Bedrock players type the address and the port apart.
    @ViewBuilder
    private func crossplay(_ bedrock: JoinWay) -> some View {
        group("join.bedrock", "join.bedrock_hint")
        if let port = bedrock.port {
            let portWords = model.t("join.bedrock_port", ["port": port])
            ForEach(homeAddresses(bedrock.local), id: \.address) { address in
                CopyRow(text: address.address, note: portWords + " · " + model.t("join.home"), palette: palette)
            }
            if let ts = bedrock.address {
                CopyRow(text: ts, note: portWords + " · " + model.t("join.tailscale"), palette: palette)
            } else {
                hint(model.t("join.no_tailscale"))
            }
        } else {
            hint(model.t("join.no_bedrock_port"))
        }
        if bedrock.ready == false { hint(model.t("cross.files_missing")) }
        hint(model.t("join.consoles"))
    }

    /// A Bedrock server of its own.
    @ViewBuilder
    private func bedrockServer(_ bedrock: JoinWay) -> some View {
        let home = homeAddresses(bedrock.local)
        let unknown = model.t("value.unknown")
        group("join.home", "join.home_hint")
        if home.isEmpty { hint(model.t("join.no_local")) }
        ForEach(home, id: \.address) { address in
            CopyRow(text: address.address, note: adapterNote(address, home.count), palette: palette)
        }
        group("join.tailscale", "join.bedrock_tailscale_hint")
        tailscale(bedrock) { $0 }
        let port: String = bedrock.port.map { String($0) } ?? unknown
        let source: String = bedrock.portSource ?? unknown
        let note: String = bedrock.defaultPort == true ? " " + model.t("join.default_port") : ""
        hint(model.t("join.bedrock_server_port", ["port": port, "source": source]) + note)
        hint(model.t("join.consoles"))
    }

    @ViewBuilder
    private func tailscale(_ way: JoinWay, _ shown: @escaping (String) -> String) -> some View {
        if let ts = way.tailscale, let address = ts.address {
            CopyRow(text: shown(address), palette: palette)
            if let name = ts.dnsName {
                CopyRow(text: shown(name), palette: palette)
            }
            if ts.verified != true {
                hint(model.t("join.ts_unconfirmed"))
            } else if ts.connected == false {
                hint(model.t("join.ts_off"))
            }
        } else {
            hint(model.t("join.no_tailscale"))
        }
    }

    private func withPort(_ host: String, _ port: Int?) -> String {
        port.map { "\(host):\($0)" } ?? host
    }

    /// Virtual adapters (VPNs, virtual machines) only in Technical words.
    private func homeAddresses(_ all: [JoinAddress]) -> [JoinAddress] {
        all.filter { model.technical || !$0.virtual }
    }

    private func adapterNote(_ address: JoinAddress, _ count: Int) -> String? {
        guard let adapter = address.adapter, model.technical || count > 1 else { return nil }
        return model.t("join.adapter", ["adapter": adapter])
    }

    private func group(_ titleKey: String, _ hintKey: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(model.t(titleKey))
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(palette.textPrimary)
            Text(model.t(hintKey))
                .font(.footnote)
                .foregroundStyle(palette.textSecondary)
        }
        .padding(.top, 4)
    }

    private func hint(_ text: String) -> some View {
        Text(text)
            .font(.footnote)
            .foregroundStyle(palette.textSecondary)
    }
}

/// Suggestions, in the agent's own words. Not now / Don't show again /
/// Show again only for someone who may change settings.
struct SuggestionsCard: View {
    let pages: ServerPages
    let palette: Palette

    @Environment(AppModel.self) private var model
    @Environment(\.openURL) private var openURL

    var body: some View {
        if pages.suggestions.problem == nil, let list = pages.suggestions.value {
            let canEdit = model.can(Permissions.SETTINGS_EDIT)
            CardBox(palette: palette) {
                Text(model.t("overview.recommendations"))
                    .font(.headline)
                    .foregroundStyle(palette.textPrimary)
                if list.recommendations.isEmpty {
                    Text(model.t("rec.none"))
                        .foregroundStyle(palette.textSecondary)
                }
                ForEach(list.recommendations, id: \.id) { rec in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(rec.title)
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(palette.textPrimary)
                        if let reason = rec.reason, !reason.isEmpty {
                            Text(reason)
                                .font(.footnote)
                                .foregroundStyle(palette.textSecondary)
                        }
                        if let evidence = rec.evidence, !evidence.isEmpty {
                            Text(evidence)
                                .font(.footnote)
                                .foregroundStyle(palette.textSecondary)
                        }
                        HStack(spacing: 16) {
                            if let label = rec.action?.label, let link = rec.action?.url, link.hasPrefix("https://"), let url = URL(string: link) {
                                Button(label) { openURL(url) }
                            }
                            if canEdit {
                                Button(model.t("rec.snooze")) { act(rec.id, "snooze") }
                                Button(model.t("rec.dismiss")) { act(rec.id, "dismiss") }
                            }
                        }
                        .buttonStyle(.borderless)
                        .font(.footnote)
                    }
                    .padding(.vertical, 4)
                }
                if !list.hidden.isEmpty {
                    Text(model.strings.tn("rec.hidden", count: list.hidden.count))
                        .font(.footnote)
                        .foregroundStyle(palette.textSecondary)
                    ForEach(list.hidden, id: \.id) { rec in
                        HStack {
                            Text(rec.title)
                                .foregroundStyle(palette.textPrimary)
                            Spacer()
                            if canEdit {
                                Button(model.t("rec.show_again")) { act(rec.id, "restore") }
                                    .buttonStyle(.borderless)
                            }
                        }
                        .frame(minHeight: 44)
                    }
                }
                if let problem = pages.cardProblem {
                    ProblemRow(text: problem, palette: palette)
                }
            }
        }
    }

    private func act(_ id: String, _ action: String) {
        Task { await pages.suggestion(id, action, model.strings) }
    }
}

/// Getting started: ticked from what the agent measured, never by a tap.
/// Gone once hidden or finished. Hide only for someone who may change settings.
struct ChecklistCard: View {
    let pages: ServerPages
    let palette: Palette

    @Environment(AppModel.self) private var model

    var body: some View {
        if pages.checklist.problem == nil, let list = pages.checklist.value, list.show {
            CardBox(palette: palette) {
                HStack {
                    Text(model.t("start.title"))
                        .font(.headline)
                        .foregroundStyle(palette.textPrimary)
                    Spacer()
                    if model.can(Permissions.SETTINGS_EDIT) {
                        Button(model.t("start.hide")) {
                            Task { await pages.hideChecklist(model.strings) }
                        }
                        .buttonStyle(.borderless)
                    }
                }
                if let done = list.done, let total = list.total {
                    Text(model.t("start.progress", ["done": done, "total": total]))
                        .font(.footnote)
                        .foregroundStyle(palette.textSecondary)
                }
                Text(model.t("start.lead"))
                    .font(.footnote)
                    .foregroundStyle(palette.textSecondary)
                TimelineView(.periodic(from: .now, by: 30)) { context in
                    VStack(alignment: .leading, spacing: 10) {
                        ForEach(list.items, id: \.id) { item in
                            HStack(alignment: .top, spacing: 10) {
                                Image(systemName: item.done ? "checkmark.circle.fill" : "circle")
                                    .foregroundStyle(item.done ? palette.tone(.success) : palette.textSecondary)
                                    .accessibilityLabel(item.done ? model.t("start.done") : "")
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(model.t("start.\(item.id)"))
                                        .foregroundStyle(palette.textPrimary)
                                    if let key = item.evidenceKey {
                                        Text(model.t("start.\(key)", [
                                            "when": item.evidence?.createdAt.map {
                                                Display.ago(model.strings, $0, now: context.date.timeIntervalSince1970)
                                            } ?? "",
                                            "name": item.evidence?.name ?? "",
                                        ]))
                                        .font(.footnote)
                                        .foregroundStyle(palette.textSecondary)
                                    }
                                }
                            }
                            .accessibilityElement(children: .combine)
                        }
                    }
                }
            }
        }
    }
}
