import Core
import SwiftUI
import UIKit

/// One of a server's screens: in the server's color, with its title, and
/// the live feed carrying this server's console and chat while it is open.
struct ServerFrame<Content: View>: View {
    let serverId: String
    let title: String
    @ViewBuilder let content: (Palette) -> Content

    @Environment(AppModel.self) private var model
    @Environment(\.colorScheme) private var colorScheme

    var body: some View {
        let palette = model.serverPalette(model.servers.first(where: { $0.id == serverId })?.color, colorScheme)
        content(palette)
            .scrollContentBackground(.hidden)
            .background(palette.sheet.ignoresSafeArea())
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(palette.sheet, for: .navigationBar)
            .onAppear { model.watch(serverId) }
            .onDisappear { model.unwatch(serverId) }
    }
}

/// A rounded card, like the dashboard's.
struct CardBox<Content: View>: View {
    let palette: Palette
    @ViewBuilder let content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            content()
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(palette.surface, in: RoundedRectangle(cornerRadius: 14))
        .overlay(
            RoundedRectangle(cornerRadius: 14)
                .strokeBorder(palette.accentEdge.opacity(0.35), lineWidth: 1)
        )
    }
}

/// A problem said plainly, in the agent's words where it gave some.
struct ProblemRow: View {
    let text: String
    let palette: Palette

    var body: some View {
        Label(text, systemImage: "exclamationmark.triangle")
            .foregroundStyle(palette.tone(.warning))
    }
}

/// An address with its Copy button.
struct CopyRow: View {
    let text: String
    var note: String? = nil
    let palette: Palette

    @Environment(AppModel.self) private var model
    @State private var copied = false

    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            VStack(alignment: .leading, spacing: 2) {
                Text(verbatim: text)
                    .font(.system(.body, design: .monospaced))
                    .foregroundStyle(palette.textPrimary)
                    .textSelection(.enabled)
                if let note = note {
                    Text(note)
                        .font(.footnote)
                        .foregroundStyle(palette.textSecondary)
                }
            }
            Spacer()
            Button {
                UIPasteboard.general.string = text
                copied = true
            } label: {
                Label(model.t(copied ? "console.copied" : "join.copy"), systemImage: copied ? "checkmark" : "doc.on.doc")
                    .labelStyle(.titleAndIcon)
            }
            .buttonStyle(.borderless)
            .accessibilityLabel(model.t("join.copy_label", ["text": text]))
        }
        .frame(minHeight: 44)
    }
}

/// A read that failed, with Retry.
struct ProblemCard: View {
    let problem: AgentError
    let palette: Palette
    let retry: () async -> Void

    @Environment(AppModel.self) private var model

    var body: some View {
        CardBox(palette: palette) {
            Text(problem.message(model.strings))
                .foregroundStyle(palette.danger)
            Button(model.t("mobile.common.retry")) {
                Task { await retry() }
            }
            .buttonStyle(.borderless)
        }
    }
}

/// A plain card saying there is nothing here yet, with a hint.
struct EmptyCard: View {
    let title: String
    var hint: String? = nil
    let palette: Palette

    var body: some View {
        CardBox(palette: palette) {
            Text(title)
                .foregroundStyle(palette.textPrimary)
            if let hint = hint {
                Text(hint)
                    .font(.footnote)
                    .foregroundStyle(palette.textSecondary)
            }
        }
    }
}

/// The bar under a screen's list: a typing box, its button and notes.
struct InputBar<Field: View>: View {
    let palette: Palette
    var problem: String? = nil
    var notes: [String] = []
    @ViewBuilder let field: () -> Field

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if let problem = problem {
                Text(problem)
                    .font(.footnote)
                    .foregroundStyle(palette.danger)
            }
            HStack(spacing: 8) {
                field()
            }
            ForEach(notes, id: \.self) { note in
                Text(note)
                    .font(.footnote)
                    .foregroundStyle(palette.textSecondary)
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(palette.surface)
    }
}
