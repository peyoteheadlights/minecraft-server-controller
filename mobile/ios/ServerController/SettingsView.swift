import Core
import SwiftUI

/// Appearance, Unlock, lock-screen alerts, This PC, and Help & About.
struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @State private var confirmSignOut = false
    @State private var confirmForget = false
    @State private var working = false

    var body: some View {
        NavigationStack {
            Form {
                appearance
                unlock
                lockScreenAlerts
                thisPC
                Section {
                    NavigationLink(model.t("mobile.settings.help")) {
                        HelpAboutView()
                    }
                    .frame(minHeight: 44)
                }
            }
            .navigationTitle(model.t("mobile.settings.title"))
            .alert(model.t("mobile.settings.sign_out_title"), isPresented: $confirmSignOut) {
                Button(model.t("mobile.settings.sign_out"), role: .destructive) {
                    working = true
                    Task {
                        await model.signOut()
                        working = false
                    }
                }
                Button(model.t("mobile.common.cancel"), role: .cancel) {}
            } message: {
                Text(model.t("mobile.settings.sign_out_body"))
            }
            .alert(model.t("mobile.settings.forget_pc_title"), isPresented: $confirmForget) {
                Button(model.t("mobile.settings.forget_pc"), role: .destructive) {
                    working = true
                    Task {
                        await model.forgetPC()
                        working = false
                    }
                }
                Button(model.t("mobile.common.cancel"), role: .cancel) {}
            } message: {
                Text(model.t("mobile.settings.forget_pc_body"))
            }
        }
    }

    private var appearance: some View {
        Section(model.t("mobile.settings.appearance")) {
            Picker(model.t("mobile.settings.theme"), selection: Binding(
                get: { model.theme },
                set: { model.setTheme($0) }
            )) {
                ForEach(ThemeChoice.allCases) { choice in
                    Text(model.t(choice.labelKey)).tag(choice)
                }
            }
            .frame(minHeight: 44)
            Picker(model.t("mobile.settings.words"), selection: Binding(
                get: { model.technical },
                set: { model.setTechnical($0) }
            )) {
                Text(model.t("mode.simple")).tag(false)
                Text(model.t("mode.technical")).tag(true)
            }
            .frame(minHeight: 44)
        }
    }

    private var unlock: some View {
        Section {
            Toggle(model.t("mobile.settings.unlock_on"), isOn: Binding(
                get: { model.unlockEnabled },
                set: { model.setUnlock($0) }
            ))
            .frame(minHeight: 44)
        } header: {
            Text(model.t("mobile.settings.unlock"))
        } footer: {
            if AppModel.deviceLockAvailable() {
                Text(model.t("mobile.settings.unlock_hint"))
            } else {
                Text(model.t("mobile.lock.unavailable"))
            }
        }
    }

    private var lockScreenAlerts: some View {
        Section {
            Text(model.t("mobile.settings.lock_alerts_ios_later"))
                .foregroundStyle(.secondary)
        } header: {
            Text(model.t("mobile.settings.lock_alerts"))
        }
    }

    private var thisPC: some View {
        Section {
            if let pairing = model.pairing {
                LabeledContent(model.t("mobile.settings.pc_address"), value: "\(pairing.host):\(pairing.port)")
                    .textSelection(.enabled)
                if model.technical, let fingerprint = pairing.fingerprint {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(model.t("mobile.settings.pc_fingerprint"))
                        Text(formatFingerprint(fingerprint))
                            .font(.system(.caption, design: .monospaced))
                            .foregroundStyle(.secondary)
                            .textSelection(.enabled)
                    }
                    .accessibilityElement(children: .combine)
                }
            }
            LabeledContent(model.t("mobile.settings.pc_version"), value: model.agentVersion ?? model.t("value.unknown"))
            LabeledContent(model.t("mobile.settings.signed_in_as"), value: model.me?.user ?? model.t("value.unknown"))
            Button(model.t("mobile.settings.sign_out")) {
                confirmSignOut = true
            }
            .frame(minHeight: 44)
            .disabled(working)
            Button(model.t("mobile.settings.forget_pc"), role: .destructive) {
                confirmForget = true
            }
            .frame(minHeight: 44)
            .disabled(working)
        } header: {
            Text(model.t("mobile.settings.this_pc"))
        }
    }
}
