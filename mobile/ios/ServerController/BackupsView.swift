import Core
import SwiftUI

/// A heading over a group of cards.
struct SectionTitle: View {
    let text: String
    let palette: Palette

    var body: some View {
        Text(text)
            .font(.headline)
            .foregroundStyle(palette.textPrimary)
            .padding(.top, 8)
            .accessibilityAddTraits(.isHeader)
    }
}

/// A small grey line under a card or a value.
struct Hint: View {
    let text: String
    let palette: Palette

    var body: some View {
        Text(verbatim: text)
            .font(.footnote)
            .foregroundStyle(palette.textSecondary)
    }
}

/// What the last button did, in green or in the warning color.
struct SaidRow: View {
    let said: Said?
    let palette: Palette

    var body: some View {
        if let said = said {
            Label(said.text, systemImage: said.good ? "checkmark.circle" : "exclamationmark.triangle")
                .foregroundStyle(palette.tone(said.good ? .success : .warning))
        }
    }
}

/// One button in a row of them.
struct Press: Identifiable {
    let title: String
    var danger = false
    var enabled = true
    let run: () -> Void

    var id: String { title }
}

/// Buttons in rows, wrapping when they don't fit.
struct Presses: View {
    let presses: [Press]
    let palette: Palette

    var body: some View {
        if !presses.isEmpty {
            FlowLayout(spacing: 8) {
                ForEach(presses) { press in
                    Button(press.title, action: press.run)
                        .buttonStyle(.bordered)
                        .tint(press.danger ? palette.danger : palette.accentInk)
                        .disabled(!press.enabled)
                }
            }
        }
    }
}

/// A destructive step waiting for "yes".
private struct Confirming: Identifiable {
    let title: String
    let body: String
    let confirm: String
    let run: () -> Void

    var id: String { title }
}

/// Back up now and Save world, the last change with Undo, each backup with
/// Check, Download, Restore and Delete, the second copy off the PC, and the
/// worlds. A download is saved where the person picks, with the sign-in in
/// a header; nothing else ever leaves the PC.
struct BackupsView: View {
    let serverId: String

    @Environment(AppModel.self) private var model
    @State private var asking: Confirming?
    @State private var moving = false

    private var world: WorldPages { model.pages(serverId).world }

    var body: some View {
        @Bindable var world = self.world
        ServerFrame(serverId: serverId, title: model.t("page.backups")) { palette in
            ScrollView {
                TimelineView(.periodic(from: .now, by: 30)) { context in
                    VStack(alignment: .leading, spacing: 12) {
                        content(world, palette, now: context.date.timeIntervalSince1970)
                    }
                    .padding(16)
                    .frame(maxWidth: 640)
                    .frame(maxWidth: .infinity)
                }
            }
            .refreshable { await world.loadBackups() }
            .alert(
                asking?.title ?? "",
                isPresented: Binding(get: { asking != nil }, set: { if !$0 { asking = nil } }),
                presenting: asking,
                actions: { ask in
                    Button(ask.confirm, role: .destructive, action: ask.run)
                    Button(model.t("mobile.common.cancel"), role: .cancel) {}
                },
                message: { ask in Text(ask.body) }
            )
            .sheet(item: $world.restoring) { ask in
                RestoreSheet(ask: ask, palette: palette) { startAfter in
                    let strings = model.strings
                    Task { await world.restore(ask, startAfter: startAfter, strings) }
                }
            }
            .fileMover(
                isPresented: $moving,
                file: world.downloaded?.file,
                onCompletion: { result in world.finishDownload(result, model.strings) },
                onCancellation: { world.finishDownload(nil, model.strings) }
            )
            .onChange(of: world.downloaded?.id) {
                moving = world.downloaded != nil
            }
            .onAppear {
                // A download that finished while another screen was open.
                if world.downloaded != nil { moving = true }
            }
        }
        .task(id: serverId) { await world.loadBackups() }
    }

    // MARK: - The page

    @ViewBuilder
    private func content(_ world: WorldPages, _ palette: Palette, now: Double) -> some View {
        let busy = world.busy
        Presses(presses: topButtons(world, busy), palette: palette)
        SaidRow(said: world.said, palette: palette)
        if let progress = world.downloading {
            HStack(spacing: 8) {
                ProgressView().controlSize(.small)
                Hint(text: downloadText(progress), palette: palette)
            }
        }
        if let job = world.lastChange, let undo = job.undo {
            lastChange(world, job, undo, busy, palette, now: now)
        }

        SectionTitle(text: model.t("backups.list"), palette: palette)
        if let problem = world.backups.problem {
            ProblemCard(problem: problem, palette: palette) { await world.loadBackups() }
        } else if let list = world.backups.value {
            if list.backups.isEmpty {
                EmptyCard(title: model.t("backups.none"), hint: model.t("backups.none_hint"), palette: palette)
            }
            ForEach(list.backups) { backup in
                backupCard(world, backup, busy, palette)
            }
            if let keeping = Backups.keeping(model.strings, list.retention) {
                Hint(text: keeping, palette: palette)
            }
        } else {
            ProgressView().frame(maxWidth: .infinity)
        }

        SectionTitle(text: model.t("page.world"), palette: palette)
        NavigationLink(value: ServerRoute.page(serverId, .world)) {
            CardBox(palette: palette) {
                HStack {
                    Text(model.t("world.lead"))
                        .foregroundStyle(palette.textPrimary)
                        .multilineTextAlignment(.leading)
                    Spacer()
                    Image(systemName: "chevron.right")
                        .font(.footnote.weight(.semibold))
                        .foregroundStyle(palette.textSecondary)
                        .accessibilityHidden(true)
                }
            }
        }
        .buttonStyle(.plain)

        offsiteCard(world, busy, palette)
        worldsCard(world, palette, now: now)
    }

    private func topButtons(_ world: WorldPages, _ busy: String?) -> [Press] {
        let strings = model.strings
        var presses: [Press] = []
        if model.can(Permissions.BACKUPS_CREATE) {
            presses.append(Press(title: model.t(busy == "backup" ? "backup.working" : "action.back_up_now"), enabled: busy == nil) {
                Task { await world.backUp(strings) }
            })
        }
        if model.canControl {
            presses.append(Press(title: model.t("backups.save_world"), enabled: busy == nil) {
                Task { await world.saveWorld(strings) }
            })
        }
        return presses
    }

    private func downloadText(_ progress: Downloading) -> String {
        let share: String
        if let size = progress.size, size > 0 {
            share = "\(progress.done * 100 / size)%"
        } else {
            share = Display.bytes(model.strings, progress.done)
        }
        return model.t("mobile.backups.downloading", ["name": progress.name]) + " " + share
    }

    @ViewBuilder
    private func lastChange(_ world: WorldPages, _ job: Job, _ undo: Undo, _ busy: String?, _ palette: Palette, now: Double) -> some View {
        let strings = model.strings
        SectionTitle(text: model.t("mobile.backups.last_change"), palette: palette)
        CardBox(palette: palette) {
            Text(model.t("mobile.backups.last_change_body", [
                "title": job.title, "when": Display.ago(strings, job.finishedAt, now: now), "backup": undo.backup,
            ]))
            .foregroundStyle(palette.textPrimary)
            if model.can(Permissions.BACKUPS_RESTORE) {
                Presses(presses: [
                    Press(title: model.t("mobile.backups.undo_change"), danger: true, enabled: busy == nil) {
                        asking = Confirming(
                            title: model.t("mobile.backups.undo_title"),
                            body: model.t("mobile.backups.undo_body", ["title": job.title, "backup": undo.backup]),
                            confirm: model.t("mobile.backups.undo_change")
                        ) {
                            Task { await world.undo(job, strings) }
                        }
                    },
                ], palette: palette)
            }
        }
    }

    private func backupCard(_ world: WorldPages, _ backup: Backup, _ busy: String?, _ palette: Palette) -> some View {
        let strings = model.strings
        let kind = Backups.kind(backup.kind).map { model.t($0.key) } ?? backup.kind ?? model.t("value.unknown")
        let status = Backups.status(backup.status)
        let copy = Backups.copy(strings, backup.copy)
        let when = Display.dateTime(strings, backup.createdAt)
        let idle = busy == nil
        var details = [kind, model.t(status.key), Display.bytes(strings, backup.sizeBytes)]
        if model.technical { details.append(when) }

        var presses = [
            Press(title: model.t(busy == "check:\(backup.id)" ? "backups.checking" : "backups.verify"), enabled: idle) {
                Task { await world.check(backup, strings) }
            },
        ]
        if model.can(Permissions.BACKUPS_DOWNLOAD) && Backups.onDisk(backup) {
            presses.append(Press(title: model.t("backups.download"), enabled: idle) {
                Task { await world.download(backup, strings) }
            })
        }
        if model.can(Permissions.BACKUPS_RESTORE) && Backups.onDisk(backup) {
            let working = busy == "restore:\(backup.id)"
            presses.append(Press(title: model.t(working ? "mobile.backups.restore_working" : "backups.restore"), enabled: idle) {
                Task { await world.askRestore(backup, strings) }
            })
        }
        if Backups.canCopyAgain(backup, offsite: world.offsite, canCreate: model.can(Permissions.BACKUPS_CREATE)) {
            presses.append(Press(title: model.t(busy == "copy:\(backup.id)" ? "offsite.copying" : "offsite.copy_now"), enabled: idle) {
                Task { await world.copyAgain(backup, strings) }
            })
        }
        if model.can(Permissions.BACKUPS_DELETE) {
            presses.append(Press(title: model.t("backups.delete"), danger: true, enabled: idle) {
                asking = Confirming(
                    title: model.t("backups.delete_title", ["name": backup.name]),
                    body: model.t("backups.delete_body"),
                    confirm: model.t("backups.delete_confirm")
                ) {
                    Task { await world.delete(backup, strings) }
                }
            })
        }

        return CardBox(palette: palette) {
            Text(verbatim: model.technical ? backup.name : when)
                .font(.headline)
                .foregroundStyle(palette.textPrimary)
            Hint(text: details.joined(separator: " · "), palette: palette)
            Text(verbatim: model.t("offsite.col") + ": " + copy.text)
                .font(.footnote)
                .foregroundStyle(copy.tone == .neutral ? palette.textSecondary : palette.tone(copy.tone))
            Presses(presses: presses, palette: palette)
        }
    }

    @ViewBuilder
    private func offsiteCard(_ world: WorldPages, _ busy: String?, _ palette: Palette) -> some View {
        let canEdit = model.can(Permissions.SETTINGS_EDIT)
        let offsite = world.offsite
        let folder = offsite?.directory ?? ""
        SectionTitle(text: model.t("offsite.title"), palette: palette)
        CardBox(palette: palette) {
            Text(model.t("offsite.lead"))
                .foregroundStyle(palette.textPrimary)
            if offsite == nil {
                Hint(text: model.t("value.unknown"), palette: palette)
            } else if folder.isEmpty {
                Hint(text: model.t("offsite.off"), palette: palette)
            } else if let reason = offsite?.unavailable {
                Text(verbatim: model.t("offsite.folder_unavailable", ["folder": folder, "reason": reason]))
                    .font(.footnote)
                    .foregroundStyle(palette.tone(.warning))
            } else {
                Hint(text: model.t("offsite.folder_ok", ["folder": folder]), palette: palette)
            }
            if model.technical, let subfolder = offsite?.subfolder {
                Hint(text: subfolder, palette: palette)
            }
            if canEdit {
                Hint(text: model.t("mobile.offsite.choose_on_pc"), palette: palette)
            }
            if canEdit && !folder.isEmpty {
                let strings = model.strings
                Presses(presses: [
                    Press(title: model.t(busy == "offsite" ? "action.saving" : "offsite.turn_off"), enabled: busy == nil) {
                        Task { await world.offsiteOff(strings) }
                    },
                ], palette: palette)
            }
        }
    }

    @ViewBuilder
    private func worldsCard(_ world: WorldPages, _ palette: Palette, now: Double) -> some View {
        if let worlds = world.worlds.value?.worlds, !worlds.isEmpty {
            let strings = model.strings
            SectionTitle(text: model.t("backups.worlds"), palette: palette)
            CardBox(palette: palette) {
                ForEach(worlds) { w in
                    let last = w.lastBackup?.createdAt.map { Display.ago(strings, $0, now: now) } ?? model.t("time.never")
                    let lastText = model.technical && w.lastBackup?.name != nil ? "\(w.lastBackup?.name ?? "") (\(last))" : last
                    VStack(alignment: .leading, spacing: 2) {
                        Text(verbatim: w.label)
                            .foregroundStyle(palette.textPrimary)
                        Hint(
                            text: !w.exists ? model.t("backups.world_missing") : [
                                Display.bytes(strings, w.sizeBytes),
                                model.t("backups.col_modified") + ": " + Display.dateTime(strings, w.modified),
                                model.t("backups.col_last_backup") + ": " + lastText,
                            ].joined(separator: " · "),
                            palette: palette
                        )
                    }
                    .frame(minHeight: 44, alignment: .leading)
                    .accessibilityElement(children: .combine)
                }
            }
        }
    }
}

/// What the agent says a restore will do, "start the server after", then
/// yes or no.
private struct RestoreSheet: View {
    let ask: RestoreAsk
    let palette: Palette
    let restore: (Bool) -> Void

    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var startAfter = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text(model.t("backups.restore_question", [
                        "name": ask.backup.name, "when": Display.dateTime(model.strings, ask.backup.createdAt),
                    ]))
                    ForEach(Array(ask.willHappen.enumerated()), id: \.offset) { _, step in
                        Label(step, systemImage: "arrow.right.circle")
                            .foregroundStyle(palette.textSecondary)
                    }
                }
                Section {
                    Toggle(model.t("backups.start_after"), isOn: $startAfter)
                }
                Section {
                    Button(model.t("backups.restore_confirm"), role: .destructive) {
                        restore(startAfter)
                        dismiss()
                    }
                }
            }
            .navigationTitle(model.t("backups.restore_title"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(model.t("mobile.common.cancel")) { dismiss() }
                }
            }
        }
        .presentationDetents([.medium, .large])
    }
}

/// Restore world: the world as it was at a point in time. Every point is a
/// backup the agent checked; going back makes a backup of the world as it
/// is now first, and the server has to be off.
struct WorldRestoreView: View {
    let serverId: String

    @Environment(AppModel.self) private var model
    @State private var asking: WorldPoint?

    private var world: WorldPages { model.pages(serverId).world }

    var body: some View {
        let world = self.world
        ServerFrame(serverId: serverId, title: model.t("page.world")) { palette in
            ScrollView {
                TimelineView(.periodic(from: .now, by: 30)) { context in
                    VStack(alignment: .leading, spacing: 12) {
                        content(world, palette, now: context.date.timeIntervalSince1970)
                    }
                    .padding(16)
                    .frame(maxWidth: 640)
                    .frame(maxWidth: .infinity)
                }
            }
            .refreshable { await world.loadTimeline() }
            .alert(
                askTitle,
                isPresented: Binding(get: { asking != nil }, set: { if !$0 { asking = nil } }),
                presenting: asking,
                actions: { point in
                    Button(model.t("world.confirm_action"), role: .destructive) {
                        let strings = model.strings
                        Task { await world.restoreWorld(point, strings) }
                    }
                    Button(model.t("mobile.common.cancel"), role: .cancel) {}
                },
                message: { point in
                    Text(model.t("world.confirm_body", ["loss": WorldRestore.lossLine(model.strings, point)]) + "\n\n" + model.t("world.confirm_safety"))
                }
            )
        }
        .task(id: serverId) { await world.loadTimeline() }
    }

    private var askTitle: String {
        guard let point = asking else { return "" }
        return model.t("world.confirm_title", ["when": WorldRestore.whenLabel(model.strings, point.createdAt, now: Date().timeIntervalSince1970)])
    }

    @ViewBuilder
    private func content(_ world: WorldPages, _ palette: Palette, now: Double) -> some View {
        let strings = model.strings
        Text(model.t("world.lead"))
            .foregroundStyle(palette.textPrimary)
        SaidRow(said: world.said, palette: palette)
        if let problem = world.timeline.problem {
            // Whether the server is off is a current state: not shown after a failed read.
            ProblemCard(problem: problem, palette: palette) { await world.loadTimeline() }
        } else if let timeline = world.timeline.value {
            if timeline.points.isEmpty {
                EmptyCard(title: model.t("world.none"), hint: model.t("world.none_hint"), palette: palette)
            } else {
                if let why = WorldRestore.blocked(strings, timeline) {
                    Label(why, systemImage: "exclamationmark.triangle")
                        .foregroundStyle(palette.tone(.warning))
                }
                let canRestore = model.can(Permissions.BACKUPS_RESTORE)
                ForEach(timeline.points) { point in
                    let tags = [
                        point.kind == "safety" ? model.t("world.tag_safety") : nil,
                        point.checked ? nil : model.t("backup.unchecked"),
                    ].compactMap { $0 }
                    CardBox(palette: palette) {
                        Text(WorldRestore.whenLabel(strings, point.createdAt, now: now))
                            .font(.headline)
                            .foregroundStyle(palette.textPrimary)
                        Hint(text: ([WorldRestore.lossLine(strings, point)] + tags).joined(separator: " · "), palette: palette)
                        if model.technical {
                            Hint(text: "\(point.name) · \(Display.bytes(strings, point.sizeBytes))", palette: palette)
                        }
                        if !point.checked {
                            Hint(text: model.t("world.not_offered"), palette: palette)
                        } else if canRestore {
                            let working = world.busy == "world:\(point.backupId)"
                            Presses(presses: [
                                Press(
                                    title: model.t(working ? "world.working" : "world.go_back"), danger: true,
                                    enabled: world.busy == nil && timeline.canRestore
                                ) { asking = point },
                            ], palette: palette)
                        }
                    }
                }
                Hint(text: model.t("world.footer"), palette: palette)
            }
        } else {
            ProgressView().frame(maxWidth: .infinity)
        }
    }
}
