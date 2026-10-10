import CryptoKit
import Foundation
import Security

/// SHA-256 of a certificate's DER bytes, as 64 lowercase hex digits.
public func certificateFingerprint(der: Data) -> String {
    let digest = SHA256.hash(data: der)
    return digest.map { byte -> String in
        let text = String(byte, radix: 16)
        return text.count == 1 ? "0" + text : text
    }.joined()
}

/// SHA-256 of a certificate, as 64 lowercase hex digits.
public func certificateFingerprint(_ certificate: SecCertificate) -> String {
    let der = SecCertificateCopyData(certificate) as Data
    return certificateFingerprint(der: der)
}

/// What the certificate check decided for one connection.
public enum TrustDecision: Equatable, Sendable {
    /// The pinned certificate, or one the phone trusts with the normal checks.
    case accept
    /// The certificate wasn't the one the pairing code named.
    case mismatch(presented: String)
    /// No pin matched and the phone doesn't trust the certificate either.
    case notTrusted(presented: String)
}

/// How the app checks the agent's certificate. Certificate checks are never
/// switched off; a certificate passes in exactly one of two ways:
///
///  1. Its SHA-256 equals `pin`, the fingerprint from the pairing code (the
///     PC's own certificate from installer/make_certs.py, whoever issued it).
///     It is accepted for the address it was paired with even if its names
///     don't include it (a typed Tailscale IP, say).
///  2. Not `strict`, and the phone's own trust store accepts it with the
///     normal checks, including the host name (a Tailscale certificate,
///     renewed every few months).
///
/// While pairing from a code, `strict` is on: only the certificate the code
/// names is accepted, so a different one is refused even if trusted.
public final class PinnedTrust: NSObject, URLSessionDelegate, @unchecked Sendable {
    public let pin: String?
    public let strict: Bool

    private let lock = NSLock()
    private var presented: String?
    private var refusal: TrustDecision?

    public init(pin: String?, strict: Bool) {
        self.pin = pin?.lowercased()
        self.strict = strict
        super.init()
    }

    /// The fingerprint of the certificate the PC last presented.
    public var lastPresented: String? {
        lock.lock()
        defer { lock.unlock() }
        return presented
    }

    /// Why the last refused connection was refused; cleared when a
    /// connection is accepted.
    public var lastRefusal: TrustDecision? {
        lock.lock()
        defer { lock.unlock() }
        return refusal
    }

    /// The rule itself, apart from the TLS plumbing. `systemTrusted` is only
    /// asked when the pin doesn't decide.
    public func decide(leafFingerprint: String, systemTrusted: @autoclosure () -> Bool) -> TrustDecision {
        if let pin = pin, leafFingerprint == pin {
            return .accept
        }
        if strict, pin != nil {
            return .mismatch(presented: leafFingerprint)
        }
        if systemTrusted() {
            return .accept
        }
        // Any refusal is a refusal: never fall through to accepting.
        if pin != nil {
            return .mismatch(presented: leafFingerprint)
        }
        return .notTrusted(presented: leafFingerprint)
    }

    public func urlSession(
        _ session: URLSession,
        didReceive challenge: URLAuthenticationChallenge,
        completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void
    ) {
        guard challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodServerTrust else {
            // Client certificates and passwords: this app never answers them.
            completionHandler(.performDefaultHandling, nil)
            return
        }
        guard let trust = challenge.protectionSpace.serverTrust,
              let chain = SecTrustCopyCertificateChain(trust) as? [SecCertificate],
              let leaf = chain.first
        else {
            completionHandler(.cancelAuthenticationChallenge, nil)
            return
        }
        let fingerprint = certificateFingerprint(leaf)
        let host = challenge.protectionSpace.host
        let decision = decide(
            leafFingerprint: fingerprint,
            systemTrusted: PinnedTrust.systemTrusts(trust, host: host)
        )
        record(presented: fingerprint, decision: decision)
        if decision == .accept {
            completionHandler(.useCredential, URLCredential(trust: trust))
        } else {
            completionHandler(.cancelAuthenticationChallenge, nil)
        }
    }

    private func record(presented fingerprint: String, decision: TrustDecision) {
        lock.lock()
        presented = fingerprint
        refusal = decision == .accept ? nil : decision
        lock.unlock()
    }

    /// The phone's own trust store, with the normal TLS checks for `host`.
    static func systemTrusts(_ trust: SecTrust, host: String) -> Bool {
        let policy = SecPolicyCreateSSL(true, host as CFString)
        guard SecTrustSetPolicies(trust, policy) == errSecSuccess else { return false }
        var error: CFError?
        return SecTrustEvaluateWithError(trust, &error)
    }
}
