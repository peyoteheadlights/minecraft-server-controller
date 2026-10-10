import Core
import SwiftUI

/// What runs on its own at set times: a form to add one, then each schedule
/// with when it runs next and how its last run went, Turn on or off, Run now
/// and Delete. Only someone allowed to manage schedules gets the buttons.
struct SchedulesView: View {
    let serverId: String

    @Environment(AppModel.self) private var model
    @State private var deleting: Schedule?

    private var world: WorldPages { model.pages(serverId).world }

    var body: some View {
        let world = self.world
        ServerFrame(serverId: serverId, title: model.t("page.schedules")) { palette in
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    content(world, palette)
                }
                .padding(16)
                .frame(maxWidth: 640)
                .frame(maxWidth: .infinity)
            }
            .refreshable { await world.loadSchedules() }
            .alert(
                deleting.map { model.t("schedules.delete_title", ["name": $0.name]) } ?? "",
                isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } }),
                presenting: deleting,
                actions: { schedule in
                    Button(model.t("schedules.delete"), role: .destructive) {
                        let strings = model.strings
                        Task { await world.deleteSchedule(schedule, strings) }
                    }
                    Button(model.t("mobile.common.cancel"), role: .cancel) {}
                },
                message: { _ in Text(model.t("schedules.delete_body")) }
            )
        }
        .task(id: serverId) { await world.loadSchedules() }
    }

    @ViewBuilder
    private func content(_ world: WorldPages, _ palette: Palette) -> some View {
        let strings = model.strings
        let canManage = model.can(Permissions.SCHEDULES_MANAGE)
        let busy = world.busy
        SaidRow(said: world.said, palette: palette)
        if let problem = world.schedules.problem {
            ProblemCard(problem: problem, palette: palette) { await world.loadSchedules() }
        } else if let list = world.schedules.value {
            // Above the list, as the dashboard has it ("Add one above").
            if canManage {
                AddScheduleForm(world: world, tasks: list.tasks, palette: palette)
            }
            SectionTitle(text: model.t("schedules.list"), palette: palette)
            if list.schedules.isEmpty {
                EmptyCard(title: model.t("schedules.none"), hint: model.t("schedules.none_hint"), palette: palette)
            }
            ForEach(list.schedules) { schedule in
                CardBox(palette: palette) {
                    Text(verbatim: schedule.name)
                        .font(.headline)
                        .foregroundStyle(palette.textPrimary)
                    Hint(
                        text: Schedules.taskName(strings, schedule.task, tasks: list.tasks) + " · " + Schedules.whenText(strings, schedule),
                        palette: palette
                    )
                    Text(verbatim: model.t("schedules.col_next") + ": " + Schedules.next(strings, schedule))
                        .font(.footnote)
                        .foregroundStyle(palette.textPrimary)
                    Hint(text: model.t("schedules.col_result") + ": " + (schedule.lastResult ?? "—"), palette: palette)
                    if canManage {
                        Presses(presses: [
                            Press(title: model.t(schedule.enabled ? "schedules.turn_off" : "schedules.turn_on"), enabled: busy == nil) {
                                Task { await world.toggle(schedule, strings) }
                            },
                            Press(title: model.t("schedules.run_now"), enabled: busy == nil) {
                                Task { await world.runNow(schedule, strings) }
                            },
                            Press(title: model.t("schedules.delete"), danger: true, enabled: busy == nil) {
                                deleting = schedule
                            },
                        ], palette: palette)
                    }
                }
            }
        } else {
            ProgressView().frame(maxWidth: .infinity)
        }
    }
}

/// Name, task, how often and when; Create sends it as the dashboard does.
private struct AddScheduleForm: View {
    let world: WorldPages
    let tasks: [String]
    let palette: Palette

    @Environment(AppModel.self) private var model
    @State private var name = ""
    @State private var task = ""
    @State private var kind = Schedules.KINDS[0]
    @State private var expr = ""

    var body: some View {
        let adding = world.busy == "add"
        let chosen = tasks.contains(task) ? task : (tasks.first ?? "")
        VStack(alignment: .leading, spacing: 12) {
            SectionTitle(text: model.t("schedules.add"), palette: palette)
            CardBox(palette: palette) {
                TextField(model.t("schedules.name_placeholder"), text: $name)
                    .textFieldStyle(.roundedBorder)
                    .accessibilityLabel(model.t("schedules.name"))
                    .onChange(of: name) {
                        if name.count > Schedules.NAME_LENGTH { name = String(name.prefix(Schedules.NAME_LENGTH)) }
                    }
                Picker(model.t("schedules.task"), selection: Binding(get: { chosen }, set: { task = $0 })) {
                    ForEach(tasks, id: \.self) { option in
                        Text(Schedules.taskName(model.strings, option, tasks: tasks)).tag(option)
                    }
                }
                .pickerStyle(.menu)
                Picker(model.t("schedules.repeat"), selection: $kind) {
                    ForEach(Schedules.KINDS, id: \.self) { option in
                        Text(model.t(Schedules.kindKey(option))).tag(option)
                    }
                }
                .pickerStyle(.segmented)
                TextField(model.t("schedules.when_placeholder"), text: $expr)
                    .textFieldStyle(.roundedBorder)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .accessibilityLabel(model.t("schedules.when"))
                    .onChange(of: expr) {
                        if expr.count > Schedules.EXPR_LENGTH { expr = String(expr.prefix(Schedules.EXPR_LENGTH)) }
                    }
                Hint(text: model.t("schedules.when_hint"), palette: palette)
                Button(model.t(adding ? "action.saving" : "schedules.create")) {
                    let strings = model.strings
                    let sent = (name, chosen, kind, expr)
                    Task {
                        if await world.addSchedule(name: sent.0, task: sent.1, kind: sent.2, expr: sent.3, strings) {
                            name = ""
                            expr = ""
                        }
                    }
                }
                .buttonStyle(.borderedProminent)
                .tint(palette.accent)
                .disabled(adding || world.busy != nil || chosen.isEmpty || expr.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
    }
}
