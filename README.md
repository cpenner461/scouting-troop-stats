# BSA Troop Analytics

A CLI tool for scoutmasters to download scout advancement data from the BSA API into a local SQLite database and run troop-wide queries. Figure out which merit badges and rank requirements the most scouts still need so you can plan troop meetings that benefit everyone.

## Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) for dependency and virtualenv management

Install uv if you don't have it:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then clone and set up:

```bash
git clone <this-repo>
cd bsa-db
uv sync
```

## Quick Start

```bash
# 1. Create the database and download rank/requirement data (no auth needed)
uv run bsa init
uv run bsa sync-ranks

# 2. Import your troop roster from a Scoutbook CSV export
uv run bsa import-roster roster.csv

# 3. Set your API token and sync each scout's advancement data
export BSA_TOKEN="eyJhbGciOi..."
uv run bsa sync-scouts

# 4. Run queries
uv run bsa query plan --min-pct 40
uv run bsa query summary
```

## Getting Your API Token

The BSA API requires a JWT (JSON Web Token) to access per-scout advancement data. The easiest way to get one is from your browser while logged into Scoutbook or Internet Advancement.

### Step-by-step: Browser Developer Tools

1. Open **Chrome** (or Firefox/Edge) and log in to [Scoutbook](https://scoutbook.scouting.org) or [Internet Advancement](https://advancements.scouting.org).
2. Open **Developer Tools** (press `F12`, or right-click the page and choose "Inspect").
3. Go to the **Network** tab.
4. Navigate to any page that loads scout data (e.g., click on a scout's advancement page).
5. In the Network tab, look for requests to `api.scouting.org`. Click on one.
6. In the **Headers** section, find the `Authorization` header. It will look like:
   ```
   Authorization: Bearer eyJhbGciOiJSUzI1NiIs...
   ```
7. Copy the entire token (everything after `Bearer `).

### Using the token

**Option A: Environment variable** (recommended for one-off use)

```bash
export BSA_TOKEN="eyJhbGciOiJSUzI1NiIs..."
uv run bsa sync-scouts
```

**Option B: Config file** (persists across sessions)

Create a `config.json` in the project directory:

```json
{
  "token": "eyJhbGciOiJSUzI1NiIs..."
}
```

This file is gitignored and will not be committed.

### Token expiration

BSA tokens expire (typically after a few hours). When `sync-scouts` starts returning `401` errors, grab a fresh token using the steps above.

## Exporting Your Troop Roster

There is no public API to pull a troop roster, so you'll export a CSV from Scoutbook Plus and import it locally.

### Step-by-step: Scoutbook Plus Export

1. Log in to [Scoutbook](https://scoutbook.scouting.org).
2. Navigate to your unit's **Roster** page.
3. Click **Export** or **Download** to save the roster as a CSV file.
4. Import it:

```bash
uv run bsa import-roster roster.csv
```

The CSV parser auto-detects common Scoutbook column names:

| Accepted columns     | What it maps to     |
|----------------------|---------------------|
| `User ID`, `UserID`  | Primary scout identifier (used for API calls) |
| `BSA Member ID`, `Member ID` | BSA membership number (fallback identifier) |
| `First Name`, `First` | Scout first name    |
| `Last Name`, `Last`   | Scout last name     |

At minimum, the CSV needs either a `User ID` or `BSA Member ID` column. Re-importing the same CSV is safe -- it updates existing records without creating duplicates.

### LLM Roster Extraction
Using the Claude Extension for Google Chrome, login to Scoutbook, go to your unit roster, and use the following prompt:

```
Create a CSV from the roster on this page that contains the fields "Name,UserId,MemberId,Type,Patrol". UserId is part of the URL linked on the Scout name, the other fields are all present in the table. Page through all pages so that we can get the full roster.
```

This should generate a CSV that you can use directly with this.

### Adding scouts manually

If you don't have a CSV, you can add scouts one at a time:

```bash
uv run bsa add-scout 123456789 "John Smith"
```

## Syncing Scout Data

Once scouts are in the database, fetch their advancement records from the API:

```bash
uv run bsa sync-scouts
```

This pulls, for each scout:
- **Advancement records** -- ranks earned, merit badges completed or in progress
- **Leadership positions** -- SPL, PL, etc. with dates and approval status

You can re-run `sync-scouts` at any time to pick up new progress. It's idempotent -- existing records are updated, not duplicated.

## Queries

All queries are run via `uv run bsa query <name>`. The database must have rank data (`sync-ranks`) and scout data (`sync-scouts`) populated first.

### `query plan` -- Optimal Group Activities

The main event. Shows which merit badges and activities would benefit the most scouts, so you can plan troop meetings around what the majority still needs.

```bash
uv run bsa query plan                 # Activities benefiting >= 50% of troop
uv run bsa query plan --min-pct 30    # Lower the threshold to 30%
```

Example output:

```
Optimal Group Activities (>= 50.0% of troop benefits):

  Activity                                 Eagle  Benefit  %
  ---------------------------------------- ----- ------- ------
  Citizenship in Society                    *      18       90.0%
  Environmental Science                     *      16       80.0%
  Sustainability                            *      15       75.0%
  Personal Management                       *      12       60.0%
```

### `query needs-mb` -- Most Common Unfinished Merit Badges

```bash
uv run bsa query needs-mb                    # Top 20 across all merit badges
uv run bsa query needs-mb --eagle-only       # Only Eagle-required MBs
uv run bsa query needs-mb --limit 10         # Top 10
```

### `query summary` -- Per-Scout Overview

```bash
uv run bsa query summary
```

Example output:

```
Troop Summary (20 scouts):

  Scout                     Rank           MBs   Eagle  In Prog
  ------------------------- ------------- ---- ----- -------
  Jane Doe                  Life Scout     32   10     3
  John Smith                Star Scout     18   6      5
  Alex Johnson              First Class    8    3      2
```

### `query next-rank` -- Scouts Closest to Next Rank

Shows who is nearest to completing their next rank, sorted by fewest requirements remaining.

```bash
uv run bsa query next-rank
```

### `query req-matrix` -- Requirement Completion Matrix

For a specific rank, shows which requirements are most commonly incomplete across the troop.

```bash
uv run bsa query req-matrix --rank-id 4     # First Class requirements
```

If you don't know the rank ID, omit `--rank-id` and it will list them:

```bash
uv run bsa query req-matrix
# Output:
#   1: Scout
#   2: Tenderfoot
#   3: Second Class
#   4: First Class
#   5: Star Scout
#   6: Life Scout
#   7: Eagle Scout
```

## Debugging

The `discover` command dumps the raw JSON response from the API for a single scout. This is useful for understanding what fields the API returns (the youth advancement endpoint isn't publicly documented).

```bash
uv run bsa discover 123456789
```

This prints both the advancement data and leadership history as raw JSON.

## Database

All data is stored in `bsa_troop.db` (SQLite) in your current working directory. You can query it directly:

```bash
sqlite3 bsa_troop.db "SELECT name FROM ranks WHERE program_id = 2 ORDER BY level;"
sqlite3 bsa_troop.db "SELECT COUNT(*) FROM scouts;"
```

Use `--db` to specify a different database path for any command:

```bash
uv run bsa --db /path/to/other.db sync-ranks
```

## Project Structure

```
bsa-db/
  pyproject.toml              # Project config, defines `bsa` CLI entry point
  uv.lock                     # Lockfile (auto-generated)
  src/bsa_db/
    cli.py                    # CLI entry point (argparse subcommands)
    api.py                    # HTTP client for api.scouting.org
    db.py                     # SQLite schema, init, upsert functions
    queries.py                # Troop-wide analytical SQL queries
```

No external dependencies -- uses only Python standard library (`urllib`, `sqlite3`, `csv`, `json`, `argparse`).
