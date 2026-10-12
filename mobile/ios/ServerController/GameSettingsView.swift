import Core
import SwiftUI

/// Game settings: the PC page's fields in its groups, each with its hint
/// (mirrors GameSettings.kt). The seed is shown but locked once the world
/// exists; someone who may not edit settings sees them all read-only. Save
/// sends only what changed, and a refused value (a port in use, a number
/// out of range) says why under the field. Saved while running, it offers
/// Restart now, which asks first.
struct GameSettingsView: View {
    let serverId: String

    @Environment(AppModel.self) private var model
    @State private var restarting = false

    private var content: ContentPages { model.pages(serverId).content }

    var body: some View {
        let content = self.content
        ServerFrame(serverId: serverId, title: model.t("page.game_settings")) { palette in
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    page(content, palette)
                }
                .padding(16)
                .frame(maxWidth: 640)
                .frame(maxWidth: .infinity)
            }
            .refreshable { await content.loadGame() }
            .alert(model.t("confirm.restart_title"), isPresented: $restarting) {
                Button(model.t("action.restart")) {
                    let strings = model.strings
                    Task { await content.restart(strings, reload: { await content.loadGame() }) }
                }
                Button(model.t("mobile.common.cancel"), role: .cancel) {}
            } message: {
                Text(model.t("confirm.restart_body"))
            }
        }
        .task(id: serverId) {
            content.said = nil
            await content.loadGame()
        }
    }

    @ViewBuilder
    private func page(_ content: ContentPages, _ palette: Palette) -> some View {
        let canEdit = model.can(Permissions.SETTINGS_GAME)
        let strings = model.strings
        let read = content.game
        Text(model.t("game.intro"))
            .foregroundStyle(palette.textPrimary)
        if !canEdit && model.me != nil {
            Hint(text: model.t("mobile.game.read_only"), palette: palette)
        }
        if let problem = read.problem {
            ProblemCard(problem: problem, palette: palette) { await content.loadGame() }
        }
        if let settings = read.value {
            if !settings.exists {
                EmptyCard(title: model.t("game.no_file"), palette: palette)
            }
            if settings.restartNeeded {
                Text(model.t("game.restart_needed"))
                    .foregroundStyle(palette.tone(.warning))
            } else if settings.running && canEdit {
                Hint(text: model.t("game.after_restart"), palette: palette)
            }
            ForEach(GameForm.groups(settings), id: \.titleKey) { group in
                SectionTitle(text: model.t(group.titleKey), palette: palette)
                CardBox(palette: palette) {
                    ForEach(group.fields) { field in
                        GameField(
                            field: field,
                            value: content.shown(field),
                            locked: GameForm.locked(field, canEdit: canEdit),
                            problem: content.fieldProblems[field.key],
                            palette: palette
                        ) { content.edit(field.key, $0) }
                    }
                }
            }
            if canEdit {
                Button {
                    Task { await content.saveGame(strings) }
                } label: {
                    Text(model.t(content.busy == "game" ? "action.saving" : "game.save"))
                        .frame(minHeight: 32)
                }
                .buttonStyle(.borderedProminent)
                .tint(palette.accent)
                .disabled(content.busy != nil || !content.gameChanged)
                Hint(text: model.t("game.copy_kept"), palette: palette)
            }
            if canEdit && RawText.allowed(model.me, technical: model.technical, permission: Permissions.SETTINGS_GAME) && settings.exists {
                SectionTitle(text: model.t("game.raw_title"), palette: palette)
                CardBox(palette: palette) {
                    RawEditorView(
                        title: model.t("game.raw_label"),
                        hint: model.t("game.raw_hint", ["file": settings.file]),
                        saved: settings.text,
                        changes: { RawText.propertyChanges(settings.text, $0) },
                        busy: content.busy != nil,
                        palette: palette
                    ) { typed in Task { await content.saveGameText(typed, strings) } }
                }
            }
            SaidRow(said: content.said, palette: palette)
            if content.gameRestart && model.canControl {
                Presses(presses: [
                    Press(title: model.t("action.restart_now"), enabled: content.busy == nil) { restarting = true },
                ], palette: palette)
            }
        } else if read.problem == nil {
            ProgressView().frame(maxWidth: .infinity)
        }
    }
}

/// One setting: a switch, choices, or a box for a number or words.
private struct GameField: View {
    let field: GameSetting
    let value: String
    let locked: Bool
    let problem: String?
    let palette: Palette
    let change: (String) -> Void

    @Environment(AppModel.self) private var model

    var body: some View {
        let strings = model.strings
        let label = GameForm.label(strings, field)
        VStack(alignment: .leading, spacing: 6) {
            switch field.kind {
            case "bool":
                Toggle(label, isOn: Binding(get: { value == "true" }, set: { change($0 ? "true" : "false") }))
                    .disabled(locked)
                    .foregroundStyle(palette.textPrimary)
            case "choice":
                Picker(label, selection: Binding(get: { value }, set: { change($0) })) {
                    // The file's own value stays listed even when it isn't one of the choices.
                    if !field.choices.contains(value) {
                        Text(verbatim: value).tag(value)
                    }
                    ForEach(field.choices, id: \.self) { choice in
                        Text(GameForm.choiceLabel(strings, choice)).tag(choice)
                    }
                }
                .disabled(locked)
                .foregroundStyle(palette.textPrimary)
            default:
                Text(label)
                    .foregroundStyle(palette.textPrimary)
                TextField(label, text: Binding(get: { value }, set: { typed in
                    change(field.maxLength.map { String(typed.prefix($0)) } ?? typed)
                }))
                .textFieldStyle(.roundedBorder)
                .keyboardType(field.kind == "int" || field.kind == "port" ? .numberPad : .default)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)
                .disabled(locked)
            }
            if let problem = problem {
                Text(verbatim: problem)
                    .font(.footnote)
                    .foregroundStyle(palette.danger)
            }
            if let fileProblem = GameForm.fileProblem(strings, field) {
                Text(verbatim: fileProblem)
                    .font(.footnote)
                    .foregroundStyle(palette.tone(.warning))
            }
            let hint = GameForm.hint(strings, field)
            if !hint.isEmpty {
                Hint(text: hint, palette: palette)
            }
        }
        .frame(minHeight: 44, alignment: .leading)
    }
}
