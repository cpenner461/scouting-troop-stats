"""Native app sync entry point for Electron integration.

Called by the Electron main process (via python-bridge/sync_runner.py when
bundled, or directly via `uv run python -m scouting_db.native_sync` in dev).

Outputs JSON-newline progress messages to stdout so the Electron renderer can
display live status. Password is read from the SCOUTING_PASSWORD env var
and never passed on the command line.

Exit codes:
  0 — success
  1 — error (message emitted before exit)
"""

import argparse
import json
import os
import sys


# ─── Progress helpers ────────────────────────────────────────────────────────

def _emit(msg_type: str, **kwargs) -> None:
    """Print a JSON progress line to stdout and flush immediately."""
    print(json.dumps({"type": msg_type, **kwargs}), flush=True)


def step(message: str) -> None:
    _emit("step", message=message)


def log(message: str) -> None:
    _emit("log", message=message)


def error(message: str) -> None:
    _emit("error", message=message)


def complete(db_path: str) -> None:
    _emit("complete", db_path=db_path)


# ─── Main ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync scouting advancement data for the native desktop app"
    )
    parser.add_argument("--username",    required=True, help="my.scouting.org username")
    parser.add_argument("--troop-name",  default="My Troop", help="Troop display name")
    parser.add_argument("--db-path",     required=True, help="Path to write SQLite database")
    parser.add_argument("--config-path", required=True, help="Path to write config.json (token)")
    parser.add_argument("--csv-path",    default=None,  help="Path to Scoutbook roster CSV (optional)")
    parser.add_argument("--skip-reqs",   action="store_true",
                        help="Skip per-requirement completion sync (faster)")
    args = parser.parse_args()

    password = os.environ.get("SCOUTING_PASSWORD", "")
    if not password:
        error("SCOUTING_PASSWORD environment variable is not set.")
        sys.exit(1)

    # Ensure parent directories exist
    for p in (args.db_path, args.config_path):
        parent = os.path.dirname(p)
        if parent:
            os.makedirs(parent, exist_ok=True)

    # ── Step 1: Authenticate ─────────────────────────────────────────────────
    step(f"Authenticating as {args.username}…")
    try:
        from scouting_db.api import ScoutingAPI, ScoutingAPIError, authenticate
    except ImportError as exc:
        error(f"Import error — packaging issue: {exc}")
        sys.exit(1)

    try:
        token, user_id = authenticate(args.username, password)
    except ScoutingAPIError as exc:
        if exc.status_code in (401, 403):
            error("Authentication failed — please check your username and password.")
        else:
            error(f"Authentication failed ({exc.status_code}): {exc.message[:200]}")
        sys.exit(1)
    except Exception as exc:
        error(f"Unexpected error during authentication: {exc}")
        sys.exit(1)

    # Save token so it can be reused without re-authenticating
    config = {"username": args.username, "token": token}
    if user_id:
        config["user_id"] = str(user_id)
    with open(args.config_path, "w") as fh:
        json.dump(config, fh, indent=2)
        fh.write("\n")

    log("  ✓ Authentication successful")

    # ── Step 2: Initialise database ──────────────────────────────────────────
    step("Initialising database…")
    try:
        from scouting_db.db import (
            get_connection, init_db, import_roster_csv,
            store_leadership, store_youth_mb_requirements,
            store_youth_merit_badges, store_youth_rank_requirements,
            store_youth_ranks, upsert_mb_requirements,
            upsert_ranks, upsert_requirements, upsert_scout,
        )
    except ImportError as exc:
        error(f"Import error: {exc}")
        sys.exit(1)

    conn = get_connection(args.db_path)
    init_db(conn, troop_name=args.troop_name)

    # ── Step 3: Sync rank definitions (public, no auth needed) ───────────────
    step("Downloading rank definitions…")
    try:
        api = ScoutingAPI(token=token)
        ranks_data = api.get_ranks(program_id=2)
        count = upsert_ranks(conn, ranks_data)
        log(f"  {count} ranks stored")

        rank_rows = conn.execute(
            "SELECT id, name FROM ranks WHERE program_id = 2 ORDER BY level"
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

    # ── Step 4: Import roster CSV (optional) ─────────────────────────────────
    if args.csv_path:
        step(f"Importing roster: {os.path.basename(args.csv_path)}…")
        try:
            imported, skipped = import_roster_csv(conn, args.csv_path)
            log(f"  {imported} Scouts imported ({skipped} rows skipped)")
        except (ValueError, OSError) as exc:
            log(f"  Warning: roster import failed: {exc}")

    # ── Step 5: Sync advancement data ────────────────────────────────────────
    scouts = conn.execute(
        "SELECT user_id, first_name, last_name FROM scouts"
    ).fetchall()

    if not scouts:
        log("No Scouts in database.")
        if not args.csv_path:
            log("Tip: import a roster CSV to add Scouts (Scoutbook → Reports → Export CSV).")
        conn.close()
        complete(args.db_path)
        return

    total = len(scouts)
    step(f"Syncing advancement data for {total} Scout{'s' if total != 1 else ''}…")

    SCOUTS_BSA_PROGRAM_ID = 2
    mb_defn_cache: dict = {}    # mb_id -> version_id (already stored)
    rank_defn_cache: set = set()  # rank_ids already stored

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
                sys.exit(1)
            log(f"    ⚠ ranks: HTTP {exc.status_code}")

        # Rank requirement completions (in-progress ranks only)
        if not args.skip_reqs and ranks_data:
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
                    try:
                        if rank_id not in rank_defn_cache:
                            defn = api.get_rank_requirements(rank_id)
                            upsert_requirements(conn, rank_id, defn)
                            rank_defn_cache.add(rank_id)
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
        if not args.skip_reqs and mb_data:
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
    complete(args.db_path)


if __name__ == "__main__":
    main()
