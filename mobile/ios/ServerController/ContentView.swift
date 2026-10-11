import Core
import SwiftUI
import UIKit
import UniformTypeIdentifiers

/// A step waiting for "yes".
private struct ContentConfirm: Identifiable {
    let title: String
    let body: String
    let confirm: String
    var danger = true
    let run: () -> Void

    var id: String { title }
}

/// Which file the Files picker is choosing.
private enum Picking {
    case jar, modpack, pack
}

/// Mods, Plugins or Packs, named for the server type (mirrors
/// ContentScreen.kt). Java servers: what's installed with on/off, Update,
/// Versions (Roll back) and Remove, Update all, the missing dependencies,
/// Modrinth search, a .jar or modpack from the phone, and the change
/// history. They change only while the server is stopped, so while it runs
/// the screen offers Stop, which asks first. Bedrock servers: their packs,
/// which change while it runs too and then offer Restart now.
struct ContentView: View {
    let serverId: String

    @Environment(AppModel.self) private var model
    @State private var asking: ContentConfirm?
    @State private var picking: Picking?
    @State private var query = ""
    @State private var web: WebLink?

    private var content: ContentPages { model.pages(serverId).content }
    private var row: ServerRow? { model.servers.first(where: { $0.id == serverId }) }

    var body: some View {
        @Bindable var content = self.content
        let kind = Content.kind(row)
        ServerFrame(serverId: serverId, title: model.t((kind ?? .mods).titleKey)) { palette in
            ScrollView {
                TimelineView(.periodic(from: .now, by: 30)) { context in
                    VStack(alignment: .leading, spacing: 12) {
                        switch kind {
                        case nil:
                            ProgressView().frame(maxWidth: .infinity)
                        case .some(ContentKind.none):
                            EmptyCard(title: model.t("mobile.content.none_for_type"), palette: palette)
                        case .some(.packs):
                            packs(content, palette)
                        case .some(let kind):
                            mods(content, kind, palette, now: context.date.timeIntervalSince1970)
                        }
                    }
                    .padding(16)
                    .frame(maxWidth: 640)
                    .frame(maxWidth: .infinity)
                }
                .sheet(item: $web) { page in
                    SafariView(url: page.url).ignoresSafeArea()
                }
            }
            .refreshable { await reload(kind) }
            .alert(
                pending(content)?.title ?? "",
                isPresented: Binding(get: { pending(content) != nil }, set: { shown in
                    if !shown {
                        asking = nil
                        content.removing = nil
                        content.updating = nil
                    }
                }),
                presenting: pending(content),
                actions: { ask in
                    Button(ask.confirm, role: ask.danger ? .destructive : nil, action: ask.run)
                    Button(model.t("mobile.common.cancel"), role: .cancel) {}
                },
                message: { ask in Text(verbatim: ask.body) }
            )
            .sheet(item: $content.versions) { ask in
                VersionsSheet(content: content, ask: ask, palette: palette)
            }
            .fileImporter(
                isPresented: Binding(get: { picking != nil }, set: { if !$0 { picking = nil } }),
                allowedContentTypes: [.item]
            ) { result in
                let what = picking
                picking = nil
                if case .success(let url) = result, let what = what {
                    picked(url, what, kind ?? .mods)
                }
            }
        }
        .sheet(item: $content.sheet, onDismiss: { content.sheetClosed() }) { sheet in
            NavigationStack {
                sheetBody(content, sheet)
            }
        }
        .task(id: serverId) {
            content.said = nil
            await reload(kind)
        }
    }

    private func reload(_ kind: ContentKind?) async {
        switch kind {
        case .packs: await content.loadAddons()
        case .mods, .plugins: await content.loadMods()
        default: break
        }
    }

    /// The question showing now: one asked here, a Remove or an Update.
    private func pending(_ content: ContentPages) -> ContentConfirm? {
        if let asking = asking { return asking }
        let strings = model.strings
        if let ask = content.removing {
            let needed = ask.impact.dependents.map { d in
                strings.t("mods.needed_by", ["name": d.name, "requires": d.requires ?? strings.t("value.unknown")])
            }
            var lines = needed.isEmpty ? [strings.t("mods.not_needed")] : needed
            if let warning = ask.impact.warning { lines.append(warning) }
            lines.append(strings.t("mods.remove_kept"))
            return ContentConfirm(
                title: strings.t("mods.remove_title", ["name": ask.mod.name]),
                body: lines.joined(separator: "\n"),
                confirm: strings.t("mods.remove")
            ) {
                Task { await content.remove(ask, strings) }
            }
        }
        if let mod = content.updating {
            let body = Content.change(strings, mod.version, mod.updateAvailable?.latestVersion) + "\n" + strings.t("mods.update_archived")
            return ContentConfirm(
                title: strings.t("mods.update_title", ["name": mod.name]),
                body: body,
                confirm: strings.t("mods.update"),
                danger: false
            ) {
                Task { await content.update(mod, strings) }
            }
        }
        return nil
    }

    // MARK: - Mods and plugins

    @ViewBuilder
    private func mods(_ content: ContentPages, _ kind: ContentKind, _ palette: Palette, now: Double) -> some View {
        let read = content.mods
        let state = content.serverState
        let changes = Content.changes(canManage: model.can(Permissions.MODS_MANAGE), serverState: state)
        let idle = content.busy == nil
        let strings = model.strings

        changesCard(content, changes, state, palette)
        taskNote(content, palette)
        SaidRow(said: content.said, palette: palette)

        if let problem = read.problem {
            Hint(text: model.t("mobile.content.unknown"), palette: palette)
            ProblemCard(problem: problem, palette: palette) { await content.loadMods() }
        }
        if let list = read.value {
            if changes == .ready {
                Presses(presses: [
                    Press(
                        title: model.t(UpdateAll.offered(list) ? "mobile.content.update_all" : "mobile.content.check_updates"),
                        enabled: idle && !list.mods.isEmpty
                    ) {
                        Task { await content.openUpdateAll() }
                    },
                ], palette: palette)
            }

            let missing = Content.missing(content.dependencies)
            // Unread is said as such, never shown as "nothing missing".
            if content.dependencies == nil {
                Hint(text: model.t("mobile.content.missing_unknown"), palette: palette)
            }
            if !missing.isEmpty {
                SectionTitle(text: model.t("mobile.content.missing_title"), palette: palette)
                CardBox(palette: palette) {
                    ForEach(missing, id: \.modId) { dep in
                        VStack(alignment: .leading, spacing: 2) {
                            Text(verbatim: dep.name.isEmpty ? dep.modId : dep.name)
                                .foregroundStyle(palette.textPrimary)
                            if let why = dep.reason ?? dep.rangeText {
                                Hint(text: why, palette: palette)
                            }
                        }
                    }
                    if changes == .ready {
                        Presses(presses: [
                            Press(title: model.t("mobile.content.install_missing"), enabled: idle) {
                                Task { await content.planMissing() }
                            },
                        ], palette: palette)
                    }
                }
            }

            SectionTitle(
                text: kind == .plugins ? model.t("page.plugins") + " · \(list.mods.count)" : strings.tn("mods.installed", count: list.mods.count),
                palette: palette
            )
            if list.mods.isEmpty {
                EmptyCard(title: model.t("mods.none"), hint: changes == .ready ? model.t("mods.none_hint") : nil, palette: palette)
            }
            ForEach(list.mods) { mod in
                modCard(content, mod, changes, palette)
            }

            if changes == .ready {
                SectionTitle(text: model.t("mobile.content.search_title"), palette: palette)
                searchCard(content, list.minecraftVersion, palette)
                found(content, palette)
                addFiles(content, palette)
            }

            SectionTitle(text: model.t("mods.change_history"), palette: palette)
            if let problem = content.history.problem {
                Hint(text: problem.message(strings), palette: palette)
            } else if let rows = content.history.value?.history {
                if rows.isEmpty {
                    EmptyCard(title: model.t("mods.no_history"), palette: palette)
                }
                ForEach(Array(rows.prefix(50).enumerated()), id: \.offset) { _, row in
                    historyCard(row, palette, now: now)
                }
            }
        } else if read.problem == nil {
            ProgressView().frame(maxWidth: .infinity)
        }
    }

    /// Why changes are off now, with Stop right here while the server runs.
    @ViewBuilder
    private func changesCard(_ content: ContentPages, _ changes: Changes, _ state: String?, _ palette: Palette) -> some View {
        switch changes {
        case .ready:
            EmptyView()
        case .notAllowed:
            Hint(text: model.t("mobile.content.not_allowed"), palette: palette)
        case .unknown:
            Text(model.t("mobile.content.state_unknown"))
                .foregroundStyle(palette.tone(.warning))
        case .stopFirst:
            CardBox(palette: palette) {
                Text(model.t("mobile.content.stop_first"))
                    .foregroundStyle(palette.textPrimary)
                if Content.canStopHere(state, canControl: model.canControl) {
                    let strings = model.strings
                    Presses(presses: [
                        Press(title: model.t(content.busy == "stop" ? "action.stopping" : "action.stop"), danger: true, enabled: content.busy == nil) {
                            asking = ContentConfirm(
                                title: strings.t("mobile.content.stop_confirm_title"),
                                body: strings.t("mobile.content.stop_confirm_body"),
                                confirm: strings.t("action.stop")
                            ) {
                                Task { await content.stop(strings) }
                            }
                        },
                    ], palette: palette)
                } else {
                    Hint(text: model.t("mods.running_notice", ["state": model.t(Display.state(state).key)]), palette: palette)
                }
            }
        }
    }

    /// A running install, Update all or modpack import, with the step the live feed last said.
    @ViewBuilder
    private func taskNote(_ content: ContentPages, _ palette: Palette) -> some View {
        if let busy = content.busy,
           busy == "update_all" || busy == "modpack" || busy == "missing" || busy.hasPrefix("install:") || busy.hasPrefix("update:") {
            HStack(spacing: 8) {
                ProgressView().controlSize(.small)
                if let step = UpdateAll.progress(content.task, serverId: serverId) {
                    Text(model.t("mobile.content.update_all_working", ["step": step]))
                } else {
                    Text(model.t("mobile.content.working"))
                }
            }
            .foregroundStyle(palette.textPrimary)
        }
    }

    private func modCard(_ content: ContentPages, _ mod: Mod, _ changes: Changes, _ palette: Palette) -> some View {
        let strings = model.strings
        let status = Content.status(mod)
        let idle = content.busy == nil
        let ready = changes == .ready && idle
        var presses: [Press] = []
        if changes != .notAllowed {
            presses.append(Press(title: model.t(mod.enabled ? "mods.turn_off" : "mods.turn_on"), enabled: ready) {
                Task { await content.setEnabled(mod, !mod.enabled, strings) }
            })
            if mod.updateAvailable != nil {
                presses.append(Press(title: model.t("mods.update"), enabled: ready) { content.updating = mod })
            }
            if !mod.modId.isEmpty {
                presses.append(Press(title: model.t("mobile.content.versions"), enabled: idle) {
                    Task { await content.showVersions(mod) }
                })
            }
            presses.append(Press(title: model.t("mods.remove"), danger: true, enabled: ready) {
                Task { await content.askRemove(mod, strings) }
            })
        }
        return CardBox(palette: palette) {
            Text(verbatim: mod.name.isEmpty ? mod.filename : mod.name)
                .font(.headline)
                .foregroundStyle(palette.textPrimary)
            Text(verbatim: (mod.version.isEmpty ? model.t("value.unknown") : mod.version) + " · " + model.t(status.key))
                .font(.footnote)
                .foregroundStyle(status.tone == .neutral ? palette.textSecondary : palette.tone(status.tone))
            ForEach(Content.problems(mod), id: \.self) { problem in
                Text(verbatim: problem)
                    .font(.footnote)
                    .foregroundStyle(palette.tone(mod.status == "error" ? .danger : .warning))
            }
            if let newer = Content.newer(strings, mod) {
                Text(verbatim: newer)
                    .font(.footnote)
                    .foregroundStyle(palette.accentInk)
            }
            if model.technical {
                Hint(text: Content.technical(strings, mod), palette: palette)
            }
            Presses(presses: presses, palette: palette)
        }
    }

    private func searchCard(_ content: ContentPages, _ minecraft: String?, _ palette: Palette) -> some View {
        let unknown = model.t("value.unknown")
        let searching = content.found?.loading == true
        return CardBox(palette: palette) {
            TextField(model.t("mods.search_label"), text: $query)
                .textFieldStyle(.roundedBorder)
                .submitLabel(.search)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)
                .onChange(of: query) { if query.count > 100 { query = String(query.prefix(100)) } }
                .onSubmit { Task { await content.search(query) } }
            Hint(text: model.t("mobile.content.search_hint", [
                "type": row?.typeName ?? unknown, "version": minecraft ?? unknown,
            ]), palette: palette)
            Presses(presses: [
                Press(title: model.t(searching ? "mods.searching" : "mods.search"), enabled: !query.trimmingCharacters(in: .whitespaces).isEmpty) {
                    Task { await content.search(query) }
                },
            ], palette: palette)
        }
    }

    @ViewBuilder
    private func found(_ content: ContentPages, _ palette: Palette) -> some View {
        if let read = content.found {
            if let problem = read.problem {
                ProblemRow(text: problem.message(model.strings), palette: palette)
            }
            if let found = read.value {
                if found.hits.isEmpty {
                    Hint(text: model.t("mods.nothing_found"), palette: palette)
                }
                ForEach(found.hits) { hit in
                    hitCard(content, hit, palette)
                }
                if found.more {
                    Presses(presses: [
                        Press(title: model.t("mobile.content.more"), enabled: !read.loading) {
                            Task { await content.searchMore() }
                        },
                    ], palette: palette)
                }
            }
        }
    }

    private func hitCard(_ content: ContentPages, _ hit: ModrinthHit, _ palette: Palette) -> some View {
        var presses = [
            Press(title: model.t("mods.install"), enabled: content.busy == nil) {
                Task { await content.openProject(hit) }
            },
        ]
        if let page = Install.page(hit.page) {
            presses.append(Press(title: model.t("mobile.content.open_page")) { web = WebLink(url: page) })
        }
        let lines: [String?] = [hit.description.map { String($0.prefix(160)) }, Install.downloads(model.strings, hit.downloads)]
        let details = lines.compactMap { $0 }
        return CardBox(palette: palette) {
            HStack(alignment: .top, spacing: 12) {
                ModIcon(icons: model.icons, url: hit.iconUrl, palette: palette)
                VStack(alignment: .leading, spacing: 4) {
                    Text(verbatim: hit.title.isEmpty ? hit.slug : hit.title)
                        .font(.headline)
                        .foregroundStyle(palette.textPrimary)
                    ForEach(details, id: \.self) { line in
                        Hint(text: line, palette: palette)
                    }
                }
            }
            Presses(presses: presses, palette: palette)
        }
    }

    /// A .jar from the phone, or a Modrinth modpack imported into this server.
    @ViewBuilder
    private func addFiles(_ content: ContentPages, _ palette: Palette) -> some View {
        let busy = content.busy
        SectionTitle(text: model.t("mobile.content.add_file"), palette: palette)
        CardBox(palette: palette) {
            Text(model.t("mobile.content.add_file_hint"))
                .foregroundStyle(palette.textPrimary)
            if busy == "upload" || busy == "modpack" {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Hint(text: model.t("mobile.content.reading"), palette: palette)
                }
            }
            Presses(presses: [
                Press(title: model.t("mobile.content.add_file"), enabled: busy == nil) { picking = .jar },
                Press(title: model.t("mobile.content.modpack_choose"), enabled: busy == nil) { picking = .modpack },
            ], palette: palette)
            Hint(text: model.t("pack.into_intro"), palette: palette)
        }
    }

    private func historyCard(_ row: ModHistoryRow, _ palette: Palette, now: Double) -> some View {
        let strings = model.strings
        var details = [strings.t("mobile.content.history_by", [
            "when": Display.ago(strings, row.ts, now: now), "who": row.user ?? strings.t("value.unknown"),
        ])]
        if row.oldVersion != nil || row.newVersion != nil {
            details.append(Content.change(strings, row.oldVersion, row.newVersion))
        }
        var result = strings.t(row.result == "ok" ? "mobile.content.result_ok" : "mobile.content.result_failed")
        if row.result != "ok", let detail = row.detail {
            result += ": " + detail
        }
        return CardBox(palette: palette) {
            Text(verbatim: Content.action(strings, row) + ": " + Content.historyName(strings, row))
                .foregroundStyle(palette.textPrimary)
            Hint(text: details.joined(separator: " · "), palette: palette)
            Text(verbatim: result)
                .font(.footnote)
                .foregroundStyle(palette.tone(Content.historyTone(row)))
        }
        .accessibilityElement(children: .combine)
    }

    // MARK: - Bedrock packs

    @ViewBuilder
    private func packs(_ content: ContentPages, _ palette: Palette) -> some View {
        let read = content.addons
        let changes = Content.packChanges(canManage: model.can(Permissions.MODS_MANAGE))
        let strings = model.strings
        let idle = content.busy == nil
        if changes == .notAllowed {
            Hint(text: model.t("mobile.content.not_allowed"), palette: palette)
        }
        SaidRow(said: content.said, palette: palette)
        if content.restartOffered && read.value?.running == true && model.canControl {
            CardBox(palette: palette) {
                Text(model.t("addons.restart"))
                    .foregroundStyle(palette.textPrimary)
                Presses(presses: [
                    Press(title: model.t("action.restart_now"), enabled: idle) {
                        asking = ContentConfirm(
                            title: strings.t("confirm.restart_title"),
                            body: strings.t("confirm.restart_body"),
                            confirm: strings.t("action.restart"),
                            danger: false
                        ) {
                            Task { await content.restart(strings, reload: { await content.loadAddons() }) }
                        }
                    },
                ], palette: palette)
            }
        }
        if let problem = read.problem {
            Hint(text: model.t("mobile.content.unknown"), palette: palette)
            ProblemCard(problem: problem, palette: palette) { await content.loadAddons() }
        }
        if let list = read.value {
            if let world = list.world {
                Hint(text: model.t("mobile.content.pack_world", ["world": world]), palette: palette)
            } else {
                Text(model.t("addons.no_world"))
                    .foregroundStyle(palette.tone(.warning))
            }
            if list.running && changes == .ready {
                Hint(text: model.t("addons.running"), palette: palette)
            }
            SectionTitle(text: strings.tn("addons.installed", count: list.addons.count), palette: palette)
            if list.addons.isEmpty {
                EmptyCard(title: model.t("addons.none"), hint: model.t("addons.none_hint"), palette: palette)
            }
            ForEach(list.addons) { addon in
                packCard(content, addon, canTurn: list.world != nil, changes, palette)
            }
            if changes == .ready {
                SectionTitle(text: model.t("addons.add_title"), palette: palette)
                CardBox(palette: palette) {
                    Text(model.t("addons.add_lead"))
                        .foregroundStyle(palette.textPrimary)
                    if content.busy == "upload" {
                        HStack(spacing: 8) {
                            ProgressView().controlSize(.small)
                            Hint(text: model.t("addons.installing"), palette: palette)
                        }
                    }
                    Presses(presses: [
                        Press(title: model.t("mobile.content.add_pack"), enabled: idle) { picking = .pack },
                    ], palette: palette)
                }
            }
        } else if read.problem == nil {
            ProgressView().frame(maxWidth: .infinity)
        }
    }

    private func packCard(_ content: ContentPages, _ addon: Addon, canTurn: Bool, _ changes: Changes, _ palette: Palette) -> some View {
        let strings = model.strings
        let idle = content.busy == nil
        let details = [
            model.t(Content.packKind(addon)),
            addon.version.isEmpty ? model.t("value.unknown") : addon.version,
            model.t(addon.enabled ? "addons.on" : "addons.off"),
        ]
        return CardBox(palette: palette) {
            Text(verbatim: addon.name.isEmpty ? addon.folder : addon.name)
                .font(.headline)
                .foregroundStyle(palette.textPrimary)
            Hint(text: details.joined(separator: " · "), palette: palette)
            if let description = addon.description, !description.isEmpty {
                Text(verbatim: String(description.prefix(200)))
                    .font(.footnote)
                    .foregroundStyle(palette.textPrimary)
            }
            if model.technical {
                Hint(text: "\(addon.uuid) · \(addon.folder)", palette: palette)
            }
            if changes == .ready {
                Presses(presses: [
                    Press(title: model.t(addon.enabled ? "addons.turn_off" : "addons.turn_on"), enabled: idle && canTurn) {
                        Task { await content.setAddon(addon, !addon.enabled, strings) }
                    },
                    Press(title: model.t("addons.remove"), danger: true, enabled: idle) {
                        asking = ContentConfirm(
                            title: strings.t("addons.remove_title", ["name": addon.name]),
                            body: strings.t("addons.remove_body"),
                            confirm: strings.t("addons.remove")
                        ) {
                            Task { await content.removeAddon(addon, strings) }
                        }
                    },
                ], palette: palette)
            }
        }
    }

    // MARK: - Files

    /// Copies the picked file into the app's own temporary folder (the
    /// picker's copy can only be read for a moment), then sends it; the copy
    /// is deleted once sent.
    private func picked(_ url: URL, _ what: Picking, _ kind: ContentKind) {
        let content = self.content
        let strings = model.strings
        let name = url.lastPathComponent
        let fits: Bool
        let expected: String
        switch what {
        case .jar:
            fits = Content.accepts(kind, name)
            expected = Content.JAR
        case .modpack:
            fits = Content.accepts(kind, name, modpack: true)
            expected = Content.MODPACK
        case .pack:
            fits = Content.accepts(.packs, name)
            expected = Content.PACK_FILES.joined(separator: ", ")
        }
        guard fits else {
            content.said = Said(text: strings.t("mobile.content.wrong_file", ["kind": expected]), good: false)
            return
        }
        Task {
            let file: PickedFile
            do {
                file = try await Task.detached { try PickedCopy.make(url) }.value
            } catch {
                content.said = Said(text: strings.t("mobile.error.failed", ["reason": error.localizedDescription]), good: false)
                return
            }
            switch what {
            case .jar: await content.uploadMod(file, strings)
            case .modpack: await content.inspectModpack(file, strings)
            case .pack: await content.uploadAddon(file, strings)
            }
        }
    }

    // MARK: - Sheets

    @ViewBuilder
    private func sheetBody(_ content: ContentPages, _ sheet: ContentSheet) -> some View {
        switch sheet {
        case .updateAll:
            UpdateAllSheet(content: content)
        case .project:
            InstallSheet(content: content)
        case .missing:
            MissingSheet(content: content)
        case .modpack:
            ModpackSheet(content: content)
        }
    }
}

/// The picked file's own copy in the app's temporary folder.
enum PickedCopy {
    static func make(_ url: URL) throws -> PickedFile {
        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("picked-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let copy = folder.appendingPathComponent(url.lastPathComponent)
        try FileManager.default.copyItem(at: url, to: copy)
        return PickedFile(name: url.lastPathComponent, url: copy)
    }
}

/// A Modrinth picture from the phone's cache, or a plain square while there is none.
private struct ModIcon: View {
    let icons: IconCache
    let url: String?
    let palette: Palette

    @State private var image: UIImage?

    var body: some View {
        Group {
            if let image = image {
                Image(uiImage: image).resizable().scaledToFill()
            } else {
                palette.sunken
            }
        }
        .frame(width: 40, height: 40)
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .accessibilityHidden(true)
        .task(id: url) {
            image = nil
            if let data = await icons.load(url) {
                image = UIImage(data: data)
            }
        }
    }
}

// MARK: - Questions

/// A read the sheet waits on: Loading, or the problem in the agent's words.
private struct SheetLoading<T>: View {
    let read: PageRead<T>

    @Environment(AppModel.self) private var model

    var body: some View {
        if let problem = read.problem {
            Text(problem.message(model.strings)).foregroundStyle(.red)
        } else if read.value == nil {
            HStack(spacing: 8) {
                ProgressView()
                Text(model.t("mobile.common.loading"))
            }
        }
    }
}

/// The kept copies of one mod, each with Roll back (which asks first).
private struct VersionsSheet: View {
    let content: ContentPages
    let ask: VersionsAsk
    let palette: Palette

    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var using: ModVersion?

    private func details(_ version: ModVersion, _ strings: Strings) -> String {
        let parts: [String?] = [
            Display.dateTime(strings, version.createdAt),
            version.isCurrent ? model.t("mods.current") : nil,
            version.exists ? nil : model.t("mods.file_missing"),
        ]
        return parts.compactMap { $0 }.joined(separator: " · ")
    }

    var body: some View {
        let strings = model.strings
        let canChange = Content.changes(canManage: model.can(Permissions.MODS_MANAGE), serverState: content.serverState) == .ready
        let read = content.versions?.versions ?? ask.versions
        NavigationStack {
            List {
                SheetLoading(read: read)
                if let list = read.value?.versions {
                    if list.isEmpty {
                        Text(model.t("mods.no_versions"))
                    }
                    ForEach(list) { version in
                        VStack(alignment: .leading, spacing: 4) {
                            Text(verbatim: version.version ?? version.filename)
                            Text(verbatim: details(version, strings))
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                            if canChange && Content.canRollBack(version) {
                                Button(model.t("mods.rollback")) { using = version }
                                    .buttonStyle(.borderless)
                            }
                        }
                        .frame(minHeight: 44, alignment: .leading)
                    }
                }
            }
            .navigationTitle(strings.t("mods.versions_title", ["name": ask.mod.name]))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(model.t("mobile.common.cancel")) { dismiss() }
                }
            }
            .alert(
                strings.t("mods.rollback_title", ["version": using.map { $0.version ?? $0.filename } ?? ""]),
                isPresented: Binding(get: { using != nil }, set: { if !$0 { using = nil } }),
                presenting: using,
                actions: { version in
                    Button(model.t("mods.rollback")) {
                        Task { await content.rollBack(ask.mod, version, strings) }
                    }
                    Button(model.t("mobile.common.cancel"), role: .cancel) {}
                },
                message: { _ in Text(model.t("mods.rollback_body")) }
            )
        }
    }
}

/// The ticked list, old version to new, then one Update all.
private struct UpdateAllSheet: View {
    @Bindable var content: ContentPages

    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        let strings = model.strings
        let read = content.plan ?? PageRead(loading: true)
        let plan = read.value
        let count = content.ticked.count
        let blocked = plan.flatMap { UpdateAll.blocked(strings, $0) }
        List {
            if plan == nil {
                if read.problem == nil {
                    HStack(spacing: 8) {
                        ProgressView()
                        Text(model.t("mobile.content.checking"))
                    }
                } else {
                    SheetLoading(read: read)
                }
            }
            if let plan = plan {
                Section {
                    Text(model.t(plan.updates.isEmpty ? "mobile.content.update_all_none" : "mobile.content.update_all_lead"))
                    if let blocked = blocked {
                        Text(verbatim: blocked).foregroundStyle(.orange)
                    }
                }
                Section {
                    ForEach(plan.updates) { row in
                        Toggle(isOn: Binding(
                            get: { content.ticked.contains(row.filename) },
                            set: { on in
                                if on { content.ticked.insert(row.filename) } else { content.ticked.remove(row.filename) }
                            }
                        )) {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(verbatim: row.name.isEmpty ? row.filename : row.name)
                                Text(verbatim: Content.change(strings, row.installedVersion, row.latestVersion))
                                    .font(.footnote)
                                    .foregroundStyle(.secondary)
                                if !row.enabled {
                                    Text(model.t("mobile.content.update_all_off"))
                                        .font(.footnote)
                                        .foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                }
                if !plan.unchecked.isEmpty {
                    Section {
                        ForEach(Array(plan.unchecked.enumerated()), id: \.offset) { _, u in
                            Text(model.t("mobile.content.update_all_unchecked", ["name": u.name, "reason": u.reason]))
                                .font(.footnote)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
            }
        }
        .navigationTitle(model.t("mobile.content.update_all"))
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button(model.t("mobile.common.cancel")) { dismiss() }
            }
            if let plan = plan, !plan.updates.isEmpty {
                ToolbarItem(placement: .confirmationAction) {
                    Button(strings.tn("mobile.content.update_all_go", count: count)) {
                        Task { await content.updateAll(strings) }
                    }
                    .disabled(count == 0 || blocked != nil)
                }
            }
        }
    }
}

/// What installing a Modrinth project would add, with its dependencies.
private struct InstallSheet: View {
    let content: ContentPages

    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var web: WebLink?
    @State private var withDependencies = true

    var body: some View {
        let strings = model.strings
        let read = content.project ?? PageRead(loading: true)
        let project = read.value
        let version = project.flatMap { Install.latest($0) }
        List {
            SheetLoading(read: read)
            if let project = project {
                if let version = version {
                    Section {
                        ForEach(Install.facts(strings, project, version), id: \.self) { fact in
                            Text(verbatim: fact)
                        }
                        Text(model.t("mods.install_checked"))
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                    let required = Install.required(version)
                    if !required.isEmpty {
                        Toggle(strings.tn("mods.install_deps", count: required.count), isOn: $withDependencies)
                    }
                } else {
                    Text(model.t("mods.no_build"))
                }
                if let page = Install.page(project.project.page) {
                    Button(model.t("mobile.content.open_page")) { web = WebLink(url: page) }
                }
            }
        }
        .sheet(item: $web) { page in
            SafariView(url: page.url).ignoresSafeArea()
        }
        .navigationTitle(model.t("mods.install_title"))
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button(model.t("mobile.common.cancel")) { dismiss() }
            }
            if version != nil {
                ToolbarItem(placement: .confirmationAction) {
                    Button(model.t("mods.install_confirm")) {
                        let deps = withDependencies
                        Task { await content.install(withDependencies: deps, strings) }
                    }
                }
            }
        }
    }
}

/// What "Install the missing ones" would download, and what it can't.
private struct MissingSheet: View {
    let content: ContentPages

    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var web: WebLink?

    private func line(_ item: PlannedDependency, _ strings: Strings) -> String {
        let parts: [String?] = [item.title ?? item.modId, item.versionNumber, item.size.map { Display.bytes(strings, $0) }]
        return parts.compactMap { $0 }.joined(separator: " · ")
    }

    var body: some View {
        let strings = model.strings
        let read = content.missingPlan ?? PageRead(loading: true)
        let plan = read.value
        List {
            SheetLoading(read: read)
            if let plan = plan {
                if !plan.items.isEmpty {
                    Section(strings.tn("mobile.content.missing_plan", count: plan.items.count)) {
                        ForEach(Array(plan.items.enumerated()), id: \.offset) { _, item in
                            Text(verbatim: line(item, strings))
                        }
                    }
                }
                ForEach(Array(plan.unresolvable.enumerated()), id: \.offset) { _, item in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(model.t("mobile.content.cant_install", ["name": item.name ?? item.modId, "reason": item.reason]))
                            .foregroundStyle(.orange)
                        if let page = Install.page(item.page) {
                            Button(model.t("mobile.content.get_it")) { web = WebLink(url: page) }
                            .buttonStyle(.borderless)
                        }
                    }
                }
            }
        }
        .sheet(item: $web) { page in
            SafariView(url: page.url).ignoresSafeArea()
        }
        .navigationTitle(model.t("mobile.content.install_missing"))
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button(model.t("mobile.common.cancel")) { dismiss() }
            }
            if let plan = plan, !plan.items.isEmpty {
                ToolbarItem(placement: .confirmationAction) {
                    Button(model.t("mods.install_confirm")) {
                        Task { await content.installMissing(strings) }
                    }
                }
            }
        }
    }
}

/// What importing a modpack here would do, then Import.
private struct ModpackSheet: View {
    let content: ContentPages

    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        let strings = model.strings
        let unknown = strings.t("value.unknown")
        if let inspected = content.modpack {
            let pack = inspected.pack
            let loader = [pack.typeName, pack.loaderVersion].compactMap { $0 }.joined(separator: " ")
            List {
                Section {
                    Text(verbatim: model.t("pack.minecraft") + ": " + (pack.minecraftVersion ?? unknown))
                    Text(verbatim: model.t("pack.loader") + ": " + (loader.isEmpty ? unknown : loader))
                    Text(verbatim: model.t("pack.files") + ": " + model.t("pack.files_value", [
                        "count": pack.downloadCount, "size": Display.bytes(strings, pack.downloadBytes),
                    ]))
                    if inspected.versionChange {
                        Text(model.t("pack.version_change", ["type": pack.typeName ?? unknown, "version": pack.minecraftVersion ?? unknown]))
                            .foregroundStyle(.orange)
                    }
                }
                if !pack.problems.isEmpty {
                    Section(model.t("pack.cant_import")) {
                        ForEach(pack.problems, id: \.self) { problem in
                            Text(verbatim: problem).foregroundStyle(.red)
                        }
                    }
                }
                if !pack.clientOnly.isEmpty {
                    Text(model.t("pack.client_only", ["names": pack.clientOnly.joined(separator: ", ")]))
                }
                if !pack.skippedOverrides.isEmpty {
                    Text(model.t("pack.skipped_extras", ["names": pack.skippedOverrides.joined(separator: ", ")]))
                }
                if pack.canImport {
                    Section(model.t("mobile.content.modpack_failed_note")) {
                        ForEach(Modpacks.steps(strings, inspected), id: \.self) { step in
                            Text(verbatim: step)
                        }
                    }
                }
                Section(model.t("pack.all_files", ["count": pack.files.count])) {
                    ForEach(Array(pack.files.prefix(200).enumerated()), id: \.offset) { _, file in
                        let status = Modpacks.fileStatus(file)
                        Text(verbatim: "\(file.name) · \(model.t(status.key))" + (file.reason.map { " (\($0))" } ?? ""))
                            .font(.footnote)
                            .foregroundStyle(status.tone == .danger ? Color.red : Color.secondary)
                    }
                }
            }
            .navigationTitle(strings.t("pack.import_title", ["name": pack.name.isEmpty ? unknown : pack.name]))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(model.t("mobile.common.cancel")) { dismiss() }
                }
                if pack.canImport {
                    ToolbarItem(placement: .confirmationAction) {
                        Button(model.t("pack.import")) {
                            Task { await content.importModpack(strings) }
                        }
                    }
                }
            }
        }
    }
}
