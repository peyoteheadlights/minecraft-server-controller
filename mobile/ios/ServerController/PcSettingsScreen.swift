import Core
import SwiftUI

/// Settings > PC settings, owner only (the dashboard's App settings; mirrors
/// PcPages in PcSettings.kt): alerts, signed-in devices, the app update,
/// Export everything, Get help, keeping the PC awake, start with Windows
/// and maintenance mode.
@MainActor
@Observable
final class PcPages {
    @ObservationIgnored private let client: () -> AgentClient?
    @ObservationIgnored private let noted: (AgentError) -> Void
    @ObservationIgnored private let strings: Strings

    init(client: @escaping () -> AgentClient?, noted: @escaping (AgentError) -> Void, strings: Strings) {
        self.client = client
        self.noted = noted
        self.strings = strings
    }

    private(set) var view = PageRead<PcSettingsView>()
    private(set) var power: PowerStatus?
    private(set) var update: UpdateStatus?
    private(set) var oldCopy: OldCopy?
    private(set) var sizes: ExportSizes?
    private(set) var devices = PageRead<[Device]>()
    private(set) var startup = PageRead<StartupReport>()
    private(set) var busy: String?
    var said: Said?

    /// The checks before updating, while the confirmation is open.
    var checks: UpdateStatus?
    /// The version asked for, while the PC updates itself and this phone waits.
    private(set) var updating: String?
    private(set) var updateLost = false
    private(set) var exporting: PcSettings.Exporting?
    /// What a help file would hold, while its confirmation is open.
    var helpFiles: HelpFiles?
    /// The help file on this phone, while the share menu is open.
    var sharing: Downloaded?

    func load() async {
        guard let client = client() else { return }
        view.loading = true
        do {
            view = PageRead(value: try await client.pcSettings())
        } catch {
            let problem = client.translateFailure(error)
            noted(problem)
            view = PageRead(value: view.value, problem: problem)
        }
        // The rest is shown when the PC answers; a part it can't read is left out.
        power = try? await client.power()
        if updating == nil { update = try? await client.updates() }
        oldCopy = (try? await client.oldCopy())?.oldCopy
        sizes = try? await client.exportSizes()
    }

    /// Only the update, for the "Version … is out" on the Settings tab.
    func loadUpdate() async {
        guard let client = client(), updating == nil else { return }
        if let now = try? await client.updates() { update = now }
    }

    private func run(_ what: String, _ work: (AgentClient) async throws -> Said?) async {
        guard let client = client(), busy == nil else { return }
        busy = what
        said = nil
        do {
            said = try await work(client)
        } catch {
            let problem = client.translateFailure(error)
            noted(problem)
            said = Said(text: problem.message(strings), good: false)
        }
        busy = nil
    }

    // MARK: settings

    func saveAlerts(before: AlertSettings, after: AlertSettings) async {
        await run("alerts") { client in
            let changes = PcSettings.changes(before, after)
            if changes.isEmpty { return Said(text: strings.t("settings.nothing_changed"), good: true) }
            let result = PcSettings.saved(strings, try await client.savePcSettings(changes))
            view = PageRead(value: try await client.pcSettings())
            return Said(text: result.text, good: result.good)
        }
    }

    private func saveOne(_ what: String, key: String, on: Bool, done: String) async {
        await run(what) { client in
            let result = PcSettings.saved(strings, try await client.savePcSettings([key: .bool(on)]))
            view = PageRead(value: try await client.pcSettings())
            if key == "power.keep_awake" { power = try? await client.power() }
            return Said(text: result.good ? done : result.text, good: result.good)
        }
    }

    func keepAwake(_ on: Bool) async {
        await saveOne("awake", key: "power.keep_awake", on: on, done: strings.t(on ? "awake.turned_on" : "awake.turned_off"))
    }

    func dailyCheck(_ on: Bool) async {
        await saveOne("daily", key: "updates.check", on: on, done: strings.t("settings.saved"))
    }

    func maintenance(_ on: Bool) async {
        await run("maintenance") { client in
            let set = try await client.maintenance(on)
            view = PageRead(value: try await client.pcSettings())
            return Said(text: strings.t(set.maintenance ? "appset.maintenance_on" : "appset.maintenance_off"), good: true)
        }
    }

    func testAlert(_ channel: String) async {
        await run("test:" + channel) { client in
            let sent = try await client.testAlert(channel).sent
            return Said(text: strings.t(sent ? "appset.test_sent" : "appset.test_failed"), good: sent)
        }
    }

    func checkStartup() async {
        guard let client = client() else { return }
        startup.loading = true
        startup.problem = nil
        do {
            startup = PageRead(value: try await client.startupCheck())
        } catch {
            let problem = client.translateFailure(error)
            noted(problem)
            startup = PageRead(problem: problem)
        }
    }

    // MARK: signed-in devices

    func loadDevices() async {
        guard let client = client() else { return }
        devices.loading = true
        do {
            devices = PageRead(value: try await client.devices().sessions)
        } catch {
            let problem = client.translateFailure(error)
            noted(problem)
            devices = PageRead(value: devices.value, problem: problem)
        }
    }

    func signOut(_ device: Device) async {
        await run(device.id) { client in
            try await client.signOutDevice(id: device.id)
            devices = PageRead(value: try await client.devices().sessions)
            return Said(text: strings.t("mobile.account.signed_out_device", ["device": device.label ?? strings.t("security.device_unknown")]), good: true)
        }
    }

    /// Signs everyone out, this phone too. True when it was done.
    func signEveryoneOut() async -> Bool {
        var done = false
        await run("everyone") { client in
            _ = try await client.signEveryoneOut()
            done = true
            return nil
        }
        return done
    }

    // MARK: the app update

    func checkForUpdate() async {
        await run("check") { client in
            let now = try await client.checkForUpdate()
            update = now
            if let error = now.error { return Said(text: strings.t("update.check_failed", ["reason": error]), good: false) }
            if now.available { return Said(text: strings.t("update.available", ["version": now.latest?.version ?? ""]), good: true) }
            return Said(text: strings.t("update.up_to_date", ["version": now.current]), good: true)
        }
    }

    /// Reads who is playing, then the confirmation opens.
    func askToUpdate() async {
        await run("checks") { client in
            checks = try await client.updateChecks()
            return nil
        }
    }

    /// Starts the update, then waits for the PC to come back by itself.
    func install() async {
        guard let client = client(), let before = checks ?? update, let target = before.latest?.version else { return }
        checks = nil
        busy = "update"
        said = nil
        updateLost = false
        defer { busy = nil }
        do {
            _ = try await client.installUpdate()
        } catch {
            let problem = client.translateFailure(error)
            noted(problem)
            said = Said(text: problem.message(strings), good: false)
            return
        }
        updating = target
        defer { updating = nil }
        let started = Date()
        while true {
            try? await Task.sleep(nanoseconds: 5_000_000_000)
            // While it restarts the PC doesn't answer: that is expected, not a problem to show.
            if let now = try? await client.updates(), PcUpdate.back(before: before, now: now, target: target) {
                update = now
                oldCopy = (try? await client.oldCopy())?.oldCopy
                if let text = PcUpdate.lastResult(strings, now.lastResult) {
                    said = Said(text: text, good: now.lastResult?.ok == true)
                }
                return
            }
            if Date().timeIntervalSince(started) > PcUpdate.waitSeconds {
                updateLost = true
                return
            }
        }
    }

    func removeOldCopy() async {
        await run("oldcopy") { client in
            let result = try await client.removeOldCopy()
            oldCopy = (try? await client.oldCopy())?.oldCopy
            return Said(text: PcUpdate.oldCopyRemoved(strings, result), good: true)
        }
    }

    // MARK: export and get help

    func export(worlds: Bool, backups: Bool, secrets: Bool, passphrase: String, folder: String) async {
        await run("export") { client in
            exporting = .running(step: nil, progress: nil)
            defer { exporting = nil }
            let started = try await client.startExport(
                PcSettings.exportBody(worlds: worlds, backups: backups, secrets: secrets, passphrase: passphrase, folder: folder)
            )
            var state = PcSettings.exporting(try await client.exportJob(started.jobId))
            exporting = state
            while case .running = state {
                try await Task.sleep(nanoseconds: 1_000_000_000)
                state = PcSettings.exporting(try await client.exportJob(started.jobId))
                exporting = state
            }
            var good = false
            if case .saved = state { good = true }
            return Said(text: PcSettings.exportSaid(strings, state) ?? "", good: good)
        }
    }

    func askForHelpFile() async {
        await run("help") { client in
            helpFiles = try await client.helpFiles()
            return nil
        }
    }

    /// Makes the help file, brings it to this phone and opens the share menu.
    func makeHelpFile() async {
        helpFiles = nil
        await run("help") { client in
            let made = try await client.makeHelpFile()
            let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
            let name = (made.filename as NSString).lastPathComponent
            let file = folder.appendingPathComponent(name.isEmpty ? "help.zip" : name)
            do {
                try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
                _ = try await client.downloadHelpFile(made, to: file)
            } catch {
                try? FileManager.default.removeItem(at: folder)
                throw error
            }
            sharing = Downloaded(name: file.lastPathComponent, file: file)
            return Said(text: strings.t("mobile.pc.help_made"), good: true)
        }
    }

    /// The share menu closed: the copy in the app's own folder goes.
    func finishSharing() {
        guard let done = sharing else { return }
        sharing = nil
        try? FileManager.default.removeItem(at: done.file.deletingLastPathComponent())
    }
}

// MARK: - Screens

/// Settings > PC settings (owner only).
struct PcSettingsScreen: View {
    @Environment(AppModel.self) private var model
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.openURL) private var openURL
    @State private var askingOldCopy = false

    var body: some View {
        @Bindable var pages = model.pcSettings
        Form {
            if let problem = pages.view.problem {
                Section { Text(problem.message(model.strings)).foregroundStyle(.red) }
            }
            if pages.said != nil {
                Section { SaidRow(said: pages.said, palette: model.basePalette(colorScheme)) }
            }
            Section {
                NavigationLink {
                    DevicesScreen()
                } label: {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(model.t("mobile.pc.devices"))
                        Text(model.t("mobile.pc.devices_hint")).font(.footnote).foregroundStyle(.secondary)
                    }
                }
                .frame(minHeight: 44)
                NavigationLink(model.t("appset.alerts")) {
                    AlertSettingsScreen()
                }
                .frame(minHeight: 44)
            }
            if let status = pages.update {
                updateSection(status)
            }
            if let old = pages.oldCopy, old.offer {
                Section(model.t("oldcopy.title")) {
                    Text(model.t("oldcopy.body", ["path": old.path]))
                    Text(model.t("oldcopy.keeps")).font(.footnote).foregroundStyle(.secondary)
                    if old.problems.isEmpty {
                        Button(model.t(pages.busy == "oldcopy" ? "oldcopy.removing" : "oldcopy.remove"), role: .destructive) {
                            askingOldCopy = true
                        }
                        .disabled(pages.busy != nil)
                        .frame(minHeight: 44)
                    } else {
                        Text(model.t("oldcopy.cant") + "\n" + old.problems.joined(separator: "\n")).foregroundStyle(.red)
                    }
                }
            }
            if let view = pages.view.value {
                Section(model.t("awake.title")) {
                    Toggle(isOn: Binding(get: { PcSettings.keepAwake(view) }, set: { on in Task { await pages.keepAwake(on) } })) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(model.t("awake.label"))
                            if let power = pages.power {
                                Text(PcSettings.awake(model.strings, power)).font(.footnote).foregroundStyle(.secondary)
                            }
                        }
                    }
                    .disabled(pages.busy != nil)
                    .frame(minHeight: 44)
                    if let power = pages.power {
                        if let problem = power.problem { Text(problem).foregroundStyle(.red) }
                        let notes = PcSettings.stillSleeps(model.strings, power)
                        if !notes.isEmpty {
                            Text(model.t("awake.still_title") + "\n" + notes.joined(separator: "\n")).foregroundStyle(.orange)
                        }
                        if model.technical, let battery = power.battery, battery.present == true {
                            Text(model.t("awake.battery", [
                                "percent": battery.percent.map(String.init) ?? model.t("value.unknown"),
                                "source": model.t(battery.pluggedIn == true ? "awake.plugged_in" : "awake.on_battery"),
                            ]))
                            .font(.footnote).foregroundStyle(.secondary)
                        }
                    }
                }
                Section(model.t("appset.maintenance")) {
                    Toggle(model.t("appset.maintenance_label"), isOn: Binding(
                        get: { PcSettings.maintenance(view) },
                        set: { on in Task { await pages.maintenance(on) } }
                    ))
                    .disabled(pages.busy != nil)
                    .frame(minHeight: 44)
                }
            }
            ExportSection()
            Section(model.t("gethelp.title")) {
                Text(model.t("gethelp.lead")).foregroundStyle(.secondary)
                Button(model.t(pages.busy == "help" ? "gethelp.listing" : "mobile.pc.help_share")) {
                    Task { await pages.askForHelpFile() }
                }
                .disabled(pages.busy != nil)
                .frame(minHeight: 44)
            }
            startupSection
        }
        .navigationTitle(model.t("mobile.pc.title"))
        .task {
            pages.said = nil
            await pages.load()
        }
        .refreshable { await pages.load() }
        .alert(
            model.t("update.confirm_title", ["version": pages.checks?.latest?.version ?? ""]),
            isPresented: Binding(get: { pages.checks != nil }, set: { if !$0 { pages.checks = nil } }),
            presenting: pages.checks
        ) { check in
            Button(PcUpdate.confirmLabel(model.strings, check), role: (check.playersOnline ?? 0) > 0 ? ButtonRole.destructive : nil) {
                Task { await pages.install() }
            }
            Button(model.t("mobile.common.cancel"), role: .cancel) { pages.checks = nil }
        } message: { check in
            Text(PcUpdate.confirmBody(model.strings, check))
        }
        .alert(
            model.t("gethelp.confirm_title"),
            isPresented: Binding(get: { pages.helpFiles != nil }, set: { if !$0 { pages.helpFiles = nil } }),
            presenting: pages.helpFiles
        ) { _ in
            Button(model.t("mobile.pc.help_share")) { Task { await pages.makeHelpFile() } }
            Button(model.t("mobile.common.cancel"), role: .cancel) { pages.helpFiles = nil }
        } message: { files in
            Text(model.t("gethelp.confirm_body") + "\n" + files.files.map { file in
                file.name + " " + (file.size.map { Display.bytes(model.strings, $0) } ?? model.t("gethelp.made_now"))
            }.joined(separator: "\n") + "\n\n" + model.t("gethelp.never"))
        }
        .alert(model.t("oldcopy.confirm_title"), isPresented: $askingOldCopy) {
            Button(model.t("oldcopy.remove"), role: .destructive) { Task { await pages.removeOldCopy() } }
            Button(model.t("mobile.common.cancel"), role: .cancel) {}
        } message: {
            Text(model.t("oldcopy.confirm_body", ["path": pages.oldCopy?.path ?? ""]))
        }
        .sheet(item: $pages.sharing, onDismiss: { pages.finishSharing() }) { done in
            ShareSheet(file: done.file)
        }
        // While the PC updates itself nothing else can be done with it.
        .fullScreenCover(isPresented: Binding(get: { pages.updating != nil }, set: { _ in })) {
            VStack(spacing: 16) {
                ProgressView()
                Text(model.t("mobile.pc.updating")).font(.title3)
                Text(model.t("mobile.pc.updating_hint")).foregroundStyle(.secondary).multilineTextAlignment(.center)
            }
            .padding()
        }
    }

    @ViewBuilder
    private func updateSection(_ status: UpdateStatus) -> some View {
        let pages = model.pcSettings
        let shows = PcUpdate.shows(status, updating: pages.updating)
        Section(model.t("update.title")) {
            VStack(alignment: .leading, spacing: 2) {
                switch shows {
                case .ready, .cantInstall:
                    Text(model.t("update.available", ["version": status.latest?.version ?? ""]))
                case .updating:
                    Text(model.t("mobile.pc.updating"))
                default:
                    Text(model.t(status.checkedAt != nil ? "update.up_to_date" : "update.current", ["version": status.current]))
                }
                if let checked = status.checkedAt {
                    Text(model.t("update.checked", ["when": Display.ago(model.strings, checked, now: Date().timeIntervalSince1970)]))
                        .font(.footnote).foregroundStyle(.secondary)
                }
            }
            .frame(minHeight: 44, alignment: .leading)
            if shows == .ready || shows == .cantInstall {
                let notes = PcUpdate.notes(status.latest)
                if !notes.isEmpty {
                    Text(model.t("update.whats_new") + "\n" + notes.map { "• " + $0 }.joined(separator: "\n"))
                }
                if let reason = status.cannotInstallReason {
                    Text(reason).font(.footnote).foregroundStyle(.secondary)
                }
                if let page = status.latest?.page, let url = URL(string: page) {
                    Button(model.t("update.release_page")) { openURL(url) }.frame(minHeight: 44)
                }
            }
            if let error = status.error {
                Text(model.t("update.check_failed", ["reason": error])).foregroundStyle(.red)
            }
            if let last = PcUpdate.lastResult(model.strings, status.lastResult) {
                Text(last).foregroundStyle(status.lastResult?.ok == true ? Color.secondary : Color.red)
            }
            if pages.updateLost {
                Text(model.t("mobile.pc.update_lost")).foregroundStyle(.red)
            }
            if let view = pages.view.value {
                Toggle(model.t("mobile.pc.daily_check"), isOn: Binding(
                    get: { PcSettings.dailyCheck(view) },
                    set: { on in Task { await pages.dailyCheck(on) } }
                ))
                .disabled(pages.busy != nil)
                .frame(minHeight: 44)
            }
            if shows == .ready {
                Button(model.t(pages.busy == "checks" ? "update.installing" : "update.install")) {
                    Task { await pages.askToUpdate() }
                }
                .disabled(pages.busy != nil)
                .frame(minHeight: 44)
            }
            Button(model.t(pages.busy == "check" ? "update.checking" : "update.check_now")) {
                Task { await pages.checkForUpdate() }
            }
            .disabled(pages.busy != nil)
            .frame(minHeight: 44)
        }
    }

    private var startupSection: some View {
        let pages = model.pcSettings
        return Section(model.t("appset.startup")) {
            Text(model.t("appset.startup_hint")).foregroundStyle(.secondary)
            if let problem = pages.startup.problem {
                Text(problem.message(model.strings)).foregroundStyle(.red)
            }
            if let report = pages.startup.value {
                let good = PcSettings.verdictGood(report)
                Text(model.t(PcSettings.verdict(report)))
                    .fontWeight(.medium)
                    .foregroundStyle(good == false ? Color.red : Color.primary)
                ForEach(Array(PcSettings.startupRows(model.strings, report, technical: model.technical).enumerated()), id: \.offset) { _, row in
                    LabeledContent(row.name, value: row.value)
                }
                if let problems = report.problems, !problems.isEmpty {
                    Text(problems.joined(separator: "\n")).foregroundStyle(.red)
                }
            }
            Button(model.t(pages.startup.loading ? "appset.startup_asking" : "appset.startup_check")) {
                Task { await pages.checkStartup() }
            }
            .disabled(pages.startup.loading)
            .frame(minHeight: 44)
        }
    }
}

/// Export everything into a folder on the PC.
private struct ExportSection: View {
    @Environment(AppModel.self) private var model
    @State private var worlds = true
    @State private var backups = false
    @State private var secrets = false
    @State private var passphrase = ""
    @State private var folder: String?
    @State private var picking = false

    var body: some View {
        let pages = model.pcSettings
        let totals = pages.sizes.map(PcSettings.totals)
        Section(model.t("export.title")) {
            Text(model.t("export.lead")).foregroundStyle(.secondary)
            Text(model.t("mobile.pc.export_hint")).font(.footnote).foregroundStyle(.secondary)
            Toggle(model.t("export.always", ["size": size(totals?.files)]), isOn: .constant(true)).disabled(true)
            Toggle(model.t("export.worlds", ["size": size(totals?.worlds)]), isOn: $worlds)
            Toggle(model.t("export.backups", ["size": size(totals?.backups)]), isOn: $backups)
            Toggle(model.t("export.secrets"), isOn: $secrets)
            if secrets {
                SecureField(model.t("export.passphrase"), text: $passphrase)
                    .textContentType(.newPassword)
                    .frame(minHeight: 44)
                Text(model.t("export.passphrase_hint")).font(.footnote).foregroundStyle(.secondary)
            }
            Button {
                picking = true
            } label: {
                LabeledContent(model.t("mobile.pc.export_folder"), value: folder ?? model.t("mobile.pc.export_pick"))
            }
            .frame(minHeight: 44)
            if case .some(.running(let step, let progress)) = pages.exporting {
                VStack(alignment: .leading, spacing: 6) {
                    Text(step ?? model.t("export.working")).foregroundStyle(.secondary)
                    if let progress = progress {
                        ProgressView(value: progress)
                    } else {
                        ProgressView()
                    }
                }
            } else {
                Button(model.t("export.button")) {
                    guard let chosen = folder else { return }
                    let phrase = passphrase
                    passphrase = ""
                    Task { await pages.export(worlds: worlds, backups: backups, secrets: secrets, passphrase: phrase, folder: chosen) }
                }
                .disabled(pages.busy != nil || !PcSettings.canExport(folder: folder, secrets: secrets, passphrase: passphrase))
                .frame(minHeight: 44)
            }
            Text(model.t("export.other_side")).font(.footnote).foregroundStyle(.secondary)
        }
        .sheet(isPresented: $picking) {
            FolderPickerView(title: model.t("mobile.pc.export_pick"), start: folder) { picked in
                folder = picked
            }
        }
    }

    private func size(_ n: Int64?) -> String {
        n == nil ? model.t("value.unknown") : Display.bytes(model.strings, n)
    }
}

/// PC settings > Signed-in devices: every account's, owner only.
struct DevicesScreen: View {
    @Environment(AppModel.self) private var model
    @Environment(\.colorScheme) private var colorScheme
    @State private var asking = false

    var body: some View {
        let pages = model.pcSettings
        let me = model.me?.user
        List {
            Section { Text(model.t("mobile.pc.devices_hint")).foregroundStyle(.secondary) }
            if pages.said != nil {
                Section { SaidRow(said: pages.said, palette: model.basePalette(colorScheme)) }
            }
            if let problem = pages.devices.problem {
                Section { Text(problem.message(model.strings)).foregroundStyle(.red) }
            }
            if let devices = pages.devices.value {
                if devices.isEmpty {
                    Section { Text(model.t("security.no_sessions")).foregroundStyle(.secondary) }
                }
                ForEach(PcSettings.byAccount(devices, me: me)) { account in
                    Section(account.user == me ? model.t("mobile.pc.you", ["name": account.user]) : account.user) {
                        ForEach(account.devices) { device in
                            HStack {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(device.current ? model.t("mobile.account.this_device") : device.label ?? model.t("security.device_unknown"))
                                    if let used = device.lastUsed {
                                        Text(Display.ago(model.strings, used, now: Date().timeIntervalSince1970))
                                            .font(.footnote).foregroundStyle(.secondary)
                                    }
                                }
                                Spacer()
                                if !device.current {
                                    Button(model.t("mobile.account.sign_out_device"), role: .destructive) {
                                        Task { await pages.signOut(device) }
                                    }
                                    .buttonStyle(.borderless)
                                    .disabled(pages.busy != nil)
                                }
                            }
                            .frame(minHeight: 44)
                        }
                    }
                }
                Section {
                    Button(model.t("security.revoke"), role: .destructive) { asking = true }
                        .disabled(pages.busy != nil)
                        .frame(minHeight: 44)
                }
            }
        }
        .navigationTitle(model.t("mobile.pc.devices"))
        .task {
            pages.said = nil
            await pages.loadDevices()
        }
        .refreshable { await pages.loadDevices() }
        .alert(model.t("security.revoke_title"), isPresented: $asking) {
            Button(model.t("security.revoke"), role: .destructive) {
                Task {
                    if await pages.signEveryoneOut() { model.signedOutEverywhere() }
                }
            }
            Button(model.t("mobile.common.cancel"), role: .cancel) {}
        } message: {
            Text(model.t("security.revoke_body"))
        }
    }
}

/// PC settings > Alerts: every alert setting the dashboard has.
struct AlertSettingsScreen: View {
    @Environment(AppModel.self) private var model
    @Environment(\.colorScheme) private var colorScheme
    @State private var saved = AlertSettings()
    @State private var edit = AlertSettings()
    /// What's typed, so a half-typed number isn't lost or saved.
    @State private var typed: [String: String] = [:]
    @State private var loaded: PcSettingsView?

    var body: some View {
        let pages = model.pcSettings
        let wrong = Set(typed.filter { PcSettings.number($0.value) == nil }.keys)
        Form {
            if let problem = pages.view.problem, pages.view.value == nil {
                Section { Text(problem.message(model.strings)).foregroundStyle(.red) }
            }
            if pages.said != nil {
                Section { SaidRow(said: pages.said, palette: model.basePalette(colorScheme)) }
            }
            if let view = pages.view.value {
                Section {
                    channel(model.t("appset.discord"), on: $edit.discord, missing: view.secrets.discord ? nil : model.t("appset.discord_missing"), test: "discord")
                    channel(model.t("appset.email"), on: $edit.email, missing: view.secrets.email ? nil : model.t("appset.email_missing"), test: "email")
                    if model.technical {
                        let to = PcSettings.emailTo(view)
                        if !to.isEmpty {
                            Text(model.t("mobile.pc.email_to", ["addresses": to.joined(separator: ", ")])).font(.footnote).foregroundStyle(.secondary)
                        }
                    }
                    Toggle(isOn: $edit.phone) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(model.t("appset.phone"))
                            Text(model.t("mobile.pc.phone_missing")).font(.footnote).foregroundStyle(.secondary)
                        }
                    }
                    .frame(minHeight: 44)
                    Text(model.t(model.technical ? "mobile.pc.secrets_technical" : "appset.secrets_note")).font(.footnote).foregroundStyle(.secondary)
                }
                Section(model.t("appset.alert_details")) {
                    ForEach(PcSettings.thresholds) { limit in
                        number(model.t(limit.label), key: limit.key, wrong: wrong.contains(limit.key)) { edit.thresholds[limit.key] = $0 }
                    }
                    number(model.t("appset.repeat_alert"), key: "repeat", wrong: wrong.contains("repeat")) { edit.repeatSeconds = $0 }
                }
                Section(model.t("appset.which_events")) {
                    ForEach(edit.events) { event in
                        // An event the phone has no words for shows the PC's own name for it.
                        Toggle(
                            model.strings.has("alert_event." + event.key) ? model.t("alert_event." + event.key) : event.key,
                            isOn: Binding(get: { edit.event(event.key) ?? false }, set: { edit.set(event: event.key, $0) })
                        )
                        .frame(minHeight: 44)
                    }
                }
                Section {
                    Button(model.t(pages.busy == "alerts" ? "action.saving" : "appset.save_alerts")) {
                        let (before, after) = (saved, edit)
                        Task { await pages.saveAlerts(before: before, after: after) }
                    }
                    .disabled(pages.busy != nil || !wrong.isEmpty)
                    .frame(minHeight: 44)
                }
            } else if pages.view.problem == nil {
                ProgressView().frame(maxWidth: .infinity)
            }
        }
        .navigationTitle(model.t("appset.alerts"))
        .task {
            pages.said = nil
            if pages.view.value == nil { await pages.load() }
        }
        .onChange(of: pages.view.value, initial: true) { _, view in
            guard let view = view, view != loaded else { return }
            loaded = view
            let alerts = PcSettings.alerts(view)
            saved = alerts
            edit = alerts
            var text: [String: String] = [:]
            for (key, value) in alerts.thresholds {
                text[key] = Display.fixed(value, value.rounded() == value ? 0 : 1)
            }
            text["repeat"] = Display.fixed(alerts.repeatSeconds, 0)
            typed = text
        }
    }

    private func channel(_ name: String, on: Binding<Bool>, missing: String?, test: String) -> some View {
        let pages = model.pcSettings
        return Group {
            Toggle(isOn: on) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(name)
                    if let missing = missing { Text(missing).font(.footnote).foregroundStyle(.secondary) }
                }
            }
            .frame(minHeight: 44)
            Button(model.t(pages.busy == "test:" + test ? "appset.sending" : "appset.send_test")) {
                Task { await pages.testAlert(test) }
            }
            .disabled(pages.busy != nil)
            .frame(minHeight: 44)
        }
    }

    private func number(_ label: String, key: String, wrong: Bool, set: @escaping (Double) -> Void) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label).font(.footnote).foregroundStyle(.secondary)
            TextField(label, text: Binding(
                get: { typed[key] ?? "" },
                set: { text in
                    typed[key] = text
                    if let n = PcSettings.number(text) { set(n) }
                }
            ))
            .keyboardType(.decimalPad)
            .frame(minHeight: 44)
            if wrong {
                Text(model.t("mobile.pc.number_wrong")).font(.footnote).foregroundStyle(.red)
            }
        }
    }
}
