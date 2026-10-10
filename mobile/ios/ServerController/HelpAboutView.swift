import Core
import SafariServices
import SwiftUI
import UIKit

/// Help topics, what's new, privacy, licenses, reporting a problem, and the
/// versions. The Mojang disclaimer is always on screen here.
struct HelpAboutView: View {
    private struct Topic: Identifiable {
        let title: String
        let body: String
        var id: String { title }
    }

    /// The same help text as the dashboard's, written for the phone.
    private let topics: [Topic] = [
        Topic(title: "mobile.help.pairing_title", body: "mobile.help.pairing_body"),
        Topic(title: "mobile.help.unreachable_title", body: "mobile.help.unreachable_body"),
        Topic(title: "mobile.help.certificate_title", body: "mobile.help.certificate_body"),
        Topic(title: "mobile.help.alerts_title", body: "mobile.help.alerts_body"),
        Topic(title: "mobile.help.signout_title", body: "mobile.help.signout_body"),
    ]

    @Environment(AppModel.self) private var model
    @State private var web: WebLink?
    @State private var copied = false

    var body: some View {
        List {
            Section(model.t("mobile.about.help")) {
                ForEach(topics) { topic in
                    NavigationLink(model.t(topic.title)) {
                        TextPage(title: model.t(topic.title), text: model.t(topic.body))
                    }
                    .frame(minHeight: 44)
                }
            }
            Section {
                webButton(model.t("mobile.about.whats_new"), Links.releases)
                NavigationLink(model.t("mobile.about.privacy")) {
                    PrivacyPage()
                }
                .frame(minHeight: 44)
                NavigationLink(model.t("mobile.about.licenses")) {
                    TextPage(title: model.t("mobile.about.licenses"), text: model.t("mobile.about.licenses_body"))
                }
                .frame(minHeight: 44)
            }
            Section {
                webButton(model.t("mobile.about.report"), Links.report)
                webButton(model.t("mobile.about.suggest"), Links.suggest)
            } header: {
                Text(model.t("mobile.about.forms_hint"))
                    .textCase(nil)
            }
            Section {
                Button(model.t("mobile.about.copy_diagnostics")) {
                    UIPasteboard.general.string = model.diagnosticsText()
                    copied = true
                    UIAccessibility.post(notification: .announcement, argument: model.t("mobile.about.copied"))
                }
                .frame(minHeight: 44)
                if copied {
                    Text(model.t("mobile.about.copied"))
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
            Section {
                Text(model.t("mobile.about.version", ["version": Bundled.appVersion]))
                webButton(model.t("mobile.about.source"), Links.repository)
                Text(model.t("mobile.about.free"))
                    .foregroundStyle(.secondary)
            }
        }
        .navigationTitle(model.t("mobile.about.title"))
        .safeAreaInset(edge: .bottom) {
            Text(model.t("mobile.about.disclaimer"))
                .font(.caption2.weight(.semibold))
                .multilineTextAlignment(.center)
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity)
                .padding(.horizontal, 16)
                .padding(.vertical, 10)
                .background(.bar)
        }
        .sheet(item: $web) { page in
            SafariView(url: page.url)
                .ignoresSafeArea()
        }
    }

    private func webButton(_ title: String, _ address: String) -> some View {
        Button {
            if let url = URL(string: address) {
                web = WebLink(url: url)
            }
        } label: {
            HStack {
                Text(title)
                Spacer()
                Image(systemName: "arrow.up.right.square")
                    .foregroundStyle(.secondary)
                    .accessibilityHidden(true)
            }
            .frame(minHeight: 44)
        }
    }
}

/// A help topic or other words on a page of their own.
struct TextPage: View {
    let title: String
    let text: String

    var body: some View {
        ScrollView {
            Text(text)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(20)
        }
        .navigationTitle(title)
        .navigationBarTitleDisplayMode(.inline)
    }
}

struct PrivacyPage: View {
    @Environment(AppModel.self) private var model
    @State private var web: WebLink?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                Text(model.t("mobile.privacy.body"))
                Button {
                    if let url = URL(string: Links.privacy) {
                        web = WebLink(url: url)
                    }
                } label: {
                    Text(model.t("mobile.privacy.full"))
                        .frame(minHeight: 44)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(20)
        }
        .navigationTitle(model.t("mobile.about.privacy"))
        .navigationBarTitleDisplayMode(.inline)
        .sheet(item: $web) { page in
            SafariView(url: page.url)
                .ignoresSafeArea()
        }
    }
}

/// A web address shown in Safari's in-app view.
struct WebLink: Identifiable {
    let url: URL
    var id: String { url.absoluteString }
}

/// Safari's in-app view: its own cookies and sign-ins, nothing from this app.
struct SafariView: UIViewControllerRepresentable {
    let url: URL

    func makeUIViewController(context: Context) -> SFSafariViewController {
        SFSafariViewController(url: url)
    }

    func updateUIViewController(_ controller: SFSafariViewController, context: Context) {}
}
