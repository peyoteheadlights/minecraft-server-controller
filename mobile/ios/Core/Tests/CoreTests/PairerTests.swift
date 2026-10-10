import XCTest
@testable import Core

final class PairerTests: XCTestCase {
    private let range = ApiRange(min: 1, max: 1)
    private let fp = String(repeating: "cd", count: 32)

    override func setUp() {
        super.setUp()
        StubAgent.reset()
    }

    private func pairer() -> Pairer {
        Pairer(range: range, configuration: { StubAgent.configuration() })
    }

    func testThePairingCodesAgentPairsWithItsFingerprintAndApi() async {
        StubAgent.health()
        let result = await pairer().check(Pairing(host: "localhost", port: 8765, fingerprint: fp))
        guard case .paired(let pairing, let health) = result else {
            return XCTFail("\(result)")
        }
        XCTAssertEqual(pairing.fingerprint, fp)
        XCTAssertEqual(pairing.apiVersion, 1)
        XCTAssertEqual(health.agentUptime, 12.5)
        XCTAssertEqual(StubAgent.requests.first?.request.url?.path, "/api/health")
        XCTAssertNil(StubAgent.requests.first?.request.value(forHTTPHeaderField: "Authorization"))
    }

    func testSomethingThatIsntTheAgentIsRefused() async {
        let answers: [StubAgent.Answer] = [
            StubAgent.Answer(status: 200, headers: ["Content-Type": "text/html"], body: Data("<html>router</html>".utf8)),
            StubAgent.Answer(status: 200, headers: ["Content-Type": "application/json"], body: Data("{\"ok\": true}".utf8)),
            StubAgent.Answer(status: 200, headers: ["Content-Type": "application/json"], body: Data("not json".utf8)),
            StubAgent.Answer(status: 404, headers: ["Content-Type": "application/json"], body: Data("{\"detail\":\"Not Found\"}".utf8)),
            StubAgent.Answer(status: 401, headers: ["Content-Type": "application/json"], body: Data("{\"detail\":\"no\"}".utf8)),
        ]
        for answer in answers {
            StubAgent.reset()
            StubAgent.enqueue(answer)
            let result = await pairer().check(Pairing(host: "localhost", port: 8765, fingerprint: fp))
            XCTAssertEqual(result, .refused(problem: .notAnAgent), "\(answer.status)")
        }
    }

    func testAnAddressNothingAnswersAtIsUnreachable() async {
        let result = await pairer().check(Pairing(host: "localhost", port: 8765, fingerprint: fp))
        XCTAssertEqual(result, .refused(problem: .unreachable))
    }

    func testAnAgentWithAnApiThisAppDoesntSpeakIsNamedNotPaired() async {
        StubAgent.health(api: 2)
        let result = await pairer().check(Pairing(host: "localhost", port: 8765, fingerprint: fp))
        XCTAssertEqual(result, .incompatible(compatibility: .agentTooNew(agentApi: 2)))
        XCTAssertEqual(compatibility(1, ApiRange(min: 2, max: 3)), .agentTooOld(agentApi: 1))
        XCTAssertEqual(compatibility(2, ApiRange(min: 2, max: 3)), .ok)
    }

    func testConfirmingAFingerprintPinsIt() async {
        StubAgent.health()
        let typed = Pairing(host: "my-pc.tail1234.ts.net", port: 8765, fingerprint: nil)
        let result = await pairer().confirm(typed, fingerprint: fp)
        guard case .paired(let pairing, _) = result else {
            return XCTFail("\(result)")
        }
        XCTAssertEqual(pairing.fingerprint, fp)
    }

    func testTheBundledVersionFileGivesTheRange() {
        XCTAssertNotNil(ApiRange.parse(Shared.data("version.json")))
    }
}
