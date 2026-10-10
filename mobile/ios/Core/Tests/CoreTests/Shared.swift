import Foundation
@testable import Core

/// The files mobile/tools/generate.py writes, which both apps bundle, found
/// by walking up from this file to mobile/.
enum Shared {
    static let mobile: URL = {
        var url = URL(fileURLWithPath: #filePath)
        while url.lastPathComponent != "mobile" && url.pathComponents.count > 1 {
            url.deleteLastPathComponent()
        }
        return url
    }()

    static let ios: URL = mobile.appendingPathComponent("ios")

    static func data(_ name: String) -> Data {
        let url = mobile.appendingPathComponent("shared").appendingPathComponent(name)
        return (try? Data(contentsOf: url)) ?? Data()
    }

    static let strings: [String: [String]] = Strings.parse(data("strings.json"))
}

/// A pretend agent: answers requests from a queue, without a network.
/// TLS isn't involved, so certificate checks are tested on their own
/// (TrustTests).
final class StubAgent: URLProtocol {
    struct Answer {
        var status: Int
        var headers: [String: String]
        var body: Data
    }

    struct Seen {
        var request: URLRequest
        var body: Data
    }

    private static let lock = NSLock()
    private static var answers: [Answer] = []
    private static var seen: [Seen] = []

    static func reset() {
        lock.lock()
        answers = []
        seen = []
        lock.unlock()
    }

    static func enqueue(_ answer: Answer) {
        lock.lock()
        answers.append(answer)
        lock.unlock()
    }

    static func json(_ body: String, status: Int = 200, headers: [String: String] = [:]) {
        var all = headers
        all["Content-Type"] = "application/json"
        enqueue(Answer(status: status, headers: all, body: Data(body.utf8)))
    }

    static func health(api: Int = 1) {
        json("{\"ok\": true, \"agent_uptime\": 12.5, \"auth_configured\": true, \"api_version\": \(api)}")
    }

    static var requests: [Seen] {
        lock.lock()
        defer { lock.unlock() }
        return seen
    }

    static func configuration() -> URLSessionConfiguration {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [StubAgent.self]
        return config
    }

    override class func canInit(with request: URLRequest) -> Bool { true }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        let body = StubAgent.readBody(request)
        StubAgent.lock.lock()
        StubAgent.seen.append(Seen(request: request, body: body))
        let answer: Answer? = StubAgent.answers.isEmpty ? nil : StubAgent.answers.removeFirst()
        StubAgent.lock.unlock()

        guard let answer = answer, let url = request.url,
              let response = HTTPURLResponse(url: url, statusCode: answer.status, httpVersion: "HTTP/1.1", headerFields: answer.headers)
        else {
            client?.urlProtocol(self, didFailWithError: URLError(.cannotConnectToHost))
            return
        }
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: answer.body)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}

    /// URLSession hands a body to a URLProtocol as a stream.
    private static func readBody(_ request: URLRequest) -> Data {
        if let body = request.httpBody {
            return body
        }
        guard let stream = request.httpBodyStream else { return Data() }
        stream.open()
        defer { stream.close() }
        var out = Data()
        var buffer = [UInt8](repeating: 0, count: 4096)
        while stream.hasBytesAvailable {
            let count = stream.read(&buffer, maxLength: buffer.count)
            if count <= 0 { break }
            out.append(buffer, count: count)
        }
        return out
    }
}
