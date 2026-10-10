import Core
import Foundation
import LocalAuthentication
import Observation
import SwiftUI
import UIKit
import WidgetKit

enum AppTab: Hashable {
    case servers
    case notifications
    case settings
}

/// Everything the screens share: which PC, whether the app is signed in and
/// unlocked, the servers and alerts last read, and the wording and theme.
/// The sign-in token is never held here; it is read from the Keychain for
/// each request.
@MainActor
@Observable
final class AppModel {
    // Fixed for the app's life.
    let strings: Strings
    let store = SharedStore()
    let requestLog = RequestLog()
    @ObservationIgnored private(set) var client: AgentClient? = nil
    @ObservationIgnored private var liveTask: Task<Void, Never>? = nil
    @ObservationIgnored private var refreshTask: Task<Void, Never>? = nil
    @ObservationIgnored private var backgroundedAt: Date? = nil

    // Settings.
    var technical: Bool
    var theme: ThemeChoice
    var unlockEnabled: Bool

    // The PC and the sign-in.
    var pairing: Pairing?
    var signedIn: Bool
    var locked: Bool
    var signInNotice: String? = nil
    var me: Me? = nil
    var agentVersion: String?
    var lastProblem: String? = nil

    // What the PC last said.
    var servers: [ServerRow] = []
    var serversLoaded = false
    var serversFresh = false
    var serversCheckedAt: Double? = nil
    var serversProblem: AgentError? = nil
    var alertState: AlertState
    var live = false
    /// Goes up whenever the live feed says something changed, so open
    /// screens read again.
    var liveTick = 0

    // Navigation.
    var tab: AppTab = .servers
    var serversPath: [String] = []

    init() {
        strings = Strings(Bundled.english)
        let saved = SharedStore()
        technical = saved.technical
        theme = ThemeChoice(rawValue: saved.theme) ?? .system
        unlockEnabled = saved.unlockEnabled
        pairing = saved.pairing
        alertState = saved.alertState
        agentVersion = saved.agentVersion
        let hasToken = TokenStore.read() != nil
        signedIn = saved.pairing != nil && hasToken
        locked = false
        strings.technical = technical
        if let pairing = pairing {
            client = makeClient(pairing)
        }
        locked = signedIn && unlockEnabled && AppModel.deviceLockAvailable()
    }

    // MARK: - Words

    /// The words for `key` in the chosen wording.
    func t(_ key: String, _ values: [String: CustomStringConvertible] = [:]) -> String {
        _ = technical
        return strings.t(key, values)
    }

    func setTechnical(_ on: Bool) {
        technical = on
        strings.technical = on
        store.technical = on
        WidgetCenter.shared.reloadAllTimelines()
    }

    func setTheme(_ choice: ThemeChoice) {
        theme = choice
        store.theme = choice.rawValue
    }

    func setUnlock(_ on: Bool) {
        unlockEnabled = on
        store.unlockEnabled = on
    }

    func basePalette(_ scheme: ColorScheme) -> Palette {
        Palette.base(Bundled.themes, theme.resolvedName(scheme))
    }

    func serverPalette(_ color: String?, _ scheme: ColorScheme) -> Palette {
        Palette.server(color, Bundled.themes, theme.resolvedName(scheme))
    }

    /// The words for an alert's kind, when they need nothing filled in.
    func feedWords(_ event: String) -> String? {
        guard let key = Bundled.feed[event] else { return nil }
        let words = t(key)
        return words.contains("{") ? nil : words
    }

    // MARK: - Pairing and signing in

    private func makeClient(_ pairing: Pairing) -> AgentClient {
        AgentClient(
            pairing: pairing,
            token: { TokenStore.read() },
            onSignedOut: { [weak self] in
                // A 401: forget the token at once, in the app and the widget.
                TokenStore.delete()
                Task { @MainActor in
                    self?.signedOutByPC()
                }
            },
            log: requestLog
        )
    }

    func makePairer() -> Pairer {
        Pairer(range: Bundled.apiRange, log: requestLog)
    }

    /// Checking found the agent: remember it and ask for the sign-in.
    func paired(_ pairing: Pairing) {
        store.pairing = pairing
        store.alertState = AlertState()
        alertState = AlertState()
        self.pairing = pairing
        client = makeClient(pairing)
        signedIn = false
        signInNotice = nil
        lastProblem = nil
    }

    /// "Server Controller on iPhone": how the PC's Security page lists this phone.
    var deviceLabel: String {
        t("mobile.signin.device", ["app": t("mobile.app_name"), "model": UIDevice.current.model])
    }

    func signIn(username: String, password: String) async throws {
        guard let client = client else { throw AgentError.unreachable }
        let result = try await client.login(username: username, password: password, device: deviceLabel)
        TokenStore.save(result.token)
        locked = false
        signInNotice = nil
        // The main screen appears and reads everything (afterSignIn).
        signedIn = true
    }

    /// Opening the app signed in, or just signed in: read who this is, the
    /// servers, the alerts, and follow the live feed.
    func afterSignIn() async {
        await loadAccount()
        await refreshServers()
        await syncAlerts()
        startLive()
    }

    func loadAccount() async {
        guard let client = client, signedIn else { return }
        do {
            me = try await client.me()
        } catch let problem as AgentError {
            note(problem)
        } catch {}
        if let version = try? await client.version() {
            agentVersion = version.version
            store.agentVersion = version.version
        }
    }

    /// Sign out here and on the PC.
    func signOut() async {
        stopLive()
        if let client = client, signedIn {
            await client.logout()
        }
        TokenStore.delete()
        clearSignedIn()
    }

    /// Forget this PC: sign out, then forget the address, the pinned
    /// certificate and the alerts.
    func forgetPC() async {
        stopLive()
        if let client = client, signedIn {
            await client.logout()
        }
        TokenStore.delete()
        store.forgetPC()
        clearSignedIn()
        pairing = nil
        client = nil
        alertState = AlertState()
        agentVersion = nil
        WidgetCenter.shared.reloadAllTimelines()
    }

    /// The PC ended the sign-in (signed out on its Security page, a helper
    /// removed, expired).
    func signedOutByPC() {
        guard signedIn else { return }
        stopLive()
        TokenStore.delete()
        clearSignedIn()
        lastProblem = AgentError.signedOut.key
        signInNotice = AgentError.signedOut.message(strings)
    }

    private func clearSignedIn() {
        signedIn = false
        locked = false
        me = nil
        servers = []
        serversLoaded = false
        serversFresh = false
        serversCheckedAt = nil
        serversProblem = nil
        serversPath = []
        tab = .servers
        live = false
    }

    private func note(_ problem: AgentError) {
        lastProblem = problem.key
    }

    // MARK: - Servers and alerts

    func refreshServers() async {
        guard let client = client, signedIn else { return }
        let now = Date().timeIntervalSince1970
        do {
            let list = try await client.servers()
            servers = list.servers
            serversFresh = true
            serversCheckedAt = now
            serversProblem = nil
            store.widgetSnapshot = WidgetSnapshot.read(list, now: now)
        } catch let problem as AgentError {
            // Never show the last reading as current.
            serversFresh = false
            serversProblem = problem
            note(problem)
            store.widgetSnapshot = WidgetSnapshot.failed(store.widgetSnapshot, problem: problem, now: now)
        } catch {
            return
        }
        serversLoaded = true
        WidgetCenter.shared.reloadAllTimelines()
    }

    func syncAlerts() async {
        guard let client = client, signedIn else { return }
        let sync = AlertSync { after, limit in
            try await client.alerts(after: after, limit: limit)
        }
        do {
            let next = try await sync.catchUp(alertState)
            alertState = next
            store.alertState = next
        } catch let problem as AgentError {
            note(problem)
        } catch {}
    }

    func markAllRead() {
        alertState = alertState.markAllRead()
        store.alertState = alertState
    }

    func serverName(_ id: String?) -> String {
        guard let id = id else { return t("mobile.alerts.pc") }
        return servers.first(where: { $0.id == id })?.name ?? id
    }

    var canControl: Bool {
        me?.can(Permissions.SERVER_CONTROL) ?? false
    }

    /// Start, stop or restart, and the words for what happened.
    func perform(_ action: String, serverId: String) async -> String {
        guard let client = client else { return AgentError.unreachable.message(strings) }
        do {
            _ = try await client.serverAction(serverId: serverId, action: action)
            scheduleRefresh()
            switch action {
            case "start": return t("mobile.server.done_start")
            case "stop": return t("mobile.server.done_stop")
            default: return t("mobile.server.done_restart")
            }
        } catch let problem as AgentError {
            note(problem)
            return problem.message(strings)
        } catch {
            return AgentError.unreachable.message(strings)
        }
    }

    // MARK: - Live feed

    func startLive() {
        guard let client = client, signedIn, !locked else { return }
        liveTask?.cancel()
        let feed = LiveFeed(client: client, token: { TokenStore.read() })
        liveTask = Task { [weak self] in
            for await signal in feed.connect(serverId: nil) {
                guard let self = self else { return }
                switch signal {
                case .ready:
                    self.live = true
                case .changed:
                    self.scheduleRefresh()
                case .closed:
                    self.live = false
                    // Ask who this is: a 401 there signs the app out.
                    await self.loadAccount()
                case .lost(let problem):
                    self.live = false
                    self.note(problem)
                case .signedOut:
                    self.live = false
                    self.signedOutByPC()
                }
            }
            self?.live = false
        }
    }

    func stopLive() {
        liveTask?.cancel()
        liveTask = nil
        live = false
    }

    /// Several events in a row (a server starting says a lot) read once.
    func scheduleRefresh() {
        refreshTask?.cancel()
        refreshTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 1_000_000_000)
            if Task.isCancelled { return }
            guard let self = self else { return }
            await self.refreshServers()
            await self.syncAlerts()
            self.liveTick += 1
        }
    }

    // MARK: - Unlock and the app switcher

    static func deviceLockAvailable() -> Bool {
        var error: NSError?
        return LAContext().canEvaluatePolicy(.deviceOwnerAuthentication, error: &error)
    }

    func unlock() async {
        let context = LAContext()
        var error: NSError?
        guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &error) else {
            // No screen lock on the phone: the app can't lock itself.
            locked = false
            return
        }
        do {
            let ok = try await context.evaluatePolicy(.deviceOwnerAuthentication, localizedReason: t("mobile.lock.reason"))
            if ok {
                // The main screen reads everything again (afterSignIn).
                locked = false
            }
        } catch {
            // Cancelled or failed: stay locked; the Unlock button asks again.
        }
    }

    func scenePhaseChanged(_ phase: ScenePhase) {
        switch phase {
        case .background:
            backgroundedAt = Date()
            stopLive()
        case .active:
            if let at = backgroundedAt, signedIn, unlockEnabled, Date().timeIntervalSince(at) > 60, AppModel.deviceLockAvailable() {
                locked = true
            }
            let wasAway = backgroundedAt != nil
            backgroundedAt = nil
            if wasAway && signedIn && !locked {
                Task { await self.afterSignIn() }
            }
        default:
            break
        }
    }

    // MARK: - Links

    func open(_ url: URL) {
        guard url.scheme?.lowercased() == DeepLink.scheme else { return }
        tab = .servers
        if let id = DeepLink.serverId(from: url) {
            serversPath = [id]
        } else {
            serversPath = []
        }
    }

    func openServer(_ id: String) {
        tab = .servers
        serversPath = [id]
    }

    // MARK: - Diagnostics

    func diagnosticsText() -> String {
        let facts = Diagnostics.Facts(
            appVersion: Bundled.appVersion,
            platform: "iOS",
            osVersion: UIDevice.current.systemVersion,
            device: UIDevice.current.model,
            agentVersion: agentVersion,
            agentApi: pairing?.apiVersion,
            paired: pairing != nil,
            pinned: pairing?.fingerprint != nil,
            signedIn: signedIn,
            lockScreenAlerts: nil,
            lastProblem: lastProblem
        )
        return Diagnostics.text(facts, log: requestLog.recent())
    }
}
