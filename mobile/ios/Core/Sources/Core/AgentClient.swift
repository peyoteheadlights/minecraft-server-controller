import Foundation

/// Why a request to the agent didn't give an answer. Each has a strings key.
public enum AgentError: Error, Equatable, Sendable {
    /// No answer at all: the PC is off or asleep, the agent isn't running,
    /// or this phone isn't on Tailscale (the dashboard's offline screen).
    case unreachable
    /// The PC presented a different certificate from the one paired with.
    case certificateChanged(presented: String?)
    /// A typed address whose certificate the phone doesn't trust.
    case certificateNotTrusted(presented: String?)
    /// The pinned certificate is past its end date (or not valid yet).
    case certificateExpired
    /// Something answered, but not this app's agent.
    case notAnAgent
    /// Work the agent answers only once done (a backup, a restore) gave no
    /// answer in time. It may still be running on the PC; the screen reads
    /// it again when the PC says it finished.
    case stillWorking
    /// The sign-in ended (signed out on the PC, a helper removed, expired).
    case signedOut
    /// Sign-in refused: the agent's own words ("Wrong username or password").
    case signInRefused(reason: String)
    /// The account isn't allowed to do that (403), in the agent's words.
    case notAllowed(reason: String)
    /// Any other refusal, in the agent's words, with its error number.
    /// `problems` gives each refused value's reason, by its key, when the
    /// agent says (a game setting that can't be used).
    case failed(status: Int, reason: String?, requestId: String?, problems: [String: String] = [:])

    public var key: String {
        switch self {
        case .unreachable: return "mobile.error.unreachable"
        case .certificateChanged: return "mobile.error.certificate_changed"
        case .certificateNotTrusted: return "mobile.error.certificate_untrusted"
        case .certificateExpired: return "mobile.error.certificate_expired"
        case .notAnAgent: return "mobile.error.not_agent"
        case .stillWorking: return "mobile.error.still_working"
        case .signedOut: return "error.session_ended"
        case .signInRefused: return "mobile.error.sign_in"
        case .notAllowed: return "mobile.error.not_allowed"
        case .failed: return "mobile.error.failed"
        }
    }

    /// The words to show, with the agent's own reason filled in.
    public func message(_ strings: Strings) -> String {
        switch self {
        case .signInRefused(let reason):
            return strings.t("mobile.error.sign_in", ["reason": reason])
        case .failed(let status, let reason, _, _):
            if let reason = reason, !reason.isEmpty {
                return strings.t("mobile.error.failed", ["reason": reason])
            }
            return strings.t("mobile.error.failed_no_reason", ["status": status])
        default:
            return strings.t(key)
        }
    }
}

/// Lines the client may log: method, path and status. Never headers, bodies
/// or the token; AgentClientTests checks that.
public protocol AgentLog: AnyObject {
    func line(_ text: String)
}

/// A log that keeps nothing.
public final class NoLog: AgentLog {
    public init() {}
    public func line(_ text: String) {}
}

/// Talks to one paired PC over HTTPS with the certificate check from
/// `PinnedTrust`. `token` is read for every request, from the phone's
/// Keychain; `onSignedOut` is called on a 401, so the app forgets the token
/// and locks itself out at once.
public final class AgentClient: @unchecked Sendable {
    public static let QUICK_ACTIONS = ["start", "stop", "restart"]

    /// How long a request may wait with nothing arriving: a PC that is off
    /// is noticed quickly.
    public static let requestTimeout: TimeInterval = 20
    /// Stopping a server waits until Minecraft has saved and exited.
    public static let actionTimeout: TimeInterval = 150
    /// No request takes longer than this in all.
    public static let totalTimeout: TimeInterval = 150
    /// Making a backup or a restore answers only once it is done, which can
    /// take many minutes for a big world. The agent sends nothing until then,
    /// so after this long with no answer the app says the PC may still be
    /// working (`AgentError.stillWorking`).
    public static let slowTimeout: TimeInterval = 30 * 60

    public let pairing: Pairing
    public let trust: PinnedTrust
    public let session: URLSession
    /// For work the agent answers only when it is done, and for files.
    public let slowSession: URLSession

    private let token: () -> String?
    private let onSignedOut: () -> Void
    private let log: AgentLog
    private let slowWait: TimeInterval

    public init(
        pairing: Pairing,
        token: @escaping () -> String?,
        onSignedOut: @escaping () -> Void = {},
        log: AgentLog = NoLog(),
        strict: Bool = false,
        configuration: URLSessionConfiguration = .ephemeral,
        slowWait: TimeInterval = AgentClient.slowTimeout
    ) {
        self.pairing = pairing
        self.slowWait = slowWait
        self.token = token
        self.onSignedOut = onSignedOut
        self.log = log
        let trust = PinnedTrust(pin: pairing.fingerprint, strict: strict)
        self.trust = trust
        let config = configuration
        config.timeoutIntervalForRequest = AgentClient.requestTimeout
        config.timeoutIntervalForResource = AgentClient.totalTimeout
        config.httpCookieStorage = nil
        config.httpShouldSetCookies = false
        config.urlCache = nil
        config.requestCachePolicy = .reloadIgnoringLocalCacheData
        self.session = URLSession(configuration: config, delegate: trust, delegateQueue: nil)
        let slow = (config.copy() as? URLSessionConfiguration) ?? .ephemeral
        slow.timeoutIntervalForRequest = slowWait
        slow.timeoutIntervalForResource = 6 * 3600
        self.slowSession = URLSession(configuration: slow, delegate: trust, delegateQueue: nil)
    }

    deinit {
        session.finishTasksAndInvalidate()
        slowSession.finishTasksAndInvalidate()
    }

    // MARK: - The agent's API (mobile/api-routes.txt)

    public func health() async throws -> Health {
        try await call("GET", "/api/health", signedIn: false, as: Health.self)
    }

    public func login(username: String, password: String, device: String) async throws -> LoginResult {
        // The app always keeps the sign-in, behind its own unlock.
        let body = LoginBody(username: username, password: password, device: device, label: device, remember: true, phone: true)
        return try await call("POST", "/api/auth/login", body: try AgentClient.encode(body), signedIn: false, as: LoginResult.self)
    }

    public func logout() async {
        _ = try? await call("POST", "/api/auth/logout", body: Data("{}".utf8), as: Empty.self)
    }

    public func me() async throws -> Me {
        try await call("GET", "/api/auth/me", as: Me.self)
    }

    public func servers() async throws -> ServerList {
        try await call("GET", "/api/servers", as: ServerList.self)
    }

    public func status(serverId: String) async throws -> ServerStatus {
        try await call("GET", "/api/servers/\(AgentClient.pathSegment(serverId))/status", as: ServerStatus.self)
    }

    /// start, stop or restart: the only things the phone ever asks the PC to run.
    public func serverAction(serverId: String, action: String) async throws -> ServerAction {
        guard AgentClient.QUICK_ACTIONS.contains(action) else {
            throw NotAnAction(action: action)
        }
        return try await call(
            "POST",
            "/api/servers/\(AgentClient.pathSegment(serverId))/server/\(action)",
            body: Data("{}".utf8),
            timeout: AgentClient.actionTimeout,
            as: ServerAction.self
        )
    }

    public func alerts(after: Int64?, limit: Int = 50) async throws -> AppAlerts {
        var query = "?limit=\(limit)"
        if let after = after {
            query += "&after=\(after)"
        }
        return try await call("GET", "/api/alerts" + query, as: AppAlerts.self)
    }

    public func phone() async throws -> AppPhone {
        try await call("GET", "/api/app/phone", as: AppPhone.self)
    }

    public func registerPhone(pushToken: String, platform: String, label: String) async throws -> AppPhone {
        let body = PhoneBody(token: pushToken, platform: platform, label: label)
        return try await call("PUT", "/api/app/phone", body: try AgentClient.encode(body), as: AppPhone.self)
    }

    public func forgetPhone() async throws -> AppPhone {
        try await call("DELETE", "/api/app/phone", as: AppPhone.self)
    }

    public func version() async throws -> VersionInfo {
        try await call("GET", "/api/version", as: VersionInfo.self)
    }

    // MARK: - Plumbing

    /// Thrown for anything but start, stop or restart: a programming error.
    public struct NotAnAction: Error, Equatable {
        public let action: String
    }

    struct Empty: Decodable {}

    private struct LoginBody: Encodable {
        let username: String
        let password: String
        let device: String
        let label: String
        let remember: Bool
        /// Kept until signed out, not for the browser's set number of days.
        let phone: Bool
    }

    private struct PhoneBody: Encodable {
        let token: String
        let platform: String
        let label: String
    }

    static func encode<T: Encodable>(_ value: T) throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        return try encoder.encode(value)
    }

    /// A server id as one path segment: "/" and everything else that isn't
    /// a plain letter, digit or one of "-._*" is percent-encoded.
    public static func pathSegment(_ id: String) -> String {
        let allowed = CharacterSet(charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._*")
        return id.addingPercentEncoding(withAllowedCharacters: allowed) ?? ""
    }

    func call<T: Decodable>(
        _ method: String,
        _ path: String,
        body: Data? = nil,
        signedIn: Bool = true,
        timeout: TimeInterval = AgentClient.requestTimeout,
        slow: Bool = false,
        upload: (file: URL, contentType: String)? = nil,
        as type: T.Type
    ) async throws -> T {
        let logPath = path.split(separator: "?", maxSplits: 1, omittingEmptySubsequences: false).first.map { String($0) } ?? path
        guard let url = URL(string: pairing.origin + path) else {
            throw AgentError.notAnAgent
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = slow ? slowWait : timeout
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let body = body {
            request.httpBody = body
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        if let upload = upload {
            request.setValue(upload.contentType, forHTTPHeaderField: "Content-Type")
        }
        if signedIn {
            guard let current = token() else {
                throw AgentError.signedOut
            }
            request.setValue("Bearer \(current)", forHTTPHeaderField: "Authorization")
        }

        let result: (Data, URLResponse)
        let started = Date()
        do {
            let chosen = slow ? slowSession : session
            if let upload = upload {
                result = try await chosen.upload(for: request, fromFile: upload.file)
            } else {
                result = try await chosen.data(for: request)
            }
        } catch {
            if Task.isCancelled {
                throw CancellationError()
            }
            log.line("\(method) \(logPath) -> no answer")
            // Only the wait for the answer runs this long; a PC that is off
            // fails to connect within seconds.
            let nsError = error as NSError
            if slow && nsError.domain == NSURLErrorDomain && nsError.code == NSURLErrorTimedOut
                && Date().timeIntervalSince(started) >= slowWait * 0.9 {
                throw AgentError.stillWorking
            }
            throw translateFailure(error)
        }
        let data = result.0
        guard let http = result.1 as? HTTPURLResponse else {
            throw AgentError.notAnAgent
        }
        let code = http.statusCode
        log.line("\(method) \(logPath) -> \(code)")
        let contentType = http.value(forHTTPHeaderField: "Content-Type") ?? ""
        let isJson = contentType.lowercased().contains("application/json")
        if code == 401 && signedIn {
            onSignedOut()
            throw AgentError.signedOut
        }
        if !(200...299).contains(code) {
            throw AgentClient.refusal(http, data, isJson: isJson)
        }
        if !isJson {
            throw AgentError.notAnAgent
        }
        do {
            return try JSONDecoder().decode(T.self, from: data)
        } catch {
            throw AgentError.notAnAgent
        }
    }

    /// A refused request, in the agent's words.
    private static func refusal(_ http: HTTPURLResponse, _ data: Data, isJson: Bool) -> AgentError {
        let code = http.statusCode
        let reason = isJson ? AgentClient.detail(data) : nil
        if code == 401 || code == 429 {
            return .signInRefused(reason: reason ?? "")
        }
        if code == 403 {
            return .notAllowed(reason: reason ?? "")
        }
        return .failed(
            status: code,
            reason: reason,
            requestId: http.value(forHTTPHeaderField: "X-Request-ID"),
            problems: isJson ? AgentClient.problems(data) : [:]
        )
    }

    /// Downloads the .zip the agent serves at `path` into `destination`,
    /// with the sign-in in a header (never in the address), and returns its
    /// size. `progress` gets the bytes so far and the size, when the PC said
    /// it, about twice a second. A refusal comes back in the agent's words.
    func downloadZip(_ path: String, to destination: URL, progress: @escaping @Sendable (Int64, Int64?) -> Void) async throws -> Int64 {
        let logPath = path.split(separator: "?", maxSplits: 1, omittingEmptySubsequences: false).first.map { String($0) } ?? path
        guard let url = URL(string: pairing.origin + path) else {
            throw AgentError.notAnAgent
        }
        guard let current = token() else {
            throw AgentError.signedOut
        }
        var request = URLRequest(url: url)
        request.timeoutInterval = 120
        request.setValue("Bearer \(current)", forHTTPHeaderField: "Authorization")

        let watch = TaskWatch()
        let ticker = Task {
            while !Task.isCancelled {
                if let bytes = watch.bytes {
                    progress(bytes.0, bytes.1)
                }
                try? await Task.sleep(nanoseconds: 500_000_000)
            }
        }
        defer { ticker.cancel() }

        let result: (URL, URLResponse)
        do {
            result = try await slowSession.download(for: request, delegate: watch)
        } catch {
            if Task.isCancelled {
                throw CancellationError()
            }
            log.line("GET \(logPath) -> no answer")
            // Writing the file on this phone failed (it's full): not the PC's
            // fault, so it is passed on as it is.
            let nsError = error as NSError
            let phoneSide = [NSURLErrorCannotCreateFile, NSURLErrorCannotOpenFile, NSURLErrorCannotWriteToFile, NSURLErrorCannotMoveFile]
            if nsError.domain == NSURLErrorDomain && phoneSide.contains(nsError.code) {
                throw error
            }
            throw translateFailure(error)
        }
        let file = result.0
        let files = FileManager.default
        guard let http = result.1 as? HTTPURLResponse else {
            try? files.removeItem(at: file)
            throw AgentError.notAnAgent
        }
        let code = http.statusCode
        log.line("GET \(logPath) -> \(code)")
        let contentType = (http.value(forHTTPHeaderField: "Content-Type") ?? "").lowercased()
        if code == 401 {
            try? files.removeItem(at: file)
            onSignedOut()
            throw AgentError.signedOut
        }
        if !(200...299).contains(code) {
            let data = (try? Data(contentsOf: file)) ?? Data()
            try? files.removeItem(at: file)
            throw AgentClient.refusal(http, data, isJson: contentType.contains("application/json"))
        }
        guard contentType.hasPrefix("application/zip") else {
            try? files.removeItem(at: file)
            throw AgentError.notAnAgent
        }
        let size = ((try? files.attributesOfItem(atPath: file.path))?[.size] as? NSNumber)?.int64Value ?? 0
        if http.expectedContentLength >= 0 && size != http.expectedContentLength {
            try? files.removeItem(at: file)
            throw AgentError.unreachable
        }
        try? files.removeItem(at: destination)
        try files.moveItem(at: file, to: destination)
        progress(size, size)
        return size
    }

    /// Each refused value's reason, by key ("problems" in the answer).
    private static func problems(_ data: Data) -> [String: String] {
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let found = object["problems"] as? [String: Any]
        else { return [:] }
        return found.compactMapValues { $0 as? String }
    }

    private static func detail(_ data: Data) -> String? {
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return nil
        }
        return object["detail"] as? String
    }

    /// A failed connection, in the app's words. A refused certificate is
    /// told apart from a PC that doesn't answer.
    public func translateFailure(_ error: Error) -> AgentError {
        if let known = error as? AgentError {
            return known
        }
        let nsError = error as NSError
        if nsError.domain == NSURLErrorDomain {
            let code = nsError.code
            let refusedByUs = code == NSURLErrorCancelled
                || code == NSURLErrorServerCertificateUntrusted
                || code == NSURLErrorServerCertificateHasBadDate
                || code == NSURLErrorServerCertificateNotYetValid
                || code == NSURLErrorServerCertificateHasUnknownRoot
                || code == NSURLErrorSecureConnectionFailed
            if refusedByUs, let refusal = trust.lastRefusal {
                switch refusal {
                case .mismatch(let presented):
                    return .certificateChanged(presented: presented)
                case .notTrusted(let presented):
                    return .certificateNotTrusted(presented: presented)
                case .expired:
                    return .certificateExpired
                case .accept:
                    break
                }
            }
            if code == NSURLErrorSecureConnectionFailed
                || code == NSURLErrorServerCertificateUntrusted
                || code == NSURLErrorServerCertificateHasBadDate
                || code == NSURLErrorServerCertificateNotYetValid
                || code == NSURLErrorServerCertificateHasUnknownRoot
                || code == NSURLErrorBadServerResponse
                || code == NSURLErrorCannotParseResponse {
                return .notAnAgent
            }
        }
        return .unreachable
    }
}

/// Keeps hold of a download's task, to read how far it has got.
final class TaskWatch: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    private let lock = NSLock()
    private var task: URLSessionTask?

    func urlSession(_ session: URLSession, didCreateTask task: URLSessionTask) {
        lock.lock()
        self.task = task
        lock.unlock()
    }

    /// Bytes so far and the size, when the PC said it.
    var bytes: (Int64, Int64?)? {
        lock.lock()
        defer { lock.unlock() }
        guard let task = task else { return nil }
        let total = task.countOfBytesExpectedToReceive
        return (task.countOfBytesReceived, total > 0 ? total : nil)
    }
}
