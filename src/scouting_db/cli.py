"""Scouting Troop Analytics CLI Tool.

Download Scout advancement data from api.scouting.org into a local
SQLite database and run troop-wide analytical queries.

Usage examples:
    scouting init
    scouting sync-ranks
    scouting import-roster roster.csv
    scouting sync-scouts
    scouting query plan --min-pct 40
    scouting query summary
"""

import argparse
import getpass
import json
import os
import sys

import click

from scouting_db.api import ScoutingAPI, ScoutingAPIError, authenticate
from scouting_db.db import (
    get_connection,
    import_roster_csv,
    init_db,
    set_setting,
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
from scouting_db.queries import (
    mb_requirement_detail,
    most_common_incomplete_merit_badges,
    optimal_group_activities,
    per_scout_summary,
    requirement_completion_matrix,
    scouts_closest_to_next_rank,
)

SCOUTS_BSA_PROGRAM_ID = 2


def get_token():
    token = os.environ.get("SCOUTING_TOKEN")
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
            'Set SCOUTING_TOKEN env var or create config.json with {"token": "..."}',
            file=sys.stderr,
        )
        sys.exit(1)
    return token


# --- Commands ---


def _ensure_troop_name(conn):
    """Prompt for the troop name if it hasn't been set yet."""
    row = conn.execute("SELECT value FROM settings WHERE key = 'troop_name'").fetchone()
    if not (row and row["value"]):
        name = input("Troop name not set. Enter troop name (e.g. 'Troop 42'): ").strip()
        if name:
            set_setting(conn, "troop_name", name)


def cmd_init(args):
    conn = get_connection(args.db)
    init_db(conn, troop_name=args.troop_name)
    conn.close()
    print(f"Database initialized at {args.db or 'scouting_troop.db'} (troop: {args.troop_name})")


def cmd_sync_ranks(args):
    conn = get_connection(args.db)
    init_db(conn)
    _ensure_troop_name(conn)
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
    _ensure_troop_name(conn)
    try:
        imported, skipped = import_roster_csv(conn, args.csv_file)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    conn.close()
    print(f"Imported {imported} Scouts ({skipped} rows skipped)")


def cmd_add_scout(args):
    conn = get_connection(args.db)
    init_db(conn)
    _ensure_troop_name(conn)
    name_parts = (args.name or "").split(" ", 1)
    first = name_parts[0] if name_parts[0] else None
    last = name_parts[1] if len(name_parts) > 1 else None
    upsert_scout(conn, args.user_id, first, last)
    conn.close()
    print(f"Added Scout {args.user_id}" + (f" ({args.name})" if args.name else ""))


def _abort_if_unauthorized(e, conn):
    """Exit immediately with a helpful message on 401 Unauthorized."""
    if e.status_code == 401:
        click.echo("")  # close any partial output line
        click.echo(
            click.style(
                "\nError: 401 Unauthorized — your token has likely expired.\n"
                "Run 'scouting get-token' to refresh it.",
                fg="red", bold=True,
            ),
            err=True,
        )
        conn.close()
        sys.exit(1)


def _ok(text):
    return click.style(text, fg="green")

def _err(text):
    return click.style(text, fg="red")

def _dim(text):
    return click.style(text, fg="bright_black")


def cmd_sync_scouts(args):
    token = require_token()
    conn = get_connection(args.db)
    init_db(conn)
    _ensure_troop_name(conn)
    api = ScoutingAPI(token=token)

    scouts = conn.execute(
        "SELECT user_id, first_name, last_name FROM scouts"
    ).fetchall()
    if not scouts:
        click.echo(click.style("No Scouts registered.", fg="yellow")
                   + " Use 'import-roster' or 'add-scout' first.")
        conn.close()
        return

    # Validate auth before starting the full sync loop
    click.echo("Validating auth... ", nl=False)
    try:
        api.validate_token(scouts[0]["user_id"])
        click.echo(click.style("✓", fg="green", bold=True))
    except ScoutingAPIError as e:
        click.echo("")
        _abort_if_unauthorized(e, conn)
        click.echo(click.style(f"⚠  auth check returned {e.status_code}, proceeding anyway.", fg="yellow"))

    skip_reqs = getattr(args, "skip_reqs", False)
    # Cache MB requirement definitions to avoid re-fetching for multiple Scouts
    mb_defn_cache = {}  # mb_id -> version_id (already stored)
    # Cache rank requirement definitions to avoid re-fetching
    rank_defn_cache = set()  # rank_ids already stored

    total = len(scouts)
    width = len(str(total))
    click.echo(f"\nSyncing {click.style(str(total), bold=True)} Scout{'s' if total != 1 else ''}\n")

    for i, scout in enumerate(scouts, 1):
        uid = scout["user_id"]
        name = f"{scout['first_name'] or ''} {scout['last_name'] or ''}".strip()
        label = name or uid

        counter = _dim(f"[{i:>{width}}/{total}]")
        click.echo(f"  {counter} {click.style(label, bold=True)}", nl=False)

        ranks_data = None
        try:
            ranks_data = api.get_youth_ranks(uid)
            count = store_youth_ranks(conn, uid, ranks_data)
            click.echo(f"  {_ok(f'ranks({count})')}", nl=False)
        except ScoutingAPIError as e:
            _abort_if_unauthorized(e, conn)
            click.echo(f"  {_err(f'[ranks:{e.status_code}]')}", nl=False)

        # Fetch per-requirement completion for in-progress ranks
        if not skip_reqs and ranks_data:
            in_progress_ranks = []
            for prog in ranks_data.get("program") or []:
                if prog.get("programId") != SCOUTS_BSA_PROGRAM_ID:
                    continue
                for rank in prog.get("ranks") or []:
                    if not (rank.get("dateEarned") or rank.get("dateCompleted")):
                        rank_id = rank.get("id")
                        if rank_id:
                            in_progress_ranks.append(int(rank_id))
            rank_req_count = 0
            for rank_id in in_progress_ranks:
                try:
                    # Cache rank requirement definitions
                    if rank_id not in rank_defn_cache:
                        defn = api.get_rank_requirements(rank_id)
                        upsert_requirements(conn, rank_id, defn)
                        rank_defn_cache.add(rank_id)

                    youth_reqs = api.get_youth_rank_requirements(uid, rank_id)
                    rank_req_count += store_youth_rank_requirements(
                        conn, uid, rank_id, youth_reqs
                    )
                except ScoutingAPIError as e:
                    _abort_if_unauthorized(e, conn)
            if rank_req_count:
                click.echo(f"  {_ok(f'rank_reqs({rank_req_count})')}", nl=False)

        mb_data = None
        try:
            mb_data = api.get_youth_merit_badges(uid)
            earned, total_mbs = store_youth_merit_badges(conn, uid, mb_data)
            click.echo(f"  {_ok(f'mbs({earned}/{total_mbs})')}", nl=False)
        except ScoutingAPIError as e:
            _abort_if_unauthorized(e, conn)
            click.echo(f"  {_err(f'[mbs:{e.status_code}]')}", nl=False)

        try:
            lead_data = api.get_leadership_history(uid)
            count = store_leadership(conn, uid, lead_data)
            click.echo(f"  {_ok(f'leadership({count})')}", nl=False)
        except ScoutingAPIError as e:
            _abort_if_unauthorized(e, conn)
            click.echo(f"  {_err(f'[lead:{e.status_code}]')}", nl=False)

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
                click.echo(f"  {_ok('dob')}", nl=False)
        except ScoutingAPIError as e:
            _abort_if_unauthorized(e, conn)
            click.echo(f"  {_err(f'[dob:{e.status_code}]')}", nl=False)

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

                    # Per-Scout completion
                    youth_reqs = api.get_youth_mb_requirements(uid, mb_id)
                    version_id = mb_defn_cache.get(mb_id) or mb.get("versionId") or ""
                    req_count += store_youth_mb_requirements(
                        conn, uid, mb_id, version_id, youth_reqs
                    )
                except ScoutingAPIError as e:
                    _abort_if_unauthorized(e, conn)
            if req_count:
                click.echo(f"  {_ok(f'reqs({req_count})')}", nl=False)

        click.echo("")  # end of scout line

    conn.close()
    click.echo(f"\n{click.style('✓', fg='green', bold=True)} Done — synced {total} Scout{'s' if total != 1 else ''}.")


def cmd_discover(args):
    token = require_token()
    conn = get_connection(args.db)
    init_db(conn)
    _ensure_troop_name(conn)
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

    # Probe rank requirement endpoints using a sample in-progress rank
    print("\n--- Rank Requirement Endpoint Probing ---\n")
    sample_rank = conn.execute(
        "SELECT advancement_id, advancement_name FROM scout_advancements "
        "WHERE scout_user_id = ? AND advancement_type = 'rank' "
        "AND status = 'in_progress' LIMIT 1",
        (uid,),
    ).fetchone()
    if not sample_rank:
        sample_rank = conn.execute(
            "SELECT advancement_id, advancement_name FROM scout_advancements "
            "WHERE advancement_type = 'rank' AND status = 'in_progress' LIMIT 1"
        ).fetchone()

    if sample_rank:
        rank_id = sample_rank["advancement_id"]
        rank_name = sample_rank["advancement_name"] or "Unknown"
        print(f"  Sample rank: {rank_name} (id={rank_id})\n")

        rank_probes = [
            (f"GET  /advancements/ranks/{rank_id}/requirements (public, definitions)",
             f"/advancements/ranks/{rank_id}/requirements"),
            (f"GET  /advancements/v2/youth/{uid}/ranks/{rank_id}/requirements (auth, per-Scout)",
             f"/advancements/v2/youth/{uid}/ranks/{rank_id}/requirements"),
        ]
        for label, path in rank_probes:
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
        print("  No in-progress ranks found to probe requirement endpoints.")

    # Probe MB requirement endpoints using a sample in-progress MB
    print("\n--- MB Requirement Endpoint Probing ---\n")
    sample = conn.execute(
        "SELECT mb_api_id, mb_version_id, merit_badge_name FROM scout_merit_badges "
        "WHERE scout_user_id = ? AND status = 'in_progress' LIMIT 1",
        (uid,),
    ).fetchone()
    if not sample:
        sample = conn.execute(
            "SELECT mb_api_id, mb_version_id, merit_badge_name FROM scout_merit_badges "
            "WHERE status = 'in_progress' LIMIT 1"
        ).fetchone()

    if sample:
        mb_id = sample["mb_api_id"]
        version_id = sample["mb_version_id"]
        mb_name = sample["merit_badge_name"]
        print(f"  Sample MB: {mb_name} (id={mb_id}, versionId={version_id})\n")

        mb_probes = [
            (f"GET  /advancements/meritBadges/{mb_id}/requirements (public, by mb id)",
             f"/advancements/meritBadges/{mb_id}/requirements"),
            (f"GET  /advancements/v2/youth/{uid}/meritBadges/{mb_id}/requirements (auth, per-Scout)",
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
            print("No Scouts in database.")
            conn.close()
            return
        print(f"\nTroop Summary ({len(rows)} Scouts):\n")
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


def cmd_get_token(args):
    config_path = os.path.join(os.getcwd(), "config.json")

    # Load existing config so we can read saved username and preserve other keys
    config = {}
    if os.path.exists(config_path):
        with open(config_path) as f:
            try:
                config = json.load(f)
            except json.JSONDecodeError:
                pass

    print("Authenticate with my.scouting.org")
    saved_username = config.get("username", "")
    prompt = f"Username [{saved_username}]: " if saved_username else "Username: "
    raw = input(prompt).strip()
    username = raw or saved_username
    password = getpass.getpass("Password: ")
    if not username or not password:
        print("Error: username and password are required.", file=sys.stderr)
        sys.exit(1)
    try:
        token, user_id = authenticate(username, password)
    except ScoutingAPIError as e:
        print(f"Authentication failed ({e.status_code}): {e.message}", file=sys.stderr)
        sys.exit(1)

    config["username"] = username
    config["token"] = token
    if user_id:
        config["user_id"] = str(user_id)

    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")

    print(f"Token saved to {config_path}")
    if user_id:
        print(f"User ID: {user_id}")


def main():
    parser = argparse.ArgumentParser(
        description="Scouting Troop Analytics CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--db", help="Path to SQLite database", default=None)
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init", help="Initialize the database")
    p_init.add_argument("troop_name", help="Name of the troop (e.g. 'Troop 42')")
    sub.add_parser("get-token", help="Authenticate with my.scouting.org and save token to config.json")
    sub.add_parser("sync-ranks", help="Download ranks and requirements")

    p_roster = sub.add_parser(
        "import-roster", help="Import Scouts from Scoutbook CSV roster export"
    )
    p_roster.add_argument("csv_file", help="Path to roster CSV file")

    p_add = sub.add_parser("add-scout", help="Manually add a single Scout")
    p_add.add_argument("user_id", help="Scout's API userId")
    p_add.add_argument("name", nargs="?", help="Scout's name ('First Last')")

    p_sync = sub.add_parser("sync-scouts", help="Fetch advancement data for all Scouts")
    p_sync.add_argument(
        "--skip-reqs", action="store_true",
        help="Skip fetching per-requirement MB completion (faster sync)",
    )

    p_disc = sub.add_parser(
        "discover", help="Print raw API response for a Scout (debugging)"
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
        "get-token": cmd_get_token,
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
