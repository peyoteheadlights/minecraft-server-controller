import Core
import SwiftUI

/// "Let Bedrock players join": its state, the port, and the agent's reason
/// when this kind of server can't have it (mirrors SetupCards.kt).
struct CrossplayCardView: View {
    let setup: SetupPages
    let canEdit: Bool
    let palette: Palette
    let ask: (SetupAsk) -> Void

    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let problem = setup.crossplay.problem {
                Text(problem.message(model.strings)).foregroundStyle(palette.danger)
            }
            if let info = setup.crossplay.value {
                if let why = Crossplay.whyNot(model.strings, info) {
                    Hint(text: why, palette: palette)
                    Hint(text: model.t("cross.switch_type"), palette: palette)
                } else {
                    details(info)
                }
            }
        }
    }

    @ViewBuilder
    private func details(_ info: CrossplayInfo) -> some View {
        Hint(text: model.t("cross.what"), palette: palette)
        if let mod = info.missingMod {
            Text(model.t("cross.needs_mod", ["mod": mod])).foregroundStyle(palette.tone(.warning))
        }
        if info.enabled {
            Text(model.t("cross.address") + ": " + (info.address ?? model.t("value.unknown"))).foregroundStyle(palette.textPrimary)
            if let why = info.addressUnknown { Hint(text: why, palette: palette) }
            Text(model.t("cross.ready") + ": " + Crossplay.ready(model.strings, info)).foregroundStyle(palette.textPrimary)
            Hint(text: model.t("cross.names") + ": " + model.t("cross.names_value", ["prefix": info.usernamePrefix]), palette: palette)
        } else {
            Text(model.t("cross.port")).foregroundStyle(palette.textPrimary)
            TextField(model.t("cross.port"), text: Binding(get: { setup.crossPort }, set: { setup.crossPort = String($0.filter(\.isNumber).prefix(5)) }))
                .textFieldStyle(.roundedBorder)
                .keyboardType(.numberPad)
                .disabled(!canEdit)
            Hint(text: model.t("cross.port_hint"), palette: palette)
        }
        if canEdit {
            if info.enabled {
                Button(model.t(setup.busy == "crossplay" ? "cross.turning_off" : "cross.turn_off")) {
                    let strings = model.strings
                    Task { await setup.setCrossplay(false, strings) }
                }
                .buttonStyle(.bordered)
                .disabled(setup.busy != nil)
            } else {
                Button(model.t(setup.busy == "crossplay" ? "cross.turning_on" : "cross.turn_on")) { ask(.crossplayOn) }
                    .buttonStyle(.borderedProminent)
                    .tint(palette.accent)
                    .disabled(setup.busy != nil)
            }
            Hint(text: model.t("cross.stopped_first"), palette: palette)
        }
        if !info.differences.isEmpty {
            Text(model.t("cross.differences")).foregroundStyle(palette.textPrimary)
            ForEach(info.differences, id: \.self) { line in
                Hint(text: "• " + line, palette: palette)
            }
        }
    }
}

/// Duplicate: a copy with its own port and color; the world copied or
/// fresh. Runs as a task; the copy joins All servers when it is checked.
struct DuplicateCardView: View {
    let setup: SetupPages
    let serverId: String
    let palette: Palette

    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Hint(text: model.t("dup.intro"), palette: palette)
            if let problem = setup.copyOptions.problem {
                Text(problem.message(model.strings)).foregroundStyle(palette.danger)
            }
            if let options = setup.copyOptions.value {
                Text(model.t("dup.name")).foregroundStyle(palette.textPrimary)
                TextField(model.t("dup.name"), text: Binding(get: { setup.copyName }, set: { setup.copyName = String($0.prefix(ServerForm.NAME_LIMIT)) }))
                    .textFieldStyle(.roundedBorder)
                Text(model.t("dup.folder")).foregroundStyle(palette.textPrimary)
                // The folder is the agent's suggestion next to this one;
                // typing a path of your own is for Technical mode.
                TextField(model.t("dup.folder"), text: Binding(get: { setup.copyFolder }, set: { setup.copyFolder = $0 }))
                    .textFieldStyle(.roundedBorder)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
                    .disabled(!model.technical)
                Hint(text: model.t("dup.folder_hint"), palette: palette)
                Picker(model.t("dup.world"), selection: Binding(get: { setup.copyWorld }, set: { setup.copyWorld = $0 })) {
                    ForEach(Duplicate.worlds(options), id: \.self) { world in
                        Text(model.t("dup.world_\(world)")).tag(world)
                    }
                }
                .pickerStyle(.inline)
                Hint(text: model.t("dup.world_\(setup.copyWorld)_hint"), palette: palette)
                if options.running { Hint(text: model.t("dup.running"), palette: palette) }
                if options.crossplay { Hint(text: model.t("dup.crossplay"), palette: palette) }
                if let step = Duplicate.progress(setup.copying, serverId: serverId) {
                    Text(model.t("mobile.version.working", ["step": step])).foregroundStyle(palette.textPrimary)
                }
                Button(model.t(setup.busy == "duplicate" ? "dup.starting" : "dup.button")) {
                    let strings = model.strings
                    Task { await setup.duplicate(strings) }
                }
                .buttonStyle(.borderedProminent)
                .tint(palette.accent)
                .disabled(setup.busy != nil || setup.copying != nil || !Duplicate.ready(setup.copyName, setup.copyFolder))
            }
        }
    }
}

/// Remove server: off the list, its folder, world and backups stay. Never
/// the last server: the button is off with the reason above it.
struct RemoveCardView: View {
    let setup: SetupPages
    let palette: Palette
    let ask: (SetupAsk) -> Void

    @Environment(AppModel.self) private var model

    var body: some View {
        let count = model.servers.count
        VStack(alignment: .leading, spacing: 8) {
            Hint(text: RemoveServer.hint(model.strings, serverCount: count), palette: palette)
            Button(model.t("serverset.remove_button"), role: .destructive) { ask(.remove) }
                .buttonStyle(.bordered)
                .disabled(setup.busy != nil || RemoveServer.blocked(model.strings, serverCount: count) != nil)
        }
    }
}

/// A Technical mode text editor. "Check changes" lists what will change
/// (added, removed, changed, with old and new values) before anything is
/// saved; `changes` compares the typed text with the saved one.
struct RawEditorView: View {
    let title: String
    let hint: String
    let saved: String
    let changes: (String) -> [RawChange]
    let busy: Bool
    let palette: Palette
    let save: (String) -> Void

    @Environment(AppModel.self) private var model
    @State private var text = ""
    @State private var review: [RawChange]?

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).foregroundStyle(palette.textPrimary)
            Hint(text: hint, palette: palette)
            TextEditor(text: $text)
                .font(.callout.monospaced())
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)
                .frame(minHeight: 160)
                .scrollContentBackground(.hidden)
                .background(palette.sunken, in: RoundedRectangle(cornerRadius: 8))
                .onChange(of: text) { review = nil }
            if let listed = review {
                if listed.isEmpty {
                    Hint(text: model.t("mobile.raw.nothing"), palette: palette)
                } else {
                    Text(model.t("mobile.raw.will_change")).foregroundStyle(palette.textPrimary)
                    ForEach(listed, id: \.key) { change in
                        Text(RawText.line(model.strings, change))
                            .font(.callout.monospaced())
                            .foregroundStyle(palette.textPrimary)
                    }
                    HStack {
                        Button(model.t("mobile.raw.save")) {
                            review = nil
                            save(text)
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(palette.accent)
                        .disabled(busy)
                        Button(model.t("mobile.raw.edit_more")) { review = nil }
                            .buttonStyle(.bordered)
                    }
                }
            } else {
                Button(model.t("mobile.raw.check")) { review = changes(text) }
                    .buttonStyle(.bordered)
                    .disabled(busy)
            }
        }
        .onAppear { text = saved }
        .onChange(of: saved) { text = saved }
    }
}

