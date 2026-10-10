import Foundation

/// The agent's port when an address is typed without one (config.example.yaml).
public let DEFAULT_PORT = 8765

/// Which PC the app talks to: its address and, from the pairing code, the
/// SHA-256 fingerprint of its certificate (64 lowercase hex digits).
///
/// The pairing code is an ordinary link (agent/pairing.py):
///   https://<address>:<port>/?pair=1&fp=<certificate SHA-256>&api=<API version>
/// A typed address has no fingerprint: the app then only accepts a
/// certificate the phone already trusts, or one the person confirms by
/// comparing the fingerprint shown in the dashboard.
public struct Pairing: Codable, Equatable, Hashable, Sendable {
    public var host: String
    public var port: Int
    public var fingerprint: String?
    public var apiVersion: Int?

    public init(host: String, port: Int, fingerprint: String?, apiVersion: Int? = nil) {
        self.host = host
        self.port = port
        self.fingerprint = fingerprint
        self.apiVersion = apiVersion
    }

    public var origin: String {
        let shown = host.contains(":") ? "[\(host)]" : host
        return "https://\(shown):\(port)"
    }
}

public enum PairingProblem: Equatable, Sendable {
    /// Nothing that looks like an address or a pairing link.
    case notAnAddress
    /// http:// or another scheme: only HTTPS is ever used.
    case notHttps
    /// A pairing link whose fingerprint isn't 64 hex digits.
    case badFingerprint

    public var key: String {
        switch self {
        case .notAnAddress: return "mobile.pair.error_not_address"
        case .notHttps: return "mobile.pair.error_not_https"
        case .badFingerprint: return "mobile.pair.error_bad_code"
        }
    }
}

public struct PairingParseError: Error, Equatable {
    public let problem: PairingProblem
    public init(_ problem: PairingProblem) { self.problem = problem }
}

public enum PairingLink {
    /// A scanned code or a typed address. Throws `PairingParseError`.
    public static func parse(_ input: String) throws -> Pairing {
        let text = input.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.isEmpty || text.unicodeScalars.contains(where: { CharacterSet.whitespacesAndNewlines.contains($0) }) {
            throw PairingParseError(.notAnAddress)
        }
        let rest: String
        if text.lowercased().hasPrefix("https://") {
            rest = String(text.dropFirst("https://".count))
        } else if text.contains("://") {
            throw PairingParseError(.notHttps)
        } else {
            rest = text
        }
        // Only plain ASCII addresses: anything else isn't one the agent has.
        if !rest.unicodeScalars.allSatisfy({ $0.isASCII }) {
            throw PairingParseError(.notAnAddress)
        }

        // authority [/path] [?query] [#fragment]
        var authorityEnd = rest.endIndex
        if let stop = rest.firstIndex(where: { $0 == "/" || $0 == "?" || $0 == "#" }) {
            authorityEnd = stop
        }
        let authority = String(rest[rest.startIndex..<authorityEnd])
        let tail = String(rest[authorityEnd...])
        var query: String? = nil
        if let q = tail.firstIndex(of: "?") {
            var raw = String(tail[tail.index(after: q)...])
            if let hash = raw.firstIndex(of: "#") {
                raw = String(raw[raw.startIndex..<hash])
            }
            query = raw
        }

        if authority.isEmpty || authority.contains("@") {
            throw PairingParseError(.notAnAddress)
        }
        let (host, portText) = try splitHostPort(authority)
        let port: Int
        if let portText = portText, !portText.isEmpty {
            guard portText.allSatisfy({ ($0.asciiValue ?? 0) >= 48 && ($0.asciiValue ?? 0) <= 57 }), let value = Int(portText) else {
                throw PairingParseError(.notAnAddress)
            }
            port = value
        } else {
            port = DEFAULT_PORT
        }
        if port < 1 || port > 65535 {
            throw PairingParseError(.notAnAddress)
        }

        let fields = parseQuery(query)
        if fields["pair"] != "1" {
            return Pairing(host: host.lowercased(), port: port, fingerprint: nil)
        }
        guard let fp = fields["fp"], isHex64(fp) else {
            throw PairingParseError(.badFingerprint)
        }
        let api = fields["api"].flatMap { Int($0) }
        return Pairing(host: host.lowercased(), port: port, fingerprint: fp.lowercased(), apiVersion: api)
    }

    /// "[v6]:port", "[v6]", "name:port" or "name".
    private static func splitHostPort(_ authority: String) throws -> (String, String?) {
        if authority.hasPrefix("[") {
            guard let close = authority.firstIndex(of: "]") else {
                throw PairingParseError(.notAnAddress)
            }
            let host = String(authority[authority.index(after: authority.startIndex)..<close])
            let after = String(authority[authority.index(after: close)...])
            if !host.isEmpty, host.allSatisfy({ isHexDigit($0) || $0 == ":" }), host.contains(":") {
                if after.isEmpty { return (host, nil) }
                if after.hasPrefix(":") { return (host, String(after.dropFirst())) }
            }
            throw PairingParseError(.notAnAddress)
        }
        let parts = authority.split(separator: ":", omittingEmptySubsequences: false)
        if parts.count > 2 {
            throw PairingParseError(.notAnAddress)
        }
        let host = String(parts[0])
        if host.isEmpty || !host.allSatisfy({ isNameCharacter($0) }) {
            throw PairingParseError(.notAnAddress)
        }
        return (host, parts.count == 2 ? String(parts[1]) : nil)
    }

    private static func isHexDigit(_ c: Character) -> Bool {
        guard let v = c.asciiValue else { return false }
        return (v >= 48 && v <= 57) || (v >= 65 && v <= 70) || (v >= 97 && v <= 102)
    }

    private static func isNameCharacter(_ c: Character) -> Bool {
        guard let v = c.asciiValue else { return false }
        let digit = v >= 48 && v <= 57
        let upper = v >= 65 && v <= 90
        let lower = v >= 97 && v <= 122
        return digit || upper || lower || c == "." || c == "-"
    }

    static func isHex64(_ text: String) -> Bool {
        text.count == 64 && text.allSatisfy { isHexDigit($0) }
    }

    private static func parseQuery(_ raw: String?) -> [String: String] {
        guard let raw = raw, !raw.isEmpty else { return [:] }
        var out: [String: String] = [:]
        for part in raw.split(separator: "&", omittingEmptySubsequences: false) {
            guard let eq = part.firstIndex(of: "="), eq != part.startIndex else { continue }
            let key = String(part[part.startIndex..<eq])
            let encoded = String(part[part.index(after: eq)...]).replacingOccurrences(of: "+", with: " ")
            guard let value = encoded.removingPercentEncoding else { continue }
            out[key] = value
        }
        return out
    }
}

/// "ab12…" as the dashboard shows it in Technical mode: pairs split by colons.
public func formatFingerprint(_ hex: String) -> String {
    let upper = Array(hex.uppercased())
    var pairs: [String] = []
    var index = 0
    while index < upper.count {
        let end = min(index + 2, upper.count)
        pairs.append(String(upper[index..<end]))
        index += 2
    }
    return pairs.joined(separator: ":")
}
