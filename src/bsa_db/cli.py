"""BSA Troop Analytics CLI Tool.

Download scout advancement data from api.scouting.org into a local
SQLite database and run troop-wide analytical queries.

Usage examples:
    bsa init
    bsa sync-ranks
    bsa import-roster roster.csv
    bsa sync-scouts
    bsa query plan --min-pct 40
    bsa query summary
"""

import argparse
import json
import os
import sys

from bsa_db.api import ScoutingAPI, ScoutingAPIError
from bsa_db.db import (
    get_connection,
    import_roster_csv,
    init_db,
    store_leadership,
    store_youth_mb_requirements,
    store_youth_merit_badges,
    store_youth_ranks,
    upsert_mb_requirements,
    upsert_ranks,
    upsert_requirements,
    upsert_scout,
)
from bsa_db.queries import (
    mb_requirement_detail,
    most_common_incomplete_merit_badges,
    optimal_group_activities,
    per_scout_summary,
    requirement_completion_matrix,
    scouts_closest_to_next_rank,
)

SCOUTS_BSA_PROGRAM_ID = 2


def get_token():
    token = os.environ.get("BSA_TOKEN")
    if token:
        return token
    config_path = os.path.join(os.getcwd(), "config.json")
    if os.path.exists(config_path):
        with open(config_path) as f:
            return json.load(f).get("token", "")
    return ""


def require_token():
    token = get_token()
    if not token:
        print(
            "Error: No API token found.\n"
            'Set BSA_TOKEN env var or create config.json with {"token": "..."}',
            file=sys.stderr,
        )
        sys.exit(1)
    return token


# --- Commands ---


def cmd_init(args):
    conn = get_connection(args.db)
    init_db(conn)
    conn.close()
    print(f"Database initialized at {args.db or 'bsa_troop.db'}")


def cmd_sync_ranks(args):
    conn = get_connection(args.db)
    init_db(conn)
    api = ScoutingAPI()

    print("Fetching ranks...")
    ranks_data = api.get_ranks(program_id=SCOUTS_BSA_PROGRAM_ID)
    count = upsert_ranks(conn, ranks_data)
    print(f"  Stored {count} ranks")

    rows = conn.execute(
        "SELECT id, name FROM ranks WHERE program_id = ? ORDER BY level",
        (SCOUTS_BSA_PROGRAM_ID,),
    ).fetchall()

    for row in rows:
        rank_id, rank_name = row["id"], row["name"]
        print(f"Fetching requirements for {rank_name} (id={rank_id})...")
        try:
            data = api.get_rank_requirements(rank_id)
            reqs = data.get("requirements", data.get("value", []))
            if isinstance(reqs, dict):
                reqs = reqs.get("requirements", [])
            count = upsert_requirements(conn, rank_id, reqs)
            print(f"  Stored {count} requirements")
        except ScoutingAPIError as e:
            print(f"  Warning: failed to fetch requirements: {e}")

    conn.close()
    print("Done.")


def cmd_import_roster(args):
    conn = get_connection(args.db)
    init_db(conn)
    try:
        imported, skipped = import_roster_csv(conn, args.csv_file)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    conn.close()
    print(f"Imported {imported} scouts ({skipped} rows skipped)")


def cmd_add_scout(args):
    conn = get_connection(args.db)
    init_db(conn)
    name_parts = (args.name or "").split(" ", 1)
    first = name_parts[0] if name_parts[0] else None
    last = name_parts[1] if len(name_parts) > 1 else None
    upsert_scout(conn, args.user_id, first, last)
    conn.close()
    print(f"Added scout {args.user_id}" + (f" ({args.name})" if args.name else ""))


def cmd_sync_scouts(args):
    token = require_token()
    conn = get_connection(args.db)
    init_db(conn)
    api = ScoutingAPI(token=token)

    scouts = conn.execute(
        "SELECT user_id, first_name, last_name FROM scouts"
    ).fetchall()
    if not scouts:
        print("No scouts registered. Use 'import-roster' or 'add-scout' first.")
        conn.close()
        return

    skip_reqs = getattr(args, "skip_reqs", False)
    # Cache MB requirement definitions to avoid re-fetching for multiple scouts
    mb_defn_cache = {}  # mb_id -> version_id (already stored)

    print(f"Syncing {len(scouts)} scouts...")
    for scout in scouts:
        uid = scout["user_id"]
        name = f"{scout['first_name'] or ''} {scout['last_name'] or ''}".strip()
        label = name or uid
        print(f"  {label}...", end=" ", flush=True)

        try:
            ranks_data = api.get_youth_ranks(uid)
            count = store_youth_ranks(conn, uid, ranks_data)
            print(f"ranks({count})", end=" ")
        except ScoutingAPIError as e:
            print(f"[ranks error: {e.status_code}]", end=" ")

        mb_data = None
        try:
            mb_data = api.get_youth_merit_badges(uid)
            earned, total = store_youth_merit_badges(conn, uid, mb_data)
            print(f"mbs({earned}/{total})", end=" ")
        except ScoutingAPIError as e:
            print(f"[mbs error: {e.status_code}]", end=" ")

        try:
            lead_data = api.get_leadership_history(uid)
            count = store_leadership(conn, uid, lead_data)
            print(f"leadership({count})", end=" ")
        except ScoutingAPIError as e:
            print(f"[lead error: {e.status_code}]", end=" ")

        # Fetch per-requirement completion for in-progress MBs
        if not skip_reqs and mb_data:
            in_progress = [
                mb for mb in (mb_data if isinstance(mb_data, list) else [])
                if not (mb.get("dateCompleted") or mb.get("dateEarned"))
            ]
            req_count = 0
            for mb in in_progress:
                mb_id = mb.get("id")
                if not mb_id:
                    continue
                try:
                    # Cache requirement definitions per MB id
                    if mb_id not in mb_defn_cache:
                        defn = api.get_mb_requirements(mb_id)
                        version_id = defn.get("versionId") or mb.get("versionId") or ""
                        upsert_mb_requirements(conn, mb_id, version_id, defn)
                        mb_defn_cache[mb_id] = version_id

                    # Per-scout completion
                    youth_reqs = api.get_youth_mb_requirements(uid, mb_id)
                    version_id = mb_defn_cache.get(mb_id) or mb.get("versionId") or ""
                    req_count += store_youth_mb_requirements(
                        conn, uid, mb_id, version_id, youth_reqs
                    )
                except ScoutingAPIError:
                    pass  # silently skip failures per-MB
            if req_count:
                print(f"reqs({req_count})", end=" ")

        print()

    conn.close()
    print("Done.")


def cmd_discover(args):
    token = require_token()
    conn = get_connection(args.db)
    init_db(conn)
    api = ScoutingAPI(token=token)
    uid = args.user_id

    print(f"Probing API endpoints for user {uid}...\n")

    paths = [
        ("GET  /advancements/v2/youth/{uid}/ranks", "GET", f"/advancements/v2/youth/{uid}/ranks"),
        ("GET  /advancements/v2/youth/{uid}/meritBadges", "GET", f"/advancements/v2/youth/{uid}/meritBadges"),
        ("GET  /advancements/v2/youth/{uid}/awards", "GET", f"/advancements/v2/youth/{uid}/awards"),
        ("GET  /advancements/v2/{uid}/userActivitySummary", "GET", f"/advancements/v2/{uid}/userActivitySummary"),
        ("GET  /advancements/youth/{uid}/leadershipPositionHistory", "GET", f"/advancements/youth/{uid}/leadershipPositionHistory"),
    ]

    for label, method, path in paths:
        print(f"  {label}...", end=" ", flush=True)
        try:
            data = api._request(path, method=method)
            preview = json.dumps(data, indent=2)
            if len(preview) > 500:
                preview = preview[:500] + "\n  ... (truncated)"
            print(f"OK\n{preview}\n")
        except ScoutingAPIError as e:
            print(f"{e.status_code}: {e.message[:200]}")

    # Probe MB requirement endpoints using a sample in-progress MB
    print("\n--- MB Requirement Endpoint Probing ---\n")
    sample = conn.execute(
        "SELECT raw_json FROM scout_merit_badges "
        "WHERE scout_user_id = ? AND status = 'in_progress' LIMIT 1",
        (uid,),
    ).fetchone()
    if not sample:
        sample = conn.execute(
            "SELECT raw_json FROM scout_merit_badges "
            "WHERE status = 'in_progress' LIMIT 1"
        ).fetchone()

    if sample:
        mb = json.loads(sample["raw_json"])
        mb_id = mb["id"]
        version_id = mb["versionId"]
        mb_name = mb["name"]
        print(f"  Sample MB: {mb_name} (id={mb_id}, versionId={version_id})\n")

        mb_probes = [
            (f"GET  /advancements/meritBadges/{mb_id}/requirements (public, by mb id)",
             f"/advancements/meritBadges/{mb_id}/requirements"),
            (f"GET  /advancements/v2/youth/{uid}/meritBadges/{mb_id}/requirements (auth, per-scout)",
             f"/advancements/v2/youth/{uid}/meritBadges/{mb_id}/requirements"),
        ]
        for label, path in mb_probes:
            print(f"  {label}...", end=" ", flush=True)
            try:
                data = api._request(path)
                preview = json.dumps(data, indent=2)
                if len(preview) > 1000:
                    preview = preview[:1000] + "\n  ... (truncated)"
                print(f"OK\n{preview}\n")
            except ScoutingAPIError as e:
                print(f"{e.status_code}: {e.message[:200]}")
    else:
        print("  No in-progress MBs found to probe requirement endpoints.")

    conn.close()



def cmd_query(args):
    conn = get_connection(args.db)

    if args.query_name == "needs-mb":
        rows = most_common_incomplete_merit_badges(
            conn, args.limit, eagle_only=args.eagle_only
        )
        if not rows:
            print("No data. Run sync-ranks and sync-scouts first.")
            conn.close()
            return
        title = "Eagle-Required" if args.eagle_only else "All"
        print(f"\nMost Common Unfinished Merit Badges ({title}):\n")
        print(f"  {'Merit Badge':<40} {'Eagle':<6} {'Need':<6} {'%':>6}")
        print(f"  {'-'*40} {'-'*5} {'-'*5} {'-'*6}")
        for r in rows:
            eagle = " *" if r["is_eagle_required"] else ""
            print(
                f"  {r['merit_badge']:<40} {eagle:<6} "
                f"{r['scouts_needing']:<6} {r['pct_needing']:>5}%"
            )

    elif args.query_name == "next-rank":
        rows = scouts_closest_to_next_rank(conn)
        if not rows:
            print("No data. Run sync-ranks and sync-scouts first.")
            conn.close()
            return
        print("\nScouts Closest to Next Rank:\n")
        print(
            f"  {'Scout':<25} {'Current':<14} {'Next':<14} "
            f"{'Done':<5} {'Left':<5} {'%':>6}"
        )
        print(f"  {'-'*25} {'-'*13} {'-'*13} {'-'*4} {'-'*4} {'-'*6}")
        for r in rows:
            print(
                f"  {r['scout_name']:<25} "
                f"{(r['current_rank'] or 'None'):<14} "
                f"{r['next_rank_name']:<14} "
                f"{r['completed_requirements']:<5} "
                f"{r['remaining']:<5} "
                f"{r['pct_complete']:>5}%"
            )

    elif args.query_name == "req-matrix":
        if not args.rank_id:
            ranks = conn.execute(
                "SELECT id, name FROM ranks WHERE program_id = 2 ORDER BY level"
            ).fetchall()
            print("Specify --rank-id. Available Scouts BSA ranks:")
            for r in ranks:
                print(f"  {r['id']}: {r['name']}")
            conn.close()
            return
        rows = requirement_completion_matrix(conn, args.rank_id)
        if not rows:
            print("No data for that rank.")
            conn.close()
            return
        rank_name = conn.execute(
            "SELECT name FROM ranks WHERE id = ?", (args.rank_id,)
        ).fetchone()
        print(f"\nRequirement Completion Matrix: {rank_name['name'] if rank_name else args.rank_id}\n")
        print(f"  {'Req':<6} {'Description':<50} {'Need':<5} {'%':>6}")
        print(f"  {'-'*5} {'-'*50} {'-'*4} {'-'*6}")
        for r in rows:
            desc = (r["requirement_desc"] or "")[:48]
            print(
                f"  {r['requirement_number'] or '':<6} {desc:<50} "
                f"{r['scouts_needing']:<5} {r['pct_incomplete']:>5}%"
            )

    elif args.query_name == "summary":
        rows = per_scout_summary(conn)
        if not rows:
            print("No scouts in database.")
            conn.close()
            return
        print(f"\nTroop Summary ({len(rows)} scouts):\n")
        print(
            f"  {'Scout':<25} {'Rank':<14} {'MBs':<5} "
            f"{'Eagle':<6} {'In Prog':<8}"
        )
        print(f"  {'-'*25} {'-'*13} {'-'*4} {'-'*5} {'-'*7}")
        for r in rows:
            print(
                f"  {r['scout_name'] or '':<25} {r['current_rank'] or '':<14} "
                f"{r['total_mbs_earned'] or 0:<5} {r['eagle_mbs_earned'] or 0:<6} "
                f"{r['mbs_in_progress'] or 0:<8}"
            )

    elif args.query_name == "mb-reqs":
        mb_name = getattr(args, "merit_badge", None)
        rows = mb_requirement_detail(conn, mb_name)
        if not rows:
            print("No MB requirement data. Run sync-scouts first (without --skip-reqs).")
            conn.close()
            return
        title = mb_name if mb_name else "All In-Progress Merit Badges"
        print(f"\nMB Requirement Detail: {title}\n")
        print(
            f"  {'Merit Badge':<35} {'Req':<6} {'Description':<40} "
            f"{'Work':<5} {'Done':<5} {'Need':<5} {'%':>6}"
        )
        print(
            f"  {'-'*35} {'-'*5} {'-'*40} "
            f"{'-'*4} {'-'*4} {'-'*4} {'-'*6}"
        )
        for r in rows:
            desc = (r["requirement_desc"] or "")[:38]
            print(
                f"  {r['merit_badge_name']:<35} "
                f"{r['requirement_number'] or '':<6} {desc:<40} "
                f"{r['scouts_working']:<5} {r['scouts_done']:<5} "
                f"{r['scouts_needing']:<5} {r['pct_complete']:>5}%"
            )

    elif args.query_name == "plan":
        rows = optimal_group_activities(conn, args.min_pct)
        if not rows:
            print(f"No activities found where >= {args.min_pct}% of troop benefits.")
            print("Try a lower --min-pct or run sync-scouts to populate data.")
            conn.close()
            return
        print(f"\nOptimal Group Activities (>= {args.min_pct}% of troop benefits):\n")
        print(f"  {'Activity':<40} {'Eagle':<6} {'Benefit':<8} {'%':>6}")
        print(f"  {'-'*40} {'-'*5} {'-'*7} {'-'*6}")
        for r in rows:
            eagle = " *" if r["is_eagle_required"] else ""
            print(
                f"  {r['activity_name']:<40} {eagle:<6} "
                f"{r['scouts_benefiting']:<8} {r['pct_benefiting']:>5}%"
            )

    conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="BSA Troop Analytics CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--db", help="Path to SQLite database", default=None)
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init", help="Initialize the database")
    sub.add_parser("sync-ranks", help="Download ranks and requirements")

    p_roster = sub.add_parser(
        "import-roster", help="Import scouts from Scoutbook CSV roster export"
    )
    p_roster.add_argument("csv_file", help="Path to roster CSV file")

    p_add = sub.add_parser("add-scout", help="Manually add a single scout")
    p_add.add_argument("user_id", help="Scout's API userId")
    p_add.add_argument("name", nargs="?", help="Scout's name ('First Last')")

    p_sync = sub.add_parser("sync-scouts", help="Fetch advancement data for all scouts")
    p_sync.add_argument(
        "--skip-reqs", action="store_true",
        help="Skip fetching per-requirement MB completion (faster sync)",
    )

    p_disc = sub.add_parser(
        "discover", help="Print raw API response for a scout (debugging)"
    )
    p_disc.add_argument("user_id", help="Scout's API userId")

    p_query = sub.add_parser("query", help="Run a troop-wide query")
    p_query.add_argument(
        "query_name",
        choices=["needs-mb", "next-rank", "req-matrix", "summary", "plan", "mb-reqs"],
        help="Query to run",
    )
    p_query.add_argument("--limit", type=int, default=20)
    p_query.add_argument("--rank-id", type=int)
    p_query.add_argument("--min-pct", type=float, default=50.0)
    p_query.add_argument(
        "--eagle-only", action="store_true",
        help="Only show Eagle-required merit badges (for needs-mb)",
    )
    p_query.add_argument(
        "--merit-badge", type=str, default=None,
        help="Filter by merit badge name (for mb-reqs)",
    )

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    commands = {
        "init": cmd_init,
        "sync-ranks": cmd_sync_ranks,
        "import-roster": cmd_import_roster,
        "add-scout": cmd_add_scout,
        "sync-scouts": cmd_sync_scouts,
        "discover": cmd_discover,
        "query": cmd_query,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
