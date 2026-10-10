import Core
import SwiftUI

/// What players say in the game, live, and a box to answer as Server
/// (for anyone allowed to chat, helpers included).
struct ChatView: View {
    let serverId: String

    @Environment(AppModel.self) private var model
    @State private var text = ""

    private let bottom = "bottom"

    private var pages: ServerPages { model.pages(serverId) }

    var body: some View {
        let pages = self.pages
        ServerFrame(serverId: serverId, title: model.t("page.chat")) { palette in
            messageList(palette)
                .safeAreaInset(edge: .bottom) { chatBox(palette) }
        }
        .task(id: serverId) { await pages.loadChat() }
    }

    private func messageList(_ palette: Palette) -> some View {
        let pages = self.pages
        let messages = pages.chat.value ?? []
        return ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 4) {
                    if let problem = pages.chat.problem {
                        ProblemCard(problem: problem, palette: palette) { await pages.loadChat() }
                    } else if pages.chat.value == nil {
                        ProgressView().frame(maxWidth: .infinity)
                    } else if messages.isEmpty {
                        EmptyCard(title: model.t("chat.empty"), hint: model.t("chat.empty_hint"), palette: palette)
                    }
                    ForEach(Array(messages.enumerated()), id: \.offset) { _, message in
                        line(message, palette)
                    }
                    Color.clear.frame(height: 1).id(bottom)
                }
                .padding(16)
            }
            .refreshable { await pages.loadChat() }
            .onAppear { proxy.scrollTo(bottom, anchor: .bottom) }
            .onChange(of: messages.last) {
                proxy.scrollTo(bottom, anchor: .bottom)
            }
        }
    }

    private func line(_ message: ChatMessage, _ palette: Palette) -> some View {
        let server = message.kind == "server"
        let who = server ? model.t("chat.server") : (message.name ?? "")
        let words = message.kind == "action" ? "• " + message.text : message.text
        return (
            Text(verbatim: Display.clock(message.ts) + "  ").foregroundStyle(palette.textSecondary)
                + Text(verbatim: who).fontWeight(.semibold).foregroundStyle(server ? palette.accentInk : palette.textPrimary)
                + Text(verbatim: "  " + words).foregroundStyle(palette.textPrimary)
        )
        .textSelection(.enabled)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder
    private func chatBox(_ palette: Palette) -> some View {
        let pages = self.pages
        if model.can(Permissions.CHAT_SEND) {
            let busy = pages.chatSending
            let notes = (pages.chatRunning == false ? [model.t("chat.offline")] : []) + [model.t("chat.hint")]
            InputBar(palette: palette, problem: pages.chatProblem, notes: notes) {
                TextField(model.t("chat.placeholder"), text: $text)
                    .textFieldStyle(.roundedBorder)
                    .submitLabel(.send)
                    .accessibilityLabel(model.t("chat.input_label"))
                    .onSubmit { send() }
                    .onChange(of: text) {
                        if text.count > ChatBuffer.MAX_LENGTH {
                            text = String(text.prefix(ChatBuffer.MAX_LENGTH))
                        }
                    }
                Button(model.t("chat.send")) { send() }
                    .buttonStyle(.borderedProminent)
                    .disabled(busy || text.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
    }

    private func send() {
        let pages = self.pages
        guard !pages.chatSending else { return }
        let typed = text
        Task {
            if await pages.sendChat(typed, model.strings) { text = "" }
        }
    }
}
