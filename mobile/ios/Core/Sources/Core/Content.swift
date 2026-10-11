import Foundation

// The Mods / Plugins / Packs and Game settings screens' rules. Mirrors
// mobile/android/core's Content.kt rule for rule.

/// What a server's add-ons are called, by its type (glossary words).
public enum ContentKind: Equatable, Sendable {
    case mods
    case plugins
    case packs
    /// Vanilla takes neither, so it has no add-ons screen.
    case none

    public var titleKey: String {
        switch self {
        case .mods, .none: return "page.mods"
        case .plugins: return "page.plugins"
        case .packs: return "mobile.content.packs"
        }
    }
}

/// Whether the add-ons screen's change buttons work now.
public enum Changes: Equatable, Sendable {
    /// The account may only look (a helper without mods.manage).
    case notAllowed
    /// Mods change only while the server is stopped.
    case stopFirst
    /// The server's state isn't known (the PC can't be reached).
    case unknown
    case ready
}

/// The Mods / Plugins / Packs screen's rules (mods.js and addons.js).
public enum Content {
    /// Mods, Plugins or Packs; nil while the server list isn't read yet.
    public static func kind(_ row: ServerRow?) -> ContentKind? {
        guard let row = row else { return nil }
        if row.capabilities?.addons == true { return .packs }
        if row.content == "plugins" { return .plugins }
        if row.content == "mods" || row.capabilities?.mods == true { return .mods }
        return ContentKind.none
    }

    /// Which change buttons a mod or plugin row offers. Only someone with
    /// mods.manage sees any; they work only while the server is stopped (or
    /// crashed, as the dashboard allows); a state not known is not guessed
    /// to be stopped.
    public static func changes(canManage: Bool, serverState: String?) -> Changes {
        if !canManage { return .notAllowed }
        guard let state = serverState, state != States.UNKNOWN else { return .unknown }
        if state == States.OFFLINE || state == States.CRASHED { return .ready }
        return .stopFirst
    }

    /// Bedrock packs change while the server runs too; they take effect
    /// after a restart, which the screen then offers.
    public static func packChanges(canManage: Bool) -> Changes {
        canManage ? .ready : .notAllowed
    }

    /// "Stop the server first" offers Stop only while Stop would work.
    public static func canStopHere(_ serverState: String?, canControl: Bool) -> Bool {
        canControl && serverState == States.ONLINE
    }

    public static func status(_ mod: Mod) -> StateWords {
        if !mod.enabled { return StateWords(key: "mods.status_off", tone: .neutral) }
        switch mod.status {
        case "ok": return StateWords(key: "mods.status_ok", tone: .success)
        case "warn": return StateWords(key: "mods.status_warn", tone: .warning)
        case "error": return StateWords(key: "mods.status_error", tone: .danger)
        default: return StateWords(key: "value.unknown", tone: .neutral)
        }
    }

    /// Each problem's reason (a missing dependency, the wrong Minecraft
    /// version or server type), worst first; notes for information left out.
    public static func problems(_ mod: Mod) -> [String] {
        let worth = mod.issues.filter { $0.severity == "error" || $0.severity == "warn" }
        let errors = worth.filter { $0.severity == "error" }
        let warnings = worth.filter { $0.severity != "error" }
        return (errors + warnings).map(\.detail).filter { !$0.isEmpty }
    }

    /// Technical words add the mod's id, file and Minecraft versions.
    public static func technical(_ strings: Strings, _ mod: Mod) -> String {
        var parts: [String] = []
        if !mod.modId.isEmpty { parts.append(mod.modId) }
        parts.append(mod.filename)
        if let range = mod.minecraftRange, !range.isEmpty {
            parts.append(strings.t("mods.install_minecraft", ["versions": range]))
        }
        return parts.joined(separator: " · ")
    }

    /// "Update: 2.0" when Modrinth had a newer one at the last check.
    public static func newer(_ strings: Strings, _ mod: Mod) -> String? {
        mod.updateAvailable.map { strings.t("mods.update_to", ["version": $0.latestVersion]) }
    }

    /// "1.0 → 2.0"; Unknown for a side the agent didn't say.
    public static func change(_ strings: Strings, _ old: String?, _ new: String?) -> String {
        let unknown = strings.t("value.unknown")
        let from = (old?.isEmpty == false ? old : nil) ?? unknown
        let to = (new?.isEmpty == false ? new : nil) ?? unknown
        return "\(from) → \(to)"
    }

    private static let actions: Set<String> = ["install", "upload", "remove", "update", "rollback", "enable", "disable"]

    /// What a history row did, in words; the agent's own name for an action the app doesn't know.
    public static func action(_ strings: Strings, _ row: ModHistoryRow) -> String {
        if row.action == "update_all" { return strings.t("mobile.content.update_all") }
        return actions.contains(row.action) ? strings.t("mobile.content.action_" + row.action) : row.action
    }

    public static func historyTone(_ row: ModHistoryRow) -> Tone {
        row.result == "ok" ? .success : .danger
    }

    /// The mod a history row is about; Update all is about several.
    public static func historyName(_ strings: Strings, _ row: ModHistoryRow) -> String {
        row.modName ?? row.modId ?? (row.action == "update_all" ? (row.detail ?? "") : strings.t("value.unknown"))
    }

    /// Only a kept version whose file is still there and isn't in use can
    /// be rolled back to.
    public static func canRollBack(_ version: ModVersion) -> Bool {
        version.exists && !version.isCurrent
    }

    /// The required dependencies still missing: what "Install the missing ones" fetches.
    public static func missing(_ report: DependencyReport?) -> [DependencyItem] {
        (report?.items ?? []).filter { !$0.platform && $0.kind == "required" && $0.status == "missing" }
    }

    /// A Bedrock pack's kind in words.
    public static func packKind(_ addon: Addon) -> String {
        addon.kind == "resource" ? "addons.kind_resource" : "addons.kind_behavior"
    }

    /// The files each screen picks.
    public static let JAR = ".jar"
    public static let PACK_FILES = [".mcpack", ".mcaddon", ".mctemplate"]
    public static let MODPACK = ".mrpack"

    /// Whether a picked file's name is one the screen sends; the agent
    /// checks again and explains anything else in its own words.
    public static func accepts(_ kind: ContentKind, _ name: String, modpack: Bool = false) -> Bool {
        let lower = name.lowercased()
        if modpack { return lower.hasSuffix(MODPACK) }
        if kind == .packs { return PACK_FILES.contains { lower.hasSuffix($0) } }
        return lower.hasSuffix(JAR)
    }
}

/// Modrinth search results and the install confirmation (installMod in mods.js).
public enum Install {
    /// The version that would be installed: the newest that fits.
    public static func latest(_ project: ModProject) -> ModrinthVersion? {
        project.versions.first
    }

    public static func required(_ version: ModrinthVersion) -> [ModrinthDependency] {
        version.dependencies.filter { $0.type == "required" }
    }

    private static let sides: Set<String> = ["required", "optional", "unsupported"]

    /// What the confirmation lists before anything is downloaded.
    public static func facts(_ strings: Strings, _ project: ModProject, _ version: ModrinthVersion) -> [String] {
        let unknown = strings.t("value.unknown")
        var out = [
            strings.t("mods.install_what", ["name": project.project.title, "version": version.versionNumber ?? unknown]),
            strings.t("mods.install_size", ["size": Display.bytes(strings, version.file?.size)]),
        ]
        if !version.gameVersions.isEmpty {
            out.append(strings.t("mods.install_minecraft", ["versions": version.gameVersions.joined(separator: ", ")]))
        }
        out.append(strings.t("mods.install_licence", ["licence": project.project.license ?? unknown]))
        out.append(strings.t("mobile.content.side_server", ["side": side(strings, project.project.serverSide)]))
        out.append(strings.t("mobile.content.side_client", ["side": side(strings, project.project.clientSide)]))
        return out
    }

    private static func side(_ strings: Strings, _ value: String?) -> String {
        guard let value = value, sides.contains(value) else { return strings.t("value.unknown") }
        return strings.t("mobile.content.side_" + value)
    }

    /// "1.2M downloads"; Unknown when Modrinth didn't say.
    public static func downloads(_ strings: Strings, _ count: Int64?) -> String {
        guard let count = count else { return strings.t("value.unknown") }
        let short: String
        if count >= 1_000_000 {
            short = Display.fixed(Double(count) / 1_000_000, 1) + "M"
        } else if count >= 1_000 {
            short = Display.fixed(Double(count) / 1_000, 1) + "K"
        } else {
            short = String(count)
        }
        return strings.t("mobile.content.downloads", ["count": short])
    }

    /// Only Modrinth's own pages open, in the in-app browser.
    public static func page(_ url: String?) -> URL? {
        guard let url = url, url.hasPrefix("https://modrinth.com/") else { return nil }
        return URL(string: url)
    }

    /// What "Install the missing ones" did with each: installed, already there, or failed and why.
    public static func missingDone(_ strings: Strings, _ results: [DependencyResult]) -> String {
        let words = results.map { r -> String in
            let said: String
            switch r.result {
            case "installed": said = strings.t("mobile.content.result_ok")
            case "skipped": said = strings.t("mobile.content.result_skipped")
            default:
                let detail = r.detail.flatMap { $0.isEmpty ? nil : ": " + $0 } ?? ""
                said = strings.t("mobile.content.result_failed") + detail
            }
            return "\(r.title) (\(said))"
        }
        return strings.t("mobile.content.missing_done", ["results": words.joined(separator: ", ")])
    }

    public static func allWorked(_ results: [DependencyResult]) -> Bool {
        results.allSatisfy { $0.result == "installed" || $0.result == "skipped" }
    }
}

/// Update all's list and what is sent (Phase 9 part 4).
public enum UpdateAll {
    /// Offered when the last check found a newer version of any mod.
    public static func offered(_ list: ModList?) -> Bool {
        list?.mods.contains { $0.updateAvailable != nil } == true
    }

    /// Ticked at first: every one that is on. Turned-off ones are listed
    /// but left for the person to tick.
    public static func ticked(_ plan: UpdateAllPlan) -> Set<String> {
        Set(plan.updates.filter(\.enabled).map(\.filename))
    }

    /// The ticked ones, in the plan's order, with the version the plan showed.
    public static func body(_ plan: UpdateAllPlan, ticked: Set<String>) -> UpdateAllBody {
        UpdateAllBody(mods: plan.updates.filter { ticked.contains($0.filename) }.map {
            UpdateAllBody.Item(filename: $0.filename, versionId: $0.versionId)
        })
    }

    /// Why it can't start now, or nil when it can.
    public static func blocked(_ strings: Strings, _ plan: UpdateAllPlan) -> String? {
        if plan.serverRunning { return strings.t("mobile.content.stop_first") }
        if let job = plan.blockedBy { return strings.t("world.busy", ["job": job]) }
        return nil
    }

    public static func done(_ strings: Strings, _ result: UpdateAllResult) -> String {
        strings.tn("mobile.content.update_all_done", count: result.updated.count, ["backup": result.safetyBackup?.name ?? strings.t("value.unknown")])
    }

    /// The step a running Update all is on, from the live feed.
    public static func progress(_ job: Job?, serverId: String) -> String? {
        guard let job = job, job.state == "running", job.serverId == serverId, job.kind == "mods" else { return nil }
        return job.step
    }
}

/// A modpack import's steps, as the dashboard's confirmation lists them.
public enum Modpacks {
    public static func steps(_ strings: Strings, _ inspected: ModpackInspected) -> [String] {
        let pack = inspected.pack
        let unknown = strings.t("value.unknown")
        var out = [strings.t("pack.step_stop"), strings.t("pack.step_backup")]
        if inspected.versionChange {
            out.append(strings.t("pack.step_version", ["type": pack.typeName ?? unknown, "version": pack.minecraftVersion ?? unknown]))
        }
        out.append(strings.t("pack.step_aside"))
        out.append(strings.t("pack.step_files", ["count": pack.downloadCount]))
        return out
    }

    public static func fileStatus(_ file: ModpackFile) -> StateWords {
        switch file.status {
        case "download": return StateWords(key: "pack.status_download", tone: .success)
        case "client_only": return StateWords(key: "pack.status_client", tone: .neutral)
        default: return StateWords(key: "pack.status_refused", tone: .danger)
        }
    }
}

/// The Game settings form (game-settings.js): which fields, in which
/// groups, their words, and what Save sends.
public enum GameForm {
    /// Each key's label and hint. Bedrock's allow-list shares the whitelist's label.
    public static let LABELS: [String: (label: String, hint: String)] = [
        "difficulty": ("game.difficulty", "game.difficulty_hint"),
        "gamemode": ("game.gamemode", "game.gamemode_hint"),
        "max-players": ("game.max_players", "game.max_players_hint"),
        "level-seed": ("game.seed", "game.seed_hint"),
        "white-list": ("game.whitelist", "game.whitelist_hint"),
        "pvp": ("game.pvp", "game.pvp_hint"),
        "view-distance": ("game.view_distance", "game.view_distance_hint"),
        "motd": ("game.motd", "game.motd_hint"),
        "server-port": ("game.port", "game.port_hint"),
        "allow-list": ("mobile.game.allowlist", "game.allowlist_hint"),
        "allow-cheats": ("game.cheats", "game.cheats_hint"),
        "server-name": ("game.server_name", "game.server_name_hint"),
    ]

    private static let choiceWords: Set<String> = ["peaceful", "easy", "normal", "hard", "survival", "creative", "adventure", "spectator"]

    /// How the game plays, who can join, then the technical bits.
    public static let ORDER: [(title: String, keys: [String])] = [
        ("game.group_play", ["gamemode", "difficulty", "pvp", "allow-cheats"]),
        ("game.group_who", ["motd", "server-name", "max-players", "white-list", "allow-list"]),
        ("game.group_world", ["level-seed", "view-distance", "server-port"]),
    ]

    public struct Group: Equatable, Sendable {
        public let titleKey: String
        public let fields: [GameSetting]
    }

    /// The groups with the fields this server's file has, in order.
    public static func groups(_ settings: GameSettings) -> [Group] {
        ORDER.compactMap { entry in
            let fields = entry.keys.compactMap { key in settings.fields.first { $0.key == key } }
            return fields.isEmpty ? nil : Group(titleKey: entry.title, fields: fields)
        }
    }

    public static func label(_ strings: Strings, _ field: GameSetting) -> String {
        LABELS[field.key].map { strings.t($0.label) } ?? field.key
    }

    public static func choiceLabel(_ strings: Strings, _ value: String) -> String {
        choiceWords.contains(value) ? strings.t("game." + value) : value
    }

    /// The value the form starts with, as text: what the file says (as
    /// written, when Minecraft wouldn't accept it), otherwise what Minecraft
    /// uses then (an empty seed means a random one). Booleans are "true" or
    /// "false".
    public static func initial(_ field: GameSetting) -> String {
        // A value Minecraft wouldn't accept is shown as the file has it (its problem is
        // said next to it), never swapped for the default.
        if field.set && field.problem != nil { return field.raw ?? "" }
        let shown = field.set ? field.value?.text : nil
        if field.kind == "seed" { return shown ?? "" }
        return shown ?? field.minecraftDefault
    }

    /// Locked: the seed once the world exists, or everything for someone
    /// who may not edit settings.
    public static func locked(_ field: GameSetting, canEdit: Bool) -> Bool {
        !canEdit || field.readOnly != nil
    }

    /// The line under a field: its hint (or why the seed is locked), and
    /// what Minecraft uses when the file doesn't set it.
    public static func hint(_ strings: Strings, _ field: GameSetting) -> String {
        var notes: [String] = []
        if field.readOnly == "world_exists" {
            notes.append(strings.t("game.seed_locked"))
        } else if let hint = LABELS[field.key]?.hint {
            notes.append(strings.t(hint))
        }
        if !field.set {
            let fallback: String
            if field.kind == "choice" {
                fallback = choiceLabel(strings, field.minecraftDefault)
            } else if field.minecraftDefault.isEmpty {
                fallback = strings.t("game.blank")
            } else {
                fallback = field.minecraftDefault
            }
            notes.append(strings.t("game.not_set", ["value": fallback]))
        }
        return notes.filter { !$0.isEmpty }.joined(separator: " ")
    }

    /// Why the file's own value couldn't be used, or nil.
    public static func fileProblem(_ strings: Strings, _ field: GameSetting) -> String? {
        field.problem.map { strings.t("game.file_problem", ["problem": $0]) }
    }

    /// Only what changed, as the agent takes it: on and off as true or
    /// false, numbers as numbers when they read as one (the agent checks and
    /// explains anything else), words as typed. Locked fields never.
    public static func changed(_ settings: GameSettings, _ edits: [String: String]) -> [String: JSONValue] {
        var out: [String: JSONValue] = [:]
        for field in settings.fields where field.readOnly == nil {
            guard let edit = edits[field.key], edit != initial(field) else { continue }
            switch field.kind {
            case "bool":
                out[field.key] = .bool(edit == "true")
            case "int", "port":
                let trimmed = edit.trimmingCharacters(in: .whitespaces)
                if let number = Int64(trimmed) {
                    out[field.key] = .number(Double(number))
                } else {
                    out[field.key] = .string(trimmed)
                }
            default:
                out[field.key] = .string(edit)
            }
        }
        return out
    }

    /// What to say after Save. Running: it waits for a restart, offered next to it.
    public static func saved(_ strings: Strings, _ result: GameSettingsSaved) -> String {
        if result.nothingChanged == true { return strings.t("settings.nothing_changed") }
        return strings.t(result.running ? "game.saved_running" : "game.saved")
    }
}

/// Modrinth's icons for the search results, loaded straight from Modrinth
/// (never through the PC) into the phone's own cache, so scrolling back
/// doesn't download them again. Only https addresses on Modrinth's own
/// hosts are loaded; anything else is no icon.
public final class IconCache: @unchecked Sendable {
    public static let MODRINTH_HOSTS: Set<String> = ["cdn.modrinth.com"]
    public static let MAX_ICON_BYTES = 1024 * 1024

    private let session: URLSession
    private let hosts: Set<String>
    private let httpsOnly: Bool
    private let memory = NSCache<NSURL, NSData>()

    /// `directory` holds the disk cache (the app's Caches folder, which iOS
    /// may clear); nil keeps icons in memory only.
    public init(
        directory: URL?,
        configuration: URLSessionConfiguration = .default,
        hosts: Set<String> = IconCache.MODRINTH_HOSTS,
        httpsOnly: Bool = true,
        kept: Int = 120
    ) {
        let config = configuration
        config.urlCache = URLCache(memoryCapacity: 4 * 1024 * 1024, diskCapacity: 20 * 1024 * 1024, directory: directory)
        config.requestCachePolicy = .returnCacheDataElseLoad
        config.httpCookieStorage = nil
        config.httpShouldSetCookies = false
        // A redirect could lead off Modrinth's own address: never followed.
        self.session = URLSession(configuration: config, delegate: NoRedirects(), delegateQueue: nil)
        self.hosts = hosts
        self.httpsOnly = httpsOnly
        memory.countLimit = kept
    }

    public func allowed(_ url: String?) -> Bool {
        guard let url = url, let parsed = URL(string: url), let host = parsed.host else { return false }
        return (!httpsOnly || parsed.scheme == "https") && hosts.contains(host)
    }

    /// The icon's bytes, from memory, the disk cache or Modrinth; nil when
    /// it isn't allowed or couldn't be loaded.
    public func load(_ url: String?) async -> Data? {
        guard let url = url, allowed(url), let parsed = URL(string: url) else { return nil }
        if let kept = memory.object(forKey: parsed as NSURL) {
            return kept as Data
        }
        guard let answer = try? await session.bytes(from: parsed),
              let http = answer.1 as? HTTPURLResponse, (200...299).contains(http.statusCode),
              http.expectedContentLength <= Int64(IconCache.MAX_ICON_BYTES)
        else { return nil }
        // Read no more than the limit, even when the size wasn't said.
        var data = Data()
        do {
            for try await byte in answer.0 {
                data.append(byte)
                if data.count > IconCache.MAX_ICON_BYTES { return nil }
            }
        } catch {
            return nil
        }
        memory.setObject(data as NSData, forKey: parsed as NSURL)
        return data
    }
}

/// Refuses every redirect, so an icon is only ever read from where it was asked for.
private final class NoRedirects: NSObject, URLSessionTaskDelegate {
    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        willPerformHTTPRedirection response: HTTPURLResponse,
        newRequest request: URLRequest,
        completionHandler: @escaping (URLRequest?) -> Void
    ) {
        completionHandler(nil)
    }
}
