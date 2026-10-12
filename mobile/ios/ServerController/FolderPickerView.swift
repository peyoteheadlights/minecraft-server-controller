import Core
import SwiftUI

/// Choose a folder on the PC (panels/folders.js; mirrors FolderPicker.kt):
/// the drives and shortcuts first, then tap into folders and press "Use
/// this folder". Technical mode can type a path, which the agent checks the
/// same way. A refused folder keeps the last listing, with the agent's
/// reason above it. Owner only.
struct FolderPickerView: View {
    let title: String
    let start: String?
    let pick: (String) -> Void

    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var read = PageRead<FolderListing>()
    @State private var typed = ""

    var body: some View {
        NavigationStack {
            List {
                if let problem = read.problem {
                    Text(problem.message(model.strings)).foregroundStyle(.red)
                }
                if let listing = read.value {
                    Section(listing.path ?? model.t("folders.this_pc")) {
                        if let up = FolderPicker.up(listing) {
                            row(model.t("folders.up"), systemImage: "arrow.up") { await open(up) }
                        }
                        if FolderPicker.atTop(listing) {
                            ForEach(listing.drives, id: \.path) { drive in
                                row(FolderPicker.driveName(model.strings, drive), systemImage: "internaldrive") { await open(drive.path) }
                            }
                            ForEach(listing.shortcuts, id: \.path) { shortcut in
                                row(FolderPicker.shortcutName(model.strings, shortcut), systemImage: "star") { await open(shortcut.path) }
                            }
                        } else {
                            ForEach(listing.folders, id: \.path) { folder in
                                row(folder.name, systemImage: "folder", tag: folder.world ? model.t("folders.world") : nil) { await open(folder.path) }
                            }
                        }
                        ForEach(FolderPicker.notes(model.strings, listing), id: \.self) { note in
                            Text(note).font(.footnote).foregroundStyle(.secondary)
                        }
                    }
                } else if read.problem == nil {
                    ProgressView().frame(maxWidth: .infinity)
                }
                if FolderPicker.canType(technical: model.technical) {
                    Section(model.t("mobile.folders.type_path")) {
                        TextField(model.t("mobile.folders.type_path"), text: $typed)
                            .autocorrectionDisabled()
                            .textInputAutocapitalization(.never)
                        Button(model.t("mobile.folders.open")) {
                            let path = typed.trimmingCharacters(in: .whitespaces)
                            Task { await open(path) }
                        }
                        .disabled(typed.trimmingCharacters(in: .whitespaces).isEmpty)
                    }
                }
            }
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(model.t("mobile.common.cancel")) { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(model.t("folders.choose")) {
                        if let path = read.value?.path {
                            pick(path)
                            dismiss()
                        }
                    }
                    .disabled(read.value?.path == nil || read.loading)
                }
            }
        }
        .task { await open(start.flatMap { $0.isEmpty ? nil : $0 }) }
    }

    private func row(_ name: String, systemImage: String, tag: String? = nil, go: @escaping () async -> Void) -> some View {
        Button {
            Task { await go() }
        } label: {
            HStack {
                Label(name, systemImage: systemImage)
                Spacer()
                if let tag { Text(tag).font(.footnote).foregroundStyle(.secondary) }
            }
            .frame(minHeight: 44)
        }
    }

    private func open(_ path: String?) async {
        guard let client = model.client else { return }
        read.loading = true
        read.problem = nil
        do {
            read = PageRead(value: try await client.folders(path: path))
        } catch let problem as AgentError {
            model.note(problem)
            read.problem = problem
            read.loading = false
        } catch {
            read.loading = false
        }
    }
}
