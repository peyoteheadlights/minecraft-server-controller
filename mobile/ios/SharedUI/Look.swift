import Core
import SwiftUI
import UIKit

// Colors and wording both the app and the widget use. The colors come from
// mobile/shared/theme.json (the dashboard's own themes) and a server's own
// color goes through ServerColors, so the phone matches the dashboard.

extension Color {
    /// "#RRGGBB" as a color, or nil for anything else.
    static func fromHex(_ hex: String?) -> Color? {
        guard let c = ServerColors.rgb(hex) else { return nil }
        return Color(red: Double(c[0]) / 255.0, green: Double(c[1]) / 255.0, blue: Double(c[2]) / 255.0)
    }
}

/// The app's look: the dashboard's theme names.
enum ThemeChoice: String, CaseIterable, Identifiable {
    case system
    case light
    case dark
    case graphite
    case contrast

    var id: String { rawValue }

    var labelKey: String {
        switch self {
        case .system: return "theme.system"
        case .light: return "theme.light"
        case .dark: return "theme.dark"
        case .graphite: return "theme.graphite"
        case .contrast: return "theme.contrast"
        }
    }

    /// Which theme.json entry to use: "Match my device" follows light or dark.
    func resolvedName(_ scheme: ColorScheme) -> String {
        if self == .system {
            return scheme == .dark ? "dark" : "light"
        }
        return rawValue
    }

    /// The light or dark system look under the theme; nil follows the device.
    var colorScheme: ColorScheme? {
        switch self {
        case .system: return nil
        case .light: return .light
        case .dark, .graphite, .contrast: return .dark
        }
    }
}

/// One theme's colors, by the dashboard's token names ("--sheet", ...).
struct Palette {
    let tokens: [String: String]

    func color(_ name: String, _ fallback: Color) -> Color {
        Color.fromHex(tokens[name]) ?? fallback
    }

    var sheet: Color { color("--sheet", Color(uiColor: .systemGroupedBackground)) }
    var surface: Color { color("--surface", Color(uiColor: .secondarySystemGroupedBackground)) }
    var sunken: Color { color("--surface-sunken", Color(uiColor: .tertiarySystemGroupedBackground)) }
    var textPrimary: Color { color("--text-primary", .primary) }
    var textSecondary: Color { color("--text-secondary", .secondary) }
    var accent: Color { color("--accent", .accentColor) }
    var accentText: Color { color("--accent-text", .white) }
    var accentInk: Color { color("--accent-ink", .accentColor) }
    var accentEdge: Color { color("--accent-edge", .gray) }
    var danger: Color { color("--danger", .red) }

    func tone(_ tone: Tone) -> Color {
        switch tone {
        case .success: return color("--success", .green)
        case .warning: return color("--warning", .orange)
        case .danger: return color("--danger", .red)
        case .neutral: return textSecondary
        }
    }

    /// The theme as theme.json has it.
    static func base(_ themes: [String: [String: String]], _ name: String) -> Palette {
        var tokens: [String: String] = [:]
        for (key, value) in themes[name] ?? [:] {
            tokens[key.hasPrefix("--") ? key : "--" + key] = value
        }
        return Palette(tokens: tokens)
    }

    /// The theme tinted with a server's color, as the dashboard tints that
    /// server's pages. A missing or broken color leaves the theme as it is.
    static func server(_ color: String?, _ themes: [String: [String: String]], _ name: String) -> Palette {
        let base = Palette.base(themes, name)
        var plain: [String: String] = [:]
        for (key, value) in themes[name] ?? [:] {
            plain[key.hasPrefix("--") ? String(key.dropFirst(2)) : key] = value
        }
        guard let color = color, let derived = ServerColors.derive(color, plain, name) else {
            return base
        }
        var tokens = base.tokens
        for (key, value) in derived {
            tokens[key] = value
        }
        return Palette(tokens: tokens)
    }
}

/// The bundled files, read once.
enum Bundled {
    static let english: [String: [String]] = {
        guard let data = SharedFiles.data("strings", "json", bundle: .main) else { return [:] }
        return Strings.parse(data)
    }()

    static let themes: [String: [String: String]] = {
        guard let data = SharedFiles.data("theme", "json", bundle: .main) else { return [:] }
        return ServerColors.parseThemes(data)
    }()

    static let feed: [String: String] = {
        guard let data = SharedFiles.data("feed", "json", bundle: .main) else { return [:] }
        return SharedFiles.parseFeed(data)
    }()

    static let apiRange: ApiRange = {
        guard let data = SharedFiles.data("version", "json", bundle: .main), let range = ApiRange.parse(data) else {
            return ApiRange(min: 1, max: 1)
        }
        return range
    }()

    static var appVersion: String {
        (Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String) ?? "0"
    }
}

/// A server's color as a small round badge, or a plain ring when it has none.
struct ColorBadge: View {
    let hex: String?
    var size: CGFloat = 14

    var body: some View {
        if let badge = ServerColors.badge(hex), let fill = Color.fromHex(badge.fill) {
            Circle()
                .fill(fill)
                .frame(width: size, height: size)
                .accessibilityHidden(true)
        } else {
            Circle()
                .strokeBorder(Color.secondary, lineWidth: 1.5)
                .frame(width: size, height: size)
                .accessibilityHidden(true)
        }
    }
}
