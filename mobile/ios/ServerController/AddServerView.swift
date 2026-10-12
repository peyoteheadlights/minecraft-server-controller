import Core
import SwiftUI
import UniformTypeIdentifiers

/// The "+" on All servers (mirrors AddServer.kt): a new server (Java or
/// Bedrock, the kinds compared, a version, name, color, memory and folder,
/// then Minecraft's rules ticked by the person), one from a modpack file on
/// the phone, or one already on the PC. Nothing is started; the new server
/// opens once it's there.
struct AddServerView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.colorScheme) private var colorScheme
    @State private var pickingFolder = false
    @State private var pickingPack = false
    @State private var web: WebLink?

    var body: some View {
        let adding = model.adding
        Form {
            if let job = adding.task {
                Section {
                    Text(model.t("mobile.add.working", ["step": job.step ?? job.title]))
                    Text(model.t("mobile.add.leave_ok")).font(.footnote).foregroundStyle(.secondary)
                }
            }
            if let problem = adding.options.problem {
                Section {
                    Text(problem.message(model.strings)).foregroundStyle(.red)
                    Button(model.t("mobile.common.retry")) { Task { await adding.loadOptions() } }
                }
            }
            if let options = adding.options.value {
                if let way = adding.way {
                    Section {
                        Button(model.t("mobile.add.start_over")) { Task { await adding.startOver() } }
                    }
                    switch way {
                    case AddServer.NEW: newServer(adding, options)
                    case AddServer.MODPACK: fromModpack(adding, options)
                    default: alreadyThere(adding, options)
                    }
                    ForEach(adding.addedLines, id: \.self) { line in Text(line) }
                    if let added = adding.added {
                        Button(model.t("mobile.add.open", ["name": added.server.name])) { adding.openAdded() }
                    }
                } else {
                    Section(model.t("add.ways")) {
                        wayButton(adding, AddServer.NEW, "add.way_new", "mobile.add.way_new_hint")
                        wayButton(adding, AddServer.MODPACK, "add.way_modpack", "mobile.add.way_modpack_hint")
                        wayButton(adding, AddServer.HAVE, "add.way_have", "mobile.add.way_have_hint")
                    }
                }
                if let said = adding.said {
                    Section { Text(said.text).foregroundStyle(said.good ? Color.primary : Color.red) }
                }
            } else if adding.options.problem == nil {
                ProgressView().frame(maxWidth: .infinity)
            }
        }
        .navigationTitle(model.t("mobile.add.title"))
        .navigationBarTitleDisplayMode(.inline)
        .task {
            if adding.options.value == nil { await adding.loadOptions() } else { await adding.resume() }
        }
        .onDisappear {
            // Leaving half way: an uploaded pack isn't left on the PC.
            Task { await adding.leave() }
        }
        .onChange(of: adding.opened) {
            guard let id = adding.opened else { return }
            // The new server opens in place of the "+" screen.
            model.serversPath = [.server(id)]
            Task { await adding.openedShown() }
        }
        .sheet(isPresented: $pickingFolder) {
            FolderPickerView(title: model.t("mobile.add.pick_folder"), start: adding.parent) { folder in
                adding.parent = folder
                adding.typedFolder = nil
            }
        }
        .sheet(item: $web) { page in
            SafariView(url: page.url).ignoresSafeArea()
        }
        .fileImporter(isPresented: $pickingPack, allowedContentTypes: [.item]) { result in
            guard case .success(let url) = result else { return }
            let strings = model.strings
            guard Content.accepts(.mods, url.lastPathComponent, modpack: true) else {
                adding.said = Said(text: strings.t("mobile.content.wrong_file", ["kind": Content.MODPACK]), good: false)
                return
            }
            Task {
                do {
                    let file = try await Task.detached { try PickedCopy.make(url) }.value
                    await adding.inspect(file, strings)
                } catch {
                    adding.said = Said(text: strings.t("mobile.error.failed", ["reason": error.localizedDescription]), good: false)
                }
            }
        }
    }

    private func wayButton(_ adding: AddServerPages, _ way: String, _ title: String, _ hint: String) -> some View {
        Button {
            Task { await adding.begin(way) }
        } label: {
            VStack(alignment: .leading, spacing: 4) {
                Text(model.t(title)).foregroundStyle(.primary)
                Text(model.t(hint)).font(.footnote).foregroundStyle(.secondary)
            }
            .frame(minHeight: 44)
        }
    }

    // MARK: - New server

    @ViewBuilder
    private func newServer(_ adding: AddServerPages, _ options: NewServerOptions) -> some View {
        Section(model.t("new.step_edition")) {
            Picker(model.t("new.edition"), selection: Binding(get: { adding.edition }, set: { edition in Task { await adding.pickEdition(edition) } })) {
                Text(model.t("new.java")).tag("java")
                Text(model.t("new.bedrock")).tag("bedrock")
            }
            .pickerStyle(.inline)
            .labelsHidden()
            Text(model.t(adding.edition == "bedrock" ? "new.bedrock_hint" : "new.java_hint")).font(.footnote).foregroundStyle(.secondary)
        }
        if adding.edition == "java" {
            Section {
                ForEach(AddServer.kinds(options), id: \.id) { kind in
                    kindCard(adding, kind, recommended: kind.id == options.recommended)
                }
            } header: {
                Text(model.t("new.step_kind"))
            } footer: {
                Text(model.t("new.kind_hint"))
            }
        } else {
            Section { Text(model.t("new.bedrock_versions")).font(.footnote).foregroundStyle(.secondary) }
        }
        if let kind = adding.type {
            versionStep(adding)
            detailsStep(adding, options, memory: AddServer.memoryShown(kind))
            rulesStep(adding, options, kind.edition)
            Section {
                Button(model.t(adding.busy == "create" ? "new.creating" : "new.create")) {
                    let strings = model.strings
                    Task { await adding.create(strings) }
                }
                .disabled(!AddServer.ready(name: adding.name, folder: adding.folder, version: adding.version?.minecraft, ruled: adding.ruled)
                    || adding.busy != nil || adding.task != nil)
            } footer: {
                Text(model.t("new.create_hint"))
            }
        }
    }

    private func kindCard(_ adding: AddServerPages, _ kind: ServerTypeInfo, recommended: Bool) -> some View {
        let chosen = adding.type?.id == kind.id
        return VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(kind.name).font(.headline)
                Spacer()
                if recommended { Text(model.t("new.recommended")).font(.footnote).foregroundStyle(.green) }
            }
            ForEach(Array(AddServer.rows(model.strings, kind, technical: model.technical).enumerated()), id: \.offset) { _, row in
                Text(verbatim: "\(row.0): \(row.1)").font(.footnote).foregroundStyle(.secondary)
            }
            Button(model.t(chosen ? "new.chosen" : "new.choose")) { Task { await adding.pickType(kind) } }
                .buttonStyle(.bordered)
                .disabled(chosen)
        }
        .padding(.vertical, 4)
    }

    @ViewBuilder
    private func versionStep(_ adding: AddServerPages) -> some View {
        Section(model.t("new.step_version")) {
            if let problem = adding.versions.problem {
                Text(problem.message(model.strings)).foregroundStyle(.red)
            }
            if let versions = adding.versions.value {
                if let source = versions.source {
                    Text(model.t("new.version_hint", ["source": source])).font(.footnote).foregroundStyle(.secondary)
                }
                if versions.snapshots {
                    Toggle(model.t("new.show_snapshots"), isOn: Binding(get: { adding.snapshots }, set: { adding.snapshots = $0 }))
                }
                Picker(model.t("new.version"), selection: Binding(get: { adding.version?.minecraft ?? "" }, set: { adding.pickVersion($0) })) {
                    if adding.version == nil { Text(model.t("mobile.version.pick")).tag("") }
                    ForEach(adding.choices, id: \.minecraft) { offered in
                        Text(offered.stable ? offered.minecraft : model.t("new.snapshot_option", ["version": offered.minecraft])).tag(offered.minecraft)
                    }
                }
                if adding.type?.picksLoader == true, let loaders = adding.version?.loaders, !loaders.isEmpty {
                    Picker(model.t("new.loader_choice"), selection: Binding(get: { adding.loader ?? loaders[0] }, set: { adding.loader = $0 })) {
                        ForEach(loaders, id: \.self) { Text($0).tag($0) }
                    }
                    Text(model.t("new.loader_hint")).font(.footnote).foregroundStyle(.secondary)
                }
            } else if adding.versions.problem == nil {
                ProgressView().frame(maxWidth: .infinity)
            }
        }
    }

    @ViewBuilder
    private func detailsStep(_ adding: AddServerPages, _ options: NewServerOptions, memory: Bool) -> some View {
        Section(model.t("new.step_details")) {
            TextField(model.t("add.name"), text: Binding(get: { adding.name }, set: { adding.name = String($0.prefix(60)) }))
            folderRows(adding, label: "new.folder", hint: "new.folder_hint")
            if memory, let mb = adding.memoryMb {
                Stepper(value: Binding(get: { mb }, set: { adding.nudgeMemory($0 - mb) }), in: 1024...(64 * 1024), step: 512) {
                    Text(verbatim: model.t("new.memory") + ": " + Memory.gb(mb))
                }
            }
            ServerColorPicker(colors: options.palette, current: adding.color, locked: false, palette: model.serverPalette(adding.color, colorScheme)) { adding.color = $0 }
        }
    }

    @ViewBuilder
    private func folderRows(_ adding: AddServerPages, label: String, hint: String) -> some View {
        if model.technical {
            TextField(model.t(label), text: Binding(get: { adding.typedFolder ?? adding.folder }, set: { adding.typedFolder = $0 }))
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)
        } else {
            LabeledContent(model.t(label), value: adding.folder.isEmpty ? model.t("mobile.add.no_folder") : adding.folder)
        }
        Button(model.t("mobile.add.pick_folder")) { pickingFolder = true }
        Text(model.t(hint)).font(.footnote).foregroundStyle(.secondary)
    }

    @ViewBuilder
    private func rulesStep(_ adding: AddServerPages, _ options: NewServerOptions, _ edition: String) -> some View {
        let bedrock = edition == "bedrock"
        Section(model.t("new.step_rules")) {
            Text(model.t(bedrock ? "new.bedrock_terms_intro" : "new.eula_intro"))
            Button(model.t("new.eula_link")) {
                if let url = URL(string: bedrock ? options.bedrock.eulaUrl : options.eulaUrl) { web = WebLink(url: url) }
            }
            if bedrock {
                Button(model.t("new.privacy_link")) {
                    if let url = URL(string: options.bedrock.privacyUrl) { web = WebLink(url: url) }
                }
            }
            Toggle(model.t(AddServer.ruleKey(edition)), isOn: Binding(get: { adding.ruled }, set: { adding.ruled = $0 }))
        }
    }

    // MARK: - From a modpack

    @ViewBuilder
    private func fromModpack(_ adding: AddServerPages, _ options: NewServerOptions) -> some View {
        Section {
            if adding.busy == "inspect" { Text(model.t("mobile.content.reading")).foregroundStyle(.secondary) }
            Button(model.t("mobile.content.modpack_choose")) { pickingPack = true }
                .disabled(adding.busy != nil)
        }
        if let inspected = adding.pack {
            let pack = inspected.pack
            let unknown = model.t("value.unknown")
            Section(model.t("mobile.add.pack_name", ["name": pack.name.isEmpty ? unknown : pack.name])) {
                Text(model.t("pack.minecraft") + ": " + (pack.minecraftVersion ?? unknown))
                Text(model.t("pack.loader") + ": " + ([pack.typeName, pack.loaderVersion].compactMap { $0 }.joined(separator: " ").nonEmpty ?? unknown))
                Text(model.t("pack.files") + ": " + model.t("pack.files_value", ["count": pack.downloadCount, "size": Display.bytes(model.strings, pack.downloadBytes)]))
                ForEach(pack.problems, id: \.self) { Text("• " + $0).foregroundStyle(.red) }
                if !pack.clientOnly.isEmpty {
                    Text(model.t("pack.client_only", ["names": pack.clientOnly.joined(separator: ", ")])).font(.footnote)
                }
            }
            if pack.canImport {
                detailsStep(adding, options, memory: true)
                rulesStep(adding, options, "java")
                Section {
                    Button(model.t(adding.busy == "create" ? "new.creating" : "new.create")) {
                        let strings = model.strings
                        Task { await adding.createFromPack(strings) }
                    }
                    .disabled(!AddServer.ready(name: adding.name, folder: adding.folder, version: pack.minecraftVersion, ruled: adding.ruled)
                        || adding.busy != nil || adding.task != nil)
                }
            }
        }
    }

    // MARK: - Already on the PC

    @ViewBuilder
    private func alreadyThere(_ adding: AddServerPages, _ options: NewServerOptions) -> some View {
        Section {
            TextField(model.t("add.name"), text: Binding(get: { adding.name }, set: { adding.name = String($0.prefix(60)) }))
            Picker(model.t("add.kind"), selection: Binding(get: { adding.type?.id ?? "" }, set: { id in
                if let kind = options.types.first(where: { $0.id == id }) { Task { await adding.pickType(kind) } }
            })) {
                if adding.type == nil { Text(model.t("mobile.version.pick")).tag("") }
                ForEach(options.types, id: \.id) { Text($0.name).tag($0.id) }
            }
            Text(model.t("add.kind_hint")).font(.footnote).foregroundStyle(.secondary)
            folderRows(adding, label: "add.folder", hint: "add.existing_hint")
            if model.technical {
                TextField(model.t("add.jar"), text: Binding(get: { adding.jar }, set: { adding.jar = String($0.prefix(180)) }))
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
                Text(model.t("add.jar_hint")).font(.footnote).foregroundStyle(.secondary)
            }
            Button(model.t(adding.busy == "add" ? "add.adding" : "add.submit")) {
                let strings = model.strings
                Task { await adding.add(strings) }
            }
            .disabled(adding.busy != nil || adding.type == nil || adding.name.trimmingCharacters(in: .whitespaces).isEmpty || adding.folder.isEmpty)
        } header: {
            Text(model.t("add.existing"))
        } footer: {
            Text(model.t("add.existing_hint"))
        }
    }
}

private extension String {
    var nonEmpty: String? { isEmpty ? nil : self }
}
