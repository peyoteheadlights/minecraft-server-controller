import Core
import SwiftUI

@main
struct ServerControllerApp: App {
    @State private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .preferredColorScheme(model.theme.colorScheme)
        }
    }
}

/// Pairing, then signing in, then the app; locked behind the phone's own
/// unlock, and covered while the app switcher takes its picture.
struct RootView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.colorScheme) private var colorScheme

    var body: some View {
        ZStack {
            content
            if model.locked {
                LockView()
                    .zIndex(1)
            }
            if scenePhase != .active {
                PrivacyCover()
                    .zIndex(2)
            }
        }
        .tint(model.basePalette(colorScheme).accentInk)
        .onChange(of: scenePhase) { _, phase in
            model.scenePhaseChanged(phase)
        }
        .onOpenURL { url in
            model.open(url)
        }
    }

    @ViewBuilder
    private var content: some View {
        if model.pairing == nil {
            PairingFlowView()
        } else if !model.signedIn {
            SignInView()
        } else {
            MainTabView()
        }
    }
}

/// What the app switcher shows instead of the screen.
struct PrivacyCover: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        ZStack {
            Color(uiColor: .systemBackground)
                .ignoresSafeArea()
            VStack(spacing: 12) {
                Image(systemName: "server.rack")
                    .font(.system(size: 48))
                    .foregroundStyle(.secondary)
                    .accessibilityHidden(true)
                Text(model.t("mobile.app_name"))
                    .font(.title2.weight(.semibold))
            }
        }
    }
}

/// Asks for Face ID, Touch ID or the passcode before anything is shown.
struct LockView: View {
    @Environment(AppModel.self) private var model
    @State private var asking = false

    var body: some View {
        ZStack {
            Color(uiColor: .systemBackground)
                .ignoresSafeArea()
            VStack(spacing: 20) {
                Image(systemName: "lock.fill")
                    .font(.system(size: 44))
                    .foregroundStyle(.secondary)
                    .accessibilityHidden(true)
                Text(model.t("mobile.lock.title"))
                    .font(.title2.weight(.semibold))
                    .multilineTextAlignment(.center)
                Button {
                    ask()
                } label: {
                    Text(model.t("mobile.lock.unlock"))
                        .frame(maxWidth: .infinity, minHeight: 44)
                }
                .buttonStyle(.borderedProminent)
                .disabled(asking)
                .padding(.horizontal, 32)
            }
            .padding()
        }
        .task {
            ask()
        }
    }

    private func ask() {
        guard !asking else { return }
        asking = true
        Task {
            await model.unlock()
            asking = false
        }
    }
}
