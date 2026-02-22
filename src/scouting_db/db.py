"""SQLite database schema, initialization, and data storage."""

import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB_PATH = Path.cwd() / "scouting_troop.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS ranks (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    level INTEGER NOT NULL,
    program_id INTEGER NOT NULL,
    program TEXT,
    image_url TEXT,
    version TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    raw_json TEXT
);

CREATE TABLE IF NOT EXISTS requirements (
    id INTEGER PRIMARY KEY,
    rank_id INTEGER NOT NULL REFERENCES ranks(id),
    parent_requirement_id INTEGER REFERENCES requirements(id),
    requirement_number TEXT,
    list_number TEXT,
    short TEXT,
    name TEXT,
    required INTEGER NOT NULL DEFAULT 1,
    children_required INTEGER,
    sort_order TEXT,
    eagle_mb_required INTEGER,
    total_mb_required INTEGER,
    service_hours_required INTEGER,
    months_since_last_rank INTEGER,
    raw_json TEXT
);

CREATE TABLE IF NOT EXISTS merit_badges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    is_eagle_required INTEGER NOT NULL DEFAULT 0,
    image_url TEXT,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS scouts (
    user_id TEXT PRIMARY KEY,
    first_name TEXT,
    last_name TEXT,
    scouting_member_id TEXT,
    patrol TEXT,
    current_rank_id INTEGER REFERENCES ranks(id),
    birthdate TEXT,
    last_synced_at TEXT
);

CREATE TABLE IF NOT EXISTS scout_advancements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scout_user_id TEXT NOT NULL REFERENCES scouts(user_id),
    advancement_type TEXT NOT NULL,
    advancement_id INTEGER,
    advancement_name TEXT,
    status TEXT,
    date_completed TEXT,
    date_started TEXT,
    raw_json TEXT,
    UNIQUE(scout_user_id, advancement_type, advancement_id)
);

CREATE TABLE IF NOT EXISTS scout_merit_badges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scout_user_id TEXT NOT NULL REFERENCES scouts(user_id),
    merit_badge_name TEXT NOT NULL,
    status TEXT NOT NULL,
    date_completed TEXT,
    date_started TEXT,
    raw_json TEXT,
    UNIQUE(scout_user_id, merit_badge_name)
);

CREATE TABLE IF NOT EXISTS scout_requirement_completions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scout_user_id TEXT NOT NULL REFERENCES scouts(user_id),
    requirement_id INTEGER NOT NULL REFERENCES requirements(id),
    rank_id INTEGER NOT NULL REFERENCES ranks(id),
    completed INTEGER NOT NULL DEFAULT 0,
    date_completed TEXT,
    UNIQUE(scout_user_id, requirement_id)
);

CREATE TABLE IF NOT EXISTS scout_leadership (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scout_user_id TEXT NOT NULL REFERENCES scouts(user_id),
    position TEXT NOT NULL,
    start_date TEXT,
    end_date TEXT,
    unit TEXT,
    patrol TEXT,
    days_in_position INTEGER,
    approved INTEGER NOT NULL DEFAULT 0,
    raw_json TEXT
);

CREATE TABLE IF NOT EXISTS mb_requirements (
    id INTEGER PRIMARY KEY,
    mb_api_id INTEGER NOT NULL,
    mb_version_id TEXT NOT NULL,
    parent_requirement_id INTEGER,
    requirement_number TEXT,
    name TEXT,
    required INTEGER NOT NULL DEFAULT 1,
    children_required INTEGER,
    sort_order TEXT,
    raw_json TEXT
);

CREATE TABLE IF NOT EXISTS scout_mb_requirement_completions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scout_user_id TEXT NOT NULL REFERENCES scouts(user_id),
    mb_requirement_id INTEGER NOT NULL,
    mb_api_id INTEGER NOT NULL,
    mb_version_id TEXT NOT NULL,
    completed INTEGER NOT NULL DEFAULT 0,
    date_completed TEXT,
    raw_json TEXT,
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

EAGLE_REQUIRED_MERIT_BADGES = [
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


def get_connection(db_path=None):
    path = db_path or str(DEFAULT_DB_PATH)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn, troop_name=None):
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    # Migrations for existing databases
    try:
        conn.execute("ALTER TABLE scouts ADD COLUMN birthdate TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists
    if troop_name is not None:
        set_setting(conn, "troop_name", troop_name)
    seed_eagle_merit_badges(conn)


def set_setting(conn, key, value):
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


def seed_eagle_merit_badges(conn):
    for name in EAGLE_REQUIRED_MERIT_BADGES:
        conn.execute(
            "INSERT OR IGNORE INTO merit_badges (name, is_eagle_required, active) "
            "VALUES (?, 1, 1)",
            (name,),
        )
    conn.commit()


def upsert_ranks(conn, ranks_data):
    """Insert/update ranks from API response. Returns count."""
    ranks = ranks_data if isinstance(ranks_data, list) else ranks_data.get("value", ranks_data.get("ranks", []))
    count = 0
    for rank in ranks:
        conn.execute(
            """INSERT OR REPLACE INTO ranks
               (id, name, level, program_id, program, image_url, version, active, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                int(rank["id"]),
                rank["name"],
                int(rank.get("level", 0)),
                int(rank.get("programId", 0)),
                rank.get("program"),
                rank.get("imageUrl200", rank.get("imageUrl100")),
                rank.get("version"),
                1 if str(rank.get("active", "True")).lower() == "true" else 0,
                json.dumps(rank),
            ),
        )
        count += 1
    conn.commit()
    return count


def upsert_requirements(conn, rank_id, requirements):
    """Insert/update rank requirement definitions. Returns count.

    Recursively walks nested children so all sub-requirements are stored.
    """
    count = 0

    def _int_or_none(val):
        return int(val) if val else None

    def _walk(reqs, parent_id=None):
        nonlocal count
        for req in reqs:
            req_id = req.get("id")
            if not req_id:
                continue
            req_id = int(req_id)
            parent = int(parent_id) if parent_id else None
            conn.execute(
                """INSERT OR REPLACE INTO requirements
                   (id, rank_id, parent_requirement_id, requirement_number,
                    list_number, short, name, required, children_required,
                    sort_order, eagle_mb_required, total_mb_required,
                    service_hours_required, months_since_last_rank, raw_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    req_id,
                    rank_id,
                    parent,
                    req.get("requirementNumber"),
                    req.get("listNumber"),
                    req.get("short"),
                    req.get("name"),
                    1 if str(req.get("required", "True")).lower() == "true" else 0,
                    _int_or_none(req.get("childrenRequired")),
                    req.get("sortOrder"),
                    _int_or_none(req.get("eagleMBRequired")),
                    _int_or_none(req.get("totalMBRequired")),
                    _int_or_none(req.get("serviceHoursRequired")),
                    _int_or_none(req.get("monthsSinceLastRankRequired")),
                    json.dumps(req),
                ),
            )
            count += 1
            children = req.get("requirements") or req.get("children") or []
            if children:
                _walk(children, parent_id=req_id)

    if isinstance(requirements, dict):
        requirements = (
            requirements.get("requirements")
            or requirements.get("value")
            or []
        )
    _walk(requirements)
    conn.commit()
    return count


def upsert_scout(conn, user_id, first_name=None, last_name=None,
                  scouting_member_id=None, patrol=None, birthdate=None):
    conn.execute(
        """INSERT INTO scouts (user_id, first_name, last_name, scouting_member_id, patrol, birthdate, last_synced_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET
               first_name = COALESCE(excluded.first_name, first_name),
               last_name = COALESCE(excluded.last_name, last_name),
               scouting_member_id = COALESCE(excluded.scouting_member_id, scouting_member_id),
               patrol = COALESCE(excluded.patrol, patrol),
               birthdate = COALESCE(excluded.birthdate, birthdate),
               last_synced_at = excluded.last_synced_at""",
        (user_id, first_name, last_name, scouting_member_id, patrol, birthdate,
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def import_roster_csv(conn, csv_path):
    """Import Scouts from a Scoutbook Plus roster CSV export.

    Auto-detects column names. Common Scoutbook columns:
    - "Scouting Member ID" or "Member ID"
    - "First Name" or "First"
    - "Last Name" or "Last"
    - "User ID" or "UserID"

    Returns (imported_count, skipped_count).
    """
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []

        header_map = {h.strip().lower().replace(" ", "_"): h for h in headers}

        def _find_col(*candidates):
            for c in candidates:
                key = c.lower().replace(" ", "_")
                if key in header_map:
                    return header_map[key]
            return None

        col_user_id = _find_col("user_id", "userid", "user id")
        col_member_id = _find_col(
            "scouting_member_id", "member_id", "scouting member id", "member id",
            "scoutingmemberid", "memberid",
        )
        col_first = _find_col("first_name", "first", "firstname")
        col_last = _find_col("last_name", "last", "lastname")
        col_name = _find_col("name", "scout_name", "scoutname") if not col_first and not col_last else None
        col_patrol = _find_col("patrol", "patrol_name", "patrolname")
        col_type = _find_col("type", "member_type", "membertype")

        if not col_user_id and not col_member_id:
            raise ValueError(
                f"CSV must have a 'User ID' or 'Scouting Member ID' column. "
                f"Found columns: {headers}"
            )

        imported = 0
        skipped = 0
        for row in reader:
            uid = (row.get(col_user_id) or "").strip() if col_user_id else ""
            mid = (row.get(col_member_id) or "").strip() if col_member_id else ""

            if col_type and (row.get(col_type) or "").strip().upper() != "YOUTH":
                skipped += 1
                continue

            if not uid and not mid:
                skipped += 1
                continue

            primary_id = uid or mid
            if col_name:
                full = (row.get(col_name) or "").strip()
                parts = full.split(" ", 1)
                first = parts[0] or None
                last = parts[1] if len(parts) > 1 else None
            else:
                first = (row.get(col_first) or "").strip() if col_first else None
                last = (row.get(col_last) or "").strip() if col_last else None

            patrol = (row.get(col_patrol) or "").strip() if col_patrol else None
            upsert_scout(conn, primary_id, first, last, mid or None, patrol or None)
            imported += 1

        return imported, skipped


def store_youth_ranks(conn, user_id, ranks_response):
    """Store rank data from the v2 ranks endpoint.

    Response shape: {"status": "All", "program": [{"programId": 2, "ranks": [...]}]}
    """
    max_bsa_rank_id = 0
    total = 0
    programs = ranks_response.get("program") or []
    for prog in programs:
        prog_id = prog.get("programId") or 0
        prog_name = prog.get("program") or ""
        for rank in prog.get("ranks") or []:
            rank_id = rank.get("id")
            if not rank_id:
                continue
            rank_id = int(rank_id)
            name = rank.get("name") or ""
            date_earned = rank.get("dateEarned")
            status = "completed" if date_earned else "in_progress"
            total += 1

            # Ensure rank exists in ranks table before FK references
            conn.execute(
                """INSERT OR IGNORE INTO ranks (id, name, level, program_id, program, active)
                   VALUES (?, ?, ?, ?, ?, 1)""",
                (rank_id, name, rank_id, prog_id, prog_name),
            )

            conn.execute(
                """INSERT OR REPLACE INTO scout_advancements
                   (scout_user_id, advancement_type, advancement_id,
                    advancement_name, status, date_completed, raw_json)
                   VALUES (?, 'rank', ?, ?, ?, ?, ?)""",
                (user_id, rank_id, name, status, date_earned, json.dumps(rank)),
            )

            # Only track Scouts BSA ranks (programId 2) for current rank
            if date_earned and prog_id == 2 and rank_id > max_bsa_rank_id:
                max_bsa_rank_id = rank_id

    if max_bsa_rank_id:
        conn.execute(
            "UPDATE scouts SET current_rank_id = ? WHERE user_id = ?",
            (max_bsa_rank_id, user_id),
        )
    conn.commit()
    return total


def store_youth_merit_badges(conn, user_id, mb_response):
    """Store merit badge data from the v2 meritBadges endpoint.

    Response is a list of merit badge objects with completion info.
    """
    items = mb_response if isinstance(mb_response, list) else []
    earned = 0
    for item in items:
        name = item.get("name") or item.get("short")
        if not name:
            continue

        date_completed = item.get("dateCompleted") or item.get("dateEarned")
        date_started = item.get("dateStarted")
        if date_completed:
            status = "completed"
            earned += 1
        elif date_started:
            status = "in_progress"
        else:
            status = "in_progress"

        is_eagle = 1 if item.get("isEagleRequired") or item.get("eagleRequired") else 0

        conn.execute(
            """INSERT OR REPLACE INTO scout_merit_badges
               (scout_user_id, merit_badge_name, status, date_completed,
                date_started, raw_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, name, status, date_completed, date_started, json.dumps(item)),
        )

        conn.execute(
            """INSERT INTO merit_badges (name, is_eagle_required, active)
               VALUES (?, ?, 1)
               ON CONFLICT(name) DO UPDATE SET is_eagle_required = excluded.is_eagle_required""",
            (name, is_eagle),
        )

    conn.commit()
    return earned, len(items)




def upsert_mb_requirements(conn, mb_api_id, mb_version_id, requirements):
    """Insert/update MB requirement definitions. Returns count."""
    count = 0

    def _walk(reqs, parent_id=None):
        nonlocal count
        for req in reqs:
            req_id = req.get("id")
            if not req_id:
                continue
            req_id = int(req_id)
            parent = int(parent_id) if parent_id else None
            conn.execute(
                """INSERT OR REPLACE INTO mb_requirements
                   (id, mb_api_id, mb_version_id, parent_requirement_id,
                    requirement_number, name, required, children_required,
                    sort_order, raw_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    req_id,
                    mb_api_id,
                    str(mb_version_id),
                    parent,
                    req.get("requirementNumber"),
                    req.get("name"),
                    1 if str(req.get("required", "True")).lower() == "true" else 0,
                    int(req["childrenRequired"]) if req.get("childrenRequired") else None,
                    req.get("sortOrder"),
                    json.dumps(req),
                ),
            )
            count += 1
            children = req.get("requirements") or req.get("children") or []
            if children:
                _walk(children, parent_id=req_id)

    if isinstance(requirements, dict):
        requirements = (
            requirements.get("requirements")
            or requirements.get("value")
            or []
        )
    _walk(requirements)
    conn.commit()
    return count


def store_youth_mb_requirements(conn, user_id, mb_api_id, mb_version_id, requirements):
    """Store per-Scout MB requirement completion. Returns count."""
    count = 0

    def _walk(reqs):
        nonlocal count
        for req in reqs:
            req_id = req.get("id")
            if not req_id:
                continue
            req_id = int(req_id)
            date_completed = req.get("dateCompleted") or req.get("dateEarned")
            completed = 1 if date_completed else 0
            conn.execute(
                """INSERT OR REPLACE INTO scout_mb_requirement_completions
                   (scout_user_id, mb_requirement_id, mb_api_id, mb_version_id,
                    completed, date_completed, raw_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    user_id,
                    req_id,
                    mb_api_id,
                    str(mb_version_id),
                    completed,
                    date_completed,
                    json.dumps(req),
                ),
            )
            count += 1
            children = req.get("requirements") or req.get("children") or []
            if children:
                _walk(children)

    if isinstance(requirements, dict):
        requirements = (
            requirements.get("requirements")
            or requirements.get("value")
            or []
        )
    _walk(requirements)
    conn.commit()
    return count


def store_youth_rank_requirements(conn, user_id, rank_id, requirements):
    """Store per-Scout rank requirement completion. Returns count."""
    count = 0

    def _walk(reqs):
        nonlocal count
        for req in reqs:
            req_id = req.get("id")
            if not req_id:
                continue
            req_id = int(req_id)
            date_completed = req.get("dateCompleted") or req.get("dateEarned")
            completed = 1 if date_completed else 0
            conn.execute(
                """INSERT OR REPLACE INTO scout_requirement_completions
                   (scout_user_id, requirement_id, rank_id,
                    completed, date_completed)
                   VALUES (?, ?, ?, ?, ?)""",
                (user_id, req_id, rank_id, completed, date_completed),
            )
            count += 1
            children = req.get("requirements") or req.get("children") or []
            if children:
                _walk(children)

    if isinstance(requirements, dict):
        requirements = (
            requirements.get("requirements")
            or requirements.get("value")
            or []
        )
    _walk(requirements)
    conn.commit()
    return count


def store_leadership(conn, user_id, positions):
    """Store leadership position history. Returns count."""
    if not isinstance(positions, list):
        positions = positions.get("value", positions.get("positions", []))
    count = 0
    for pos in positions:
        position_name = (
            pos.get("positionTitle")
            or pos.get("position")
            or pos.get("title")
            or "Unknown"
        )
        conn.execute(
            """INSERT OR REPLACE INTO scout_leadership
               (scout_user_id, position, start_date, end_date,
                unit, patrol, days_in_position, approved, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                position_name,
                pos.get("dateStarted") or pos.get("startDate"),
                pos.get("dateEnded") or pos.get("endDate"),
                pos.get("unit"),
                pos.get("patrol"),
                pos.get("numberOfDaysInPosition") or pos.get("daysInPosition"),
                1 if pos.get("approvalStatus") or pos.get("approved") else 0,
                json.dumps(pos),
            ),
        )
        count += 1
    conn.commit()
    return count


