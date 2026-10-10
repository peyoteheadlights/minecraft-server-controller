import Foundation

/// Which agent API versions this app works with (mobile/version.json).
public struct ApiRange: Equatable, Sendable {
    public let min: Int
    public let max: Int

    public init(min: Int, max: Int) {
        self.min = min
        self.max = max
    }

    /// From the bundled version.json: {"agent_api": {"min": 1, "max": 1}}.
    public static func parse(_ data: Data) -> ApiRange? {
        guard let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let api = root["agent_api"] as? [String: Any],
              let low = api["min"] as? Int,
              let high = api["max"] as? Int
        else { return nil }
        return ApiRange(min: low, max: high)
    }
}

public enum Compatibility: Equatable, Sendable {
    case ok
    /// The agent is older than this app needs: update the app on the PC.
    case agentTooOld(agentApi: Int)
    /// The agent is newer than this app knows: update the phone app.
    case agentTooNew(agentApi: Int)

    public var key: String? {
        switch self {
        case .ok: return nil
        case .agentTooOld: return "mobile.pair.too_old"
        case .agentTooNew: return "mobile.pair.too_new"
        }
    }
}

public func compatibility(_ agentApi: Int, _ range: ApiRange) -> Compatibility {
    if agentApi < range.min { return .agentTooOld(agentApi: agentApi) }
    if agentApi > range.max { return .agentTooNew(agentApi: agentApi) }
    return .ok
}

/// What checking an address found.
public enum PairResult: Equatable, Sendable {
    /// It is this app's agent, with the certificate the code named (or one
    /// the phone trusts) and an API this app speaks: save `pairing`.
    case paired(pairing: Pairing, health: Health)
    /// A typed address with a certificate the phone doesn't trust: show
    /// `fingerprint` and ask the person to compare it with the dashboard's.
    case confirmFingerprint(pairing: Pairing, fingerprint: String)
    case refused(problem: AgentError)
    case incompatible(compatibility: Compatibility)
}

/// Checks an address before anything else is sent to it: only /api/health,
/// which needs no sign-in and reveals nothing. Refuses a certificate that
/// isn't the one the pairing code names, and an answer that isn't the agent's.
public final class Pairer {
    private let range: ApiRange
    private let log: AgentLog
    private let configuration: () -> URLSessionConfiguration

    public init(
        range: ApiRange,
        log: AgentLog = NoLog(),
        configuration: @escaping () -> URLSessionConfiguration = { URLSessionConfiguration.ephemeral }
    ) {
        self.range = range
        self.log = log
        self.configuration = configuration
    }

    public func check(_ pairing: Pairing) async -> PairResult {
        let client = AgentClient(
            pairing: pairing,
            token: { nil },
            log: log,
            strict: pairing.fingerprint != nil,
            configuration: configuration()
        )
        let health: Health
        do {
            health = try await client.health()
        } catch let problem as AgentError {
            switch problem {
            case .certificateNotTrusted(let presented):
                guard let seen = presented else { return .refused(problem: problem) }
                return .confirmFingerprint(pairing: pairing, fingerprint: seen)
            case .certificateChanged:
                return .refused(problem: problem)
            case .failed, .signInRefused, .notAllowed:
                return .refused(problem: .notAnAgent)
            default:
                return .refused(problem: problem)
            }
        } catch {
            return .refused(problem: .unreachable)
        }
        guard health.ok, let api = health.apiVersion, health.agentUptime != nil else {
            return .refused(problem: .notAnAgent)
        }
        let fit = compatibility(api, range)
        if fit != .ok {
            return .incompatible(compatibility: fit)
        }
        // A typed address the phone trusts: remember the certificate it
        // showed, so a different one later is noticed.
        var pinned = pairing
        pinned.fingerprint = pairing.fingerprint ?? client.trust.lastPresented
        pinned.apiVersion = api
        return .paired(pairing: pinned, health: health)
    }

    /// The person compared the fingerprint and it matches the dashboard's.
    public func confirm(_ pairing: Pairing, fingerprint: String) async -> PairResult {
        var pinned = pairing
        pinned.fingerprint = fingerprint
        return await check(pinned)
    }
}
