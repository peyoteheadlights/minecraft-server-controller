import Core
import SwiftUI

/// Appearance, Unlock, lock-screen alerts, This PC, and Help & About.
struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @State private var confirmSignOut = false
    @State private var confirmForget = false
    @State private var working = false
    @State private var scanning = false
    /// A scanned code for another PC, waiting for "Switch".
    @State private var otherPc: Pairing?
    @State private var rescanProblem: String?

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
            .alert(
                model.t("mobile.rescan.other_title"),
                isPresented: Binding(get: { otherPc != nil }, set: { if !$0 { otherPc = nil } }),
                presenting: otherPc
            ) { next in
                Button(model.t("mobile.rescan.switch"), role: .destructive) {
                    check(next)
                }
                Button(model.t("mobile.common.cancel"), role: .cancel) {}
            } message: { next in
                Text(model.t("mobile.rescan.other_body", [
                    "address": "\(next.host):\(next.port)",
                    "current": model.pairing.map { "\($0.host):\($0.port)" } ?? model.t("value.unknown"),
                ]))
            }
            .sheet(isPresented: $scanning) {
                ScannerSheet { next in
                    scanning = false
                    scanned(next)
                }
            }
        }
    }

    // MARK: - Scan the code again

    /// The same address and port keeps the sign-in (a renewed certificate);
    /// another PC is asked about first, and signs this phone out.
    private func scanned(_ next: Pairing) {
        if let current = model.pairing, !current.samePc(next) {
            otherPc = next
        } else {
            check(next)
        }
    }

    private func check(_ next: Pairing) {
        working = true
        rescanProblem = nil
        let pairer = model.makePairer()
        Task {
            let result = await pairer.check(next)
            switch result {
            case .paired(let pairing, _):
                await model.rescanned(pairing)
            case .confirmFingerprint:
                // A scanned code always names the certificate; this one didn't match.
                rescanProblem = AgentError.certificateNotTrusted(presented: nil).message(model.strings)
            case .refused(let problem):
                rescanProblem = problem.message(model.strings)
            case .incompatible(let fit):
                rescanProblem = model.t(fit.key ?? "mobile.pair.too_new")
            }
            working = false
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
            Button {
                scanning = true
            } label: {
                VStack(alignment: .leading, spacing: 2) {
                    Text(model.t("mobile.settings.rescan"))
                    Text(model.t("mobile.settings.rescan_hint"))
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
            .frame(minHeight: 44)
            .disabled(working)
            if working {
                ProgressView()
            }
            if let problem = rescanProblem {
                Label(problem, systemImage: "exclamationmark.triangle")
                    .foregroundStyle(.red)
            }
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
