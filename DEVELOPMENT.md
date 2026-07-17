# Development Guide

Developer-focused documentation for working on Scouting Troop Stats. For general usage, see the [README](README.md).

## Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) for dependency and virtualenv management

Install uv if you don't have it, then clone and set up:

```bash
git clone <this-repo>
cd scouting-troop-stats
uv sync
```

## CLI Reference

All commands are run via `uv run scouting <subcommand>`.

### Database Setup

```bash
# Create the database and download rank/requirement data (no auth needed)
uv run scouting init
uv run scouting sync-ranks
```

### Importing Your Troop Roster

There is no public API to pull a troop roster, so you'll export a CSV from Scoutbook Plus and import it locally.

1. Log in to [Scoutbook](https://scoutbook.scouting.org).
2. Navigate to your unit's **Roster** page.
3. Click **Export** or **Download** to save the roster as a CSV file.
4. Import it:

```bash
uv run scouting import-roster roster.csv
```

The CSV parser auto-detects common Scoutbook column names:

| Accepted columns     | What it maps to     |
|----------------------|---------------------|
| `User ID`, `UserID`  | Primary Scout identifier (used for API calls) |
| `Scouting Member ID`, `Member ID` | BSA membership number (fallback identifier) |
| `First Name`, `First` | Scout first name    |
| `Last Name`, `Last`   | Scout last name     |

At minimum, the CSV needs either a `User ID` or `Scouting Member ID` column. Re-importing the same CSV is safe -- it updates existing records without creating duplicates.

#### LLM Roster Extraction

Using the Claude Extension for Google Chrome, login to Scoutbook, go to your unit roster, and use the following prompt:

```
Create a CSV from the roster on this page that contains the fields "Name,UserId,MemberId,Type,Patrol". UserId is part of the URL linked on the Scout name, the other fields are all present in the table. Page through all pages so that we can get the full roster.
```

#### Adding Scouts manually

```bash
uv run scouting add-scout 123456789 "John Smith"
```

### Getting Your API Token

#### Option A: `get-token` command (recommended)

```bash
uv run scouting get-token
```

This prompts for your `my.scouting.org` username and password, fetches a JWT, and saves it to `config.json`. The saved username is remembered for subsequent runs.

#### Option B: Browser Developer Tools

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
export SCOUTING_TOKEN="eyJhbGciOiJSUzI1NiIs..."
uv run scouting sync-scouts
```

**Config file** (persists across sessions)

Create a `config.json` in the project directory:

```json
{
  "token": "eyJhbGciOiJSUzI1NiIs..."
}
```

This file is gitignored and will not be committed.

#### Token expiration

BSA tokens expire (typically after a few hours). When `sync-scouts` returns `401` errors, run `scouting get-token` again or grab a fresh token from the browser.

### Syncing Scout Data

Once Scouts are in the database, fetch their advancement records from the API:

```bash
uv run scouting sync-scouts
```

This pulls, for each Scout:
- **Rank advancement** -- ranks earned and in-progress, including per-requirement completion for in-progress ranks
- **Merit badges** -- completed and in-progress, including per-requirement completion for in-progress MBs
- **Leadership positions** -- SPL, PL, etc. with dates and approval status

You can re-run `sync-scouts` at any time to pick up new progress. It's idempotent -- existing records are updated, not duplicated.

#### `--skip-reqs` flag

To skip the per-requirement detail fetching (faster, fewer API calls):

```bash
uv run scouting sync-scouts --skip-reqs
```

### Queries

All queries are run via `uv run scouting query <name>`. The database must have rank data (`sync-ranks`) and Scout data (`sync-scouts`) populated first.

#### `query plan` -- Optimal Group Activities

Shows which merit badges and activities would benefit the most Scouts, so you can plan troop meetings around what the majority still needs.

```bash
uv run scouting query plan                 # Activities benefiting >= 50% of troop
uv run scouting query plan --min-pct 30    # Lower the threshold to 30%
```

#### `query needs-mb` -- Most Common Unfinished Merit Badges

```bash
uv run scouting query needs-mb                    # Top 20 across all merit badges
uv run scouting query needs-mb --eagle-only       # Only Eagle-required MBs
uv run scouting query needs-mb --limit 10         # Top 10
```

#### `query mb-reqs` -- Merit Badge Requirement Detail

```bash
uv run scouting query mb-reqs                              # All in-progress MBs
uv run scouting query mb-reqs --merit-badge "First Aid"    # Filter to one MB
```

Requires `sync-scouts` to have been run without `--skip-reqs`.

#### `query summary` -- Per-Scout Overview

```bash
uv run scouting query summary
```

#### `query next-rank` -- Scouts Closest to Next Rank

```bash
uv run scouting query next-rank
```

#### `query req-matrix` -- Requirement Completion Matrix

```bash
uv run scouting query req-matrix --rank-id 4     # First Class requirements
uv run scouting query req-matrix                  # Lists available rank IDs
```

### Web Server

```bash
uv run scouting serve                # starts on http://127.0.0.1:8765/, opens a browser
uv run scouting serve --port 9000    # use a different port
uv run scouting serve --no-browser   # don't auto-open a browser
```

Serves the dashboard at `/` (reading the `.db` at `--db`, or the default `scouting_troop.db` in the current directory) and a sign-in/sync form at `/sync` that streams live progress while it authenticates, imports an optional roster CSV, and syncs advancement data -- the same pipeline as `sync-scouts`, in the browser.

### Debugging

The `discover` command probes multiple API endpoints for a single Scout and prints the raw JSON responses:

```bash
uv run scouting discover 123456789
```

## MCP Server

The project ships an [MCP](https://modelcontextprotocol.io) server that exposes the local SQLite database to AI assistants like Claude.

### Starting the server

```bash
uv run scouting-mcp
```

The server communicates over stdio. Use the `BSA_DB_PATH` environment variable to point it at a non-default database path:

```bash
BSA_DB_PATH=/path/to/other.db uv run scouting-mcp
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
  "scouting": {
    "command": "uv",
    "args": ["run", "--directory", "/path/to/scouting-troop-stats", "scouting-mcp"],
    "env": {
      "BSA_DB_PATH": "/path/to/scouting-troop-stats/scouting_troop.db"
    }
  }
}
```

## Database

All data is stored in `scouting_troop.db` (SQLite) in your current working directory. You can query it directly:

```bash
sqlite3 scouting_troop.db "SELECT name FROM ranks WHERE program_id = 2 ORDER BY level;"
sqlite3 scouting_troop.db "SELECT COUNT(*) FROM scouts;"
```

Use `--db` to specify a different database path for any command:

```bash
uv run scouting --db /path/to/other.db sync-ranks
```

## Project Structure

```
scouting-troop-stats/
  pyproject.toml              # Project config, defines `scouting` and `scouting-mcp` entry points
  uv.lock                     # Lockfile (auto-generated)
  dashboard.html              # Browser dashboard (open via http.server or file picker)
  sample_troop.db             # Sample database with 50 fictional scouts for exploring the dashboard
  src/scouting_db/
    cli.py                    # CLI entry point (argparse subcommands)
    api.py                    # HTTP client for api.scouting.org
    db.py                     # SQLite schema, init, upsert functions
    queries.py                # Troop-wide analytical SQL queries
    sync_pipeline.py          # Shared authenticate+sync pipeline (used by CLI and web server)
    webserver.py              # Local web server: dashboard, synced .db, sync form (SSE)
    multipart.py              # Minimal multipart/form-data parser for the sync form upload
    mcp_server.py             # MCP server exposing the database to AI assistants
```

Dependencies: `mcp[cli]` (for the MCP server). The CLI itself uses only the Python standard library (`urllib`, `sqlite3`, `csv`, `json`, `argparse`).

