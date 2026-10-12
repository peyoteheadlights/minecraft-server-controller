import Core
import SwiftUI

/// What Server settings asks to confirm.
enum SetupAsk: Identifiable {
    case change, rollBack, crossplayOn, remove

    var id: Self { self }
}

/// The server's kind and version as its console said them, the EULA when
/// the server needs it, and changing the version or kind: checked first,
/// one confirmation, then a task the phone can leave and come back to
/// (mirrors VersionCard.kt).
struct VersionCardView: View {
    let setup: SetupPages
    let canEdit: Bool
    let palette: Palette
    let ask: (SetupAsk) -> Void

    @Environment(AppModel.self) private var model
    @State private var open = false
    @State private var eulaTicked = false
    @State private var web: WebLink?

    var body: some View {
        let strings = model.strings
        VStack(alignment: .leading, spacing: 8) {
            if let problem = setup.version.problem {
                Text(problem.message(strings)).foregroundStyle(palette.danger)
            }
            if let version = setup.version.value {
                details(version)
                if VersionChange.eulaNeeded(version) { eula(version) }
                if setup.task != nil || setup.busy == "version" || setup.busy == "roll_back" {
                    Text(setup.task?.step.map { model.t("mobile.version.working", ["step": $0]) } ?? model.t("mobile.version.working_plain"))
                        .foregroundStyle(palette.textPrimary)
                    Hint(text: model.t("mobile.version.leave_ok"), palette: palette)
                }
                if let last = version.lastChange, let at = last.at {
                    Hint(text: model.t("version.last_change", [
                        "what": [last.type, last.minecraftVersion].compactMap { $0 }.joined(separator: " "),
                        "when": Display.dateTime(strings, at),
                    ]), palette: palette)
                }
                if canEdit && VersionChange.canRollBack(version) {
                    Button(model.t("version.back")) { ask(.rollBack) }
                        .buttonStyle(.bordered)
                        .disabled(setup.busy != nil || setup.task != nil)
                }
                if canEdit { changer(version) }
            } else if setup.version.problem == nil {
                ProgressView().frame(maxWidth: .infinity)
            }
        }
        .sheet(item: $web) { page in
            SafariView(url: page.url).ignoresSafeArea()
        }
    }

    @ViewBuilder
    private func details(_ version: ServerVersion) -> some View {
        Text(model.t("version.kind") + ": " + (version.capabilities.name.isEmpty ? version.type : version.capabilities.name))
            .foregroundStyle(palette.textPrimary)
        Text(model.t("version.minecraft") + ": " + (version.minecraftVersion ?? model.t("value.unknown")))
            .foregroundStyle(palette.textPrimary)
        if let loader = version.loaderName {
            Text(loader + ": " + (version.loaderVersion ?? model.t("value.unknown"))).foregroundStyle(palette.textSecondary)
        }
        if model.technical, let source = version.minecraftVersionSource {
            Text(model.t("version.seen_in") + ": " + source).foregroundStyle(palette.textSecondary)
        }
        if version.minecraftVersion == nil {
            Hint(text: model.t("version.not_seen_yet"), palette: palette)
        }
        if let detected = version.detectedType, detected != version.type {
            Text(model.t("version.type_disagrees", ["console": detected, "set": version.capabilities.name]))
                .foregroundStyle(palette.tone(.warning))
        }
        if let pending = VersionChange.pending(version) {
            Hint(text: model.t("version.pending", ["version": pending]) + " " + model.t("version.pending_note"), palette: palette)
        }
    }

    @ViewBuilder
    private func eula(_ version: ServerVersion) -> some View {
        Text(model.t("version.eula_needed")).foregroundStyle(palette.tone(.warning))
        if canEdit {
            Button(model.t("new.eula_link")) {
                if let url = URL(string: version.eulaUrl) { web = WebLink(url: url) }
            }
            Toggle(model.t("new.eula_tick"), isOn: $eulaTicked)
                .foregroundStyle(palette.textPrimary)
            Button(model.t(setup.busy == "eula" ? "version.accepting" : "version.eula_accept")) {
                let strings = model.strings
                Task { await setup.acceptEula(strings) }
            }
            .buttonStyle(.borderedProminent)
            .tint(palette.accent)
            .disabled(!eulaTicked || setup.busy != nil)
        }
    }

    @ViewBuilder
    private func changer(_ version: ServerVersion) -> some View {
        DisclosureGroup(model.t("version.change_opener"), isExpanded: Binding(get: { open }, set: { now in
            open = now
            if now { Task { await setup.openChanger() } }
        })) {
            VStack(alignment: .leading, spacing: 8) {
                Picker(model.t("version.change_kind"), selection: Binding(get: { setup.pickedType ?? version.type }, set: { id in
                    Task { await setup.pickType(id) }
                })) {
                    ForEach(setup.types, id: \.id) { type in
                        Text(type.name).tag(type.id)
                    }
                }
                Hint(text: model.t(version.capabilities.edition == "bedrock" ? "version.only_bedrock" : "version.only_java"), palette: palette)
                if let problem = setup.versions.problem {
                    Text(problem.message(model.strings)).foregroundStyle(palette.danger)
                }
                if setup.versions.loading { ProgressView() }
                if let list = setup.versions.value { versionPickers(list) }
                report()
                HStack {
                    Button(model.t(setup.report?.loading == true ? "version.checking" : "version.check")) {
                        Task { await setup.check() }
                    }
                    .buttonStyle(.bordered)
                    .disabled(setup.pickedVersion == nil || setup.report?.loading == true || setup.busy != nil)
                    Button(model.t(setup.busy == "version" ? "version.changing" : "version.change")) { ask(.change) }
                        .buttonStyle(.borderedProminent)
                        .tint(palette.accent)
                        .disabled(setup.report?.value == nil || setup.busy != nil || setup.task != nil)
                }
            }
            .padding(.top, 8)
        }
        .foregroundStyle(palette.textPrimary)
    }

    @ViewBuilder
    private func versionPickers(_ list: TypeVersions) -> some View {
        if let problem = list.sourceProblem {
            Text(problem).foregroundStyle(palette.tone(.warning))
        }
        if list.latestOnly {
            Hint(text: model.t("new.bedrock_versions"), palette: palette)
        }
        if list.snapshots {
            Toggle(model.t("new.show_snapshots"), isOn: Binding(get: { setup.snapshots }, set: { setup.snapshots = $0 }))
        }
        Picker(model.t("version.change_to"), selection: Binding(get: { setup.pickedVersion ?? "" }, set: { setup.pickVersion($0) })) {
            ForEach(VersionChange.choices(list, snapshots: setup.snapshots), id: \.minecraft) { offered in
                Text(offered.stable ? offered.minecraft : model.t("new.snapshot_option", ["version": offered.minecraft])).tag(offered.minecraft)
            }
        }
        let loaders = list.versions.first { $0.minecraft == setup.pickedVersion }?.loaders ?? []
        if model.technical && !loaders.isEmpty {
            Picker(model.t("version.loader_pick"), selection: Binding(get: { setup.pickedLoader ?? loaders[0] }, set: { setup.pickLoader($0) })) {
                ForEach(loaders, id: \.self) { Text($0).tag($0) }
            }
        }
    }

    @ViewBuilder
    private func report() -> some View {
        if let problem = setup.report?.problem {
            Text(problem.message(model.strings)).foregroundStyle(palette.danger)
        }
        if let checked = setup.report?.value {
            Text(model.t("version.after") + ": " + VersionChange.target(checked)).foregroundStyle(palette.textPrimary)
            if let java = checked.javaRequired {
                Text(model.t("version.java_needed") + ": Java \(java)").foregroundStyle(palette.textSecondary)
            }
            if model.technical, let detail = checked.java.detail {
                Text(model.t("version.java_here") + ": " + detail).foregroundStyle(palette.textSecondary)
            }
            ForEach(Array(VersionChange.lines(model.strings, checked).enumerated()), id: \.offset) { _, line in
                Text(line.text).foregroundStyle(line.tone == .neutral ? palette.textSecondary : palette.tone(line.tone))
            }
        }
    }
}
