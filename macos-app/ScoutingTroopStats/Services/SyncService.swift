import Foundation

/// Orchestrates the full sync pipeline: auth → DB init → rank defs → CSV roster → per-Scout data.
/// Mirrors the logic in the Python `native_sync.py` module.
final class SyncService {
    typealias Message   = AppState.SyncMessage
    typealias MsgType   = AppState.SyncMessage.MessageType
    typealias Progress  = (Message) async -> Void

    private static let scoutsBSAProgramId = 2

    /// Run the full sync.  Returns `true` on success, `false` if a fatal error occurred.
    func sync(
        username: String,
        password: String,
        troopName: String,
        dbPath: String,
        csvPath: String?,
        progress: Progress
    ) async -> Bool {

        func step(_ text: String)  async { await progress(Message(type: .step,     text: text)) }
        func log(_ text: String)   async { await progress(Message(type: .log,      text: text)) }
        func err(_ text: String)   async { await progress(Message(type: .error,    text: text)) }
        func done(_ path: String)  async { await progress(Message(type: .complete, text: path)) }

        // ── Step 1: Authenticate ──────────────────────────────────────────────
        await step("Authenticating as \(username)…")
        let api = ScoutingAPIService()
        do {
            let (_, _) = try await api.authenticate(username: username, password: password)
            await log("  ✓ Authentication successful")
        } catch {
            await err("Authentication failed: \(error.localizedDescription)")
            return false
        }

        // ── Step 2: Initialise database ───────────────────────────────────────
        await step("Initialising database…")
        let db: DatabaseService
        do {
            db = try DatabaseService(path: dbPath)
            try db.initDB(troopName: troopName)
        } catch {
            await err("Database initialisation failed: \(error.localizedDescription)")
            return false
        }

        // ── Step 3: Sync rank definitions (public API) ────────────────────────
        await step("Downloading rank definitions…")
        do {
            let ranksData = try await api.getRanks(programId: Self.scoutsBSAProgramId)
            let count = try db.upsertRanks(ranksData)
            await log("  \(count) ranks stored")

            for rank in db.queryRanks(programId: Self.scoutsBSAProgramId) {
                do {
                    let reqs = try await api.getRankRequirements(rankId: rank.id)
                    try db.upsertRequirements(rankId: rank.id, data: reqs)
                } catch { /* non-fatal: rank defs may already be cached */ }
            }
            await log("  Rank requirements stored")
        } catch {
            await log("  Warning: could not sync ranks — continuing")
        }

        // ── Step 4: Import roster CSV (optional) ──────────────────────────────
        if let csvPath {
            let filename = URL(fileURLWithPath: csvPath).lastPathComponent
            await step("Importing roster: \(filename)…")
            do {
                let (imported, skipped) = try db.importRosterCSV(path: csvPath)
                await log("  \(imported) Scouts imported (\(skipped) rows skipped)")
            } catch {
                await log("  Warning: roster import failed — \(error.localizedDescription)")
            }
        }

        // ── Step 5: Per-Scout advancement data ────────────────────────────────
        let scouts = db.queryScouts()
        guard !scouts.isEmpty else {
            await log("No Scouts in database.")
            if csvPath == nil {
                await log("Tip: import a roster CSV to add Scouts (Scoutbook → Reports → Export CSV).")
            }
            await done(dbPath)
            return true
        }

        let total = scouts.count
        await step("Syncing advancement data for \(total) Scout\(total != 1 ? "s" : "")…")

        var mbDefnCache: Set<Int>   = []
        var rankDefnCache: Set<Int> = []

        for (i, scout) in scouts.enumerated() {
            let name = [scout.firstName, scout.lastName]
                .filter { !$0.isEmpty }
                .joined(separator: " ")
            let display = name.isEmpty ? scout.userId : name
            await log("  [\(i + 1)/\(total)] \(display)")

            // Ranks
            var ranksResponse: [String: Any] = [:]
            do {
                ranksResponse = try await api.getYouthRanks(userId: scout.userId)
                try db.storeYouthRanks(userId: scout.userId, response: ranksResponse)
            } catch let e as ScoutingAPIError where e.isAuthError {
                await err("Token expired mid-sync — please re-authenticate.")
                return false
            } catch {
                await log("    ⚠ ranks: \(error.localizedDescription)")
            }

            // Rank requirement completions for in-progress ranks
            for prog in (ranksResponse["program"] as? [[String: Any]]) ?? [] {
                guard asInt(prog["programId"] ?? 0) == Self.scoutsBSAProgramId else { continue }
                for rank in (prog["ranks"] as? [[String: Any]]) ?? [] {
                    guard (rank["dateEarned"] as? String) == nil else { continue }
                    guard let idRaw = rank["id"] else { continue }
                    let rankId = asInt(idRaw)
                    do {
                        if !rankDefnCache.contains(rankId) {
                            let defn = try await api.getRankRequirements(rankId: rankId)
                            try db.upsertRequirements(rankId: rankId, data: defn)
                            rankDefnCache.insert(rankId)
                        }
                        let yReqs = try await api.getYouthRankRequirements(userId: scout.userId, rankId: rankId)
                        try db.storeYouthRankRequirements(userId: scout.userId, rankId: rankId, data: yReqs)
                    } catch { /* non-fatal */ }
                }
            }

            // Merit badges
            var mbData: [[String: Any]] = []
            do {
                mbData = try await api.getYouthMeritBadges(userId: scout.userId)
                try db.storeYouthMeritBadges(userId: scout.userId, data: mbData)
            } catch {
                await log("    ⚠ merit badges: \(error.localizedDescription)")
            }

            // MB requirement completions for in-progress MBs
            let inProgress = mbData.filter {
                let dc = ($0["dateCompleted"] ?? $0["dateEarned"]) as? String
                return dc == nil || dc!.isEmpty
            }
            for mb in inProgress {
                guard let idRaw = mb["id"] else { continue }
                let mbId       = asInt(idRaw)
                let versionId  = (mb["versionId"] as? String)
                              ?? mb["versionId"].map { "\($0)" } ?? ""
                do {
                    if !mbDefnCache.contains(mbId) {
                        let defn = try await api.getMBRequirements(mbId: mbId)
                        try db.upsertMBRequirements(mbApiId: mbId, mbVersionId: versionId, data: defn)
                        mbDefnCache.insert(mbId)
                    }
                    let yReqs = try await api.getYouthMBRequirements(userId: scout.userId, mbId: mbId)
                    try db.storeYouthMBRequirements(userId: scout.userId, mbApiId: mbId,
                                                    mbVersionId: versionId, data: yReqs)
                } catch { /* non-fatal */ }
            }

            // Leadership history
            do {
                let lead = try await api.getLeadershipHistory(userId: scout.userId)
                try db.storeLeadership(userId: scout.userId, data: lead)
            } catch { /* non-fatal */ }

            // Birthdate from person profile
            do {
                let profile = try await api.getPersonProfile(userId: scout.userId)
                let bd = (profile["dateOfBirth"]
                       ?? profile["birthDate"]
                       ?? profile["dob"]
                       ?? (profile["profile"] as? [String: Any])?["dateOfBirth"]) as? String
                if let bd { try db.upsertScout(userId: scout.userId, birthdate: bd) }
            } catch { /* non-fatal */ }
        }

        await step("✓ Synced \(total) Scout\(total != 1 ? "s" : "") successfully")
        await done(dbPath)
        return true
    }

    // MARK: - Helpers

    private func asInt(_ v: Any) -> Int {
        switch v {
        case let n as Int:    return n
        case let n as Int64:  return Int(n)
        case let n as Double: return Int(n)
        case let s as String: return Int(s) ?? 0
        default:              return 0
        }
    }
}
