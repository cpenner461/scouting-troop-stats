import Foundation
import SQLite3

// MARK: - Errors

enum DatabaseError: Error, LocalizedError {
    case openFailed(String)
    case execFailed(String, sql: String)
    case csvMissingIdColumn(found: [String])

    var errorDescription: String? {
        switch self {
        case .openFailed(let msg):
            return "Could not open database: \(msg)"
        case .execFailed(let msg, let sql):
            return "SQL error: \(msg)\nSQL: \(String(sql.prefix(200)))"
        case .csvMissingIdColumn(let cols):
            return "CSV must have a 'User ID' or 'Member ID' column. Found: \(cols.joined(separator: ", "))"
        }
    }
}

// MARK: - DatabaseService

/// SQLite wrapper that mirrors the Python `db.py` module.
/// Uses the sqlite3 C library bundled with macOS — no external dependencies.
final class DatabaseService {
    private var db: OpaquePointer?
    let path: String

    static let eagleRequiredMeritBadges: [String] = [
        "Camping",
        "Citizenship in the Community",
        "Citizenship in the Nation",
        "Citizenship in the World",
        "Citizenship in Society",
        "Communication",
        "Cooking",
        "Emergency Preparedness",
        "Environmental Science",
        "Family Life",
        "First Aid",
        "Lifesaving",
        "Hiking",
        "Cycling",
        "Personal Fitness",
        "Personal Management",
        "Sustainability",
        "Swimming",
    ]

    // MARK: - Init / deinit

    init(path: String) throws {
        self.path = path
        let dir = URL(fileURLWithPath: path).deletingLastPathComponent()
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        guard sqlite3_open(path, &db) == SQLITE_OK else {
            let msg = db.flatMap { String(cString: sqlite3_errmsg($0)) } ?? "unknown"
            throw DatabaseError.openFailed(msg)
        }
        sqlite3_exec(db, "PRAGMA journal_mode=WAL", nil, nil, nil)
        sqlite3_exec(db, "PRAGMA foreign_keys=ON", nil, nil, nil)
    }

    deinit { sqlite3_close(db) }

    // MARK: - Schema

    func initDB(troopName: String? = nil) throws {
        try exec(Self.schemaSql)
        if let name = troopName { try setSetting("troop_name", value: name) }
        try seedEagleMeritBadges()
    }

    private func setSetting(_ key: String, value: String) throws {
        try exec("""
            INSERT INTO settings (key, value) VALUES ('\(q(key))', '\(q(value))')
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """)
    }

    private func seedEagleMeritBadges() throws {
        for name in Self.eagleRequiredMeritBadges {
            try exec("""
                INSERT OR IGNORE INTO merit_badges (name, is_eagle_required, active)
                VALUES ('\(q(name))', 1, 1)
            """)
        }
    }

    // MARK: - Ranks

    @discardableResult
    func upsertRanks(_ data: Any) throws -> Int {
        let ranks = extractArray(data, keys: ["value", "ranks"])
        var count = 0
        for rank in ranks {
            guard let idRaw = rank["id"] else { continue }
            let id       = asInt(idRaw)
            let name     = (rank["name"] as? String) ?? ""
            let level    = asInt(rank["level"] ?? 0)
            let progId   = asInt(rank["programId"] ?? 0)
            let program  = sqlStr(rank["program"] as? String)
            let imageUrl = sqlStr((rank["imageUrl200"] ?? rank["imageUrl100"]) as? String)
            let version  = sqlStr(rank["version"] as? String)
            let active   = asStr(rank["active"] ?? "True").lowercased() == "true" ? 1 : 0
            try exec("""
                INSERT OR REPLACE INTO ranks
                    (id, name, level, program_id, program, image_url, version, active)
                VALUES (\(id), '\(q(name))', \(level), \(progId), \(program), \(imageUrl), \(version), \(active))
            """)
            count += 1
        }
        return count
    }

    func upsertRequirements(rankId: Int, data: Any) throws {
        let reqs = extractReqArray(data)
        try walkRankReqs(reqs, rankId: rankId, parentId: nil)
    }

    private func walkRankReqs(_ reqs: [[String: Any]], rankId: Int, parentId: Int?) throws {
        for req in reqs {
            guard let idRaw = req["id"] else { continue }
            let reqId     = asInt(idRaw)
            let parentStr = parentId.map { "\($0)" } ?? "NULL"
            let reqNum    = sqlStr(req["requirementNumber"] as? String)
            let listNum   = sqlStr(req["listNumber"] as? String)
            let short_    = sqlStr(req["short"] as? String)
            let name      = sqlStr(req["name"] as? String)
            let required  = asStr(req["required"] ?? "True").lowercased() == "true" ? 1 : 0
            let childReq  = req["childrenRequired"].map { "\(asInt($0))" } ?? "NULL"
            let sortOrder = sqlStr(req["sortOrder"] as? String)
            let eagleMB   = req["eagleMBRequired"].map { "\(asInt($0))" } ?? "NULL"
            let totalMB   = req["totalMBRequired"].map { "\(asInt($0))" } ?? "NULL"
            let svcHrs    = req["serviceHoursRequired"].map { "\(asInt($0))" } ?? "NULL"
            let months    = req["monthsSinceLastRankRequired"].map { "\(asInt($0))" } ?? "NULL"
            try exec("""
                INSERT OR REPLACE INTO requirements
                    (id, rank_id, parent_requirement_id, requirement_number, list_number,
                     short, name, required, children_required, sort_order,
                     eagle_mb_required, total_mb_required,
                     service_hours_required, months_since_last_rank)
                VALUES (\(reqId), \(rankId), \(parentStr), \(reqNum), \(listNum),
                        \(short_), \(name), \(required), \(childReq), \(sortOrder),
                        \(eagleMB), \(totalMB), \(svcHrs), \(months))
            """)
            let children = childArray(req)
            if !children.isEmpty { try walkRankReqs(children, rankId: rankId, parentId: reqId) }
        }
    }

    // MARK: - Scouts

    func upsertScout(
        userId: String,
        firstName: String? = nil,
        lastName: String? = nil,
        scoutingMemberId: String? = nil,
        patrol: String? = nil,
        birthdate: String? = nil
    ) throws {
        let now = ISO8601DateFormatter().string(from: Date())
        try exec("""
            INSERT INTO scouts
                (user_id, first_name, last_name, scouting_member_id, patrol, birthdate, last_synced_at)
            VALUES
                ('\(q(userId))', \(sqlStr(firstName)), \(sqlStr(lastName)),
                 \(sqlStr(scoutingMemberId)), \(sqlStr(patrol)), \(sqlStr(birthdate)), '\(now)')
            ON CONFLICT(user_id) DO UPDATE SET
                first_name         = COALESCE(excluded.first_name, first_name),
                last_name          = COALESCE(excluded.last_name, last_name),
                scouting_member_id = COALESCE(excluded.scouting_member_id, scouting_member_id),
                patrol             = COALESCE(excluded.patrol, patrol),
                birthdate          = COALESCE(excluded.birthdate, birthdate),
                last_synced_at     = excluded.last_synced_at
        """)
    }

    func importRosterCSV(path: String) throws -> (imported: Int, skipped: Int) {
        let raw = try String(contentsOfFile: path, encoding: .utf8)
        var lines = raw.components(separatedBy: "\n").filter { !$0.trimmingCharacters(in: .whitespaces).isEmpty }
        guard !lines.isEmpty else { return (0, 0) }

        let headers = parseCSVLine(lines.removeFirst())
        let hmap: [String: Int] = Dictionary(
            uniqueKeysWithValues: headers.enumerated().map {
                ($0.element.trimmingCharacters(in: .whitespaces)
                    .lowercased()
                    .replacingOccurrences(of: " ", with: "_"),
                 $0.offset)
            }
        )
        func find(_ alts: String...) -> Int? {
            for a in alts {
                if let i = hmap[a.lowercased().replacingOccurrences(of: " ", with: "_")] { return i }
            }
            return nil
        }

        let colUID  = find("user_id", "userid", "user id")
        let colMID  = find("scouting_member_id", "member_id", "scouting member id",
                           "member id", "scoutingmemberid", "memberid")
        guard colUID != nil || colMID != nil else {
            throw DatabaseError.csvMissingIdColumn(found: headers)
        }

        let colFirst  = find("first_name", "first", "firstname")
        let colLast   = find("last_name", "last", "lastname")
        let colName   = (colFirst == nil && colLast == nil) ? find("name", "scout_name", "scoutname") : nil
        let colPatrol = find("patrol", "patrol_name", "patrolname")
        let colType   = find("type", "member_type", "membertype")

        var imported = 0, skipped = 0
        for line in lines {
            let fields = parseCSVLine(line)
            func field(_ idx: Int?) -> String? {
                guard let i = idx, i < fields.count else { return nil }
                let v = fields[i].trimmingCharacters(in: .whitespaces)
                return v.isEmpty ? nil : v
            }
            if let ti = colType, let t = field(ti), t.uppercased() != "YOUTH" { skipped += 1; continue }

            let uid = field(colUID) ?? ""
            let mid = field(colMID) ?? ""
            let primary = uid.isEmpty ? mid : uid
            guard !primary.isEmpty else { skipped += 1; continue }

            let (first, last): (String?, String?)
            if let ni = colName, let full = field(ni) {
                let parts = full.split(separator: " ", maxSplits: 1)
                first = parts.count > 0 ? String(parts[0]) : nil
                last  = parts.count > 1 ? String(parts[1]) : nil
            } else {
                first = field(colFirst)
                last  = field(colLast)
            }

            try upsertScout(userId: primary, firstName: first, lastName: last,
                            scoutingMemberId: mid.isEmpty ? nil : mid, patrol: field(colPatrol))
            imported += 1
        }
        return (imported, skipped)
    }

    // MARK: - Youth rank data

    func storeYouthRanks(userId: String, response: [String: Any]) throws {
        var maxBSARankId = 0
        let programs = (response["program"] as? [[String: Any]]) ?? []
        for prog in programs {
            let progId   = asInt(prog["programId"] ?? 0)
            let progName = (prog["program"] as? String) ?? ""
            for rank in (prog["ranks"] as? [[String: Any]]) ?? [] {
                guard let idRaw = rank["id"] else { continue }
                let rankId      = asInt(idRaw)
                let name        = (rank["name"] as? String) ?? ""
                let dateEarned  = rank["dateEarned"] as? String
                let status      = dateEarned != nil ? "completed" : "in_progress"

                try exec("""
                    INSERT OR IGNORE INTO ranks (id, name, level, program_id, program, active)
                    VALUES (\(rankId), '\(q(name))', \(rankId), \(progId), '\(q(progName))', 1)
                """)
                try exec("""
                    INSERT OR REPLACE INTO scout_advancements
                        (scout_user_id, advancement_type, advancement_id,
                         advancement_name, status, date_completed)
                    VALUES ('\(q(userId))', 'rank', \(rankId), '\(q(name))',
                            '\(status)', \(sqlStr(dateEarned)))
                """)
                if dateEarned != nil && progId == 2 && rankId > maxBSARankId {
                    maxBSARankId = rankId
                }
            }
        }
        if maxBSARankId > 0 {
            try exec("UPDATE scouts SET current_rank_id = \(maxBSARankId) WHERE user_id = '\(q(userId))'")
        }
    }

    // MARK: - Youth merit badge data

    func storeYouthMeritBadges(userId: String, data: Any) throws {
        guard let items = data as? [[String: Any]] else { return }
        for item in items {
            guard let name = (item["name"] ?? item["short"]) as? String, !name.isEmpty else { continue }
            let dateCompleted  = (item["dateCompleted"] ?? item["dateEarned"]) as? String
            let dateStarted    = item["dateStarted"] as? String
            let status         = dateCompleted != nil ? "completed" : "in_progress"
            let isEagle        = ((item["isEagleRequired"] as? Bool) == true ||
                                  (item["eagleRequired"] as? Bool) == true) ? 1 : 0
            let mbApiId        = item["id"].map { "\(asInt($0))" } ?? "NULL"
            let mbVersionId    = (item["versionId"] as? String)
                                 ?? item["versionId"].map { "\($0)" }
            try exec("""
                INSERT OR REPLACE INTO scout_merit_badges
                    (scout_user_id, merit_badge_name, status, date_completed,
                     date_started, mb_api_id, mb_version_id)
                VALUES ('\(q(userId))', '\(q(name))', '\(status)',
                        \(sqlStr(dateCompleted)), \(sqlStr(dateStarted)),
                        \(mbApiId), \(sqlStr(mbVersionId)))
            """)
            try exec("""
                INSERT INTO merit_badges (name, is_eagle_required, active) VALUES ('\(q(name))', \(isEagle), 1)
                ON CONFLICT(name) DO UPDATE SET is_eagle_required = excluded.is_eagle_required
            """)
        }
    }

    // MARK: - MB requirement definitions

    func upsertMBRequirements(mbApiId: Int, mbVersionId: String, data: Any) throws {
        let reqs = extractReqArray(data)
        try walkMBReqs(reqs, mbApiId: mbApiId, mbVersionId: mbVersionId, parentId: nil)
    }

    private func walkMBReqs(
        _ reqs: [[String: Any]], mbApiId: Int, mbVersionId: String, parentId: Int?
    ) throws {
        for req in reqs {
            guard let idRaw = req["id"] else { continue }
            let reqId     = asInt(idRaw)
            let parentStr = parentId.map { "\($0)" } ?? "NULL"
            let reqNum    = sqlStr(req["requirementNumber"] as? String)
            let name      = sqlStr(req["name"] as? String)
            let required  = asStr(req["required"] ?? "True").lowercased() == "true" ? 1 : 0
            let childReq  = req["childrenRequired"].map { "\(asInt($0))" } ?? "NULL"
            let sortOrder = sqlStr(req["sortOrder"] as? String)
            try exec("""
                INSERT OR REPLACE INTO mb_requirements
                    (id, mb_api_id, mb_version_id, parent_requirement_id,
                     requirement_number, name, required, children_required, sort_order)
                VALUES (\(reqId), \(mbApiId), '\(q(mbVersionId))', \(parentStr),
                        \(reqNum), \(name), \(required), \(childReq), \(sortOrder))
            """)
            let children = childArray(req)
            if !children.isEmpty {
                try walkMBReqs(children, mbApiId: mbApiId, mbVersionId: mbVersionId, parentId: reqId)
            }
        }
    }

    // MARK: - Per-Scout rank requirement completions

    func storeYouthRankRequirements(userId: String, rankId: Int, data: Any) throws {
        let reqs = extractReqArray(data)
        try walkYouthRankReqs(reqs, userId: userId, rankId: rankId)
    }

    private func walkYouthRankReqs(_ reqs: [[String: Any]], userId: String, rankId: Int) throws {
        for req in reqs {
            guard let idRaw = req["id"] else { continue }
            let reqId         = asInt(idRaw)
            let dateCompleted = (req["dateCompleted"] ?? req["dateEarned"]) as? String
            let completed     = dateCompleted != nil ? 1 : 0
            try exec("""
                INSERT OR REPLACE INTO scout_requirement_completions
                    (scout_user_id, requirement_id, rank_id, completed, date_completed)
                VALUES ('\(q(userId))', \(reqId), \(rankId), \(completed), \(sqlStr(dateCompleted)))
            """)
            let children = childArray(req)
            if !children.isEmpty { try walkYouthRankReqs(children, userId: userId, rankId: rankId) }
        }
    }

    // MARK: - Per-Scout MB requirement completions

    func storeYouthMBRequirements(
        userId: String, mbApiId: Int, mbVersionId: String, data: Any
    ) throws {
        let reqs = extractReqArray(data)
        try walkYouthMBReqs(reqs, userId: userId, mbApiId: mbApiId, mbVersionId: mbVersionId)
    }

    private func walkYouthMBReqs(
        _ reqs: [[String: Any]], userId: String, mbApiId: Int, mbVersionId: String
    ) throws {
        for req in reqs {
            guard let idRaw = req["id"] else { continue }
            let reqId         = asInt(idRaw)
            let dateCompleted = (req["dateCompleted"] ?? req["dateEarned"]) as? String
            let completed     = dateCompleted != nil ? 1 : 0
            try exec("""
                INSERT OR REPLACE INTO scout_mb_requirement_completions
                    (scout_user_id, mb_requirement_id, mb_api_id, mb_version_id,
                     completed, date_completed)
                VALUES ('\(q(userId))', \(reqId), \(mbApiId), '\(q(mbVersionId))',
                        \(completed), \(sqlStr(dateCompleted)))
            """)
            let children = childArray(req)
            if !children.isEmpty {
                try walkYouthMBReqs(children, userId: userId, mbApiId: mbApiId, mbVersionId: mbVersionId)
            }
        }
    }

    // MARK: - Leadership

    func storeLeadership(userId: String, data: Any) throws {
        let items: [[String: Any]]
        if let arr = data as? [[String: Any]] {
            items = arr
        } else if let dict = data as? [String: Any] {
            items = (dict["value"] as? [[String: Any]])
                 ?? (dict["positions"] as? [[String: Any]]) ?? []
        } else { return }

        for pos in items {
            let posName = ((pos["positionTitle"] ?? pos["position"] ?? pos["title"]) as? String) ?? "Unknown"
            let start   = sqlStr((pos["dateStarted"] ?? pos["startDate"]) as? String)
            let end_    = sqlStr((pos["dateEnded"]   ?? pos["endDate"])   as? String)
            let unit    = sqlStr(pos["unit"]   as? String)
            let patrol  = sqlStr(pos["patrol"] as? String)
            let days    = (pos["numberOfDaysInPosition"] ?? pos["daysInPosition"]).map { "\(asInt($0))" } ?? "NULL"
            let approved = (pos["approvalStatus"] != nil || pos["approved"] as? Bool == true) ? 1 : 0
            try exec("""
                INSERT OR REPLACE INTO scout_leadership
                    (scout_user_id, position, start_date, end_date,
                     unit, patrol, days_in_position, approved)
                VALUES ('\(q(userId))', '\(q(posName))', \(start), \(end_),
                        \(unit), \(patrol), \(days), \(approved))
            """)
        }
    }

    // MARK: - Queries

    func queryScouts() -> [(userId: String, firstName: String, lastName: String)] {
        var result: [(String, String, String)] = []
        var stmt: OpaquePointer?
        sqlite3_prepare_v2(db, "SELECT user_id, first_name, last_name FROM scouts", -1, &stmt, nil)
        defer { sqlite3_finalize(stmt) }
        while sqlite3_step(stmt) == SQLITE_ROW {
            let uid = String(cString: sqlite3_column_text(stmt, 0))
            let fn  = sqlite3_column_text(stmt, 1).map { String(cString: $0) } ?? ""
            let ln  = sqlite3_column_text(stmt, 2).map { String(cString: $0) } ?? ""
            result.append((uid, fn, ln))
        }
        return result
    }

    func queryRanks(programId: Int) -> [(id: Int, name: String)] {
        var result: [(Int, String)] = []
        var stmt: OpaquePointer?
        sqlite3_prepare_v2(db,
            "SELECT id, name FROM ranks WHERE program_id = \(programId) ORDER BY level",
            -1, &stmt, nil)
        defer { sqlite3_finalize(stmt) }
        while sqlite3_step(stmt) == SQLITE_ROW {
            let id   = Int(sqlite3_column_int(stmt, 0))
            let name = String(cString: sqlite3_column_text(stmt, 1))
            result.append((id, name))
        }
        return result
    }

    // MARK: - Low-level exec

    private func exec(_ sql: String) throws {
        var errMsg: UnsafeMutablePointer<CChar>?
        let rc = sqlite3_exec(db, sql, nil, nil, &errMsg)
        if rc != SQLITE_OK {
            let msg = errMsg.map { String(cString: $0) } ?? "rc=\(rc)"
            sqlite3_free(errMsg)
            throw DatabaseError.execFailed(msg, sql: sql)
        }
    }

    // MARK: - Value helpers

    /// Escape a string for use in a SQL literal (doubles single-quotes).
    private func q(_ s: String) -> String { s.replacingOccurrences(of: "'", with: "''") }

    /// Return SQL literal `'value'` or `NULL`.
    private func sqlStr(_ s: String?) -> String {
        guard let s else { return "NULL" }
        return "'\(q(s))'"
    }

    /// Coerce Any to Int.
    private func asInt(_ v: Any) -> Int {
        switch v {
        case let n as Int:    return n
        case let n as Int64:  return Int(n)
        case let n as Double: return Int(n)
        case let s as String: return Int(s) ?? 0
        default:              return 0
        }
    }

    /// Coerce Any to String.
    private func asStr(_ v: Any) -> String { "\(v)" }

    /// Extract an array of requirement objects from a dict or array.
    private func extractReqArray(_ data: Any) -> [[String: Any]] {
        if let arr = data as? [[String: Any]] { return arr }
        if let dict = data as? [String: Any] {
            return (dict["requirements"] as? [[String: Any]])
                ?? (dict["value"]        as? [[String: Any]]) ?? []
        }
        return []
    }

    /// Extract a top-level array from a response, trying multiple key names.
    private func extractArray(_ data: Any, keys: [String]) -> [[String: Any]] {
        if let arr = data as? [[String: Any]] { return arr }
        if let dict = data as? [String: Any] {
            for key in keys {
                if let arr = dict[key] as? [[String: Any]] { return arr }
            }
        }
        return []
    }

    /// Return child requirements from a requirement dict.
    private func childArray(_ req: [String: Any]) -> [[String: Any]] {
        (req["requirements"] as? [[String: Any]])
            ?? (req["children"] as? [[String: Any]]) ?? []
    }

    // MARK: - CSV parser

    private func parseCSVLine(_ line: String) -> [String] {
        var fields: [String] = []
        var current = ""
        var inQuotes = false
        var idx = line.startIndex
        while idx < line.endIndex {
            let ch = line[idx]
            if ch == "\"" {
                let next = line.index(after: idx)
                if inQuotes && next < line.endIndex && line[next] == "\"" {
                    current.append("\"")
                    idx = next
                } else {
                    inQuotes.toggle()
                }
            } else if ch == "," && !inQuotes {
                fields.append(current)
                current = ""
            } else {
                current.append(ch)
            }
            idx = line.index(after: idx)
        }
        fields.append(current)
        return fields
    }

    // MARK: - Schema SQL (mirrors db.py SCHEMA_SQL)

    static let schemaSql = """
    CREATE TABLE IF NOT EXISTS settings (
        key   TEXT PRIMARY KEY,
        value TEXT
    );
    CREATE TABLE IF NOT EXISTS ranks (
        id         INTEGER PRIMARY KEY,
        name       TEXT    NOT NULL,
        level      INTEGER NOT NULL,
        program_id INTEGER NOT NULL,
        program    TEXT,
        image_url  TEXT,
        version    TEXT,
        active     INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS requirements (
        id                        INTEGER PRIMARY KEY,
        rank_id                   INTEGER NOT NULL REFERENCES ranks(id),
        parent_requirement_id     INTEGER REFERENCES requirements(id),
        requirement_number        TEXT,
        list_number               TEXT,
        short                     TEXT,
        name                      TEXT,
        required                  INTEGER NOT NULL DEFAULT 1,
        children_required         INTEGER,
        sort_order                TEXT,
        eagle_mb_required         INTEGER,
        total_mb_required         INTEGER,
        service_hours_required    INTEGER,
        months_since_last_rank    INTEGER
    );
    CREATE TABLE IF NOT EXISTS merit_badges (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        name             TEXT NOT NULL UNIQUE,
        is_eagle_required INTEGER NOT NULL DEFAULT 0,
        image_url        TEXT,
        active           INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS scouts (
        user_id            TEXT PRIMARY KEY,
        first_name         TEXT,
        last_name          TEXT,
        scouting_member_id TEXT,
        patrol             TEXT,
        current_rank_id    INTEGER REFERENCES ranks(id),
        birthdate          TEXT,
        last_synced_at     TEXT
    );
    CREATE TABLE IF NOT EXISTS scout_advancements (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        scout_user_id    TEXT    NOT NULL REFERENCES scouts(user_id),
        advancement_type TEXT    NOT NULL,
        advancement_id   INTEGER,
        advancement_name TEXT,
        status           TEXT,
        date_completed   TEXT,
        date_started     TEXT,
        UNIQUE(scout_user_id, advancement_type, advancement_id)
    );
    CREATE TABLE IF NOT EXISTS scout_merit_badges (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        scout_user_id    TEXT NOT NULL REFERENCES scouts(user_id),
        merit_badge_name TEXT NOT NULL,
        status           TEXT NOT NULL,
        date_completed   TEXT,
        date_started     TEXT,
        mb_api_id        INTEGER,
        mb_version_id    TEXT,
        UNIQUE(scout_user_id, merit_badge_name)
    );
    CREATE TABLE IF NOT EXISTS scout_requirement_completions (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        scout_user_id TEXT    NOT NULL REFERENCES scouts(user_id),
        requirement_id INTEGER NOT NULL REFERENCES requirements(id),
        rank_id       INTEGER NOT NULL REFERENCES ranks(id),
        completed     INTEGER NOT NULL DEFAULT 0,
        date_completed TEXT,
        UNIQUE(scout_user_id, requirement_id)
    );
    CREATE TABLE IF NOT EXISTS scout_leadership (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        scout_user_id   TEXT NOT NULL REFERENCES scouts(user_id),
        position        TEXT NOT NULL,
        start_date      TEXT,
        end_date        TEXT,
        unit            TEXT,
        patrol          TEXT,
        days_in_position INTEGER,
        approved        INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS mb_requirements (
        id                   INTEGER PRIMARY KEY,
        mb_api_id            INTEGER NOT NULL,
        mb_version_id        TEXT    NOT NULL,
        parent_requirement_id INTEGER,
        requirement_number   TEXT,
        name                 TEXT,
        required             INTEGER NOT NULL DEFAULT 1,
        children_required    INTEGER,
        sort_order           TEXT
    );
    CREATE TABLE IF NOT EXISTS scout_mb_requirement_completions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        scout_user_id   TEXT    NOT NULL REFERENCES scouts(user_id),
        mb_requirement_id INTEGER NOT NULL,
        mb_api_id       INTEGER NOT NULL,
        mb_version_id   TEXT    NOT NULL,
        completed       INTEGER NOT NULL DEFAULT 0,
        date_completed  TEXT,
        UNIQUE(scout_user_id, mb_requirement_id)
    );
    CREATE INDEX IF NOT EXISTS idx_scout_adv_type
        ON scout_advancements(advancement_type, advancement_name);
    CREATE INDEX IF NOT EXISTS idx_scout_mb_status
        ON scout_merit_badges(status);
    CREATE INDEX IF NOT EXISTS idx_scout_mb_name
        ON scout_merit_badges(merit_badge_name);
    CREATE INDEX IF NOT EXISTS idx_scout_req_rank
        ON scout_requirement_completions(rank_id, completed);
    CREATE INDEX IF NOT EXISTS idx_scout_req_scout
        ON scout_requirement_completions(scout_user_id);
    CREATE INDEX IF NOT EXISTS idx_mb_req_version
        ON mb_requirements(mb_api_id, mb_version_id);
    CREATE INDEX IF NOT EXISTS idx_scout_mb_req_scout
        ON scout_mb_requirement_completions(scout_user_id, mb_api_id);
    """
}
