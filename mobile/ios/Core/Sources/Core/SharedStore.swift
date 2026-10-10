import Foundation
import Security

/// The app group the app and its widget share (project.yml entitlements).
public enum AppGroup {
    public static let id = "group.io.github.peyoteheadlights.mcsc"

    public static var defaults: UserDefaults {
        UserDefaults(suiteName: id) ?? UserDefaults.standard
    }
}

/// What the app and the widget both read: which PC, the wording and theme
/// chosen, the Notifications list and the widget's last reading. Nothing
/// secret: the sign-in token is only ever in the Keychain (`TokenStore`).
public final class SharedStore: @unchecked Sendable {
    private let defaults: UserDefaults

    private enum Key {
        static let pairing = "mcsc.pairing"
        static let alerts = "mcsc.alerts"
        static let widget = "mcsc.widget"
        static let technical = "mcsc.technical"
        static let theme = "mcsc.theme"
        static let unlock = "mcsc.unlock"
        static let agentVersion = "mcsc.agentVersion"
    }

    public init(defaults: UserDefaults = AppGroup.defaults) {
        self.defaults = defaults
    }

    public var pairing: Pairing? {
        get { load(Pairing.self, Key.pairing) }
        set { save(newValue, Key.pairing) }
    }

    public var alertState: AlertState {
        get { load(AlertState.self, Key.alerts) ?? AlertState() }
        set { save(newValue, Key.alerts) }
    }

    public var widgetSnapshot: WidgetSnapshot? {
        get { load(WidgetSnapshot.self, Key.widget) }
        set { save(newValue, Key.widget) }
    }

    public var technical: Bool {
        get { defaults.bool(forKey: Key.technical) }
        set { defaults.set(newValue, forKey: Key.technical) }
    }

    /// "system", "light", "dark", "graphite" or "contrast".
    public var theme: String {
        get { defaults.string(forKey: Key.theme) ?? "system" }
        set { defaults.set(newValue, forKey: Key.theme) }
    }

    /// The app asks for the phone's unlock; on unless turned off.
    public var unlockEnabled: Bool {
        get { defaults.object(forKey: Key.unlock) as? Bool ?? true }
        set { defaults.set(newValue, forKey: Key.unlock) }
    }

    public var agentVersion: String? {
        get { defaults.string(forKey: Key.agentVersion) }
        set { defaults.set(newValue, forKey: Key.agentVersion) }
    }

    /// Forget this PC: the pairing, its alerts and what the widget showed.
    public func forgetPC() {
        defaults.removeObject(forKey: Key.pairing)
        defaults.removeObject(forKey: Key.alerts)
        defaults.removeObject(forKey: Key.widget)
        defaults.removeObject(forKey: Key.agentVersion)
    }

    private func load<T: Decodable>(_ type: T.Type, _ key: String) -> T? {
        guard let data = defaults.data(forKey: key) else { return nil }
        return try? JSONDecoder().decode(T.self, from: data)
    }

    private func save<T: Encodable>(_ value: T?, _ key: String) {
        guard let value = value, let data = try? JSONEncoder().encode(value) else {
            defaults.removeObject(forKey: key)
            return
        }
        defaults.set(data, forKey: key)
    }
}

/// The sign-in token, in the Keychain only, readable after the phone's
/// first unlock and never copied to another device. Items go to the app's
/// default access group, the first in its keychain-access-groups
/// entitlement (…mcsc.shared), which the widget shares.
public enum TokenStore {
    private static let service = "io.github.peyoteheadlights.mcsc.session"
    private static let account = "token"

    private static func baseQuery() -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
    }

    public static func read() -> String? {
        var query = baseQuery()
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        guard status == errSecSuccess, let data = item as? Data else { return nil }
        let token = String(data: data, encoding: .utf8)
        return (token?.isEmpty ?? true) ? nil : token
    }

    @discardableResult
    public static func save(_ token: String) -> Bool {
        delete()
        var query = baseQuery()
        query[kSecValueData as String] = Data(token.utf8)
        query[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        return SecItemAdd(query as CFDictionary, nil) == errSecSuccess
    }

    public static func delete() {
        SecItemDelete(baseQuery() as CFDictionary)
    }
}

/// Links into the app: mcsc://server/<id> opens that server's screen.
public enum DeepLink {
    public static let scheme = "mcsc"

    public static var home: URL {
        URL(string: "mcsc://servers") ?? URL(fileURLWithPath: "/")
    }

    public static func server(_ id: String) -> URL? {
        URL(string: "mcsc://server/" + AgentClient.pathSegment(id))
    }

    public static func serverId(from url: URL) -> String? {
        guard let parts = URLComponents(url: url, resolvingAgainstBaseURL: false),
              parts.scheme?.lowercased() == scheme,
              parts.host == "server"
        else { return nil }
        var path = parts.percentEncodedPath
        if path.hasPrefix("/") {
            path.removeFirst()
        }
        guard !path.isEmpty, !path.contains("/"), let id = path.removingPercentEncoding, !id.isEmpty else {
            return nil
        }
        return id
    }
}

/// The JSON files mobile/tools/generate.py writes, bundled in the "shared"
/// folder of the app and the widget.
public enum SharedFiles {
    public static func data(_ name: String, _ ext: String, bundle: Bundle) -> Data? {
        if let url = bundle.url(forResource: name, withExtension: ext, subdirectory: "shared") {
            return try? Data(contentsOf: url)
        }
        if let url = bundle.url(forResource: name, withExtension: ext) {
            return try? Data(contentsOf: url)
        }
        return nil
    }

    /// feed.json: the agent's event name -> the words' key.
    public static func parseFeed(_ data: Data) -> [String: String] {
        guard let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return [:] }
        var out: [String: String] = [:]
        for (event, key) in root {
            if let key = key as? String {
                out[event] = key
            }
        }
        return out
    }
}
