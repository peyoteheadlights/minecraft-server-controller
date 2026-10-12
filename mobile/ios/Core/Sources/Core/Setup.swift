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
    public static func editable(_ me: Me?) -> Bool { me?.can(Permissions.SETTINGS_SERVER) == true }

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

/// Which CPU cores a server may use. What it really uses is read back from
/// the running server; the boxes are only the setting. Cores are counted
/// from 0 here and shown from 1.
public enum CpuCores {
    /// The other servers set to use each core, by core.
    public static func sharedBy(_ cpu: CpuOverview) -> [Int: [String]] {
        var used: [Int: [String]] = [:]
        for other in cpu.others {
            for core in other.cores { used[core, default: []].append(other.name) }
        }
        return used
    }

    /// "1-4, 7": cores as people count them, runs shortened.
    public static func describe(_ cores: [Int]) -> String {
        let numbers = cores.sorted().map { $0 + 1 }
        guard var start = numbers.first else { return "" }
        var prev = start
        var runs: [String] = []
        for n in numbers.dropFirst().map(Optional.some) + [nil] {
            if let n, n == prev + 1 {
                prev = n
                continue
            }
            runs.append(start == prev ? "\(start)" : "\(start)-\(prev)")
            if let n {
                start = n
                prev = n
            }
        }
        return runs.joined(separator: ", ")
    }

    /// The first half of the cores, rounded up.
    public static func half(_ count: Int) -> Set<Int> { Set(0..<((count + 1) / 2)) }

    /// What the running server uses now, or why that isn't known.
    public static func nowLine(_ strings: Strings, _ cpu: CpuOverview) -> String {
        if let applied = cpu.status.applied {
            let cores = applied.count == cpu.logicalCores ? strings.t("serverset.every_core") : describe(applied)
            return strings.t("serverset.cores_now", ["cores": cores])
        }
        return strings.t("serverset.cores_unknown", ["reason": cpu.status.appliedReason ?? strings.t("value.unknown")])
    }

    /// What to send: empty for every core. nil when no core is picked.
    public static func toSave(all: Bool, picked: Set<Int>) -> [Int]? {
        if all { return [] }
        if picked.isEmpty { return nil }
        return picked.sorted()
    }

    public static func update(_ cores: [Int]) -> [String: JSONValue] {
        ["server.cpu_cores": .array(cores.map { .number(Double($0)) })]
    }

    /// After Save: used now, from the next start, or not applied and why.
    public static func saved(_ strings: Strings, _ result: ServerSettingsSaved) -> String {
        guard let live = result.cpuCores else { return strings.t("serverset.cores_next_start") }
        if !live.ok { return strings.t("serverset.cores_not_applied", ["reason": live.reason ?? strings.t("value.unknown")]) }
        return strings.t("serverset.cores_applied")
    }
}

/// The memory slider: only the -Xmx limit, bounded by the PC's memory as
/// measured; every other Java option stays as it is.
public enum Memory {
    /// "6 GB", "1.5 GB".
    public static func gb(_ mb: Int) -> String {
        mb % 1024 == 0 ? "\(mb / 1024) GB" : "\(Display.fixed(Double(mb) / 1024.0, 1)) GB"
    }

    /// No slider when the PC's memory couldn't be read, or the server type
    /// takes no limit (Bedrock).
    public static func slider(_ memory: MemoryOverview) -> Bool { memory.takesMemoryLimit && memory.totalMb != nil }

    /// Where the slider starts: the current limit, else 2 GB, kept inside the bounds.
    public static func start(_ memory: MemoryOverview) -> Int {
        guard let total = memory.totalMb else { return memory.limitMb ?? 2048 }
        return min(total, max(memory.minMb, memory.limitMb ?? 2048))
    }

    /// A slider position, snapped to the step and kept inside the bounds.
    public static func snap(_ memory: MemoryOverview, _ mb: Double) -> Int {
        guard let total = memory.totalMb else { return memory.minMb }
        let step = Double(max(1, memory.stepMb))
        let snapped = memory.minMb + Int(((mb - Double(memory.minMb)) / step).rounded()) * Int(step)
        return min(total, max(memory.minMb, snapped))
    }

    /// The warning when this server, with the others running, may use more
    /// than the PC has. nil when it fits or the PC's memory isn't known.
    public static func warning(_ strings: Strings, _ memory: MemoryOverview, _ chosen: Int) -> String? {
        guard let total = memory.totalMb else { return nil }
        let others = memory.servers.filter { !$0.isThis && $0.running }
        let together = others.reduce(0) { $0 + ($1.limitMb ?? 0) } + chosen
        if together <= total { return nil }
        if !others.isEmpty {
            return strings.t("memory.over_together", ["names": others.map(\.name).joined(separator: ", "), "total": gb(together), "pc": gb(total)])
        }
        return strings.t("memory.over_alone", ["total": gb(together), "pc": gb(total)])
    }

    /// Under the slider: what is set now.
    public static func nowLine(_ strings: Strings, _ memory: MemoryOverview) -> String {
        guard let limit = memory.limitMb else { return strings.t("memory.unset") }
        return strings.t("memory.now", ["limit": gb(limit)])
    }

    /// Why there is no slider.
    public static func noSlider(_ strings: Strings, _ memory: MemoryOverview, bedrock: Bool) -> String {
        if !memory.takesMemoryLimit { return strings.t(bedrock ? "memory.not_bedrock" : "memory.not_used") }
        return strings.t("memory.pc_unknown")
    }
}

/// Changing a server's version or type: checked first (what might break),
/// one confirmation (the server stops and a backup is taken first), then a
/// task with progress. Roll back puts the previous software back.
public enum VersionChange {
    /// A line of the check's report, and how loud it is.
    public struct Line: Equatable, Sendable {
        public let text: String
        public let tone: Tone
    }

    public static let KINDS: Set<String> = ["version_change", "version_rollback"]

    /// Java and Bedrock worlds differ, so only this edition's kinds are offered.
    public static func sameEdition(_ types: [ServerTypeInfo], _ current: ServerVersion) -> [ServerTypeInfo] {
        types.filter { $0.edition == current.capabilities.edition }
    }

    /// The versions to pick from: snapshots only when asked for.
    public static func choices(_ versions: TypeVersions, snapshots: Bool) -> [OfferedVersion] {
        snapshots ? versions.versions : versions.versions.filter(\.stable)
    }

    /// What the server is now: "Fabric 1.21.1", or that it isn't known yet.
    public static func now(_ strings: Strings, _ version: ServerVersion) -> String {
        guard let minecraft = version.minecraftVersion else { return strings.t("version.not_seen_yet") }
        return "\(version.capabilities.name) \(minecraft)"
    }

    /// "Fabric 1.21.4", for the check and the confirmation.
    public static func target(_ report: VersionPreflight) -> String {
        "\(report.target.typeName) \(report.target.minecraftVersion ?? "")".trimmingCharacters(in: .whitespaces)
    }

    /// What the check found, loudest first; then that a backup comes first.
    public static func lines(_ strings: Strings, _ report: VersionPreflight) -> [Line] {
        var out: [Line] = []
        if report.java.verdict == "incompatible" {
            out.append(Line(text: report.java.detail ?? strings.t("value.unknown"), tone: .danger))
        }
        if report.downgradeWarning { out.append(Line(text: strings.t("version.downgrade"), tone: .warning)) }
        if report.typeChange {
            out.append(report.gentleTypeChange
                ? Line(text: strings.t("version.type_change_gentle"), tone: .neutral)
                : Line(text: strings.t("version.type_change", ["from": report.current.typeName, "to": report.target.typeName]), tone: .warning))
        }
        if report.crossplay && !report.crossplayAvailable {
            out.append(Line(text: strings.t("version.crossplay_lost"), tone: .warning))
        }
        if !report.notSupporting.isEmpty {
            let words = strings.t("version.not_supporting", ["count": report.notSupporting.count, "version": report.target.minecraftVersion ?? ""])
            out.append(Line(text: words + " " + report.notSupporting.prefix(8).joined(separator: ", "), tone: .warning))
        }
        if !report.movedAside.isEmpty {
            out.append(Line(text: strings.t("version.moved_aside", ["count": report.movedAside.count]) + " " + strings.t("version.moved_aside_note"), tone: .warning))
        }
        if !report.unknownSupport.isEmpty {
            out.append(Line(text: strings.t("version.unknown_support", ["count": report.unknownSupport.count]) + " " + strings.t("version.unknown_support_note"), tone: .neutral))
        }
        if report.java.verdict == "unknown" { out.append(Line(text: strings.t("version.java_unknown"), tone: .neutral)) }
        out.append(Line(text: strings.t("version.backup_first"), tone: .neutral))
        return out
    }

    /// The confirmation's button is red for a downgrade or a hard type change.
    public static func danger(_ report: VersionPreflight) -> Bool {
        report.downgradeWarning || (report.typeChange && !report.gentleTypeChange)
    }

    /// The server won't start until Minecraft's EULA is agreed to.
    public static func eulaNeeded(_ version: ServerVersion) -> Bool { version.eulaRequired }

    /// The version set up but not yet confirmed by the console.
    public static func pending(_ version: ServerVersion) -> String? { version.pendingVersion?["minecraft_version"]?.text }

    public static func canRollBack(_ version: ServerVersion) -> Bool { version.lastChange?.canRollBack == true }

    /// A version change or roll back running on this server now, to show
    /// its progress when the screen is opened again.
    public static func running(_ jobs: [Job], serverId: String) -> Job? {
        jobs.first { KINDS.contains($0.kind) && $0.state == "running" && ($0.serverId == nil || $0.serverId == serverId) }
    }
}

/// "Let Bedrock players join": only for kinds Geyser is built for.
public enum Crossplay {
    /// Why this server can't have it, in the agent's words when it gave them.
    public static func whyNot(_ strings: Strings, _ info: CrossplayInfo) -> String? {
        info.available ? nil : (info.unavailableReason ?? strings.t("cross.not_for_type"))
    }

    /// The port box starts at the saved port, else the agent's free one, else 19132.
    public static func port(_ info: CrossplayInfo) -> String { String(info.port ?? info.suggestedPort ?? info.defaultPort) }

    /// The typed port to send; nil lets the agent pick a free one.
    public static func typedPort(_ text: String) -> Int? {
        guard let port = Int(text.trimmingCharacters(in: .whitespaces)), (1...65535).contains(port) else { return nil }
        return port
    }

    /// The "turn it on" question names the typed port, or says the agent picks one.
    public static func confirm(_ strings: Strings, _ text: String) -> String {
        guard let port = typedPort(text) else { return strings.t("mobile.cross.on_body_free") }
        return strings.t("cross.on_body", ["port": port])
    }

    /// Whether it is ready, only when both files are really there.
    public static func ready(_ strings: Strings, _ info: CrossplayInfo) -> String {
        strings.t(info.ready ? "cross.ready_yes" : "cross.files_missing")
    }
}

/// Duplicate: a copy of the server with its own port and color, owner only.
public enum Duplicate {
    public static let COPY = "copy"
    public static let FRESH = "fresh"

    public static func allowed(_ me: Me?) -> Bool { me?.can(Permissions.SERVERS_MANAGE) == true }

    /// The world choices: copy what's there (when there is a world) or start fresh.
    public static func worlds(_ options: DuplicateOptions) -> [String] {
        options.worldFolders.isEmpty ? [FRESH] : [COPY, FRESH]
    }

    /// Both name and folder are needed; the agent checks the rest.
    public static func ready(_ name: String, _ directory: String) -> Bool {
        !name.trimmingCharacters(in: .whitespaces).isEmpty && !directory.trimmingCharacters(in: .whitespaces).isEmpty
    }

    /// A running copy's progress, from the live feed.
    public static func progress(_ job: Job?, serverId: String) -> String? {
        guard let job, job.kind == "duplicate", job.state == "running", job.serverId == serverId else { return nil }
        return job.step
    }
}

/// Remove server: off the list, nothing deleted. Owner only, never the last one.
public enum RemoveServer {
    public static func allowed(_ me: Me?) -> Bool { me?.can(Permissions.SERVERS_MANAGE) == true }

    /// Why the button is off, or nil when it can be pressed.
    public static func blocked(_ strings: Strings, serverCount: Int) -> String? {
        serverCount <= 1 ? strings.t("serverset.remove_last") : nil
    }

    /// The line under the heading: what removing does, or why it can't.
    public static func hint(_ strings: Strings, serverCount: Int) -> String {
        blocked(strings, serverCount: serverCount) ?? strings.t("serverset.remove_hint")
    }
}

/// One line of "These settings will change": `old` is nil for an added
/// key, `new` is nil for a removed one.
public struct RawChange: Equatable, Sendable {
    public var key: String
    public var old: String?
    public var new: String?

    public init(_ key: String, _ old: String?, _ new: String?) {
        self.key = key
        self.old = old
        self.new = new
    }
}

/// The Technical mode editors: server.properties and the Java options as
/// text. Before saving, the phone lists what will change, read the same way
/// the agent reads the file, so comments and order never count as changes.
public enum RawText {
    /// Technical mode, with the permission for that file: Game settings for
    /// server.properties, Server settings for Java options.
    public static func allowed(_ me: Me?, technical: Bool, permission: String = Permissions.SETTINGS_SERVER) -> Bool {
        technical && me?.can(permission) == true
    }

    /// Each key's value, as the agent reads server.properties (agent/minecraft/properties.py).
    public static func properties(_ text: String) -> [String: String] {
        let lines = text.replacingOccurrences(of: "\r\n", with: "\n").replacingOccurrences(of: "\r", with: "\n")
            .components(separatedBy: "\n").map { Array($0.unicodeScalars) }
        var found: [String: String] = [:]
        var i = 0
        while i < lines.count {
            var logical = lines[i]
            let first = trimStart(logical).first
            let comment = first == "#" || first == "!"
            while !comment && continues(logical) && i + 1 < lines.count {
                i += 1
                logical = Array(logical.dropLast()) + trimStart(lines[i])
            }
            i += 1
            if let pair = split(logical) { found[pair.0] = pair.1 }
        }
        return found
    }

    public static func propertyChanges(_ before: String, _ after: String) -> [RawChange] {
        changes(properties(before), properties(after))
    }

    /// The Java options typed on one line or several.
    public static func args(_ text: String) -> [String] {
        text.components(separatedBy: .whitespacesAndNewlines).filter { !$0.isEmpty }
    }

    /// Options are matched by name (-Xmx, -Dname, -XX:Name), so a moved option
    /// isn't a change. A name given more than once is counted: "-Dx (2)".
    public static func argChanges(_ before: [String], _ after: [String]) -> [RawChange] {
        changes(byKey(before), byKey(after))
    }

    public static func argKey(_ arg: String) -> String {
        if arg.hasPrefix("-Xmx") || arg.hasPrefix("-Xms") || arg.hasPrefix("-Xss") { return String(arg.prefix(4)) }
        if arg.hasPrefix("-XX:+") || arg.hasPrefix("-XX:-") { return "-XX:" + String(arg.dropFirst(5)) }
        if let equals = arg.firstIndex(of: "=") { return String(arg[..<equals]) }
        return arg
    }

    public static func line(_ strings: Strings, _ change: RawChange) -> String {
        if change.old == nil { return strings.t("mobile.raw.added", ["key": change.key, "new": change.new ?? ""]) }
        if change.new == nil { return strings.t("mobile.raw.removed", ["key": change.key, "old": change.old ?? ""]) }
        return strings.t("mobile.raw.changed", ["key": change.key, "old": change.old ?? "", "new": change.new ?? ""])
    }

    private static func byKey(_ args: [String]) -> [String: String] {
        var found: [String: String] = [:]
        var seen: [String: Int] = [:]
        for arg in args {
            let key = argKey(arg)
            let count = (seen[key] ?? 0) + 1
            seen[key] = count
            found[count == 1 ? key : "\(key) (\(count))"] = arg
        }
        return found
    }

    private static func changes(_ before: [String: String], _ after: [String: String]) -> [RawChange] {
        Set(before.keys).union(after.keys).sorted().compactMap { key in
            before[key] == after[key] ? nil : RawChange(key, before[key], after[key])
        }
    }

    private static let blank: Set<Unicode.Scalar> = [" ", "\t", "\u{0C}"]

    private static func trimStart(_ line: [Unicode.Scalar]) -> [Unicode.Scalar] {
        Array(line.drop(while: { blank.contains($0) }))
    }

    private static func continues(_ line: [Unicode.Scalar]) -> Bool {
        line.reversed().prefix(while: { $0 == "\\" }).count % 2 == 1
    }

    private static func split(_ logical: [Unicode.Scalar]) -> (String, String)? {
        let text = trimStart(logical)
        guard let first = text.first, first != "#", first != "!" else { return nil }
        var key: [Unicode.Scalar] = []
        var i = 0
        while i < text.count {
            let c = text[i]
            if c == "\\" && i + 1 < text.count {
                key += text[i...(i + 1)]
                i += 2
                continue
            }
            if c == "=" || c == ":" || blank.contains(c) { break }
            key.append(c)
            i += 1
        }
        var rest = trimStart(Array(text[i...]))
        if rest.first == "=" || rest.first == ":" { rest = trimStart(Array(rest.dropFirst())) }
        return (unescape(key), unescape(rest))
    }

    private static let escapes: [Unicode.Scalar: Unicode.Scalar] = ["t": "\t", "n": "\n", "r": "\r", "f": "\u{0C}"]

    private static func unescape(_ text: [Unicode.Scalar]) -> String {
        var out = String.UnicodeScalarView()
        var i = 0
        while i < text.count {
            let c = text[i]
            if c != "\\" || i + 1 >= text.count {
                out.append(c)
                i += 1
                continue
            }
            let next = text[i + 1]
            if next == "u", i + 6 <= text.count, text[(i + 2)..<(i + 6)].allSatisfy({ $0.properties.isASCIIHexDigit }),
               let code = UInt32(String(String.UnicodeScalarView(text[(i + 2)..<(i + 6)])), radix: 16),
               let scalar = Unicode.Scalar(code) {
                out.append(scalar)
                i += 6
                continue
            }
            out.append(escapes[next] ?? next)
            i += 2
        }
        return String(out)
    }
}

/// The PC folder picker (panels/folders.js): tap through the PC's folders,
/// names only, and choose one. The owner's alone (files.browse); typing a
/// path is for Technical mode, checked by the agent the same way.
public enum FolderPicker {
    public static func allowed(_ me: Me?) -> Bool { me?.can(Permissions.FILES_BROWSE) == true }

    public static func canType(technical: Bool) -> Bool { technical }

    /// The drives and shortcuts, before any folder is open.
    public static func atTop(_ listing: FolderListing) -> Bool { listing.path == nil }

    /// Where "Up one folder" goes: the parent, "" (the drives) from a
    /// drive's root, or nil when already at the top.
    public static func up(_ listing: FolderListing) -> String? {
        atTop(listing) ? nil : (listing.parent ?? "")
    }

    public static func shortcutName(_ strings: Strings, _ shortcut: PcShortcut) -> String {
        strings.t("folders.\(shortcut.key)")
    }

    public static func driveName(_ strings: Strings, _ drive: PcDrive) -> String {
        strings.t("folders.drive", ["name": drive.name])
    }

    /// The lines under the list: empty, or only the first 500 shown.
    public static func notes(_ strings: Strings, _ listing: FolderListing) -> [String] {
        var lines: [String] = []
        if !atTop(listing) && listing.folders.isEmpty { lines.append(strings.t("folders.empty")) }
        if listing.truncated { lines.append(strings.t("folders.truncated")) }
        return lines
    }
}

/// The "+" on All servers (pages/add-server.js, panels/newserver.js): a new
/// server, one from a modpack, or one already on the PC. The owner's alone.
public enum AddServer {
    public static let NEW = "new"
    public static let MODPACK = "modpack"
    public static let HAVE = "have"
    public static let WAYS = [NEW, MODPACK, HAVE]

    /// Memory after More or Less: at least 1 GB, and no more than the PC has (64 GB when that's unknown).
    public static func nudged(_ memoryMb: Int, _ stepMb: Int, totalMb: Int?) -> Int {
        Swift.min(Swift.max(memoryMb + stepMb, 1024), Swift.max(1024, totalMb ?? 64 * 1024))
    }

    public static let EDITION = "edition"
    public static let KIND = "kind"
    public static let VERSION = "version"
    public static let DETAILS = "details"
    public static let RULES = "rules"

    public static func allowed(_ me: Me?) -> Bool { me?.can(Permissions.SERVERS_MANAGE) == true }

    /// Bedrock has one kind of server, so it skips the table.
    public static func steps(_ edition: String) -> [String] {
        edition == "bedrock" ? [EDITION, VERSION, DETAILS, RULES] : [EDITION, KIND, VERSION, DETAILS, RULES]
    }

    /// The Java kinds for the table, as the agent lists them.
    public static func kinds(_ options: NewServerOptions) -> [ServerTypeInfo] { options.types.filter { $0.edition == "java" } }

    public static func bedrockType(_ options: NewServerOptions) -> ServerTypeInfo? { options.types.first { $0.edition == "bedrock" } }

    public static func memoryShown(_ type: ServerTypeInfo) -> Bool { type.takesMemoryLimit && type.edition != "bedrock" }

    /// One kind's column of the table, as label and value; Technical mode
    /// adds the loader, files and source.
    public static func rows(_ strings: Strings, _ type: ServerTypeInfo, technical: Bool) -> [(String, String)] {
        func yesNo(_ value: Bool) -> String { strings.t(value ? "value.yes" : "value.no") }
        let content: String
        switch type.content {
        case nil: content = "new.content_none"
        case "plugins": content = "new.content_plugins"
        default: content = "new.content_mods"
        }
        var rows: [(String, String)] = [
            (strings.t("new.col_best_for"), strings.t("types.\(type.id).best")),
            (strings.t("new.col_content"), strings.t(content)),
            (strings.t("new.col_modrinth"), yesNo(type.modrinth)),
            (strings.t("new.col_crossplay"), yesNo(type.crossplay)),
            (strings.t("new.col_ease"), type.ease.map { strings.t("new.ease_\($0)") } ?? strings.t("value.unknown")),
        ]
        if technical {
            rows.append((strings.t("new.col_loader"), type.loaderName ?? strings.t("new.content_none")))
            rows.append((strings.t("new.col_metadata"), type.metadataFiles.isEmpty ? "—" : type.metadataFiles.joined(separator: ", ")))
            rows.append((strings.t("new.col_source"), type.versionSource ?? strings.t("value.unknown")))
        }
        return rows
    }

    /// The newest finished version, picked for the person.
    public static func firstVersion(_ versions: TypeVersions) -> OfferedVersion? {
        versions.versions.first { $0.minecraft == versions.latestStable }
            ?? versions.versions.first { $0.latest && $0.stable }
            ?? versions.versions.first { $0.stable }
    }

    /// A new folder named after the server inside the one picked on the PC.
    public static func folderFor(_ parent: String, _ name: String) -> String {
        let bad = Set("<>:\"/\\|?*")
        let safe = String(name.filter { !bad.contains($0) }).trimmingCharacters(in: .whitespaces)
        if safe.isEmpty { return parent }
        let slash = parent.contains("\\") ? "\\" : "/"
        var base = parent
        while base.hasSuffix("\\") || base.hasSuffix("/") { base.removeLast() }
        return base + slash + safe
    }

    public static func ready(name: String, folder: String, version: String?, ruled: Bool) -> Bool {
        !name.trimmingCharacters(in: .whitespaces).isEmpty && !folder.trimmingCharacters(in: .whitespaces).isEmpty && version != nil && ruled
    }

    /// The tick box: Minecraft's rules, and for Bedrock the Privacy Policy too.
    public static func ruleKey(_ edition: String) -> String { edition == "bedrock" ? "new.bedrock_tick" : "new.eula_tick" }

    /// A new server still being set up, to show its progress again.
    public static func creating(_ jobs: [Job]) -> Job? { jobs.first { $0.kind == "server_create" && $0.state == "running" } }

    /// What adding said: the server's name, then the agent's own warnings.
    public static func addedLines(_ strings: Strings, _ added: ServerAdded) -> [String] {
        [strings.t("add.added", ["name": added.server.name])] + added.warnings
    }
}

