import Core
import SwiftUI
import UIKit

/// "Bring a world in" (a zip from the phone, a folder on the PC or one of
/// single-player's saves) and "Take the world home" (world.js). Each card
/// shows only to someone allowed to use it (mirrors WorldImportCards.kt).
struct WorldImportCards: View {
    let world: WorldPages
    let timeline: WorldTimeline?
    let bedrock: Bool
    let palette: Palette
    let pickZip: () -> Void
    let pickFolder: () -> Void
    let stop: () -> Void
    let now: Double

    @Environment(AppModel.self) private var model

    var body: some View {
        let strings = model.strings
        if WorldImport.canImport(model.me), let timeline = timeline {
            let blocked = WorldImport.blocked(strings, timeline)
            let free = blocked == nil && world.busy == nil
            SectionTitle(text: model.t("import.title"), palette: palette)
            CardBox(palette: palette) {
                Text(model.t(bedrock ? "import.lead_bedrock" : "import.lead"))
                    .foregroundStyle(palette.textPrimary)
                if let why = blocked {
                    Label(why, systemImage: "exclamationmark.triangle")
                        .foregroundStyle(palette.tone(.warning))
                }
                if let progress = world.sending {
                    HStack(spacing: 8) {
                        ProgressView().controlSize(.small)
                        Hint(text: progressText(model, "mobile.import.sending", progress), palette: palette)
                    }
                } else if world.busy == "import" {
                    Hint(text: model.t("import.reading"), palette: palette)
                }
                Presses(presses: importPresses(timeline, free), palette: palette)
            }
            // Single-player's saves folder holds Java worlds; Bedrock keeps its own.
            let saves = world.saves?.worlds ?? []
            if !bedrock && !saves.isEmpty {
                SectionTitle(text: model.t("import.from_saves"), palette: palette)
                CardBox(palette: palette) {
                    ForEach(saves, id: \.path) { save in
                        Text(verbatim: save.folder)
                            .foregroundStyle(palette.textPrimary)
                        Hint(text: Display.ago(strings, save.modified, now: now), palette: palette)
                        Presses(presses: [
                            Press(title: model.t("import.use"), enabled: free) {
                                Task { await world.pickWorldFolder(save.path, strings) }
                            },
                        ], palette: palette)
                    }
                }
            }
        }
        if WorldImport.canDownload(model.me) {
            SectionTitle(text: model.t("download.title"), palette: palette)
            CardBox(palette: palette) {
                Text(model.t(bedrock ? "download.lead_bedrock" : "download.lead"))
                    .foregroundStyle(palette.textPrimary)
                if let progress = world.downloading {
                    HStack(spacing: 8) {
                        ProgressView().controlSize(.small)
                        Hint(text: progressText(model, "mobile.backups.downloading", progress), palette: palette)
                    }
                }
                let packing = world.busy == "take_home" && world.downloading == nil
                Presses(presses: [
                    Press(title: model.t(packing ? "download.packing" : "download.button"), enabled: world.busy == nil) {
                        Task { await world.takeHome(strings) }
                    },
                ], palette: palette)
            }
        }
    }

    private func importPresses(_ timeline: WorldTimeline, _ free: Bool) -> [Press] {
        if world.sending != nil {
            return [Press(title: model.t("action.cancel")) { world.cancelSending() }]
        }
        if timeline.serverRunning && model.canControl {
            return [Press(title: model.t("mobile.import.stop_ask"), danger: true, run: stop)]
        }
        var presses = [Press(title: model.t(bedrock ? "import.choose_mcworld" : "import.choose_zip"), enabled: free, run: pickZip)]
        if FolderPicker.allowed(model.me) {
            presses.append(Press(title: model.t("import.choose_folder"), enabled: free, run: pickFolder))
        }
        return presses
    }
}

/// "Sending w.zip… 40%": the name, then the share done or the bytes so far.
@MainActor
func progressText(_ model: AppModel, _ key: String, _ progress: Downloading) -> String {
    let share: String
    if let size = progress.size, size > 0 {
        share = "\(progress.done * 100 / size)%"
    } else {
        share = Display.bytes(model.strings, progress.done)
    }
    return model.t(key, ["name": progress.name]) + " " + share
}

/// The world read, shown before it replaces anything; Cancel forgets it on the agent.
struct WorldReadSheet: View {
    let read: WorldRead
    let replace: () -> Void

    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        let strings = model.strings
        List {
            Section {
                ForEach(WorldImport.facts(strings, read.world), id: \.0) { fact in
                    LabeledContent(fact.0) { Text(verbatim: fact.1) }
                }
            }
            let lines = WorldImport.lines(strings, read)
            if !lines.isEmpty {
                Section {
                    ForEach(lines, id: \.text) { line in
                        Text(verbatim: line.text).foregroundStyle(tone(line.tone))
                    }
                }
            }
            Section {
                Text(model.t("import.confirm_body"))
                Button(model.t("import.confirm_action"), role: .destructive, action: replace)
                .disabled(!WorldImport.canUse(read))
            }
        }
        .navigationTitle(model.t("import.confirm_title", ["name": WorldImport.title(read)]))
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button(model.t("mobile.common.cancel")) { dismiss() }
            }
        }
    }

    private func tone(_ tone: Tone) -> Color {
        switch tone {
        case .danger: return .red
        case .warning: return .orange
        default: return .primary
        }
    }
}

/// The phone's share menu for a file: save it to Files, or send it to another app.
struct ShareSheet: UIViewControllerRepresentable {
    let file: URL

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: [file], applicationActivities: nil)
    }

    func updateUIViewController(_ controller: UIActivityViewController, context: Context) {}
}
