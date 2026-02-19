# Scouting Troop Stats

A tool for Scout leaders to download Scout advancement data from the Scouting America API into a local SQLite database, then explore it through an interactive browser dashboard or CLI queries. Figure out which merit badges and rank requirements the most Scouts still need so you can plan troop meetings that benefit everyone.

**NOTE:** While there is a "real" API that powers the likes of Scoutbook and other Scouting sites, it doesn't seem like it's meant to be used for actual application development. So ... this takes the approach of having you (a person) manually authenticate, and then pull down all of the relevant info for your roster. From that point you have a local SQLite database that you can query as much as you want.

**ALSO:** This is not an officially sanctioned tool. Use at your own risk.

## Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) for dependency and virtualenv management

Install uv if you don't have it, then clone and set up:

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

# 3. Authenticate and save your API token
uv run bsa get-token

# 4. Sync each scout's advancement data
uv run bsa sync-scouts

# 5. Open the dashboard
python -m http.server 8000
# then open http://localhost:8000/dashboard.html in your browser
```

## Dashboard

`dashboard.html` is an interactive browser UI that reads your `bsa_troop.db` directly — no extra server or build step required. It's the primary way to explore your troop's data visually.

### Opening the dashboard

Serve the project directory over HTTP so the dashboard can auto-load the database:

```bash
python -m http.server 8000
```

Then open **http://localhost:8000/dashboard.html** in your browser. The dashboard will automatically find and load `bsa_troop.db` from the same directory.

If you can't run a local server, open `dashboard.html` directly in your browser and use the **Open Database** button to load `bsa_troop.db` manually from your filesystem.

### Scout view

Select any Scout by name to see their full record:

- **Overview** — current rank, total merit badges earned (with Eagle count), in-progress MBs, and leadership days
- **Rank progress** — which requirements for their next rank are complete, in progress, or still needed
- **Merit badges** — completed and in-progress badges; click any in-progress badge to see a per-requirement breakdown
- **Eagle pipeline** — a visual tracker showing exactly which of the 14 Eagle-required MBs they've earned, are working on, or still need (with "choose one" group slots)
- **Leadership history** — all positions held with dates and approval status

### Troop view

Troop-wide analytics across all Scouts:

- **Rank distribution** — bar chart of how many Scouts are at each rank
- **Eagle MB gaps** — every Eagle-required badge ranked by how many Scouts still need it, with in-progress counts
- **All-MB gaps** — top 20 merit badges by number of Scouts who haven't earned them
- **Closest to next rank** — who needs the fewest requirements to advance, sorted by completion percentage
- **Activity planner** — merit badges where ≥ 40% of the troop would benefit, flagged by Eagle status
- **Roster** — full sortable table of all Scouts with rank, MB counts, and patrol

### How it works

The dashboard uses [sql.js](https://sql.js.org) (SQLite compiled to WebAssembly) to read the `.db` file entirely in the browser. Your data never leaves your machine.

## Getting Your API Token

### Option A: `get-token` command (recommended)

The easiest way to get and save a token is to let the CLI do it:

```bash
uv run bsa get-token
```

This prompts for your `my.scouting.org` username and password, fetches a JWT, and saves it to `config.json`. The saved username is remembered for subsequent runs.

### Option B: Browser Developer Tools

If `get-token` doesn't work, you can grab a token manually from your browser while logged into Scoutbook or Internet Advancement.

1. Open **Chrome** (or Firefox/Edge) and log in to [Scoutbook](https://scoutbook.scouting.org) or [Internet Advancement](https://advancements.scouting.org).
2. Open **Developer Tools** (press `F12`, or right-click the page and choose "Inspect").
3. Go to the **Network** tab.
4. Navigate to any page that loads Scout data (e.g., click on a Scout's advancement page).
5. In the Network tab, look for requests to `api.scouting.org`. Click on one.
6. In the **Headers** section, find the `Authorization` header. It will look like:
   ```
   Authorization: Bearer eyJhbGciOiJSUzI1NiIs...
   ```
7. Copy the entire token (everything after `Bearer `).

Then supply it via environment variable or config file:

**Environment variable** (one-off use)

```bash
export BSA_TOKEN="eyJhbGciOiJSUzI1NiIs..."
uv run bsa sync-scouts
```

**Config file** (persists across sessions)

Create a `config.json` in the project directory:

```json
{
  "token": "eyJhbGciOiJSUzI1NiIs..."
}
```

This file is gitignored and will not be committed.

### Token expiration

BSA tokens expire (typically after a few hours). When `sync-scouts` returns `401` errors, run `bsa get-token` again or grab a fresh token from the browser.

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
| `User ID`, `UserID`  | Primary Scout identifier (used for API calls) |
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

### Adding Scouts manually

If you don't have a CSV, you can add Scouts one at a time:

```bash
uv run bsa add-scout 123456789 "John Smith"
```

## Syncing Scout Data

Once Scouts are in the database, fetch their advancement records from the API:

```bash
uv run bsa sync-scouts
```

This pulls, for each Scout:
- **Rank advancement** -- ranks earned and in-progress, including per-requirement completion for in-progress ranks
- **Merit badges** -- completed and in-progress, including per-requirement completion for in-progress MBs
- **Leadership positions** -- SPL, PL, etc. with dates and approval status

You can re-run `sync-scouts` at any time to pick up new progress. It's idempotent -- existing records are updated, not duplicated.

### `--skip-reqs` flag

To skip the per-requirement detail fetching (faster, fewer API calls):

```bash
uv run bsa sync-scouts --skip-reqs
```

This skips the individual requirement completion endpoints for in-progress ranks and merit badges. Useful when you only need high-level rank/MB status and want a quicker sync.

## Queries

All queries are run via `uv run bsa query <name>`. The database must have rank data (`sync-ranks`) and Scout data (`sync-scouts`) populated first.

### `query plan` -- Optimal Group Activities

The main event. Shows which merit badges and activities would benefit the most Scouts, so you can plan troop meetings around what the majority still needs.

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

### `query mb-reqs` -- Merit Badge Requirement Detail

For in-progress merit badges, shows which individual requirements Scouts still need to complete.

```bash
uv run bsa query mb-reqs                              # All in-progress MBs
uv run bsa query mb-reqs --merit-badge "First Aid"    # Filter to one MB
```

Requires `sync-scouts` to have been run without `--skip-reqs`.

### `query summary` -- Per-Scout Overview

```bash
uv run bsa query summary
```

Example output:

```
Troop Summary (20 Scouts):

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

## MCP Server

The project ships an [MCP](https://modelcontextprotocol.io) server that exposes the local SQLite database to AI assistants like Claude. This lets you ask natural-language questions about your troop's data.

### Starting the server

```bash
uv run bsa-mcp
```

The server communicates over stdio. Use the `BSA_DB_PATH` environment variable to point it at a non-default database path:

```bash
BSA_DB_PATH=/path/to/other.db uv run bsa-mcp
```

### Tools exposed

| Tool | Description |
|------|-------------|
| `schema` | Returns all `CREATE TABLE` and `CREATE INDEX` statements so the AI understands the database structure |
| `query` | Executes any read-only `SELECT` statement and returns results as JSON |

The database is opened in **read-only mode** -- the MCP server cannot modify your data.

### Configuring Claude Code

Add the server to your Claude Code MCP settings (`.claude/mcp_servers.json` or via `/mcp add`):

```json
{
  "bsa-db": {
    "command": "uv",
    "args": ["run", "--directory", "/path/to/bsa-troop-stats", "bsa-mcp"],
    "env": {
      "BSA_DB_PATH": "/path/to/bsa-troop-stats/bsa_troop.db"
    }
  }
}
```

## Debugging

The `discover` command probes multiple API endpoints for a single Scout and prints the raw JSON responses. Useful for understanding what data the API returns (the youth advancement endpoints aren't publicly documented).

```bash
uv run bsa discover 123456789
```

This probes:
- `/advancements/v2/youth/{uid}/ranks`
- `/advancements/v2/youth/{uid}/meritBadges`
- `/advancements/v2/youth/{uid}/awards`
- `/advancements/v2/{uid}/userActivitySummary`
- `/advancements/youth/{uid}/leadershipPositionHistory`
- Rank requirement endpoints (public definitions + per-Scout completion) for any in-progress rank found in the database
- MB requirement endpoints (public definitions + per-Scout completion) for any in-progress MB found in the database

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
  pyproject.toml              # Project config, defines `bsa` and `bsa-mcp` entry points
  uv.lock                     # Lockfile (auto-generated)
  dashboard.html              # Browser dashboard (open via http.server or file picker)
  src/bsa_db/
    cli.py                    # CLI entry point (argparse subcommands)
    api.py                    # HTTP client for api.scouting.org
    db.py                     # SQLite schema, init, upsert functions
    queries.py                # Troop-wide analytical SQL queries
    mcp_server.py             # MCP server exposing the database to AI assistants
```

Dependencies: `mcp[cli]` (for the MCP server). The CLI itself uses only the Python standard library (`urllib`, `sqlite3`, `csv`, `json`, `argparse`).
