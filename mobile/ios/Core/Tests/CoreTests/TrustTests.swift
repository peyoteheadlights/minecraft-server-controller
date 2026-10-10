import CryptoKit
import Security
import XCTest
@testable import Core

/// The certificate rule, apart from TLS: a pinned certificate passes on its
/// fingerprint alone; otherwise only one the phone trusts, and never while
/// pairing from a code.
final class TrustTests: XCTestCase {
    /// A small self-signed certificate (CN=Test Agent, DNS:localhost), DER.
    private let certificateBase64 =
        "MIIBljCCATugAwIBAgIUCyoVdgffgaXDqJ2896FqVm3qnuUwCgYIKoZIzj0EAwIwFTETMBEGA1UEAwwKVGVzdCBBZ2VudDAeFw0yNjEwMDkyMjUwNDJaFw0zNjEwMDYyMjUwNDJaMBUxEzARBgNVBAMMClRlc3QgQWdlbnQwWTATBgcqhkjOPQIBBggqhkjOPQMBBwNCAATS84KRZ73r9JtgzZB8SFBjzDeF2CD/gUXHmIFmP2EFBWkiE5Wzwrz75X4kVrWN066znFEhevaPGNYtd30lJjpgo2kwZzAdBgNVHQ4EFgQU1zJ8Q880VaCTfhQRk4zYrbmVJB4wHwYDVR0jBBgwFoAU1zJ8Q880VaCTfhQRk4zYrbmVJB4wDwYDVR0TAQH/BAUwAwEB/zAUBgNVHREEDTALgglsb2NhbGhvc3QwCgYIKoZIzj0EAwIDSQAwRgIhALt4p4c+twm3WSx0iUjZYpp5eTpsYk/J/wk65Hkvp404AiEAvuikZuD6JaM0XQK+YEWIGtgTFkbbokbT2PV6cdFsMN0="
    /// `sha256sum` of the DER file.
    private let expected = "dcd563389706762536c2f9da8ed48beaa765a8dfab00b8b9c19347b38f2068bb"

    func testTheFingerprintIsTheSha256OfTheCertificate() throws {
        let der = try XCTUnwrap(Data(base64Encoded: certificateBase64))
        let certificate = try XCTUnwrap(SecCertificateCreateWithData(nil, der as CFData))
        let byCryptoKit = SHA256.hash(data: der).map { String(format: "%02x", $0) }.joined()
        XCTAssertEqual(byCryptoKit, expected)
        XCTAssertEqual(certificateFingerprint(certificate), expected)
        XCTAssertEqual(certificateFingerprint(der: der), expected)
    }

    func testThePinnedCertificatePassesEvenIfThePhoneDoesntTrustIt() {
        let trust = PinnedTrust(pin: expected, strict: true)
        XCTAssertEqual(trust.decide(leafFingerprint: expected, systemTrusted: false), .accept)
        let typed = PinnedTrust(pin: expected, strict: false)
        XCTAssertEqual(typed.decide(leafFingerprint: expected, systemTrusted: false), .accept)
    }

    func testWhilePairingFromACodeADifferentCertificateIsRefusedEvenATrustedOne() {
        let trust = PinnedTrust(pin: expected, strict: true)
        let other = String(repeating: "00", count: 32)
        var asked = false
        let decision = trust.decide(leafFingerprint: other, systemTrusted: { () -> Bool in asked = true; return true }())
        XCTAssertEqual(decision, .mismatch(presented: other))
        XCTAssertFalse(asked, "the phone's trust store isn't even asked")
    }

    func testAfterPairingATrustedRenewedCertificatePasses() {
        let trust = PinnedTrust(pin: expected, strict: false)
        let renewed = String(repeating: "11", count: 32)
        XCTAssertEqual(trust.decide(leafFingerprint: renewed, systemTrusted: true), .accept)
        XCTAssertEqual(trust.decide(leafFingerprint: renewed, systemTrusted: false), .mismatch(presented: renewed))
    }

    func testWithoutAPinOnlyATrustedCertificatePasses() {
        let trust = PinnedTrust(pin: nil, strict: false)
        XCTAssertEqual(trust.decide(leafFingerprint: expected, systemTrusted: true), .accept)
        XCTAssertEqual(trust.decide(leafFingerprint: expected, systemTrusted: false), .notTrusted(presented: expected))
    }

    func testAPinIsComparedInLowercase() {
        let trust = PinnedTrust(pin: expected.uppercased(), strict: true)
        XCTAssertEqual(trust.decide(leafFingerprint: expected, systemTrusted: false), .accept)
    }

    func testAnExpiredPinnedCertificateIsRefused() {
        let trust = PinnedTrust(pin: expected, strict: false)
        XCTAssertEqual(trust.decide(leafFingerprint: expected, systemTrusted: false, expired: true), .expired(presented: expected))
        XCTAssertEqual(trust.decide(leafFingerprint: expected, systemTrusted: false, expired: false), .accept)
        // Any other certificate is decided as before; the dates are in the phone's own check.
        let other = String(repeating: "22", count: 32)
        XCTAssertEqual(trust.decide(leafFingerprint: other, systemTrusted: true, expired: true), .accept)
    }

    func testTheCertificatesOwnDatesAreRead() throws {
        // The test certificate is valid from 2026-10-09 to 2036-10-06.
        let der = try XCTUnwrap(Data(base64Encoded: certificateBase64))
        let certificate = try XCTUnwrap(SecCertificateCreateWithData(nil, der as CFData))
        let year: (Int) -> Date = { y in
            DateComponents(calendar: Calendar(identifier: .gregorian), timeZone: TimeZone(identifier: "UTC"), year: y, month: 6, day: 1).date!
        }
        XCTAssertFalse(PinnedTrust.outsideItsDates(certificate, at: year(2027)))
        XCTAssertTrue(PinnedTrust.outsideItsDates(certificate, at: year(2039)))
        XCTAssertTrue(PinnedTrust.outsideItsDates(certificate, at: year(2023)))
    }

    func testAnExpiredCertificateIsNamedAsSuch() {
        let client = AgentClient(
            pairing: Pairing(host: "localhost", port: 8765, fingerprint: expected),
            token: { nil },
            configuration: StubAgent.configuration()
        )
        XCTAssertEqual(AgentError.certificateExpired.key, "mobile.error.certificate_expired")
        XCTAssertNotEqual(Strings(Shared.strings).t(AgentError.certificateExpired.key), "mobile.error.certificate_expired")
        // Without a refusal recorded, a failed handshake is not called expired.
        XCTAssertNotEqual(client.translateFailure(URLError(.serverCertificateHasBadDate)), .certificateExpired)
    }

    func testARefusedCertificateIsToldApartFromNoAnswer() {
        let client = AgentClient(
            pairing: Pairing(host: "localhost", port: 8765, fingerprint: expected),
            token: { nil },
            configuration: StubAgent.configuration()
        )
        XCTAssertEqual(client.translateFailure(URLError(.cannotConnectToHost)), .unreachable)
        XCTAssertEqual(client.translateFailure(URLError(.timedOut)), .unreachable)
        XCTAssertEqual(client.translateFailure(URLError(.secureConnectionFailed)), .notAnAgent)
    }
}
