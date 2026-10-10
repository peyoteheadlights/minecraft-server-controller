import XCTest
@testable import Core

final class DiagnosticsTests: XCTestCase {
    func testDiagnosticsHaveVersionsAndRequestsNothingThatSignsInOrFindsThePC() {
        let log = RequestLog(size: 2, clock: { Date(timeIntervalSince1970: 0) })
        log.line("GET /api/servers -> 200")
        log.line("GET /api/alerts -> 401")
        log.line("POST /api/auth/login -> 200")
        XCTAssertEqual(log.recent().count, 2)
        XCTAssertEqual(log.recent().first, "1970-01-01T00:00:00Z GET /api/alerts -> 401")
        let text = Diagnostics.text(
            Diagnostics.Facts(
                appVersion: "0.1.0", platform: "iOS", osVersion: "18.0", device: "iPhone",
                agentVersion: "1.3.0", agentApi: 1, paired: true, pinned: true,
                signedIn: true, lockScreenAlerts: nil, lastProblem: "mobile.error.unreachable"
            ),
            log: log.recent()
        )
        XCTAssertTrue(text.contains("App: 0.1.0 (iOS 18.0, iPhone)"), text)
        XCTAssertTrue(text.contains("Lock-screen alerts: Unknown"), text)
        XCTAssertTrue(text.contains("POST /api/auth/login -> 200"), text)
        XCTAssertFalse(text.contains("/api/servers"), text)
        for secret in ["token", "Bearer", "password", "ts.net", "fingerprint"] {
            XCTAssertNil(text.range(of: secret, options: .caseInsensitive), secret)
        }
    }
}
