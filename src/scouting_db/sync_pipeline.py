"""Shared sync pipeline: authenticate, initialize the database, sync ranks,
optionally import a roster CSV, then sync all Scouts' advancement data.

Progress is reported via the on_progress(kind, data) callback instead of
printing to stdout, so callers (e.g. the web server's SSE stream) can
forward each event to a client in real time.

kind is one of: "step", "log", "error", "complete".
"""

import json
import os

from scouting_db.api import ScoutingAPI, ScoutingAPIError, authenticate
from scouting_db.db import (
    get_connection,
    import_roster_csv,
    init_db,
    store_leadership,
    store_youth_mb_requirements,
    store_youth_merit_badges,
    store_youth_rank_requirements,
    store_youth_ranks,
    upsert_mb_requirements,
    upsert_ranks,
    upsert_requirements,
    upsert_scout,
)

SCOUTS_BSA_PROGRAM_ID = 2


def run_sync(
    username,
    password,
    troop_name,
    db_path,
    config_path,
    csv_path=None,
    skip_reqs=False,
    on_progress=lambda kind, data: None,
):
    """Run the full sync pipeline, reporting progress via on_progress.

    Returns True on success, False if it stopped early due to an error
    (an "error" event has already been sent to on_progress in that case).
    """
    def step(message):
        on_progress("step", {"message": message})

    def log(message):
        on_progress("log", {"message": message})

    def error(message):
        on_progress("error", {"message": message})

    def complete():
        on_progress("complete", {"db_path": db_path})

    for p in (db_path, config_path):
        parent = os.path.dirname(p)
        if parent:
            os.makedirs(parent, exist_ok=True)

    # ── Step 1: Authenticate ─────────────────────────────────────────────
    step(f"Authenticating as {username}…")
    try:
        token, user_id = authenticate(username, password)
    except ScoutingAPIError as exc:
        if exc.status_code in (401, 403):
            error("Authentication failed — please check your username and password.")
        else:
            error(f"Authentication failed ({exc.status_code}): {exc.message[:200]}")
        return False

    config = {"username": username, "token": token}
    if user_id:
        config["user_id"] = str(user_id)
    with open(config_path, "w") as fh:
        json.dump(config, fh, indent=2)
        fh.write("\n")

    log("  ✓ Authentication successful")

    # ── Step 2: Initialise database ──────────────────────────────────────
    step("Initialising database…")
    conn = get_connection(db_path)
    init_db(conn, troop_name=troop_name)

    # ── Step 3: Sync rank definitions (public, no auth needed) ──────────
    step("Downloading rank definitions…")
    api = ScoutingAPI(token=token)
    try:
        ranks_data = api.get_ranks(program_id=SCOUTS_BSA_PROGRAM_ID)
        count = upsert_ranks(conn, ranks_data)
        log(f"  {count} ranks stored")

        rank_rows = conn.execute(
            "SELECT id, name FROM ranks WHERE program_id = ? ORDER BY level",
            (SCOUTS_BSA_PROGRAM_ID,),
        ).fetchall()
        for row in rank_rows:
            try:
                data = api.get_rank_requirements(row["id"])
                reqs = data.get("requirements", data.get("value", []))
                if isinstance(reqs, dict):
                    reqs = reqs.get("requirements", [])
                upsert_requirements(conn, row["id"], reqs)
            except ScoutingAPIError:
                pass  # Non-fatal; rank definitions may already exist
        log("  Rank requirements stored")
    except ScoutingAPIError as exc:
        log(f"  Warning: could not sync ranks ({exc.status_code}) — continuing")

    # ── Step 4: Import roster CSV (optional) ─────────────────────────────
    if csv_path:
        step(f"Importing roster: {os.path.basename(csv_path)}…")
        try:
            imported, skipped = import_roster_csv(conn, csv_path)
            log(f"  {imported} Scouts imported ({skipped} rows skipped)")
        except (ValueError, OSError) as exc:
            log(f"  Warning: roster import failed: {exc}")

    # ── Step 5: Sync advancement data ─────────────────────────────────────
    scouts = conn.execute(
        "SELECT user_id, first_name, last_name FROM scouts"
    ).fetchall()

    if not scouts:
        log("No Scouts in database.")
        if not csv_path:
            log("Tip: import a roster CSV to add Scouts (Scoutbook → Reports → Export CSV).")
        conn.close()
        complete()
        return True

    total = len(scouts)
    step(f"Syncing advancement data for {total} Scout{'s' if total != 1 else ''}…")

    mb_defn_cache = {}     # mb_id -> version_id (already stored)
    rank_defn_cache = set()  # (rank_id, version_id) pairs already stored

    for i, scout in enumerate(scouts, 1):
        uid = scout["user_id"]
        name = f"{scout['first_name'] or ''} {scout['last_name'] or ''}".strip() or str(uid)
        log(f"  [{i}/{total}] {name}")

        # Ranks
        ranks_data = None
        try:
            ranks_data = api.get_youth_ranks(uid)
            store_youth_ranks(conn, uid, ranks_data)
        except ScoutingAPIError as exc:
            if exc.status_code == 401:
                error("Token expired mid-sync. Please re-authenticate.")
                conn.close()
                return False
            log(f"    ⚠ ranks: HTTP {exc.status_code}")

        # Rank requirement completions (in-progress ranks only)
        if not skip_reqs and ranks_data:
            for prog in ranks_data.get("program") or []:
                if prog.get("programId") != SCOUTS_BSA_PROGRAM_ID:
                    continue
                for rank in prog.get("ranks") or []:
                    if rank.get("dateEarned") or rank.get("dateCompleted"):
                        continue
                    rank_id = rank.get("id")
                    if not rank_id:
                        continue
                    rank_id = int(rank_id)
                    version_id = rank.get("versionId")
                    try:
                        cache_key = (rank_id, version_id)
                        if cache_key not in rank_defn_cache:
                            defn = api.get_rank_requirements(rank_id, version_id=version_id)
                            upsert_requirements(conn, rank_id, defn)
                            rank_defn_cache.add(cache_key)
                        youth_reqs = api.get_youth_rank_requirements(uid, rank_id)
                        store_youth_rank_requirements(conn, uid, rank_id, youth_reqs)
                    except ScoutingAPIError:
                        pass

        # Merit badges
        mb_data = None
        try:
            mb_data = api.get_youth_merit_badges(uid)
            store_youth_merit_badges(conn, uid, mb_data)
        except ScoutingAPIError as exc:
            log(f"    ⚠ merit badges: HTTP {exc.status_code}")

        # MB requirement completions (in-progress MBs only)
        if not skip_reqs and mb_data:
            in_progress = [
                mb for mb in (mb_data if isinstance(mb_data, list) else [])
                if not (mb.get("dateCompleted") or mb.get("dateEarned"))
            ]
            for mb in in_progress:
                mb_id = mb.get("id")
                if not mb_id:
                    continue
                try:
                    if mb_id not in mb_defn_cache:
                        defn = api.get_mb_requirements(mb_id)
                        version_id = defn.get("versionId") or mb.get("versionId") or ""
                        upsert_mb_requirements(conn, mb_id, version_id, defn)
                        mb_defn_cache[mb_id] = version_id
                    youth_reqs = api.get_youth_mb_requirements(uid, mb_id)
                    version_id = mb_defn_cache.get(mb_id) or mb.get("versionId") or ""
                    store_youth_mb_requirements(conn, uid, mb_id, version_id, youth_reqs)
                except ScoutingAPIError:
                    pass

        # Leadership history
        try:
            lead_data = api.get_leadership_history(uid)
            store_leadership(conn, uid, lead_data)
        except ScoutingAPIError:
            pass

        # Birthdate (from person profile)
        try:
            profile = api.get_person_profile(uid)
            birthdate = (
                profile.get("dateOfBirth")
                or profile.get("birthDate")
                or profile.get("dob")
                or (profile.get("profile") or {}).get("dateOfBirth")
            )
            if birthdate:
                upsert_scout(conn, uid, birthdate=birthdate)
        except ScoutingAPIError:
            pass

    conn.close()
    step(f"✓ Synced {total} Scout{'s' if total != 1 else ''} successfully")
    complete()
    return True
