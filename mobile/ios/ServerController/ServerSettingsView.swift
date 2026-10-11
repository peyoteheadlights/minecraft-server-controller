import Core
import SwiftUI

/// Server settings: how Command Block runs this server (Game settings are
/// the game's own rules; mirrors ServerSettings.kt). Name and color, what
/// happens after a crash, sleep when empty, backups kept, and the start and
/// stop limits. Save sends only what changed; a refused value says why
/// under its field. Someone who may only look sees it all read-only.
struct ServerSettingsView: View {
    let serverId: String

    @Environment(AppModel.self) private var model

    private var setup: SetupPages { model.pages(serverId).setup }

    var body: some View {
        let setup = self.setup
        ServerFrame(serverId: serverId, title: model.t("page.server_settings")) { palette in
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    page(setup, palette)
                }
                .padding(16)
                .frame(maxWidth: 640)
                .frame(maxWidth: .infinity)
            }
            .refreshable { await setup.loadSettings() }
        }
        .task(id: serverId) {
            setup.said = nil
            await setup.loadSettings()
        }
    }

    @ViewBuilder
    private func page(_ setup: SetupPages, _ palette: Palette) -> some View {
        let canEdit = ServerForm.editable(model.me)
        let strings = model.strings
        let read = setup.settings
        Text(model.t("mobile.serverset.intro"))
            .foregroundStyle(palette.textPrimary)
        if !canEdit && model.me != nil {
            Hint(text: model.t("mobile.serverset.read_only"), palette: palette)
        }
        if let problem = read.problem {
            ProblemCard(problem: problem, palette: palette) { await setup.loadSettings() }
        }
        if let settings = read.value {
            SectionTitle(text: model.t("serverset.identity"), palette: palette)
            CardBox(palette: palette) {
                SettingField(
                    label: model.t("serverset.name"), kind: "text", value: setup.shown(ServerForm.NAME),
                    locked: !canEdit, problem: setup.fieldProblems[ServerForm.NAME], palette: palette
                ) { setup.edit(ServerForm.NAME, String($0.prefix(ServerForm.NAME_LIMIT))) }
                ServerColorPicker(
                    colors: settings.palette, current: setup.color ?? settings.color, locked: !canEdit, palette: palette
                ) { setup.pickColor($0) }
            }
            ForEach(ServerForm.GROUPS, id: \.titleKey) { group in
                SectionTitle(text: model.t(group.titleKey), palette: palette)
                CardBox(palette: palette) {
                    ForEach(group.fields, id: \.key) { field in
                        SettingField(
                            label: model.t(field.labelKey), kind: field.kind, value: setup.shown(field.key),
                            locked: !canEdit, problem: setup.fieldProblems[field.key], palette: palette,
                            hint: field.hintKey.map { model.t($0, ["minutes": ServerForm.initial(settings, "monitor.crash_window_minutes")]) }
                        ) { setup.edit(field.key, $0) }
                    }
                    if group.titleKey == "serverset.sleep" {
                        Text(ServerForm.sleepLine(strings, settings))
                            .foregroundStyle(palette.textSecondary)
                    }
                    if let note = group.noteKey {
                        Hint(text: model.t(note), palette: palette)
                    }
                }
            }
            if canEdit {
                Button {
                    Task { await setup.saveSettings(strings) }
                } label: {
                    Text(model.t(setup.busy == "settings" ? "action.saving" : "mobile.serverset.save"))
                        .frame(minHeight: 32)
                }
                .buttonStyle(.borderedProminent)
                .tint(palette.accent)
                .disabled(setup.busy != nil)
            }
            SaidRow(said: setup.said, palette: palette)
        } else if read.problem == nil {
            ProgressView().frame(maxWidth: .infinity)
        }
    }
}

/// One setting: a switch, or a box for a number or words.
struct SettingField: View {
    let label: String
    let kind: String
    let value: String
    let locked: Bool
    let problem: String?
    let palette: Palette
    var hint: String? = nil
    let change: (String) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if kind == "bool" {
                Toggle(label, isOn: Binding(get: { value == "true" }, set: { change($0 ? "true" : "false") }))
                    .disabled(locked)
                    .foregroundStyle(palette.textPrimary)
            } else {
                Text(label)
                    .foregroundStyle(palette.textPrimary)
                TextField(label, text: Binding(get: { value }, set: { change($0) }))
                    .textFieldStyle(.roundedBorder)
                    .keyboardType(kind == "int" ? .numberPad : kind == "number" ? .decimalPad : .default)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(kind == "text" ? .sentences : .never)
                    .disabled(locked)
            }
            if let problem {
                Text(verbatim: problem)
                    .font(.footnote)
                    .foregroundStyle(palette.danger)
            }
            if let hint, !hint.isEmpty {
                Hint(text: hint, palette: palette)
            }
        }
        .frame(minHeight: 44, alignment: .leading)
    }
}

/// The palette as dots, and a box for any color typed as #RRGGBB. The
/// preview is the server's badge, so its text is checked to stay readable.
private struct ServerColorPicker: View {
    let colors: [PaletteColor]
    let current: String?
    let locked: Bool
    let palette: Palette
    let pick: (String) -> Void

    @Environment(AppModel.self) private var model
    @State private var typed = ""

    var body: some View {
        let typedColor = ServerForm.color(typed)
        let bad = !typed.isEmpty && typedColor == nil
        VStack(alignment: .leading, spacing: 8) {
            Text(model.t("serverset.color"))
                .foregroundStyle(palette.textPrimary)
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 44))], alignment: .leading, spacing: 10) {
                ForEach(colors, id: \.id) { color in
                    let chosen = color.hex.caseInsensitiveCompare(current ?? "") == .orderedSame
                    Button {
                        pick(color.hex)
                    } label: {
                        Circle()
                            .fill(Color.fromHex(color.hex) ?? .gray)
                            .frame(width: 36, height: 36)
                            .overlay(Circle().stroke(chosen ? palette.textPrimary : palette.textSecondary, lineWidth: chosen ? 3 : 1))
                            .frame(width: 44, height: 44)
                    }
                    .disabled(locked)
                    .accessibilityLabel(model.t("color.\(color.id)"))
                    .accessibilityAddTraits(chosen ? .isSelected : [])
                }
            }
            TextField(model.t("serverset.custom_color"), text: Binding(get: { typed }, set: { text in
                typed = String(text.prefix(7))
                if let hex = ServerForm.color(typed) { pick(hex) }
            }))
            .textFieldStyle(.roundedBorder)
            .autocorrectionDisabled()
            .textInputAutocapitalization(.characters)
            .disabled(locked)
            Text(model.t(bad ? "mobile.serverset.color_bad" : "mobile.serverset.color_hint"))
                .font(.footnote)
                .foregroundStyle(bad ? palette.danger : palette.textSecondary)
            if let rgb = ServerColors.rgb(current) {
                let fill = ServerColors.fillWithText(rgb)
                Text(verbatim: (current ?? "").uppercased())
                    .padding(.horizontal, 12)
                    .padding(.vertical, 4)
                    .foregroundStyle(Color.fromHex(ServerColors.hex(fill.text)) ?? palette.textPrimary)
                    .background(Capsule().fill(Color.fromHex(ServerColors.hex(fill.fill)) ?? .gray))
            }
        }
        .onAppear { typed = current ?? "" }
    }
}
