import Foundation

/// The Server settings screen: how Command Block runs one server (not the
/// game's own rules, which are Game settings). Each field is a key the
/// agent's PUT /settings takes; Save sends only what changed, and the
/// agent says why it refused any of them.
public enum ServerForm {
    public struct Field: Equatable, Sendable {
        /// bool, int, number (seconds, may have a fraction) or text.
        public let key: String
        public let kind: String
        public let labelKey: String
        public let hintKey: String?

        public init(_ key: String, _ kind: String, _ labelKey: String, _ hintKey: String? = nil) {
            self.key = key
            self.kind = kind
            self.labelKey = labelKey
            self.hintKey = hintKey
        }
    }

    public struct Group: Equatable, Sendable {
        public let titleKey: String
        public let fields: [Field]
        public let noteKey: String?
    }

    public static let GROUPS: [Group] = [
        Group(titleKey: "serverset.crashes", fields: [
            Field("monitor.auto_restart", "bool", "serverset.auto_restart"),
            Field("monitor.restart_delay", "number", "serverset.restart_delay"),
            Field("monitor.max_crashes", "int", "serverset.max_crashes", "serverset.max_crashes_hint"),
        ], noteKey: nil),
        Group(titleKey: "serverset.sleep", fields: [
            Field("server.autosleep", "bool", "serverset.sleep_label"),
            Field("server.autosleep_minutes", "int", "serverset.sleep_minutes", "serverset.sleep_minutes_hint"),
        ], noteKey: "serverset.sleep_restart_note"),
        Group(titleKey: "serverset.keep_label", fields: [
            Field("backups.keep_daily", "int", "serverset.keep_daily"),
            Field("backups.keep_weekly", "int", "serverset.keep_weekly"),
            Field("backups.keep_monthly", "int", "serverset.keep_monthly"),
        ], noteKey: nil),
        Group(titleKey: "serverset.timing", fields: [
            Field("server.start_timeout", "number", "serverset.start_timeout"),
            Field("server.stop_timeout", "number", "serverset.stop_timeout", "serverset.stop_timeout_hint"),
            Field("server.autostart_minecraft", "bool", "mobile.serverset.autostart", "mobile.serverset.autostart_hint"),
        ], noteKey: nil),
    ]

    public static let NAME = "server.name"
    public static let NAME_LIMIT = 60

    public static var FIELDS: [Field] { GROUPS.flatMap(\.fields) }

    /// The saved value, as the agent has it.
    public static func value(_ settings: ServerSettings, _ key: String) -> JSONValue? {
        let parts = key.split(separator: ".", maxSplits: 1).map(String.init)
        guard parts.count == 2 else { return nil }
        switch parts[0] {
        case "server": return settings.server[parts[1]]
        case "monitor": return settings.monitor[parts[1]]
        case "backups": return settings.backups[parts[1]]
        case "mods": return settings.mods[parts[1]]
        default: return nil
        }
    }

    /// The form's starting text: "true"/"false", a number without a
    /// pointless ".0", or the words. Empty when the agent didn't say.
    public static func initial(_ settings: ServerSettings, _ key: String) -> String {
        switch value(settings, key) {
        case .bool, .number, .string: return value(settings, key)?.text ?? ""
        default: return ""
        }
    }

    /// View it: everyone the agent lets read settings.
    public static func visible(_ me: Me?) -> Bool { me?.can(Permissions.SETTINGS_VIEW) == true }

    /// Change it: only with settings.edit; anyone else sees it read-only.
    public static func editable(_ me: Me?) -> Bool { me?.can(Permissions.SETTINGS_EDIT) == true }

    /// Only what changed, typed as the agent takes it: on and off as true
    /// or false, numbers as numbers when they read as one (the agent checks
    /// the rest and says why), the name trimmed. A blank name is not sent.
    public static func changed(_ settings: ServerSettings, _ edits: [String: String]) -> [String: JSONValue] {
        var out: [String: JSONValue] = [:]
        if let name = edits[NAME]?.trimmingCharacters(in: .whitespaces), !name.isEmpty, name != initial(settings, NAME) {
            out[NAME] = .string(name)
        }
        for field in FIELDS {
            guard let edit = edits[field.key] else { continue }
            let trimmed = edit.trimmingCharacters(in: .whitespaces)
            if trimmed == initial(settings, field.key) { continue }
            switch field.kind {
            case "bool": out[field.key] = .bool(edit == "true")
            case "int": out[field.key] = Int64(trimmed).map { .number(Double($0)) } ?? .string(trimmed)
            case "number": out[field.key] = Double(trimmed).map { .number($0) } ?? .string(trimmed)
            default: out[field.key] = .string(edit)
            }
        }
        return out
    }

    /// The color as it will be sent: "#RRGGBB" in capitals. nil when it
    /// isn't a color.
    public static func color(_ text: String) -> String? {
        var typed = text.trimmingCharacters(in: .whitespaces)
        if !typed.hasPrefix("#") { typed = "#" + typed }
        let digits = typed.dropFirst()
        guard digits.count == 6, digits.allSatisfy(\.isHexDigit) else { return nil }
        return typed.uppercased()
    }

    /// What to say after Save: "Nothing changed", saved, or that some
    /// fields were refused (each says why under it).
    public static func saved(_ strings: Strings, sent: Bool, result: ServerSettingsSaved?) -> String {
        if !sent { return strings.t("settings.nothing_changed") }
        if let result, !result.rejected.isEmpty { return strings.t("mobile.game.fix_marked") }
        return strings.t("settings.saved")
    }

    /// Sleep when empty, as measured now; never a guess.
    public static func sleepLine(_ strings: Strings, _ settings: ServerSettings) -> String {
        guard case .bool(true) = value(settings, "server.autosleep") else { return strings.t("serverset.sleep_off") }
        guard let sleep = settings.sleep else { return strings.t("value.unknown") }
        if sleep.listAnswered == false { return strings.t("serverset.sleep_no_answer") }
        guard let count = sleep.playersOnline else { return strings.t("serverset.sleep_unknown_players") }
        if count > 0 { return strings.t("serverset.sleep_players", ["count": String(count)]) }
        if let left = sleep.stopsIn {
            return strings.t("serverset.sleep_countdown", ["duration": Display.duration(strings, left)])
        }
        return strings.t("serverset.sleep_waiting")
    }
}
