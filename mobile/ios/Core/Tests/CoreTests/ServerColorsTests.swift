import XCTest
@testable import Core

/// The app tints a server's screens with exactly the colors the dashboard
/// does: every palette color in every theme, against colors.js's own output.
final class ServerColorsTests: XCTestCase {
    private let themes = ServerColors.parseThemes(Shared.data("theme.json"))

    private func tokens(_ theme: String) -> [String: String] {
        var out: [String: String] = [:]
        for (key, value) in themes[theme] ?? [:] {
            out[key.hasPrefix("--") ? String(key.dropFirst(2)) : key] = value
        }
        return out
    }

    func testEveryColorInEveryThemeMatchesTheDashboard() throws {
        let cases = try XCTUnwrap(JSONSerialization.jsonObject(with: Shared.data("color-cases.json")) as? [[String: Any]])
        XCTAssertGreaterThanOrEqual(cases.count, 40)
        for item in cases {
            let theme = try XCTUnwrap(item["theme"] as? String)
            let base = try XCTUnwrap(item["base"] as? String)
            let expected = try XCTUnwrap(item["tokens"] as? [String: String])
            XCTAssertEqual(ServerColors.derive(base, tokens(theme), theme), expected, "\(theme) \(base)")
        }
    }

    func testColorsPeopleReadPassWcagAA() throws {
        XCTAssertEqual(Set(themes.keys), ["light", "dark", "graphite", "contrast"])
        for theme in themes.keys {
            for base in ["#FFFF00", "#000000", "#FFFFFF", "#7F7F7F", "#1967D4"] {
                let out = try XCTUnwrap(ServerColors.derive(base, tokens(theme), theme))
                func c(_ name: String) throws -> [Int] {
                    try XCTUnwrap(ServerColors.rgb(out[name]))
                }
                for bg in ["--surface", "--sheet"] {
                    XCTAssertGreaterThanOrEqual(ServerColors.contrast(try c("--accent-ink"), try c(bg)), 4.5, "\(theme) \(base) text on \(bg)")
                }
                XCTAssertGreaterThanOrEqual(ServerColors.contrast(try c("--accent"), try c("--accent-text")), 4.5, "\(theme) \(base) button")
            }
        }
    }

    func testAColorThatIsntOneIsIgnored() {
        XCTAssertNil(ServerColors.derive("red", [:], "light"))
        XCTAssertNil(ServerColors.badge(nil))
        let badge = ServerColors.badge("#ffffff")
        XCTAssertEqual(badge?.fill, "#FFFFFF")
        XCTAssertEqual(badge?.text, "#111111")
    }
}
