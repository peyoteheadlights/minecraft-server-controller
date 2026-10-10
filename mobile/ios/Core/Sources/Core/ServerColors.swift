import Foundation

/// A server's color carried through its whole screen, the same sums as the
/// dashboard's agent/web/js/colors.js (deriveFrom): the screen, cards and
/// sunken areas take a little of the color, buttons are filled with it, and
/// every color people read is shaded until it passes WCAG AA (4.5:1 for
/// text, 3:1 for marks). ServerColorsTests checks every palette color in
/// every theme against what colors.js itself gives (mobile/shared/color-cases.json).
public enum ServerColors {
    public static let AA_TEXT = 4.5
    public static let AA_MARK = 3.0

    public typealias RGB = [Int]

    static let BLACK: RGB = [0, 0, 0]
    static let WHITE: RGB = [255, 255, 255]

    public static func rgb(_ hex: String?) -> RGB? {
        guard var text = hex?.trimmingCharacters(in: .whitespacesAndNewlines) else { return nil }
        if text.hasPrefix("#") {
            text.removeFirst()
        }
        guard text.count == 6, text.allSatisfy({ $0.isHexDigit && $0.isASCII }), let n = Int(text, radix: 16) else {
            return nil
        }
        return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
    }

    public static func hex(_ color: RGB) -> String {
        let digits = Array("0123456789ABCDEF")
        var out = "#"
        for value in color {
            let c = Swift.max(0, Swift.min(255, value))
            out.append(digits[c / 16])
            out.append(digits[c % 16])
        }
        return out
    }

    private static func channel(_ c: Int) -> Double {
        let s = Double(c) / 255.0
        return s <= 0.04045 ? s / 12.92 : pow((s + 0.055) / 1.055, 2.4)
    }

    public static func luminance(_ color: RGB) -> Double {
        0.2126 * channel(color[0]) + 0.7152 * channel(color[1]) + 0.0722 * channel(color[2])
    }

    public static func contrast(_ a: RGB, _ b: RGB) -> Double {
        let la = luminance(a)
        let lb = luminance(b)
        return (Swift.max(la, lb) + 0.05) / (Swift.min(la, lb) + 0.05)
    }

    /// JavaScript's Math.round: halves go up.
    private static func jsRound(_ x: Double) -> Int {
        Int((x + 0.5).rounded(.down))
    }

    public static func mix(_ a: RGB, _ b: RGB, _ amount: Double) -> RGB {
        (0..<3).map { i in jsRound(Double(a[i]) + Double(b[i] - a[i]) * amount) }
    }

    public static func readable(_ color: RGB, _ backgrounds: [RGB], minimum: Double = AA_TEXT) -> RGB {
        let darkest = backgrounds.map { luminance($0) }.min() ?? 0
        let target = darkest > 0.18 ? BLACK : WHITE
        for step in 0...20 {
            let candidate = mix(color, target, Double(step) / 20.0)
            if backgrounds.allSatisfy({ contrast(candidate, $0) >= minimum }) {
                return candidate
            }
        }
        return target
    }

    public struct Fill: Equatable {
        public let fill: RGB
        public let text: RGB
    }

    public static func fillWithText(_ color: RGB) -> Fill {
        let dark: RGB = [17, 17, 17]
        let textIsWhite = contrast(color, WHITE) >= contrast(color, dark)
        let text = textIsWhite ? WHITE : dark
        let away = textIsWhite ? BLACK : WHITE
        for step in 0...20 {
            let fill = mix(color, away, Double(step) / 20.0)
            if contrast(fill, text) >= AA_TEXT {
                return Fill(fill: fill, text: text)
            }
        }
        return Fill(fill: away, text: text)
    }

    private struct Amounts {
        let sheet: Double
        let surface: Double
        let sunken: Double
        let band: Double
    }

    private static func tintAmounts(dark: Bool, theme: String) -> Amounts {
        if theme == "contrast" { return Amounts(sheet: 0.1, surface: 0.06, sunken: 0.1, band: 0.2) }
        if dark { return Amounts(sheet: 0.18, surface: 0.13, sunken: 0.16, band: 0.3) }
        return Amounts(sheet: 0.2, surface: 0.07, sunken: 0.18, band: 0.32)
    }

    private static func keepReadable(_ color: RGB?, before: [RGB], after: [RGB], floor: Double = AA_TEXT) -> RGB? {
        guard let color = color else { return nil }
        let was = before.map { contrast(color, $0) }.min() ?? floor
        return readable(color, after, minimum: Swift.min(floor, was))
    }

    /// Every token a server's color sets, as "#RRGGBB" (and "--accent-soft" as
    /// an rgba() string), for theme tokens `k` ("sheet" -> "#F7F7F9", without
    /// the leading dashes) of the theme named `theme` ("light", "dark",
    /// "graphite", "contrast"). Keys of the result keep their dashes.
    public static func derive(_ baseHex: String, _ k: [String: String], _ theme: String) -> [String: String]? {
        guard let base = rgb(baseHex) else { return nil }
        func tok(_ name: String) -> RGB? { rgb(k[name]) }
        let sheet0 = tok("sheet") ?? WHITE
        let surface0 = tok("surface") ?? WHITE
        let sunken0 = tok("surface-sunken") ?? surface0
        let float0 = tok("surface-float") ?? surface0
        let desk = tok("desk") ?? WHITE
        let dark = luminance(sheet0) < 0.18
        let amount = tintAmounts(dark: dark, theme: theme)
        let sheet = mix(sheet0, base, amount.sheet)
        let surface = mix(surface0, base, amount.surface)
        let sunken = mix(sunken0, base, amount.sunken)
        let float = mix(float0, base, amount.surface)
        let band = mix(sheet0, base, amount.band)
        let before = [sheet0, surface0, sunken0]
        let after = [sheet, surface, sunken, band]
        func textOn(_ name: String) -> RGB? { keepReadable(tok(name), before: before, after: after) }
        let fill = fillWithText(base)
        let hover = fillWithText(mix(fill.fill, dark ? WHITE : BLACK, 0.12))
        let ink = readable(base, [surface, sheet, band])
        let ring = readable(base, [surface, sheet], minimum: AA_MARK)
        let tab = mix(desk, base, dark ? 0.32 : 0.24)
        let tokens: [(String, RGB?)] = [
            ("--sheet", sheet),
            ("--surface", surface),
            ("--surface-sunken", sunken),
            ("--surface-float", float),
            ("--text-primary", textOn("text-primary")),
            ("--text-secondary", textOn("text-secondary")),
            ("--text-tertiary", textOn("text-tertiary")),
            ("--success", textOn("success")),
            ("--warning", textOn("warning")),
            ("--danger", textOn("danger")),
            ("--accent", fill.fill),
            ("--accent-text", fill.text),
            ("--accent-hover", hover.fill),
            ("--accent-hover-text", hover.text),
            ("--accent-ink", ink),
            ("--accent-band", band),
            ("--accent-edge", base),
            ("--accent-ring", ring),
            ("--tab-fill", tab),
            ("--tab-text", readable(tok("text-primary") ?? BLACK, [tab])),
        ]
        var out: [String: String] = [:]
        for (name, value) in tokens {
            if let value = value {
                out[name] = hex(value)
            }
        }
        let parts = base.map { String($0) }.joined(separator: ", ")
        out["--accent-soft"] = "rgba(\(parts), \(dark ? "0.2" : "0.13"))"
        return out
    }

    /// A server's badge: its color as a fill, with text that reads on it,
    /// as ("#RRGGBB" fill, "#RRGGBB" text).
    public static func badge(_ baseHex: String?) -> (fill: String, text: String)? {
        guard let base = rgb(baseHex) else { return nil }
        let f = fillWithText(base)
        return (hex(f.fill), hex(f.text))
    }

    /// The themes in mobile/shared/theme.json: name -> token -> "#RRGGBB".
    /// Tokens that aren't plain colors (a color with alpha) are left out.
    public static func parseThemes(_ data: Data) -> [String: [String: String]] {
        guard let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return [:]
        }
        var out: [String: [String: String]] = [:]
        for (name, value) in root {
            guard let tokens = value as? [String: Any] else { continue }
            var plain: [String: String] = [:]
            for (token, raw) in tokens {
                if let text = raw as? String {
                    plain[token] = text
                }
            }
            out[name] = plain
        }
        return out
    }
}
