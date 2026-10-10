import Core
import SwiftUI

/// Connecting the phone to a PC: Tailscale first, then the pairing code (or
/// a typed address), checking it, and the error screens.
struct PairingFlowView: View {
    private enum Phase: Equatable {
        case welcome
        case connect
        case typing
        case checking
        case confirm(Pairing, String)
        case mismatch
        case failed(message: String, detail: String?, retry: Pairing?)
    }

    @Environment(AppModel.self) private var model
    @Environment(\.openURL) private var openURL
    @State private var phase: Phase = .welcome
    @State private var scanning = false
    @State private var address = ""
    @State private var addressProblem: String?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    content
                }
                .padding(20)
                .frame(maxWidth: 560, alignment: .leading)
                .frame(maxWidth: .infinity)
            }
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    if showsStartOver {
                        Button(model.t("mobile.pair.start_over")) {
                            phase = .welcome
                        }
                    }
                }
            }
        }
        .sheet(isPresented: $scanning) {
            ScannerSheet { pairing in
                scanning = false
                check(pairing)
            }
        }
    }

    private var title: String {
        switch phase {
        case .typing: return model.t("mobile.type.title")
        case .confirm: return model.t("mobile.pair.confirm_title")
        default: return model.t("mobile.app_name")
        }
    }

    private var showsStartOver: Bool {
        switch phase {
        case .welcome, .connect, .checking: return false
        default: return true
        }
    }

    @ViewBuilder
    private var content: some View {
        switch phase {
        case .welcome:
            welcome
        case .connect:
            connect
        case .typing:
            typing
        case .checking:
            checking
        case .confirm(let pairing, let fingerprint):
            confirm(pairing, fingerprint)
        case .mismatch:
            mismatch
        case .failed(let message, let detail, let retry):
            failed(message, detail, retry)
        }
    }

    // MARK: - Screens

    private var welcome: some View {
        VStack(alignment: .leading, spacing: 20) {
            Image(systemName: "server.rack")
                .font(.system(size: 48))
                .foregroundStyle(.tint)
                .accessibilityHidden(true)
            Text(model.t("mobile.welcome.title"))
                .font(.largeTitle.weight(.bold))
            Text(model.t("mobile.welcome.lead"))
                .font(.body)
            Text(model.t("mobile.welcome.need_tailscale"))
                .font(.body)
                .foregroundStyle(.secondary)
            Button {
                if let url = URL(string: Links.tailscaleAppStore) {
                    openURL(url)
                }
            } label: {
                Label(model.t("mobile.welcome.get_tailscale"), systemImage: "arrow.down.app")
                    .frame(maxWidth: .infinity, minHeight: 44)
            }
            .buttonStyle(.bordered)
            Button {
                phase = .connect
            } label: {
                Text(model.t("mobile.welcome.have_tailscale"))
                    .frame(maxWidth: .infinity, minHeight: 44)
            }
            .buttonStyle(.borderedProminent)
        }
    }

    private var connect: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text(model.t("mobile.welcome.scan"))
                .font(.title.weight(.bold))
            Text(model.t("mobile.welcome.scan_hint"))
                .font(.body)
                .foregroundStyle(.secondary)
            Button {
                scanning = true
            } label: {
                Label(model.t("mobile.welcome.scan"), systemImage: "qrcode.viewfinder")
                    .frame(maxWidth: .infinity, minHeight: 44)
            }
            .buttonStyle(.borderedProminent)
            Button {
                addressProblem = nil
                phase = .typing
            } label: {
                Text(model.t("mobile.welcome.type"))
                    .frame(maxWidth: .infinity, minHeight: 44)
            }
            .buttonStyle(.bordered)
        }
    }

    private var typing: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(model.t("mobile.type.label"))
                .font(.headline)
            TextField(model.t("mobile.type.label"), text: $address)
                .textFieldStyle(.roundedBorder)
                .keyboardType(.URL)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled(true)
                .submitLabel(.go)
                .onSubmit { submitAddress() }
                .frame(minHeight: 44)
            Text(model.t("mobile.type.hint"))
                .font(.footnote)
                .foregroundStyle(.secondary)
            if let problem = addressProblem {
                Text(problem)
                    .font(.callout)
                    .foregroundStyle(.red)
            }
            Button {
                submitAddress()
            } label: {
                Text(model.t("mobile.type.go"))
                    .frame(maxWidth: .infinity, minHeight: 44)
            }
            .buttonStyle(.borderedProminent)
            .disabled(address.trimmingCharacters(in: .whitespaces).isEmpty)
        }
    }

    private var checking: some View {
        VStack(spacing: 16) {
            ProgressView()
                .controlSize(.large)
            Text(model.t("mobile.pair.checking"))
                .font(.body)
        }
        .frame(maxWidth: .infinity, minHeight: 240)
        .accessibilityElement(children: .combine)
    }

    private func confirm(_ pairing: Pairing, _ fingerprint: String) -> some View {
        VStack(alignment: .leading, spacing: 20) {
            Text(model.t("mobile.pair.confirm_lead"))
                .font(.body)
            Text(pairing.host)
                .font(.headline)
            Text(formatFingerprint(fingerprint))
                .font(.system(.callout, design: .monospaced))
                .textSelection(.enabled)
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color(uiColor: .secondarySystemBackground), in: RoundedRectangle(cornerRadius: 10))
            Button {
                confirmed(pairing, fingerprint)
            } label: {
                Text(model.t("mobile.pair.confirm_yes"))
                    .frame(maxWidth: .infinity, minHeight: 44)
            }
            .buttonStyle(.borderedProminent)
            Button(role: .destructive) {
                phase = .mismatch
            } label: {
                Text(model.t("mobile.pair.confirm_no"))
                    .frame(maxWidth: .infinity, minHeight: 44)
            }
            .buttonStyle(.bordered)
        }
    }

    private var mismatch: some View {
        VStack(alignment: .leading, spacing: 20) {
            Image(systemName: "exclamationmark.shield")
                .font(.system(size: 44))
                .foregroundStyle(.red)
                .accessibilityHidden(true)
            Text(model.t("mobile.pair.confirm_no_body"))
                .font(.body)
            startOverButton
        }
    }

    private func failed(_ message: String, _ detail: String?, _ retry: Pairing?) -> some View {
        VStack(alignment: .leading, spacing: 20) {
            Image(systemName: "exclamationmark.triangle")
                .font(.system(size: 44))
                .foregroundStyle(.orange)
                .accessibilityHidden(true)
            Text(message)
                .font(.body)
            if let detail = detail {
                Text(detail)
                    .font(.system(.footnote, design: .monospaced))
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
            }
            if let retry = retry {
                Button {
                    check(retry)
                } label: {
                    Text(model.t("mobile.pair.try_again"))
                        .frame(maxWidth: .infinity, minHeight: 44)
                }
                .buttonStyle(.borderedProminent)
            }
            startOverButton
        }
    }

    private var startOverButton: some View {
        Button {
            phase = .welcome
        } label: {
            Text(model.t("mobile.pair.start_over"))
                .frame(maxWidth: .infinity, minHeight: 44)
        }
        .buttonStyle(.bordered)
    }

    // MARK: - Actions

    private func submitAddress() {
        do {
            let pairing = try PairingLink.parse(address)
            addressProblem = nil
            check(pairing)
        } catch let error as PairingParseError {
            addressProblem = model.t(error.problem.key)
        } catch {
            addressProblem = model.t(PairingProblem.notAnAddress.key)
        }
    }

    private func check(_ pairing: Pairing) {
        phase = .checking
        let pairer = model.makePairer()
        Task {
            let result = await pairer.check(pairing)
            handle(result, pairing)
        }
    }

    private func confirmed(_ pairing: Pairing, _ fingerprint: String) {
        phase = .checking
        let pairer = model.makePairer()
        Task {
            let result = await pairer.confirm(pairing, fingerprint: fingerprint)
            handle(result, pairing)
        }
    }

    private func handle(_ result: PairResult, _ tried: Pairing) {
        switch result {
        case .paired(let pairing, _):
            model.paired(pairing)
        case .confirmFingerprint(let pairing, let fingerprint):
            phase = .confirm(pairing, fingerprint)
        case .refused(let problem):
            var detail: String? = nil
            if model.technical, case .certificateChanged(let presented) = problem, let presented = presented {
                // Technical mode names the certificate the PC showed.
                detail = formatFingerprint(presented)
            }
            phase = .failed(message: problem.message(model.strings), detail: detail, retry: tried)
        case .incompatible(let fit):
            let key = fit.key ?? "mobile.pair.too_new"
            phase = .failed(message: model.t(key), detail: nil, retry: tried)
        }
    }
}

/// Addresses the app opens. Other companies' sites and GitHub open in
/// Safari's in-app view; the sign-in token never goes to any web page.
enum Links {
    static let tailscaleAppStore = "https://apps.apple.com/app/tailscale/id1470499037"
    static let repository = "https://github.com/peyoteheadlights/minecraft-server-controller"
    static let releases = "https://github.com/peyoteheadlights/minecraft-server-controller/releases"
    static let privacy = "https://github.com/peyoteheadlights/minecraft-server-controller/blob/main/PRIVACY.md"
    static let report = "https://github.com/peyoteheadlights/minecraft-server-controller/issues/new?template=bug_report.yml"
    static let suggest = "https://github.com/peyoteheadlights/minecraft-server-controller/issues/new?template=feature_request.yml"
}
