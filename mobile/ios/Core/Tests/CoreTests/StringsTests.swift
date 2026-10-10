import XCTest
@testable import Core

final class StringsTests: XCTestCase {
    /// Every key written out in the app's Swift code, the same pattern as the
    /// Android app's StringsTest.
    private func usedKeys() throws -> Set<String> {
        let pattern = "\"((?:mobile|state|time|value|servers|hero|action|confirm|error|feed|theme|mode|login|page)\\.[a-z0-9_.]+)\""
        let regex = try NSRegularExpression(pattern: pattern)
        let roots = [
            Shared.ios.appendingPathComponent("Core/Sources"),
            Shared.ios.appendingPathComponent("ServerController"),
            Shared.ios.appendingPathComponent("ServerControllerWidget"),
            Shared.ios.appendingPathComponent("SharedUI"),
        ]
        var used = Set<String>()
        for root in roots {
            guard let walker = FileManager.default.enumerator(at: root, includingPropertiesForKeys: nil) else { continue }
            for case let file as URL in walker where file.pathExtension == "swift" {
                let text = try String(contentsOf: file, encoding: .utf8)
                let range = NSRange(text.startIndex..<text.endIndex, in: text)
                for match in regex.matches(in: text, range: range) {
                    if let r = Range(match.range(at: 1), in: text) {
                        used.insert(String(text[r]))
                    }
                }
            }
        }
        return used
    }

    func testEveryKeyTheAppUsesIsInTheTable() throws {
        let used = try usedKeys()
        XCTAssertGreaterThan(used.count, 20)
        let missing = used.filter { Shared.strings[$0] == nil }.sorted()
        XCTAssertEqual(missing, [], "missing from strings.json")
    }

    func testKeysTheAppBuildsFromPartsAreInTheTable() {
        var built: [String] = []
        for action in ["start", "stop", "restart"] {
            built.append("action.\(action)")
            built.append("mobile.server.done_\(action)")
        }
        for action in ["stop", "restart"] {
            built.append("confirm.\(action)_title")
            built.append("confirm.\(action)_body")
        }
        for topic in ["pairing", "unreachable", "certificate", "alerts", "signout"] {
            built.append("mobile.help.\(topic)_title")
            built.append("mobile.help.\(topic)_body")
        }
        for theme in ["system", "light", "dark", "graphite", "contrast"] {
            built.append("theme.\(theme)")
        }
        XCTAssertEqual(built.filter { Shared.strings[$0] == nil }, [])
    }

    func testBothWordingsExistAndTheAppsKeysAreItsOwn() throws {
        let data = try Data(contentsOf: Shared.mobile.appendingPathComponent("app-strings.json"))
        let app = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        for key in app.keys {
            XCTAssertTrue(key.hasPrefix("mobile."), key)
            XCTAssertEqual(Shared.strings[key]?.count, 2, key)
        }
        let s = Strings(Shared.strings)
        XCTAssertEqual(s.t("overview.players_unknown"), "Players not known")
        s.technical = true
        XCTAssertEqual(s.t("overview.players_unknown"), "Player list not read")
    }

    func testValuesFillInTranslationsFallBackToEnglish() {
        let s = Strings(
            ["a": ["Up for {duration}", "Up {duration}"], "b": ["Hi", "Hi"]],
            translated: ["a": ["Seit {duration}", "Seit {duration}"], "b": ["", ""]]
        )
        XCTAssertEqual(s.t("a", ["duration": "5m"]), "Seit 5m")
        XCTAssertEqual(s.t("b"), "Hi")
        XCTAssertEqual(s.t("nope"), "nope")
        XCTAssertEqual(Strings(Shared.strings).tn("head.players", count: 1), "1 player online")
        XCTAssertEqual(Strings(Shared.strings).tn("head.players", count: 3), "3 players online")
    }

    func testEveryAlertKindHasItsWords() {
        let feed = SharedFiles.parseFeed(Shared.data("feed.json"))
        XCTAssertGreaterThan(feed.count, 10)
        for (event, key) in feed {
            XCTAssertNotNil(Shared.strings[key], "\(event) -> \(key)")
        }
    }
}
