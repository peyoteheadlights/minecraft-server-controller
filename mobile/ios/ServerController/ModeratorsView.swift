import Core
import SwiftUI

/// The owner's moderators (mirrors ModeratorPages in Moderators.kt): the
/// list, adding one, their permissions and invites.
@MainActor
@Observable
final class ModeratorPages {
    @ObservationIgnored private let client: () -> AgentClient?
    @ObservationIgnored private let noted: (AgentError) -> Void
    @ObservationIgnored private let strings: Strings

    init(client: @escaping () -> AgentClient?, noted: @escaping (AgentError) -> Void, strings: Strings) {
        self.client = client
        self.noted = noted
        self.strings = strings
    }

    private(set) var list = PageRead<ModeratorList>()
    private(set) var busy: String?
    var said: Said?
    /// The invite just made, shown once: the agent keeps only its hash.
    var invite: InviteCode?

    func moderator(_ name: String) -> Moderator? {
        list.value?.helpers.first { $0.username == name }
    }

    func load() async {
        guard let client = client() else { return }
        list.loading = true
        do {
            list = PageRead(value: try await client.moderators())
        } catch {
            let problem = client.translateFailure(error)
            noted(problem)
            list = PageRead(value: list.value, problem: problem)
        }
    }

    /// Runs one change, says what went wrong in the agent's words, and reads the list again.
    private func run(_ what: String, _ work: (AgentClient) async throws -> Void) async -> Bool {
        guard let client = client() else { return false }
        busy = what
        said = nil
        var done = false
        do {
            try await work(client)
            done = true
        } catch {
            let problem = client.translateFailure(error)
            noted(problem)
            said = Said(text: problem.message(strings), good: false)
        }
        busy = nil
        await load()
        return done
    }

    func add(name: String, servers: [String]?, permissions: Set<String>) async -> Bool {
        await run("add") { client in
            let added = try await client.addModerator(
                username: name.trimmingCharacters(in: .whitespaces), servers: servers, permissions: permissions
            )
            invite = added.invite
        }
    }

    func save(_ name: String, _ body: [String: JSONValue]) async {
        let saved = await run("save") { client in
            _ = try await client.saveModerator(username: name, body: body)
        }
        if saved { said = Said(text: strings.t("mobile.mod.saved"), good: true) }
    }

    /// A new invite; with `forgetPassword` the owner's Reset password.
    func newInvite(_ name: String, forgetPassword: Bool) async -> Bool {
        await run(forgetPassword ? "reset" : "invite") { client in
            invite = try await client.inviteModerator(username: name, forgetPassword: forgetPassword)
        }
    }

    func cancelInvite(_ name: String) async {
        if await run("cancel", { client in try await client.cancelInvite(username: name) }) {
            invite = nil
            said = Said(text: strings.t("mobile.mod.invite_cancelled"), good: true)
        }
    }

    func remove(_ name: String) async -> Bool {
        let removed = await run("remove") { client in
            _ = try await client.removeModerator(username: name)
        }
        if removed { said = Said(text: strings.t("mobile.mod.removed", ["name": name]), good: true) }
        return removed
    }
}

/// "Your account": a moderator's password and their own signed-in devices.
@MainActor
@Observable
final class AccountPages {
    @ObservationIgnored private let client: () -> AgentClient?
    @ObservationIgnored private let noted: (AgentError) -> Void
    @ObservationIgnored private let strings: Strings

    init(client: @escaping () -> AgentClient?, noted: @escaping (AgentError) -> Void, strings: Strings) {
        self.client = client
        self.noted = noted
        self.strings = strings
    }

    private(set) var devices = PageRead<[Device]>()
    private(set) var busy: String?
    var said: Said?

    /// Only this account's devices: the owner's list (ticket 08) has everyone's.
    func load(_ user: String?) async {
        guard let client = client() else { return }
        devices.loading = true
        do {
            devices = PageRead(value: try await client.devices().sessions.filter { user == nil || $0.user == user })
        } catch {
            let problem = client.translateFailure(error)
            noted(problem)
            devices = PageRead(value: devices.value, problem: problem)
        }
    }

    func changePassword(current: String, new: String) async -> Bool {
        guard let client = client() else { return false }
        busy = "password"
        said = nil
        defer { busy = nil }
        do {
            try await client.changePassword(current: current, new: new)
            said = Said(text: strings.t("account.changed"), good: true)
            return true
        } catch {
            let problem = client.translateFailure(error)
            noted(problem)
            said = Said(text: problem.message(strings), good: false)
            return false
        }
    }

    func signOut(_ device: Device, user: String?) async {
        guard let client = client() else { return }
        busy = device.id
        said = nil
        do {
            try await client.signOutDevice(id: device.id)
            said = Said(text: strings.t("mobile.account.signed_out_device", ["device": device.label ?? device.id]), good: true)
        } catch {
            let problem = client.translateFailure(error)
            noted(problem)
            said = Said(text: problem.message(strings), good: false)
        }
        busy = nil
        await load(user)
    }
}

// MARK: - Screens

/// Settings > Moderators (owner only).
struct ModeratorsView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.colorScheme) private var colorScheme
    @State private var adding = false

    var body: some View {
        let pages = model.moderators
        List {
            Section {
                Text(model.t("mobile.mod.lead")).foregroundStyle(.secondary)
            }
            if let problem = pages.list.problem {
                Section { Text(problem.message(model.strings)).foregroundStyle(.red) }
            }
            if let list = pages.list.value {
                Section {
                    if list.helpers.isEmpty {
                        Text(model.t("mobile.mod.none"))
                    }
                    ForEach(list.helpers) { mod in
                        NavigationLink {
                            ModeratorView(name: mod.username)
                        } label: {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(mod.username)
                                Text(subtitle(mod)).font(.footnote).foregroundStyle(.secondary)
                            }
                        }
                        .frame(minHeight: 44)
                    }
                }
            } else if pages.list.problem == nil {
                ProgressView()
            }
            Section {
                Button(model.t("mobile.mod.add")) { adding = true }
                    .frame(minHeight: 44)
            }
        }
        .navigationTitle(model.t("mobile.mod.title"))
        .task { await pages.load() }
        .refreshable { await pages.load() }
        .sheet(isPresented: $adding) {
            AddModeratorSheet()
        }
    }

    private func subtitle(_ mod: Moderator) -> String {
        if mod.inviteWaiting { return model.t("mobile.mod.invite_waiting") }
        guard let used = mod.lastUsed else { return model.t("mobile.mod.never_used") }
        return model.t("mobile.mod.last_used", ["time": Display.ago(model.strings, used, now: Date().timeIntervalSince1970)])
    }
}

/// Add moderator: the name, the servers and the level, then the invite in the same sheet.
struct AddModeratorSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var all = false
    @State private var picked: Set<String> = []
    @State private var level = Levels.LOOK_AFTER_IT
    @State private var added: String?

    var body: some View {
        let pages = model.moderators
        NavigationStack {
            if let added {
                InviteView(name: added)
                    .toolbar {
                        ToolbarItem(placement: .confirmationAction) {
                            Button(model.t("mobile.common.close")) { dismiss() }
                        }
                    }
            } else {
                form(pages)
                    .navigationTitle(model.t("mobile.mod.add"))
                    .navigationBarTitleDisplayMode(.inline)
                    .toolbar {
                        ToolbarItem(placement: .cancellationAction) {
                            Button(model.t("mobile.common.cancel")) { dismiss() }
                        }
                    }
            }
        }
        .task {
            pages.said = nil
            if pages.list.value == nil { await pages.load() }
            if let wanted = pages.list.value?.permissions.defaultLevel { level = wanted }
        }
    }

    private func form(_ pages: ModeratorPages) -> some View {
        let nameOk = Moderators.nameOk(name)
        return Form {
            Section {
                TextField(model.t("mobile.mod.name"), text: $name)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled(true)
                    .frame(minHeight: 44)
            } footer: {
                Text(model.t(!name.isEmpty && !nameOk ? "mobile.mod.name_bad" : "mobile.mod.name_hint"))
                    .foregroundStyle(!name.isEmpty && !nameOk ? .red : .secondary)
            }
            if let list = pages.list.value {
                Section {
                    Toggle(isOn: $all) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(model.t("mobile.mod.all_servers"))
                            Text(model.t("mobile.mod.all_servers_hint")).font(.footnote).foregroundStyle(.secondary)
                        }
                    }
                    if !all {
                        ForEach(list.servers) { server in
                            Toggle(server.name, isOn: Binding(
                                get: { picked.contains(server.id) },
                                set: { on in if on { picked.insert(server.id) } else { picked.remove(server.id) } }
                            ))
                            .frame(minHeight: 44)
                        }
                    }
                } header: {
                    Text(model.t("mobile.mod.servers"))
                } footer: {
                    if !all && picked.isEmpty { Text(model.t("mobile.mod.pick_a_server")) }
                }
                LevelPicker(catalogue: list.permissions, selected: level) { level = $0 }
            } else if let problem = pages.list.problem {
                Section { Text(problem.message(model.strings)).foregroundStyle(.red) }
            }
            Section {
                SaidRow(said: pages.said, palette: model.basePalette(colorScheme))
                Button {
                    guard let list = pages.list.value else { return }
                    let servers = all ? nil : list.servers.map(\.id).filter { picked.contains($0) }
                    let permissions = Moderators.level(level, list.permissions)
                    let chosen = name
                    Task {
                        if await pages.add(name: chosen, servers: servers, permissions: permissions) {
                            added = chosen.trimmingCharacters(in: .whitespaces)
                        }
                    }
                } label: {
                    Text(model.t(pages.busy == "add" ? "helpers.adding" : "mobile.mod.add"))
                        .fontWeight(.semibold)
                        .frame(maxWidth: .infinity, minHeight: 44)
                }
                .disabled(pages.list.value == nil || !nameOk || (!all && picked.isEmpty) || pages.busy != nil)
            }
        }
    }
}

/// The three levels, and "Custom" when the set is none of them (shown, never picked).
struct LevelPicker: View {
    @Environment(AppModel.self) private var model
    let catalogue: PermissionCatalogue
    let selected: String
    let pick: (String) -> Void

    var body: some View {
        Section(model.t("mobile.mod.level")) {
            ForEach(catalogue.levels, id: \.id) { level in
                Button {
                    pick(level.id)
                } label: {
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(model.t("mobile.mod.level_\(level.id)")).foregroundStyle(.primary)
                            Text(model.t("mobile.mod.level_\(level.id)_hint")).font(.footnote).foregroundStyle(.secondary)
                        }
                        Spacer()
                        if selected == level.id {
                            Image(systemName: "checkmark").foregroundStyle(.tint)
                        }
                    }
                    .frame(minHeight: 44)
                }
                .accessibilityAddTraits(selected == level.id ? .isSelected : [])
            }
            if selected == Levels.CUSTOM {
                HStack {
                    Text(model.t("mobile.mod.level_custom"))
                    Spacer()
                    Image(systemName: "checkmark").foregroundStyle(.tint)
                }
                .accessibilityAddTraits(.isSelected)
            }
            if selected == Levels.NONE {
                Text(model.t("mobile.mod.level_none")).foregroundStyle(.secondary)
            }
        }
    }
}

/// The invite sheet's own wrapper for Reset password and Make a new invite.
private struct InviteSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let name: String

    var body: some View {
        NavigationStack {
            InviteView(name: name)
                .toolbar {
                    ToolbarItem(placement: .confirmationAction) {
                        Button(model.t("mobile.common.close")) { dismiss() }
                    }
                }
        }
    }
}

/// One moderator: their servers with a summary each, their invite, Reset password and Remove.
struct ModeratorView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.dismiss) private var dismiss
    let name: String
    @State private var asking: String?
    @State private var showingInvite = false

    var body: some View {
        let pages = model.moderators
        Form {
            if let problem = pages.list.problem {
                Section { Text(problem.message(model.strings)).foregroundStyle(.red) }
            }
            if pages.said != nil {
                Section { SaidRow(said: pages.said, palette: model.basePalette(colorScheme)) }
            }
            if let list = pages.list.value, let mod = pages.moderator(name) {
                if mod.inviteWaiting {
                    Section(model.t("mobile.mod.invite_waiting")) {
                        if let invite = mod.invite {
                            Text(model.t("mobile.mod.invite_expires", ["time": Display.dateTime(invite.expiresAt)]))
                        }
                        Button {
                            Task { if await pages.newInvite(name, forgetPassword: false) { showingInvite = true } }
                        } label: {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(model.t("mobile.mod.invite_new"))
                                Text(model.t("mobile.mod.invite_new_hint")).font(.footnote).foregroundStyle(.secondary)
                            }
                        }
                        .frame(minHeight: 44)
                        Button(model.t("mobile.mod.invite_cancel"), role: .destructive) {
                            Task { await pages.cancelInvite(name) }
                        }
                        .frame(minHeight: 44)
                    }
                } else {
                    Section {
                        Text(mod.lastUsed.map { model.t("mobile.mod.last_used", ["time": Display.ago(model.strings, $0, now: Date().timeIntervalSince1970)]) }
                            ?? model.t("mobile.mod.never_used"))
                            .foregroundStyle(.secondary)
                    }
                }
                Section(model.t("mobile.mod.servers")) {
                    Toggle(isOn: Binding(
                        get: { mod.allServers },
                        set: { on in Task { await pages.save(name, Moderators.allServers(on, mod, list.permissions)) } }
                    )) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(model.t("mobile.mod.all_servers"))
                            Text(model.t("mobile.mod.all_servers_hint")).font(.footnote).foregroundStyle(.secondary)
                        }
                    }
                    .disabled(pages.busy != nil)
                    ForEach(mod.access) { access in
                        NavigationLink {
                            ModeratorServerView(name: name, serverId: access.id)
                        } label: {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(access.name)
                                Text(Moderators.summary(Set(access.permissions), list.permissions, model.strings))
                                    .font(.footnote).foregroundStyle(.secondary)
                            }
                        }
                        .frame(minHeight: 44)
                    }
                    if mod.allServers {
                        NavigationLink {
                            ModeratorServerView(name: name, serverId: nil)
                        } label: {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(model.t("mobile.mod.new_servers"))
                                Text(Moderators.summary(Set(mod.newServer.permissions), list.permissions, model.strings))
                                    .font(.footnote).foregroundStyle(.secondary)
                            }
                        }
                        .frame(minHeight: 44)
                    }
                }
                Section(model.t("account.title")) {
                    Button(model.t("mobile.mod.reset")) { asking = "reset" }
                        .frame(minHeight: 44)
                    Button(model.t("mobile.mod.remove"), role: .destructive) { asking = "remove" }
                        .frame(minHeight: 44)
                }
            } else if pages.list.value == nil {
                ProgressView()
            }
        }
        .navigationTitle(name)
        .task {
            pages.said = nil
            if pages.list.value == nil { await pages.load() }
        }
        .sheet(isPresented: $showingInvite) {
            InviteSheet(name: name)
        }
        .alert(model.t("mobile.mod.reset_title", ["name": name]), isPresented: Binding(get: { asking == "reset" }, set: { if !$0 { asking = nil } })) {
            Button(model.t("mobile.mod.reset"), role: .destructive) {
                Task { if await pages.newInvite(name, forgetPassword: true) { showingInvite = true } }
            }
            Button(model.t("mobile.common.cancel"), role: .cancel) {}
        } message: {
            Text(model.t("mobile.mod.reset_body"))
        }
        .alert(model.t("helpers.remove_title", ["name": name]), isPresented: Binding(get: { asking == "remove" }, set: { if !$0 { asking = nil } })) {
            Button(model.t("mobile.mod.remove"), role: .destructive) {
                Task { if await pages.remove(name) { dismiss() } }
            }
            Button(model.t("mobile.common.cancel"), role: .cancel) {}
        } message: {
            Text(model.t("mobile.mod.remove_body"))
        }
    }
}

/// One server of one moderator (or, with no server, their "New servers" set):
/// the level, the switches and where to save.
struct ModeratorServerView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.colorScheme) private var colorScheme
    let name: String
    let serverId: String?
    @State private var perms: Set<String>? = nil
    @State private var editing = false
    @State private var picking = false

    var body: some View {
        let pages = model.moderators
        Group {
            if let list = pages.list.value, let mod = pages.moderator(name) {
                content(pages, list, mod)
            } else if let problem = pages.list.problem {
                Text(problem.message(model.strings)).foregroundStyle(.red)
            } else {
                ProgressView()
            }
        }
        .task {
            pages.said = nil
            if pages.list.value == nil { await pages.load() }
        }
    }

    private func saved(_ mod: Moderator) -> Set<String> {
        guard let serverId else { return Set(mod.newServer.permissions) }
        return Set(mod.access.first { $0.id == serverId }?.permissions ?? [])
    }

    private func content(_ pages: ModeratorPages, _ list: ModeratorList, _ mod: Moderator) -> some View {
        let catalogue = list.permissions
        let before = saved(mod)
        let current = perms ?? before
        let level = Moderators.levelOf(current, catalogue)
        let title = serverId.map { id in mod.access.first { $0.id == id }?.name ?? id } ?? model.t("mobile.mod.new_servers")
        let busy = pages.busy != nil
        return Form {
            if serverId == nil {
                Section { Text(model.t("mobile.mod.new_servers_hint")).foregroundStyle(.secondary) }
            }
            LevelPicker(catalogue: catalogue, selected: level) { perms = Moderators.level($0, catalogue) }
            if !editing && level != Levels.CUSTOM {
                Section {
                    Button(model.t("mobile.mod.change")) { editing = true }
                        .frame(minHeight: 44)
                }
            } else {
                ForEach(catalogue.groups, id: \.id) { group in
                    let shown = Moderators.shown(group, technical: model.technical, catalogue)
                    if !shown.isEmpty {
                        Section(model.t("mobile.mod.group_\(group.id)")) {
                            ForEach(shown, id: \.self) { permission in
                                Toggle(model.t(Moderators.switchKey(permission)), isOn: Binding(
                                    get: { current.contains(permission) },
                                    set: { on in perms = Moderators.toggle(current, permission, on: on, catalogue) }
                                ))
                                .frame(minHeight: 44)
                            }
                        }
                    }
                }
                let hidden = Moderators.hiddenTicked(current, technical: model.technical, catalogue)
                if hidden > 0 {
                    Section { Text(model.t("mobile.mod.more_technical", ["count": hidden])).foregroundStyle(.secondary) }
                }
            }
            if Moderators.warns(current, catalogue) {
                Section {
                    Label(model.t("mobile.mod.warn"), systemImage: "exclamationmark.triangle")
                        .foregroundStyle(model.basePalette(colorScheme).tone(.warning))
                }
            }
            Section {
                SaidRow(said: pages.said, palette: model.basePalette(colorScheme))
                if let serverId {
                    Button(model.t("mobile.mod.save_here")) {
                        Task { await save(pages, Moderators.saveFor([serverId], current)) }
                    }
                    .frame(minHeight: 44)
                    .disabled(busy || current == before)
                    Button(model.t("mobile.mod.save_for")) { picking = true }
                        .frame(minHeight: 44)
                        .disabled(busy)
                    Button(model.t("mobile.mod.apply_all")) {
                        Task { await save(pages, Moderators.applyToAll(list.servers.map(\.id), current, allServers: mod.allServers)) }
                    }
                    .frame(minHeight: 44)
                    .disabled(busy)
                } else {
                    Button(model.t("mobile.mod.save")) {
                        Task { await save(pages, Moderators.newServers(current)) }
                    }
                    .frame(minHeight: 44)
                    .disabled(busy || current == before)
                }
            }
        }
        .navigationTitle("\(name) · \(title)")
        .navigationBarTitleDisplayMode(.inline)
        .sheet(isPresented: $picking) {
            SaveForSheet(servers: list.servers, start: Set(serverId.map { [$0] } ?? [])) { chosen in
                picking = false
                Task { await save(pages, Moderators.saveFor(list.servers.map(\.id).filter { chosen.contains($0) }, current)) }
            }
        }
    }

    /// Saved: the screen shows what the agent now has.
    private func save(_ pages: ModeratorPages, _ body: [String: JSONValue]) async {
        await pages.save(name, body)
        perms = nil
    }
}

/// "Save for…": pick the servers that get this set.
private struct SaveForSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    let servers: [ServerName]
    let start: Set<String>
    let done: (Set<String>) -> Void
    @State private var chosen: Set<String>

    init(servers: [ServerName], start: Set<String>, done: @escaping (Set<String>) -> Void) {
        self.servers = servers
        self.start = start
        self.done = done
        _chosen = State(initialValue: start)
    }

    var body: some View {
        NavigationStack {
            List(servers) { server in
                Toggle(server.name, isOn: Binding(
                    get: { chosen.contains(server.id) },
                    set: { on in if on { chosen.insert(server.id) } else { chosen.remove(server.id) } }
                ))
                .frame(minHeight: 44)
            }
            .navigationTitle(model.t("mobile.mod.pick_servers"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(model.t("mobile.common.cancel")) { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(model.t("mobile.mod.save")) { done(chosen) }
                        .disabled(chosen.isEmpty)
                }
            }
        }
    }
}

/// The invite just made: its QR code, Share, and the Tailscale reminder.
struct InviteView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openURL) private var openURL
    let name: String

    var body: some View {
        let invite = model.moderators.invite.flatMap { $0.username == name ? $0 : nil }
        Form {
            if let invite, invite.ok, let url = invite.url, let qr = invite.qr {
                Section {
                    Text(model.t("mobile.mod.invite_lead", ["name": name]))
                    QRCodeView(rows: qr)
                        .frame(maxWidth: 320)
                        .frame(maxWidth: .infinity)
                        .accessibilityLabel(model.t("mobile.mod.invite_title", ["name": name]))
                    Text(model.t("mobile.mod.invite_expires", ["time": Display.dateTime(invite.expiresAt)]))
                        .foregroundStyle(.secondary)
                    ShareLink(item: model.t("mobile.mod.invite_message", ["name": name, "app": Links.appDownload, "link": url])) {
                        Label(model.t("mobile.mod.invite_share"), systemImage: "square.and.arrow.up")
                            .frame(maxWidth: .infinity, minHeight: 44)
                    }
                }
                Section {
                    Text(model.t("mobile.mod.invite_tailscale", ["name": name]))
                    Button {
                        if let link = URL(string: Links.tailscaleSharing) { openURL(link) }
                    } label: {
                        Label(model.t("mobile.mod.invite_tailscale_how"), systemImage: "arrow.up.right.square")
                    }
                    .frame(minHeight: 44)
                }
            } else if let invite {
                Text(model.t("mobile.mod.no_code", ["reason": invite.reason ?? model.t("value.unknown")]))
                    .foregroundStyle(.red)
            } else {
                Text(model.t("mobile.mod.invite_gone"))
            }
        }
        .navigationTitle(model.t("mobile.mod.invite_title", ["name": name]))
        .navigationBarTitleDisplayMode(.inline)
    }
}

/// A QR code from the agent's rows of 0 and 1, black on white with its
/// quiet border, so it scans in dark mode too.
struct QRCodeView: View {
    let rows: [String]

    var body: some View {
        Canvas { context, size in
            let cells = CGFloat(rows.count + 8)
            let cell = size.width / cells
            context.fill(Path(CGRect(origin: .zero, size: size)), with: .color(.white))
            for (y, row) in rows.enumerated() {
                for (x, c) in row.enumerated() where c == "1" {
                    let rect = CGRect(x: (CGFloat(x) + 4) * cell, y: (CGFloat(y) + 4) * cell, width: cell + 0.5, height: cell + 0.5)
                    context.fill(Path(rect), with: .color(.black))
                }
            }
        }
        .aspectRatio(1, contentMode: .fit)
    }
}

/// Settings > Your account: the name, the password and this account's own devices.
struct AccountView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.colorScheme) private var colorScheme
    @State private var current = ""
    @State private var new = ""
    @State private var repeated = ""

    var body: some View {
        let pages = model.yourAccount
        let user = model.me?.user
        let owner = model.me?.isOwner == true
        Form {
            Section {
                Text(model.t(owner ? "account.owner" : "account.helper", ["name": user ?? model.t("value.unknown")]))
            }
            Section(model.t("account.change")) {
                if owner {
                    Text(model.t("mobile.account.owner_forgot")).foregroundStyle(.secondary)
                } else {
                    SecureField(model.t("account.current"), text: $current)
                        .textContentType(.password)
                        .frame(minHeight: 44)
                    SecureField(model.t("account.new"), text: $new)
                        .textContentType(.newPassword)
                        .frame(minHeight: 44)
                    if !new.isEmpty && new.count < 10 {
                        Text(model.t("mobile.invite.too_short")).foregroundStyle(.red)
                    }
                    SecureField(model.t("mobile.invite.repeat"), text: $repeated)
                        .textContentType(.newPassword)
                        .frame(minHeight: 44)
                    if !repeated.isEmpty && repeated != new {
                        Text(model.t("mobile.invite.mismatch")).foregroundStyle(.red)
                    }
                    Button {
                        let (was, next) = (current, new)
                        Task {
                            if await pages.changePassword(current: was, new: next) {
                                current = ""
                                new = ""
                                repeated = ""
                                await pages.load(user)
                            }
                        }
                    } label: {
                        Text(model.t(pages.busy == "password" ? "mobile.account.saving" : "account.change"))
                            .frame(maxWidth: .infinity, minHeight: 44)
                    }
                    .disabled(pages.busy != nil || current.isEmpty || new.count < 10 || new != repeated)
                    Text(model.t("mobile.account.forgot")).font(.footnote).foregroundStyle(.secondary)
                }
            }
            if pages.said != nil {
                Section { SaidRow(said: pages.said, palette: model.basePalette(colorScheme)) }
            }
            Section(model.t("mobile.account.devices")) {
                if let problem = pages.devices.problem {
                    Text(problem.message(model.strings)).foregroundStyle(.red)
                }
                if let devices = pages.devices.value {
                    if !devices.contains(where: { !$0.current }) {
                        Text(model.t("mobile.account.no_devices")).foregroundStyle(.secondary)
                    }
                    ForEach(devices.sorted { $0.current && !$1.current }) { device in
                        HStack {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(device.current ? model.t("mobile.account.this_device") : device.label ?? model.t("value.unknown"))
                                if let used = device.lastUsed {
                                    Text(Display.ago(model.strings, used, now: Date().timeIntervalSince1970))
                                        .font(.footnote).foregroundStyle(.secondary)
                                }
                            }
                            Spacer()
                            if !device.current {
                                Button(model.t("mobile.account.sign_out_device"), role: .destructive) {
                                    Task { await pages.signOut(device, user: user) }
                                }
                                .buttonStyle(.borderless)
                                .disabled(pages.busy != nil)
                            }
                        }
                        .frame(minHeight: 44)
                    }
                }
            }
        }
        .navigationTitle(model.t("account.title"))
        .task { await pages.load(user) }
        .refreshable { await pages.load(user) }
    }
}
