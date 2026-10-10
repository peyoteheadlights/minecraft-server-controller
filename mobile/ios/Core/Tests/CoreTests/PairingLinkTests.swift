import XCTest
@testable import Core

final class PairingLinkTests: XCTestCase {
    private let fp = String(repeating: "AB", count: 32)

    private func problem(_ text: String) -> PairingProblem? {
        do {
            _ = try PairingLink.parse(text)
            return nil
        } catch let error as PairingParseError {
            return error.problem
        } catch {
            return nil
        }
    }

    func testAPairingCodeGivesTheAddressPortFingerprintAndApi() throws {
        let p = try PairingLink.parse("https://My-PC.tail1234.ts.net:9000/?pair=1&fp=\(fp)&api=1")
        XCTAssertEqual(p, Pairing(host: "my-pc.tail1234.ts.net", port: 9000, fingerprint: fp.lowercased(), apiVersion: 1))
        XCTAssertEqual(p.origin, "https://my-pc.tail1234.ts.net:9000")
    }

    func testATypedAddressUsesTheAgentsPortAndHasNoFingerprint() throws {
        let p = try PairingLink.parse("  my-pc.tail1234.ts.net ")
        XCTAssertEqual(p.port, DEFAULT_PORT)
        XCTAssertNil(p.fingerprint)
        XCTAssertEqual(try PairingLink.parse("100.101.102.103:8000").port, 8000)
    }

    func testAnIPv6AddressKeepsItsBracketsInTheOrigin() throws {
        let p = try PairingLink.parse("[fd7a:115c:a1e0::1]:8765")
        XCTAssertEqual(p.origin, "https://[fd7a:115c:a1e0::1]:8765")
    }

    func testHttpAndOtherSchemesAreRefused() {
        for text in ["http://my-pc:8765", "ftp://my-pc", "javascript://x"] {
            XCTAssertEqual(problem(text), .notHttps, text)
        }
    }

    func testThingsThatArentAddressesAreRefused() {
        for text in ["", "my pc", "https://", "https://user:pw@my-pc", "https://my-pc:99999", "héllo"] {
            XCTAssertEqual(problem(text), .notAnAddress, text)
        }
    }

    func testAPairingCodeWithABrokenFingerprintIsRefused() {
        for bad in ["", "abc", String(repeating: "zz", count: 32), fp + "00"] {
            XCTAssertEqual(problem("https://my-pc:8765/?pair=1&fp=\(bad)"), .badFingerprint, bad)
        }
        XCTAssertEqual(problem("https://my-pc:8765/?pair=1"), .badFingerprint)
    }

    func testFingerprintsReadAsTheDashboardShowsThem() {
        XCTAssertEqual(formatFingerprint("abcd01"), "AB:CD:01")
    }

    func testDeepLinksCarryAServerIdSafely() throws {
        let url = try XCTUnwrap(DeepLink.server("my world/x"))
        XCTAssertEqual(url.absoluteString, "mcsc://server/my%20world%2Fx")
        XCTAssertEqual(DeepLink.serverId(from: url), "my world/x")
        XCTAssertNil(DeepLink.serverId(from: DeepLink.home))
        XCTAssertNil(DeepLink.serverId(from: try XCTUnwrap(URL(string: "https://server/x"))))
    }

    func testANewCodeKeepsTheSignInOnlyForTheSameAddressAndPort() {
        let current = Pairing(host: "my-pc.tail1234.ts.net", port: 9000, fingerprint: fp.lowercased())
        XCTAssertTrue(current.samePc(Pairing(host: "MY-PC.tail1234.ts.net", port: 9000, fingerprint: String(repeating: "cd", count: 32))))
        XCTAssertFalse(current.samePc(Pairing(host: "my-pc.tail1234.ts.net", port: 9001, fingerprint: nil)))
        XCTAssertFalse(current.samePc(Pairing(host: "other-pc.tail1234.ts.net", port: 9000, fingerprint: nil)))
    }
}
