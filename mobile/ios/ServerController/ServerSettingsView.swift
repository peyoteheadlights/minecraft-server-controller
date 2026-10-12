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
    @State private var asking: SetupAsk?

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
            .refreshable {
                await setup.loadSettings()
                await setup.loadMemory()
                await setup.loadVersion()
                await setup.loadCrossplay()
            }
            .alert(askTitle(setup), isPresented: Binding(get: { asking != nil }, set: { if !$0 { asking = nil } })) {
                Button(askButton,
                       role: asking == .remove || (asking == .change && setup.report?.value.map(VersionChange.danger) == true) ? .destructive : nil) {
                    let strings = model.strings
                    let what = asking
                    asking = nil
                    Task {
                        switch what {
                        case .rollBack: await setup.rollBack(strings)
                        case .change: await setup.changeVersion(strings)
                        case .crossplayOn: await setup.setCrossplay(true, strings)
                        // The server is gone: back to All servers, not to its page.
                        case .remove: if await setup.removeServer(strings) { model.serversPath = [] }
                        case nil: break
                        }
                    }
                }
                Button(model.t("mobile.common.cancel"), role: .cancel) { asking = nil }
            } message: {
                Text(askBody(setup))
            }
        }
        .task(id: serverId) {
            setup.said = nil
            await setup.loadSettings()
            await setup.loadMemory()
            await setup.loadVersion()
            await setup.loadCrossplay()
            if Duplicate.allowed(model.me) { await setup.loadCopyOptions() }
        }
    }

    private func askTitle(_ setup: SetupPages) -> String {
        switch asking {
        case .rollBack: return model.t("version.back_title")
        case .change: return model.t("version.confirm_title", ["name": setup.report?.value.map(VersionChange.target) ?? ""])
        case .crossplayOn: return model.t("cross.on_title")
        case .remove: return model.t("serverset.remove_title", ["name": model.servers.first(where: { $0.id == serverId })?.name ?? serverId])
        case nil: return ""
        }
    }

    private var askButton: String {
        switch asking {
        case .rollBack: return model.t("version.back_button")
        case .crossplayOn: return model.t("cross.on_button")
        case .remove: return model.t("serverset.remove_confirm")
        default: return model.t("version.confirm_button")
        }
    }

    private func askBody(_ setup: SetupPages) -> String {
        switch asking {
        case .rollBack: return model.t("version.back_body")
        case .crossplayOn: return Crossplay.confirm(model.strings, setup.crossPort)
        case .remove: return model.t("serverset.remove_body")
        default: return model.t("version.confirm_body")
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
            SectionTitle(text: model.t("serverset.cpu"), palette: palette)
            CardBox(palette: palette) { coresCard(setup, settings.cpu, canEdit, palette) }
            SectionTitle(text: model.t("version.title"), palette: palette)
            CardBox(palette: palette) {
                VersionCardView(setup: setup, canEdit: canEdit, palette: palette) { asking = $0 }
            }
            SectionTitle(text: model.t("cross.title"), palette: palette)
            CardBox(palette: palette) {
                CrossplayCardView(setup: setup, canEdit: canEdit, palette: palette) { asking = $0 }
            }
            SectionTitle(text: model.t("memory.title"), palette: palette)
            CardBox(palette: palette) { memoryCard(setup, canEdit, palette) }
            if let memory = setup.memory.value, RawText.allowed(model.me, technical: model.technical) {
                CardBox(palette: palette) {
                    RawEditorView(
                        title: model.t("mobile.raw.args_title"),
                        hint: model.t("mobile.raw.args_hint"),
                        saved: memory.jvmArgs.joined(separator: " "),
                        changes: { RawText.argChanges(memory.jvmArgs, RawText.args($0)) },
                        busy: setup.busy != nil,
                        palette: palette
                    ) { typed in
                        let strings = model.strings
                        Task { await setup.saveJavaOptions(RawText.args(typed), strings) }
                    }
                }
            }
            if Duplicate.allowed(model.me) {
                SectionTitle(text: model.t("dup.title"), palette: palette)
                CardBox(palette: palette) { DuplicateCardView(setup: setup, serverId: serverId, palette: palette) }
            }
            if RemoveServer.allowed(model.me) {
                SectionTitle(text: model.t("serverset.remove"), palette: palette)
                CardBox(palette: palette) { RemoveCardView(setup: setup, palette: palette) { asking = $0 } }
            }
        } else if read.problem == nil {
            ProgressView().frame(maxWidth: .infinity)
        }
    }
}

extension ServerSettingsView {
    /// Which CPU cores the server may use, who else uses each, and what the
    /// running server really got; or why this PC can't limit them.
    @ViewBuilder
    func coresCard(_ setup: SetupPages, _ cpu: CpuOverview, _ canEdit: Bool, _ palette: Palette) -> some View {
        if !cpu.supported || (cpu.logicalCores ?? 0) == 0 {
            Text(cpu.unsupportedReason ?? model.t("serverset.cpu_unreadable"))
                .foregroundStyle(palette.textSecondary)
        } else {
            let count = cpu.logicalCores ?? 0
            let shared = CpuCores.sharedBy(cpu)
            Toggle(model.t("serverset.all_cores", ["count": count]), isOn: Binding(get: { setup.everyCore }, set: { setup.setAllCores($0) }))
                .disabled(!canEdit)
                .foregroundStyle(palette.textPrimary)
            if !setup.everyCore {
                ForEach(0..<count, id: \.self) { core in
                    Toggle(isOn: Binding(get: { setup.pickedCores.contains(core) }, set: { _ in setup.toggleCore(core) })) {
                        VStack(alignment: .leading) {
                            Text(model.t("serverset.core", ["n": core + 1]))
                            if let names = shared[core] {
                                Text(model.t("serverset.core_shared", ["names": names.joined(separator: ", ")]))
                                    .font(.footnote)
                                    .foregroundStyle(palette.textSecondary)
                            }
                        }
                    }
                    .disabled(!canEdit)
                    .foregroundStyle(palette.textPrimary)
                }
            }
            Text(CpuCores.nowLine(model.strings, cpu))
                .foregroundStyle(palette.textSecondary)
            if let problem = cpu.status.problems.first {
                Text(verbatim: problem).foregroundStyle(palette.danger)
            }
            if canEdit {
                HStack {
                    Button(model.t(setup.busy == "cores" ? "action.saving" : "action.save")) {
                        let strings = model.strings
                        Task { await setup.saveCores(strings) }
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(palette.accent)
                    Button(model.t("serverset.half_cores")) { setup.pickHalf(count) }
                        .buttonStyle(.bordered)
                }
                .disabled(setup.busy != nil)
            }
        }
    }

    /// The memory slider: bounded by the PC's memory, with the warning when
    /// every running server together may use more than the PC has.
    @ViewBuilder
    func memoryCard(_ setup: SetupPages, _ canEdit: Bool, _ palette: Palette) -> some View {
        if let problem = setup.memory.problem {
            Text(problem.message(model.strings)).foregroundStyle(palette.danger)
        }
        if let memory = setup.memory.value {
            let bedrock = model.servers.first(where: { $0.id == serverId })?.edition == "bedrock"
            Text(model.t("memory.label")).foregroundStyle(palette.textPrimary)
            Text(memory.totalMb.map { model.t("memory.pc_has", ["total": Memory.gb($0)]) } ?? model.t("memory.pc_unknown"))
                .foregroundStyle(palette.textSecondary)
            if Memory.slider(memory) {
                let chosen = setup.memoryChoice ?? Memory.start(memory)
                HStack {
                    Slider(
                        value: Binding(get: { Double(chosen) }, set: { setup.slideMemory($0) }),
                        in: Double(memory.minMb)...Double(max(memory.minMb, memory.totalMb ?? memory.minMb))
                    )
                    .disabled(!canEdit)
                    .accessibilityValue(Memory.gb(chosen))
                    Text(Memory.gb(chosen)).foregroundStyle(palette.textPrimary).monospacedDigit()
                }
                Text(Memory.nowLine(model.strings, memory)).foregroundStyle(palette.textSecondary)
                if let warning = Memory.warning(model.strings, memory, chosen) {
                    Text(warning).foregroundStyle(palette.tone(.warning))
                }
                if canEdit {
                    Button(model.t(setup.busy == "memory" ? "action.saving" : "memory.save")) {
                        let strings = model.strings
                        Task { await setup.saveMemory(strings) }
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(palette.accent)
                    .disabled(setup.busy != nil)
                }
            } else if !memory.takesMemoryLimit {
                Text(Memory.noSlider(model.strings, memory, bedrock: bedrock)).foregroundStyle(palette.textSecondary)
            }
        } else if setup.memory.problem == nil {
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
struct ServerColorPicker: View {
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
