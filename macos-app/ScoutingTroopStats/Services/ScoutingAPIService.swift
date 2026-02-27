import Foundation

// MARK: - Errors

enum ScoutingAPIError: Error, LocalizedError {
    case httpError(Int, String)
    case authenticationFailed(String)
    case noToken
    case invalidResponse

    var errorDescription: String? {
        switch self {
        case .httpError(let code, let msg):
            return "HTTP \(code): \(msg)"
        case .authenticationFailed(let reason):
            return "Authentication failed: \(reason)"
        case .noToken:
            return "No authentication token — please sign in first"
        case .invalidResponse:
            return "Unexpected response format from server"
        }
    }

    var isAuthError: Bool {
        if case .authenticationFailed = self { return true }
        if case .httpError(let code, _) = self, code == 401 || code == 403 { return true }
        return false
    }
}

// MARK: - API service

/// HTTP client for api.scouting.org and my.scouting.org.
/// Mirrors the Python `api.py` module. All methods are async and throw on error.
actor ScoutingAPIService {
    private static let baseURL  = "https://api.scouting.org"
    private static let authBase = "https://my.scouting.org/api/users"
    private static let userAgent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) " +
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

    private(set) var token: String?

    init(token: String? = nil) { self.token = token }

    // MARK: - Authentication

    /// Authenticate with my.scouting.org.  Returns `(token, userId)`.
    func authenticate(username: String, password: String) async throws -> (token: String, userId: String?) {
        guard let encoded = username.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed),
              let url = URL(string: "\(Self.authBase)/\(encoded)/authenticate")
        else { throw ScoutingAPIError.invalidResponse }

        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        req.setValue("application/json; version=2", forHTTPHeaderField: "Accept")
        req.setValue(Self.userAgent, forHTTPHeaderField: "User-Agent")
        // .urlQueryAllowed does not encode '=' or '&', so a password containing
        // those characters would break the form body (the server sees extra keys).
        // Strip them so the value is safely percent-encoded.
        var formValueChars = CharacterSet.urlQueryAllowed
        formValueChars.remove(charactersIn: "=&#")
        let encodedPassword = password.addingPercentEncoding(withAllowedCharacters: formValueChars) ?? ""
        let bodyStr = "password=\(encodedPassword)"
        req.httpBody = bodyStr.data(using: .utf8)

        let data = try await perform(req)
        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let tok = json["token"] as? String
        else {
            throw ScoutingAPIError.authenticationFailed("No token in response")
        }

        let userId = (json["account"] as? [String: Any]).flatMap {
            ($0["userId"] as? String) ?? ($0["userId"].map { "\($0)" })
        }
        self.token = tok
        return (tok, userId)
    }

    // MARK: - Public endpoints (no auth)

    func getRanks(programId: Int? = nil) async throws -> Any {
        var q = "version=2&status=Active"
        if let id = programId { q += "&programId=\(id)" }
        return try await getJSON("/advancements/ranks?\(q)", auth: false)
    }

    func getRankRequirements(rankId: Int) async throws -> Any {
        return try await getJSON("/advancements/ranks/\(rankId)/requirements", auth: false)
    }

    func getMBRequirements(mbId: Int) async throws -> Any {
        return try await getJSON("/advancements/meritBadges/\(mbId)/requirements", auth: false)
    }

    // MARK: - Auth-required endpoints

    func getYouthRanks(userId: String) async throws -> [String: Any] {
        let raw = try await getJSON("/advancements/v2/youth/\(userId)/ranks", auth: true)
        return (raw as? [String: Any]) ?? [:]
    }

    func getYouthMeritBadges(userId: String) async throws -> [[String: Any]] {
        let raw = try await getJSON("/advancements/v2/youth/\(userId)/meritBadges", auth: true)
        return (raw as? [[String: Any]]) ?? []
    }

    func getYouthRankRequirements(userId: String, rankId: Int) async throws -> Any {
        return try await getJSON("/advancements/v2/youth/\(userId)/ranks/\(rankId)/requirements", auth: true)
    }

    func getYouthMBRequirements(userId: String, mbId: Int) async throws -> Any {
        return try await getJSON("/advancements/v2/youth/\(userId)/meritBadges/\(mbId)/requirements", auth: true)
    }

    func getLeadershipHistory(userId: String) async throws -> Any {
        return try await getJSON("/advancements/youth/\(userId)/leadershipPositionHistory", auth: true)
    }

    func getPersonProfile(userId: String) async throws -> [String: Any] {
        let raw = try await getJSON("/persons/v2/\(userId)/personprofile", auth: true)
        return (raw as? [String: Any]) ?? [:]
    }

    // MARK: - Private helpers

    private func getJSON(_ path: String, auth: Bool) async throws -> Any {
        guard let url = URL(string: Self.baseURL + path) else {
            throw ScoutingAPIError.invalidResponse
        }
        var req = URLRequest(url: url)
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        if auth {
            guard let tok = token else { throw ScoutingAPIError.noToken }
            req.setValue("Bearer \(tok)", forHTTPHeaderField: "Authorization")
        }
        let data = try await perform(req)
        return (try? JSONSerialization.jsonObject(with: data)) ?? [String: Any]()
    }

    private func perform(_ request: URLRequest) async throws -> Data {
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw ScoutingAPIError.invalidResponse
        }
        if http.statusCode >= 400 {
            let body = String(data: data, encoding: .utf8).map { String($0.prefix(300)) } ?? ""
            if http.statusCode == 401 || http.statusCode == 403 {
                throw ScoutingAPIError.authenticationFailed("HTTP \(http.statusCode)")
            }
            throw ScoutingAPIError.httpError(http.statusCode, body)
        }
        return data
    }
}
