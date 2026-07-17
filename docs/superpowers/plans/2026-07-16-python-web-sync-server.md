# Python Web Sync Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the native macOS app with a local Python web server (`uv run scouting serve`) that syncs troop data and serves the dashboard from one browser tab, while removing the Electron/Swift-specific code paths.

**Architecture:** Extract the existing sync pipeline (currently locked inside `native_sync.py`, built for the removed Electron/Swift bridge) into a reusable `sync_pipeline.py` module with a progress-callback interface. Build a stdlib-only `http.server`-based web server (`webserver.py`) that serves `dashboard.html`, serves the current `.db` file at a fixed path (which `dashboard.html` already auto-fetches), and exposes a sync form that streams progress over a POST-based SSE-style stream. Wire it up as a new `scouting serve` CLI subcommand. Delete `macos-app/` and the dead Electron branch in `dashboard.html`.

**Tech Stack:** Python 3.10+ stdlib only (`http.server`, `urllib`, `sqlite3`, `argparse`, `tempfile`, `webbrowser`) — no new dependencies. Existing test stack: `pytest`, `unittest.mock`.

## Global Constraints

- No new third-party dependencies — stdlib only, matching the project's existing philosophy (stdlib `urllib` for the API client, stdlib `sqlite3`, stdlib `argparse`).
- The web server binds to `127.0.0.1` only — never exposed beyond the local machine.
- Passwords are never persisted — only the resulting auth token is written to `config.json` (matches the existing `get-token` CLI command's behavior).
- The CLI's existing data commands (`init`, `sync-ranks`, `import-roster`, `add-scout`, `sync-scouts`, `discover`, `query ...`) must keep working unchanged.
- `dashboard.html` must remain openable standalone via `file://` with the manual "Open Database" file picker, exactly as today.
- Python 3.10+ compatibility (`requires-python = ">=3.10"` in `pyproject.toml`) — do not use the stdlib `cgi` module (deprecated in 3.11, removed in 3.13); use the hand-written multipart parser from Task 2 instead.

---

### Task 1: Shared sync pipeline module

**Files:**
- Create: `src/scouting_db/sync_pipeline.py`
- Delete: `src/scouting_db/native_sync.py`
- Test: `tests/test_sync_pipeline.py`

**Interfaces:**
- Produces: `scouting_db.sync_pipeline.run_sync(username: str, password: str, troop_name: str, db_path: str, config_path: str, csv_path: str | None = None, skip_reqs: bool = False, on_progress: Callable[[str, dict], None] = lambda kind, data: None) -> bool`. `on_progress` is called with `(kind, data)` where `kind` is one of `"step"`, `"log"`, `"error"`, `"complete"` and `data` is `{"message": str}` for step/log/error or `{"db_path": str}` for complete. Returns `True` on success, `False` if it stopped early (an `"error"` event was already sent).

`native_sync.py` currently implements this exact pipeline (authenticate → init db → sync ranks → optional CSV import → sync all Scouts) but prints JSON lines to stdout for the now-deleted Electron/Swift bridge. This task moves that logic into a plain function with a callback, and deletes the file whose only purpose was bridging to the removed native apps (confirmed via `grep -rn "native_sync"` — nothing else references it).

Note: `tests/conftest.py`'s `conn` fixture is untouched by this task. `_mock_response`/`_http_error` are defined locally in the test file below (as a plain function, `tests/conftest.py` is only importable as `tests.conftest` because `tests/__init__.py` exists — a bare `from conftest import ...` fails — so this follows `test_api.py`'s existing pattern of a local, file-scoped helper instead of a cross-file import).

- [ ] **Step 1: Write the failing tests for `run_sync`**

Create `tests/test_sync_pipeline.py`:

```python
"""Tests for scouting_db.sync_pipeline."""

import io
import json
import urllib.error
from unittest.mock import MagicMock, patch

from scouting_db.api import ScoutingAPIError
from scouting_db.sync_pipeline import run_sync


def _mock_response(data) -> MagicMock:
    """Create a MagicMock that acts as a urllib context-manager response."""
    mock = MagicMock()
    mock.read.return_value = json.dumps(data).encode("utf-8")
    mock.__enter__.return_value = mock
    mock.__exit__.return_value = False
    return mock


def _http_error(code: int, body: str = "error") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://example.com", code, "HTTP Error", MagicMock(), io.BytesIO(body.encode())
    )


class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, kind, data):
        self.calls.append((kind, data))


class TestRunSyncAuthFailure:
    def test_bad_credentials_emits_error_and_returns_false(self, tmp_path):
        recorder = _Recorder()
        with patch(
            "scouting_db.sync_pipeline.authenticate",
            side_effect=ScoutingAPIError(401, "bad creds"),
        ):
            result = run_sync(
                "user", "wrongpass", "Troop 1",
                str(tmp_path / "t.db"), str(tmp_path / "config.json"),
                on_progress=recorder,
            )
        assert result is False
        kinds = [k for k, _ in recorder.calls]
        assert "error" in kinds
        assert not (tmp_path / "config.json").exists()


class TestRunSyncNoScouts:
    def test_no_scouts_and_no_csv_completes_with_tip(self, tmp_path):
        recorder = _Recorder()
        responses = [
            _mock_response({"token": "tok", "account": {"userId": "U1"}}),  # authenticate
            _mock_response([]),  # get_ranks -> empty list
        ]
        with patch("scouting_db.api.urllib.request.urlopen", side_effect=responses):
            result = run_sync(
                "user", "pass", "Troop 1",
                str(tmp_path / "t.db"), str(tmp_path / "config.json"),
                on_progress=recorder,
            )
        assert result is True
        assert (tmp_path / "config.json").exists()
        config = json.loads((tmp_path / "config.json").read_text())
        assert config["token"] == "tok"
        messages = " ".join(d.get("message", "") for _, d in recorder.calls)
        assert "No Scouts" in messages
        assert any(kind == "complete" for kind, _ in recorder.calls)


class TestRunSyncWithRoster:
    def test_csv_import_then_sync_completes(self, tmp_path):
        csv_path = tmp_path / "roster.csv"
        csv_path.write_text("User ID,First Name,Last Name,Type\nU1,Jane,Doe,YOUTH\n")

        recorder = _Recorder()
        responses = [
            _mock_response({"token": "tok", "account": {"userId": "U1"}}),  # authenticate
            _mock_response([]),  # get_ranks -> empty list
            _mock_response({"program": []}),  # get_youth_ranks for U1
            _mock_response([]),  # get_youth_merit_badges for U1
            _mock_response({}),  # get_leadership_history for U1
            _mock_response({}),  # get_person_profile for U1
        ]
        with patch("scouting_db.api.urllib.request.urlopen", side_effect=responses):
            result = run_sync(
                "user", "pass", "Troop 1",
                str(tmp_path / "t.db"), str(tmp_path / "config.json"),
                csv_path=str(csv_path), skip_reqs=True,
                on_progress=recorder,
            )
        assert result is True
        messages = " ".join(d.get("message", "") for _, d in recorder.calls)
        assert "1 Scouts imported" in messages
        assert any(kind == "complete" for kind, _ in recorder.calls)


class TestRunSyncTokenExpiresMidSync:
    def test_401_during_scout_sync_emits_error_and_stops(self, tmp_path):
        csv_path = tmp_path / "roster.csv"
        csv_path.write_text("User ID,First Name,Last Name,Type\nU1,Jane,Doe,YOUTH\n")

        recorder = _Recorder()
        responses = [
            _mock_response({"token": "tok", "account": {"userId": "U1"}}),  # authenticate
            _mock_response([]),  # get_ranks -> empty list
            _http_error(401, "expired"),  # get_youth_ranks for U1 -> 401
        ]
        with patch("scouting_db.api.urllib.request.urlopen", side_effect=responses):
            result = run_sync(
                "user", "pass", "Troop 1",
                str(tmp_path / "t.db"), str(tmp_path / "config.json"),
                csv_path=str(csv_path), skip_reqs=True,
                on_progress=recorder,
            )
        assert result is False
        messages = " ".join(d.get("message", "") for _, d in recorder.calls)
        assert "Token expired" in messages
```

Note: `_mock_response` wraps a dict/list as the JSON body; `urlopen`'s `side_effect` list is consumed once per call in call order (authenticate is one `urlopen` call, each `ScoutingAPI._request` is one more).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --with pytest pytest tests/test_sync_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scouting_db.sync_pipeline'`

- [ ] **Step 3: Create `src/scouting_db/sync_pipeline.py`**

```python
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
    rank_defn_cache = set()  # rank_ids already stored

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
```

- [ ] **Step 4: Delete `native_sync.py`**

```bash
git rm src/scouting_db/native_sync.py
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run --with pytest pytest tests/test_sync_pipeline.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Run the full test suite to confirm no regressions**

Run: `uv run --with pytest pytest tests/ -v`
Expected: PASS (all tests, including the pre-existing 159)

- [ ] **Step 7: Commit**

```bash
git add src/scouting_db/sync_pipeline.py tests/test_sync_pipeline.py
git commit -m "Extract sync pipeline into reusable module with progress callback

Replaces native_sync.py, which existed only to bridge to the now-removed
Electron/Swift native apps."
```

---

### Task 2: Multipart form parser

**Files:**
- Create: `src/scouting_db/multipart.py`
- Test: `tests/test_multipart.py`

**Interfaces:**
- Produces: `scouting_db.multipart.parse_multipart(body: bytes, content_type: str) -> dict[str, str | dict]`. Text fields map to `str` values; file fields map to `{"filename": str, "content": bytes}`. Raises `ValueError` if `content_type` has no `multipart/form-data` boundary.

The web server needs to accept a `POST /api/sync` form with a username, password, troop name, and an optional CSV file upload. The stdlib's `cgi` module (which used to handle this) is deprecated since Python 3.11 and removed in 3.13, so this is a small hand-written parser instead, kept independently testable.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_multipart.py`:

```python
"""Tests for scouting_db.multipart."""

import pytest

from scouting_db.multipart import parse_multipart


def _build_body(boundary, fields):
    """fields: list of (name, value) where value is str or {"filename": str, "content": bytes}."""
    lines = []
    for name, value in fields:
        lines.append(f"--{boundary}".encode())
        if isinstance(value, dict):
            lines.append(
                f'Content-Disposition: form-data; name="{name}"; '
                f'filename="{value["filename"]}"'.encode()
            )
            lines.append(b"Content-Type: text/csv")
            lines.append(b"")
            lines.append(value["content"])
        else:
            lines.append(f'Content-Disposition: form-data; name="{name}"'.encode())
            lines.append(b"")
            lines.append(value.encode())
    lines.append(f"--{boundary}--".encode())
    return b"\r\n".join(lines) + b"\r\n"


class TestParseMultipart:
    def test_parses_text_fields(self):
        body = _build_body("B1", [("username", "alice"), ("password", "s3cret")])
        fields = parse_multipart(body, "multipart/form-data; boundary=B1")
        assert fields["username"] == "alice"
        assert fields["password"] == "s3cret"

    def test_parses_file_field(self):
        body = _build_body("B2", [
            ("username", "alice"),
            ("csv_file", {"filename": "roster.csv", "content": b"User ID\nU1\n"}),
        ])
        fields = parse_multipart(body, "multipart/form-data; boundary=B2")
        assert fields["csv_file"]["filename"] == "roster.csv"
        assert fields["csv_file"]["content"] == b"User ID\nU1\n"

    def test_empty_file_field_has_empty_filename(self):
        body = _build_body("B3", [("csv_file", {"filename": "", "content": b""})])
        fields = parse_multipart(body, "multipart/form-data; boundary=B3")
        assert fields["csv_file"]["filename"] == ""

    def test_quoted_boundary_is_handled(self):
        body = _build_body("B4", [("username", "bob")])
        fields = parse_multipart(body, 'multipart/form-data; boundary="B4"')
        assert fields["username"] == "bob"

    def test_missing_boundary_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_multipart(b"irrelevant", "multipart/form-data")

    def test_non_multipart_content_type_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_multipart(b"irrelevant", "application/json")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --with pytest pytest tests/test_multipart.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scouting_db.multipart'`

- [ ] **Step 3: Create `src/scouting_db/multipart.py`**

```python
"""Minimal multipart/form-data request body parser (stdlib only).

Written by hand because Python's cgi module (the historical way to parse
multipart bodies) is deprecated since 3.11 and removed in 3.13.
"""


def parse_multipart(body: bytes, content_type: str) -> dict:
    """Parse a multipart/form-data request body.

    Returns a dict mapping field name -> str value for text fields, or
    field name -> {"filename": str, "content": bytes} for file fields.
    Raises ValueError if content_type has no multipart/form-data boundary.
    """
    boundary = _extract_boundary(content_type)
    if boundary is None:
        raise ValueError("Content-Type is not multipart/form-data with a boundary")

    delimiter = b"--" + boundary
    fields = {}
    for part in body.split(delimiter):
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        if b"\r\n\r\n" not in part:
            continue
        header_blob, content = part.split(b"\r\n\r\n", 1)
        content = content[:-2] if content.endswith(b"\r\n") else content
        headers = _parse_headers(header_blob)
        disposition = headers.get("content-disposition", "")
        name = _extract_param(disposition, "name")
        if name is None:
            continue
        filename = _extract_param(disposition, "filename")
        if filename is not None:
            fields[name] = {"filename": filename, "content": content}
        else:
            fields[name] = content.decode("utf-8")
    return fields


def _extract_boundary(content_type: str):
    if "multipart/form-data" not in content_type:
        return None
    for piece in content_type.split(";"):
        piece = piece.strip()
        if piece.startswith("boundary="):
            return piece[len("boundary="):].strip('"').encode("utf-8")
    return None


def _parse_headers(header_blob: bytes) -> dict:
    headers = {}
    for line in header_blob.split(b"\r\n"):
        if b":" not in line:
            continue
        key, value = line.split(b":", 1)
        headers[key.strip().lower().decode("utf-8")] = value.strip().decode("utf-8")
    return headers


def _extract_param(header_value: str, param_name: str):
    prefix = f"{param_name}="
    for piece in header_value.split(";"):
        piece = piece.strip()
        if piece.startswith(prefix):
            return piece[len(prefix):].strip('"')
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --with pytest pytest tests/test_multipart.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/scouting_db/multipart.py tests/test_multipart.py
git commit -m "Add stdlib-only multipart/form-data parser for the sync form upload"
```

---

### Task 3: Web server static routes

**Files:**
- Create: `src/scouting_db/webserver.py`
- Test: `tests/test_webserver.py`

**Interfaces:**
- Consumes: nothing from earlier tasks yet (this task only wires static routes; Task 4 wires the sync endpoint using Task 1/2's `run_sync`/`parse_multipart`).
- Produces: `scouting_db.webserver.build_server(db_path: str, port: int = 8765) -> http.server.ThreadingHTTPServer` (server instance with `.db_path` attribute set, not yet serving). `scouting_db.webserver.serve(db_path: str, port: int = 8765, open_browser: bool = True) -> None` (blocks, calls `build_server` then `serve_forever`). Routes so far: `GET /` → `dashboard.html`, `GET /scouting_troop.db` → current db file bytes, anything else → 404.

`dashboard.html` already contains `fetch('./scouting_troop.db')` as an auto-load fallback (see `dashboard.html` around the `initSQL`/`loadDbBuffer` functions) — serving the `.db` file at that same-origin path means the dashboard's existing JS works with zero changes.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_webserver.py`:

```python
"""Tests for scouting_db.webserver."""

import http.client
import threading

import pytest

from scouting_db.db import get_connection, init_db
from scouting_db.webserver import build_server


@pytest.fixture
def running_server(tmp_path):
    db_path = tmp_path / "scouting_troop.db"
    conn = get_connection(str(db_path))
    init_db(conn, troop_name="Test Troop")
    conn.close()

    httpd = build_server(str(db_path), port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd.server_address[1], db_path
    finally:
        httpd.shutdown()
        thread.join()


class TestStaticRoutes:
    def test_root_serves_dashboard_html(self, running_server):
        port, _ = running_server
        conn = http.client.HTTPConnection("127.0.0.1", port)
        conn.request("GET", "/")
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        assert resp.status == 200
        assert resp.getheader("Content-Type") == "text/html"
        assert b"<!DOCTYPE html>" in body or b"<html" in body

    def test_db_route_serves_current_db_bytes(self, running_server):
        port, db_path = running_server
        conn = http.client.HTTPConnection("127.0.0.1", port)
        conn.request("GET", "/scouting_troop.db")
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        assert resp.status == 200
        assert body == db_path.read_bytes()

    def test_db_route_404s_when_db_missing(self, tmp_path):
        httpd = build_server(str(tmp_path / "missing.db"), port=0)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1])
            conn.request("GET", "/scouting_troop.db")
            resp = conn.getresponse()
            resp.read()
            conn.close()
            assert resp.status == 404
        finally:
            httpd.shutdown()
            thread.join()

    def test_unknown_route_returns_404(self, running_server):
        port, _ = running_server
        conn = http.client.HTTPConnection("127.0.0.1", port)
        conn.request("GET", "/nope")
        resp = conn.getresponse()
        resp.read()
        conn.close()
        assert resp.status == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --with pytest pytest tests/test_webserver.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scouting_db.webserver'`

- [ ] **Step 3: Create `src/scouting_db/webserver.py`** (static routes only — the `/sync` and `/api/sync` routes are added in Task 4)

```python
"""Local web server: serves the dashboard and the synced database.

Binds to 127.0.0.1 only. Started via `uv run scouting serve`.
"""

import http.server
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

DASHBOARD_PATH = Path(__file__).resolve().parent.parent.parent / "dashboard.html"


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # quiet console; errors still surface via HTTP status codes

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self._serve_file(DASHBOARD_PATH, "text/html")
        elif path == "/scouting_troop.db":
            self._serve_file(Path(self.server.db_path), "application/octet-stream")
        else:
            self.send_error(404)

    def _serve_file(self, path: Path, content_type: str):
        if not path.exists():
            self.send_error(404, f"{path.name} not found")
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def build_server(db_path: str, port: int = 8765) -> http.server.ThreadingHTTPServer:
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    httpd.db_path = db_path
    return httpd


def serve(db_path: str, port: int = 8765, open_browser: bool = True) -> None:
    httpd = build_server(db_path, port)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"Serving at {url} (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server.")
    finally:
        httpd.server_close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --with pytest pytest tests/test_webserver.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/scouting_db/webserver.py tests/test_webserver.py
git commit -m "Add local web server serving the dashboard and synced database"
```

---

### Task 4: Sync form and SSE endpoint

**Files:**
- Modify: `src/scouting_db/webserver.py`
- Modify: `tests/test_webserver.py`

**Interfaces:**
- Consumes: `scouting_db.sync_pipeline.run_sync(...)` (Task 1), `scouting_db.multipart.parse_multipart(body, content_type)` (Task 2).
- Produces: `GET /sync` → sync form HTML page. `POST /api/sync` → streams `text/event-stream`-framed (`data: {...}\n\n`) JSON progress events by calling `run_sync`, forwarding each `(kind, data)` as `{"type": kind, **data}`.

Browsers' native `EventSource` only supports GET, so the sync form's JS uses `fetch()` with a streamed `ReadableStream` response body reader to consume the SSE-framed output from a POST request.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_webserver.py` (add these imports at the top alongside the existing ones, and these classes at the end of the file):

```python
import json
from unittest.mock import MagicMock, patch

from scouting_db.api import ScoutingAPIError


def _mock_response(data) -> MagicMock:
    """Create a MagicMock that acts as a urllib context-manager response."""
    mock = MagicMock()
    mock.read.return_value = json.dumps(data).encode("utf-8")
    mock.__enter__.return_value = mock
    mock.__exit__.return_value = False
    return mock
```

```python
def _post_multipart(port, fields):
    """fields: list of (name, value) where value is str or {"filename": str, "content": bytes}."""
    boundary = "----testboundary1234"
    lines = []
    for name, value in fields:
        lines.append(f"--{boundary}".encode())
        if isinstance(value, dict):
            lines.append(
                f'Content-Disposition: form-data; name="{name}"; '
                f'filename="{value["filename"]}"'.encode()
            )
            lines.append(b"")
            lines.append(value["content"])
        else:
            lines.append(f'Content-Disposition: form-data; name="{name}"'.encode())
            lines.append(b"")
            lines.append(value.encode())
    lines.append(f"--{boundary}--".encode())
    body = b"\r\n".join(lines) + b"\r\n"

    conn = http.client.HTTPConnection("127.0.0.1", port)
    conn.request(
        "POST", "/api/sync", body=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
    )
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp, data


def _parse_sse_events(raw: bytes):
    text = raw.decode("utf-8")
    return [
        json.loads(chunk[len("data: "):])
        for chunk in text.split("\n\n")
        if chunk.startswith("data: ")
    ]


class TestSyncFormRoute:
    def test_sync_form_route_returns_html_form(self, running_server):
        port, _ = running_server
        conn = http.client.HTTPConnection("127.0.0.1", port)
        conn.request("GET", "/sync")
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        assert resp.status == 200
        assert b"<form" in body
        assert b'name="username"' in body
        assert b'name="csv_file"' in body


class TestSyncEndpoint:
    def test_auth_failure_streams_error_event(self, running_server):
        port, _ = running_server
        with patch(
            "scouting_db.sync_pipeline.authenticate",
            side_effect=ScoutingAPIError(401, "bad creds"),
        ):
            resp, body = _post_multipart(port, [
                ("username", "u"), ("password", "p"), ("troop_name", "T"),
            ])
        assert resp.status == 200
        assert resp.getheader("Content-Type") == "text/event-stream"
        events = _parse_sse_events(body)
        assert any(e["type"] == "error" for e in events)

    def test_successful_sync_with_no_scouts_streams_complete_event(self, running_server):
        port, _ = running_server
        responses = [
            _mock_response({"token": "tok", "account": {"userId": "U1"}}),  # authenticate
            _mock_response([]),  # get_ranks
        ]
        with patch("scouting_db.api.urllib.request.urlopen", side_effect=responses):
            resp, body = _post_multipart(port, [
                ("username", "u"), ("password", "p"), ("troop_name", "Test Troop"),
            ])
        events = _parse_sse_events(body)
        assert events[-1]["type"] == "complete"

    def test_csv_upload_is_imported_before_sync(self, running_server):
        port, _ = running_server
        responses = [
            _mock_response({"token": "tok", "account": {"userId": "U1"}}),  # authenticate
            _mock_response([]),  # get_ranks
            _mock_response({"program": []}),  # get_youth_ranks for U1
            _mock_response([]),  # get_youth_merit_badges for U1
            _mock_response({}),  # get_leadership_history for U1
            _mock_response({}),  # get_person_profile for U1
        ]
        csv_content = b"User ID,First Name,Last Name,Type\nU1,Jane,Doe,YOUTH\n"
        with patch("scouting_db.api.urllib.request.urlopen", side_effect=responses):
            resp, body = _post_multipart(port, [
                ("username", "u"), ("password", "p"), ("troop_name", "Test Troop"),
                ("skip_reqs", "on"),
                ("csv_file", {"filename": "roster.csv", "content": csv_content}),
            ])
        events = _parse_sse_events(body)
        messages = " ".join(e.get("message", "") for e in events)
        assert "1 Scouts imported" in messages
        assert events[-1]["type"] == "complete"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --with pytest pytest tests/test_webserver.py -v`
Expected: FAIL — `/sync` and `/api/sync` return 404 (routes don't exist yet)

- [ ] **Step 3: Add the sync form and SSE endpoint to `src/scouting_db/webserver.py`**

Add these imports at the top of `src/scouting_db/webserver.py` (alongside the existing ones):

```python
import json
import os
import tempfile

from scouting_db.multipart import parse_multipart
from scouting_db.sync_pipeline import run_sync
```

Add this module-level constant (place it after `DASHBOARD_PATH`):

```python
SYNC_FORM_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Sync — Scouting Stats</title>
<style>
  :root {
    --gold: #FDB927; --gold-dark: #92400e;
    --olive: #4a5e28; --olive-dark: #344219; --bg: #e8ead8;
  }
  body { font-family: system-ui, -apple-system, 'Segoe UI', sans-serif;
         background: var(--bg); margin: 0; padding: 0; }
  header { background: var(--olive); color: white; padding: 16px 24px;
           font-size: 20px; font-weight: bold; }
  main { max-width: 480px; margin: 32px auto; padding: 0 16px; }
  label { display: block; margin: 16px 0 4px; font-weight: 600; color: var(--olive-dark); }
  input[type=text], input[type=password] {
    width: 100%; box-sizing: border-box; padding: 8px; border: 1px solid #ccc;
    border-radius: 4px; font-size: 14px;
  }
  .checkbox-row { display: flex; align-items: center; gap: 8px; margin-top: 16px; }
  .checkbox-row label { margin: 0; }
  button { margin-top: 24px; background: var(--gold); color: var(--olive-dark);
           border: none; border-radius: 4px; padding: 10px 20px; font-size: 15px;
           font-weight: 600; cursor: pointer; }
  button:disabled { opacity: 0.6; cursor: default; }
  #log { white-space: pre-wrap; background: #fff; border: 1px solid #ccc;
         border-radius: 4px; padding: 12px; margin-top: 20px; min-height: 60px;
         font-family: ui-monospace, monospace; font-size: 13px; }
  #log a { color: var(--olive); font-weight: 600; }
</style>
</head>
<body>
<header>Scouting Stats — Sync</header>
<main>
  <form id="sync-form">
    <label for="username">my.scouting.org username</label>
    <input type="text" id="username" name="username" required>

    <label for="password">Password</label>
    <input type="password" id="password" name="password" required>

    <label for="troop_name">Troop name</label>
    <input type="text" id="troop_name" name="troop_name" value="My Troop">

    <label for="csv_file">Roster CSV (optional)</label>
    <input type="file" id="csv_file" name="csv_file" accept=".csv">

    <div class="checkbox-row">
      <input type="checkbox" id="skip_reqs" name="skip_reqs">
      <label for="skip_reqs">Skip per-requirement detail (faster)</label>
    </div>

    <button type="submit" id="submit-btn">Sign In &amp; Sync</button>
  </form>
  <div id="log"></div>
</main>
<script>
document.getElementById('sync-form').addEventListener('submit', async function (e) {
  e.preventDefault();
  const log = document.getElementById('log');
  const btn = document.getElementById('submit-btn');
  log.textContent = '';
  btn.disabled = true;
  const formData = new FormData(e.target);
  try {
    const resp = await fetch('/api/sync', { method: 'POST', body: formData });
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    let done = false;
    while (!done) {
      const result = await reader.read();
      done = result.done;
      if (result.value) buf += decoder.decode(result.value, { stream: true });
      let idx;
      while ((idx = buf.indexOf('\\n\\n')) !== -1) {
        const chunk = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        if (!chunk.startsWith('data: ')) continue;
        const event = JSON.parse(chunk.slice(6));
        if (event.type === 'complete') {
          log.textContent += '\\n\\u2713 Done!\\n';
          const link = document.createElement('a');
          link.href = '/';
          link.textContent = 'Open dashboard \\u2192';
          log.appendChild(link);
        } else {
          log.textContent += (event.type === 'error' ? '\\u26a0 ' : '') + (event.message || '') + '\\n';
        }
      }
    }
  } catch (err) {
    log.textContent += '\\n\\u26a0 ' + err.message;
  } finally {
    btn.disabled = false;
  }
});
</script>
</body>
</html>
"""
```

Replace the `do_GET` method with one that adds the `/sync` route, and add `do_POST`:

```python
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self._serve_file(DASHBOARD_PATH, "text/html")
        elif path == "/scouting_troop.db":
            self._serve_file(Path(self.server.db_path), "application/octet-stream")
        elif path == "/sync":
            self._serve_html(SYNC_FORM_HTML)
        else:
            self.send_error(404)

    def do_POST(self):
        if urlparse(self.path).path == "/api/sync":
            self._handle_sync()
        else:
            self.send_error(404)

    def _serve_html(self, html: str):
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle_sync(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        content_type = self.headers.get("Content-Type", "")
        try:
            fields = parse_multipart(body, content_type)
        except ValueError as exc:
            self.send_error(400, str(exc))
            return

        username = fields.get("username", "")
        password = fields.get("password", "")
        troop_name = fields.get("troop_name") or "My Troop"
        skip_reqs = fields.get("skip_reqs") == "on"

        csv_path = None
        tmp_csv_name = None
        csv_field = fields.get("csv_file")
        if isinstance(csv_field, dict) and csv_field.get("filename"):
            tmp_csv = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
            tmp_csv.write(csv_field["content"])
            tmp_csv.close()
            csv_path = tmp_csv.name
            tmp_csv_name = tmp_csv.name

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        def on_progress(kind, data):
            payload = json.dumps({"type": kind, **data})
            self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
            self.wfile.flush()

        config_path = os.path.join(os.getcwd(), "config.json")
        try:
            run_sync(
                username, password, troop_name,
                self.server.db_path, config_path,
                csv_path=csv_path, skip_reqs=skip_reqs,
                on_progress=on_progress,
            )
        finally:
            if tmp_csv_name:
                os.unlink(tmp_csv_name)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --with pytest pytest tests/test_webserver.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Run the full test suite to confirm no regressions**

Run: `uv run --with pytest pytest tests/ -v`
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
git add src/scouting_db/webserver.py tests/test_webserver.py
git commit -m "Add sync form and SSE-streamed /api/sync endpoint to the web server"
```

---

### Task 5: `scouting serve` CLI subcommand

**Files:**
- Modify: `src/scouting_db/cli.py:24-38` (imports), `src/scouting_db/cli.py:614-685` (`main()`)

**Interfaces:**
- Consumes: `scouting_db.webserver.serve(db_path, port=8765, open_browser=True)` (Task 3/4), `scouting_db.db.DEFAULT_DB_PATH`.
- Produces: `uv run scouting serve [--port PORT] [--no-browser]` CLI command.

This project has no existing CLI unit tests (only `test_api.py`, `test_db.py`, `test_queries.py`, plus the new `test_sync_pipeline.py`/`test_multipart.py`/`test_webserver.py`), so this task is verified manually rather than with a new test file, consistent with how the other `cmd_*` functions in `cli.py` are (un)tested today.

- [ ] **Step 1: Add the `DEFAULT_DB_PATH` import**

In `src/scouting_db/cli.py`, modify the `from scouting_db.db import (...)` block (lines 24-38) to add `DEFAULT_DB_PATH`:

```python
from scouting_db.db import (
    DEFAULT_DB_PATH,
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
```

- [ ] **Step 2: Add `cmd_serve`**

Add this function in `src/scouting_db/cli.py`, directly above `def main():` (currently line 614):

```python
def cmd_serve(args):
    from scouting_db.webserver import serve

    db_path = args.db or str(DEFAULT_DB_PATH)
    serve(db_path, port=args.port, open_browser=not args.no_browser)
```

- [ ] **Step 3: Register the `serve` subparser and command**

In `main()`, add a new subparser. Insert this directly after the `p_query` argument block (after line 663, before `args = parser.parse_args()` at line 665):

```python
    p_serve = sub.add_parser(
        "serve", help="Start the local web server (sync form + dashboard)"
    )
    p_serve.add_argument(
        "--port", type=int, default=8765, help="Port to listen on (default: 8765)"
    )
    p_serve.add_argument(
        "--no-browser", action="store_true",
        help="Don't automatically open a browser window",
    )
```

Then add `"serve": cmd_serve` to the `commands` dict (currently lines 670-679):

```python
    commands = {
        "init": cmd_init,
        "get-token": cmd_get_token,
        "sync-ranks": cmd_sync_ranks,
        "import-roster": cmd_import_roster,
        "add-scout": cmd_add_scout,
        "sync-scouts": cmd_sync_scouts,
        "discover": cmd_discover,
        "query": cmd_query,
        "serve": cmd_serve,
    }
```

- [ ] **Step 4: Run the full test suite to confirm no regressions**

Run: `uv run --with pytest pytest tests/ -v`
Expected: PASS (all tests)

- [ ] **Step 5: Manually verify the CLI wiring**

Run: `uv run scouting --help`
Expected: output includes a `serve` entry in the subcommand list

Run: `uv run scouting serve --help`
Expected: usage text showing `--port` and `--no-browser`

- [ ] **Step 6: Commit**

```bash
git add src/scouting_db/cli.py
git commit -m "Add 'scouting serve' CLI subcommand to start the local web server"
```

---

### Task 6: Remove the native macOS app and dead Electron code

**Files:**
- Delete: `macos-app/` (entire directory)
- Modify: `dashboard.html:967-974`, `dashboard.html:1121-1141`
- Modify: `.gitignore`

**Interfaces:** None — cleanup only, no behavior change to any function signature used elsewhere.

- [ ] **Step 1: Delete the macOS app directory**

```bash
git rm -r macos-app
```

- [ ] **Step 2: Simplify the sql.js script loading in `dashboard.html`**

In `dashboard.html`, replace lines 967-974:

```html
<!-- ══════════ SCRIPTS ══════════ -->
<script>
// Load sql.js from CDN for standalone web use.
// In Electron, sql.js is vendored locally and loaded via IPC in initSQL().
if (!window.electronAPI) {
  document.write('<script src="https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.10.2/sql-wasm.js"></' + 'script>');
}
</script>
```

with:

```html
<!-- ══════════ SCRIPTS ══════════ -->
<script src="https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.10.2/sql-wasm.js"></script>
```

- [ ] **Step 3: Remove the dead Electron branch from `initSQL()`**

In `dashboard.html`, replace lines 1121-1141:

```javascript
// ─── DB loading ──────────────────────────────────────────────────────────────
async function initSQL() {
  if (SQL) return;
  if (window.electronAPI) {
    // Electron: load vendored sql.js entirely via IPC (no fetch/CDN needed).
    const { vendorPath } = await window.electronAPI.getPaths();
    if (typeof initSqlJs === 'undefined') {
      const jsBuf = await window.electronAPI.readFile(vendorPath + '/sql-wasm.js');
      const s = document.createElement('script');
      s.textContent = new TextDecoder().decode(jsBuf);
      document.head.appendChild(s);
    }
    const wasmBuf = await window.electronAPI.readFile(vendorPath + '/sql-wasm.wasm');
    SQL = await initSqlJs({ wasmBinary: new Uint8Array(wasmBuf) });
  } else {
    // Standalone web: fetch WASM from CDN
    SQL = await initSqlJs({
      locateFile: f => 'https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.10.2/' + f
    });
  }
}
```

with:

```javascript
// ─── DB loading ──────────────────────────────────────────────────────────────
async function initSQL() {
  if (SQL) return;
  SQL = await initSqlJs({
    locateFile: f => 'https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.10.2/' + f
  });
}
```

- [ ] **Step 4: Clean up `.gitignore`**

Remove the now-dead macOS app entries from the end of `.gitignore`:

```
# macOS native app
macos-app/build/
macos-app/ScoutingTroopStats.xcodeproj/
```

(Leave the rest of `.gitignore` — `config.json`, `*.db`, `*.db-shm`, `*.db-wal`, `__pycache__/`, `*.pyc`, `.venv/`, `*.csv` — unchanged.)

- [ ] **Step 5: Manually verify the dashboard still loads**

Run: `uv run scouting serve --no-browser &` then in another terminal `curl -s http://127.0.0.1:8765/ | head -5`
Expected: HTML output starting with `<!DOCTYPE html>`, no references to `window.electronAPI` remain (`grep -c electronAPI dashboard.html` should print `0`)

Stop the background server: `kill %1` (or find and kill the `scouting serve` process).

- [ ] **Step 6: Run the full test suite to confirm no regressions**

Run: `uv run --with pytest pytest tests/ -v`
Expected: PASS (all tests)

- [ ] **Step 7: Commit**

```bash
git add -A dashboard.html .gitignore
git commit -m "Remove native macOS app and dead Electron code path from dashboard.html"
```

---

### Task 7: Update documentation

**Files:**
- Modify: `README.md`
- Modify: `DEVELOPMENT.md`

**Interfaces:** None — documentation only.

- [ ] **Step 1: Replace the macOS App section in `README.md`**

In `README.md`, replace:

```markdown
### macOS App (recommended)

The native macOS app handles everything -- sign in, sync your troop's data, and explore the dashboard -- all in one window with no prerequisites to install. It's a lightweight SwiftUI wrapper around the same dashboard, with built-in sync. No Electron, no Python runtime, just a ~10 MB `.app` that runs on macOS 13+.

```bash
# Build and create a DMG (requires Xcode 15+ and xcodegen)
brew install xcodegen
cd macos-app
make dmg
```

The DMG is created at `macos-app/build/Scouting Stats.dmg`. See [`macos-app/README.md`](macos-app/README.md) for full build options including signed distribution.
```

with:

```markdown
### Web App (recommended)

Run a local web server that handles everything -- sign in, sync your troop's data, and explore the dashboard -- all in one browser tab. Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
git clone <this-repo>
cd scouting-troop-stats
uv sync
uv run scouting serve
```

This opens your browser to `http://127.0.0.1:8765/`. Visit `/sync` to sign in and sync your troop's data (with an optional roster CSV upload); the dashboard at `/` reads directly from the resulting `scouting_troop.db`.
```

- [ ] **Step 2: Update the "For Developers" pointer if needed**

Leave the rest of `README.md` unchanged — the "Browser Dashboard", "Try It Out", "Dashboard Features", "How It Works", "Background", and "For Developers" sections all remain accurate as-is.

- [ ] **Step 3: Remove the macOS App Development section from `DEVELOPMENT.md`**

In `DEVELOPMENT.md`, remove this section entirely (it is the last section in the file):

```markdown
## macOS App Development

See the [macOS app README](macos-app/README.md) for building and developing the native Swift app.
```

- [ ] **Step 4: Add the `serve` command to the CLI Reference in `DEVELOPMENT.md`**

In `DEVELOPMENT.md`, after the `### Queries` section and before `### Debugging`, add:

```markdown
### Web Server

```bash
uv run scouting serve                # starts on http://127.0.0.1:8765/, opens a browser
uv run scouting serve --port 9000    # use a different port
uv run scouting serve --no-browser   # don't auto-open a browser
```

Serves the dashboard at `/` (reading the `.db` at `--db`, or the default `scouting_troop.db` in the current directory) and a sign-in/sync form at `/sync` that streams live progress while it authenticates, imports an optional roster CSV, and syncs advancement data -- the same pipeline as `sync-scouts`, in the browser.
```

- [ ] **Step 5: Update the Project Structure listing in `DEVELOPMENT.md`**

In `DEVELOPMENT.md`'s `## Project Structure` section, replace:

```
  macos-app/                  # Native macOS app (SwiftUI + WKWebView)
    project.yml               # XcodeGen spec — `xcodegen generate` creates the Xcode project
    Makefile                  # `make dmg` builds a distributable DMG
  src/scouting_db/
    cli.py                    # CLI entry point (argparse subcommands)
    api.py                    # HTTP client for api.scouting.org
    db.py                     # SQLite schema, init, upsert functions
    queries.py                # Troop-wide analytical SQL queries
    mcp_server.py              # MCP server exposing the database to AI assistants
```

with:

```
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

- [ ] **Step 6: Commit**

```bash
git add README.md DEVELOPMENT.md
git commit -m "Update docs: replace macOS app instructions with 'scouting serve'"
```

---

### Task 8: End-to-end manual verification

**Files:** None (verification only).

**Interfaces:** None.

- [ ] **Step 1: Run the full automated test suite**

Run: `uv run --with pytest pytest tests/ -v`
Expected: PASS (all tests — the pre-existing suite plus the new sync_pipeline/multipart/webserver tests)

- [ ] **Step 2: Start the server against the sample database**

```bash
cp sample_troop.db /tmp/scouting_verify.db
uv run scouting serve --db /tmp/scouting_verify.db --no-browser
```

Expected: prints `Serving at http://127.0.0.1:8765/ (Ctrl+C to stop)`

- [ ] **Step 3: Verify the dashboard loads with data, in a browser**

Open `http://127.0.0.1:8765/` in a browser.
Expected: the dashboard auto-loads (no manual file picker needed) and shows "Sample Troop 999" data (50 Scouts) exactly as it does when `sample_troop.db` is opened via the file picker today.

- [ ] **Step 4: Verify the sync form renders**

Open `http://127.0.0.1:8765/sync` in a browser.
Expected: a form with username, password, troop name, CSV upload, and a "Sign In & Sync" button, styled consistent with the dashboard's olive/gold color scheme.

- [ ] **Step 5: Stop the server**

Press `Ctrl+C` in the terminal running `scouting serve`.
Expected: prints `Stopping server.` and exits cleanly.

- [ ] **Step 6: Confirm the standalone dashboard still works unchanged**

Open `dashboard.html` directly via `file://` in a browser (double-click it, or `open dashboard.html` on macOS) and use the "Open Database" button to load `sample_troop.db`.
Expected: works exactly as before this plan (this exercises the manual file-picker path, which Task 6 did not touch).
