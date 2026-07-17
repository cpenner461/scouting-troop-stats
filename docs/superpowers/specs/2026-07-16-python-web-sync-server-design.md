# Design: Replace native macOS app with a local Python web server

## Goal

Replace the native macOS app (SwiftUI + WKWebView) with a local Python web server
that handles both syncing troop data and viewing the dashboard, in one browser
tab. The `.db` file and `dashboard.html` remain the portable, shareable outputs
they are today — this is a simplification, not a rearchitecture of the data model
or the dashboard's core loading behavior.

## Non-goals

- No packaging of a no-install/no-Python-required binary (e.g. PyInstaller). This
  was raised during design and is explicitly deferred to a future spec once the
  web server itself exists and its shape is settled.
- No changes to the CLI's existing data commands (`init`, `sync-ranks`,
  `import-roster`, `sync-scouts`, `query ...`) beyond adding one new subcommand.
- No changes to the database schema or query layer.
- No new third-party dependencies (stdlib only, consistent with the project's
  existing philosophy: stdlib `urllib` for the API client, stdlib `sqlite3`,
  stdlib `argparse`).

## What gets removed

- `macos-app/` in its entirety: the SwiftUI project, xcodegen spec, Makefile,
  DMG build scripts, vendored `sql-wasm.js`/`sql-wasm.wasm` copies, icons.
- The dead Electron branch in `dashboard.html`'s `initSQL()` function (checks
  `window.electronAPI`, which can never be true now that Electron was removed
  in commit `0e96df6` — this is stale code left over from before that removal).
- `src/scouting_db/native_sync.py` — superseded by the shared sync pipeline
  module described below (its logic moves, the file doesn't survive as a
  separate Electron/Swift bridge entry point).
- macOS app references in `README.md` and `DEVELOPMENT.md`.

## What stays unchanged

- The CLI (`scouting init`, `sync-ranks`, `import-roster`, `add-scout`,
  `sync-scouts`, `discover`, `query ...`) — fully intact for power users.
- `dashboard.html` as a standalone file: it can still be opened directly via
  `file://` and used with the "Open Database" file picker, or shared alongside
  a `.db` file, exactly as today.
- The `.db` file as the portable artifact and `sample_troop.db` as the demo.
- The MCP server (`scouting-mcp`).

## Architecture

### 1. Shared sync pipeline

`native_sync.py` already implements the full pipeline end-to-end: authenticate,
initialize the database, sync rank definitions, optionally import a roster CSV,
then sync per-Scout advancement data — reporting progress via `step()`/`log()`/
`error()`/`complete()` callbacks that currently just print JSON lines to stdout
for the (now-removed) Electron/Swift bridge.

This logic is refactored into `src/scouting_db/sync_pipeline.py` as a single
function:

```python
def run_sync(
    username: str,
    password: str,
    troop_name: str,
    db_path: str,
    config_path: str,
    csv_path: str | None = None,
    skip_reqs: bool = False,
    on_progress: Callable[[str, dict], None] = lambda kind, data: None,
) -> None:
    ...
```

`on_progress` is called with `(kind, data)` for each step/log/error/complete
event instead of printing to stdout. This is the one implementation of the
"authenticate → init → sync ranks → import CSV → sync scouts" flow; both the
CLI and the new web server call into it (the CLI's existing `sync-scouts`
command continues to call the lower-level `db.py`/`api.py` functions directly
and is unaffected — this refactor only replaces `native_sync.py`'s reason for
existing).

### 2. Web server

New module `src/scouting_db/webserver.py`, built on stdlib `http.server`.

New CLI subcommand, added to `cli.py`:

```
uv run scouting serve [--db PATH] [--port 8765] [--no-browser]
```

- Binds to `127.0.0.1` only — never exposed beyond the local machine.
- Opens the default browser to `http://127.0.0.1:<port>/` automatically via
  stdlib `webbrowser`, unless `--no-browser` is passed.
- `--db` defaults to the same default the CLI already uses (`scouting_troop.db`
  in the current working directory).

Routes:

| Route | Method | Behavior |
|---|---|---|
| `/` | GET | Serves `dashboard.html` unmodified (aside from the Electron cleanup above) |
| `/scouting_troop.db` | GET | Serves the current `.db` file's bytes from `--db` |
| `/sync` | GET | Serves a small HTML sync form: username, password, troop name, optional CSV file upload |
| `/api/sync` | POST | Accepts the form (multipart, for the CSV upload), calls `run_sync(...)`, streams progress back as Server-Sent Events (`text/event-stream`) |

Because `dashboard.html` already does:

```js
// Auto-load scouting_troop.db from the same directory (works when served over HTTP)
const resp = await fetch('./scouting_troop.db');
```

...serving the `.db` file at that same-origin path means **no dashboard.html
changes are required** for auto-load to work under the new server. The existing
manual "Open Database" file picker also keeps working unchanged, since it's a
local `<input type=file>` + `arrayBuffer()` read, unaffected by being served
over HTTP instead of opened via `file://`.

### 3. Credentials handling

The sync form posts username/password once to `/api/sync` over the loopback
connection; the password is never persisted (same as the CLI's `get-token`
flow today). Only the resulting auth token is written to `config.json`.

### 4. Progress reporting

`POST /api/sync` streams Server-Sent Events, one per pipeline progress
callback (`step`, `log`, `error`, `complete`), so the browser shows live
per-step status ("Authenticating…", "Syncing Scout 12/50…") the same way the
macOS app's sync screen did, without polling.

## Testing

- `tests/test_sync_pipeline.py` — mocks `scouting_db.api.urllib.request.urlopen`
  (same pattern as `test_api.py`), verifies the progress-callback sequence for
  a successful sync and for an auth failure, and that CSV import is invoked
  only when a path is given.
- `tests/test_webserver.py` — starts a real server instance on an ephemeral
  port, uses stdlib `http.client` to verify: `GET /` returns the dashboard
  HTML, `GET /scouting_troop.db` returns the expected bytes, `POST /api/sync`
  streams the expected SSE events for a mocked successful sync and a mocked
  auth failure.
- Existing 159 tests in `test_api.py`, `test_db.py`, `test_queries.py` continue
  to pass unchanged.

## Documentation updates

- `README.md`: replace the "macOS App (recommended)" section with a
  "Web App (recommended)" section describing `uv run scouting serve`. Keep the
  "Browser Dashboard" section (opening `dashboard.html` directly) for the
  share-a-`.db`-file case.
- `DEVELOPMENT.md`: remove the "macOS App Development" section and its
  project-structure entry; add `webserver.py` and `sync_pipeline.py` to the
  project structure listing; document the `serve` subcommand alongside the
  other CLI commands.

## Deferred (future spec)

A no-install distribution path (e.g. a PyInstaller-built single executable per
OS) so non-technical users don't need Python/uv installed. This is out of
scope here; the web server's shape should settle first.
