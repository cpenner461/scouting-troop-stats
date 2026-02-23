# Troop Scout Stats — Native Desktop App

Electron-based desktop wrapper that ships the existing `dashboard.html` as a
native macOS or Windows application — no terminal, no Python, no browser.

---

## User Workflow

1. **Open the app** — double-click the app icon.
2. **First time:** click **"Sign In & Sync"**, enter your `my.scouting.org`
   credentials, and optionally import a roster CSV from Scoutbook.
3. The app downloads your troop's advancement data into a local SQLite
   database stored in your OS user-data folder.
4. Click **"View Dashboard →"** to explore the data in the full dashboard.
5. To refresh: click the **"⇄ Sync"** button in the top-right of the dashboard
   to return to the sync panel at any time.

> Your password is used only to authenticate and is **never stored on disk**.
> The JWT token (valid for one session) is saved so you can re-sync without
> re-entering credentials.

---

## Running in Development

Requires **Node.js ≥ 18**, **npm**, and **[uv](https://docs.astral.sh/uv/)**.

```bash
cd native-app
npm install
npm run dev        # NODE_ENV=development electron .
```

In dev mode the Python sync falls back to running
`uv run python -m scouting_db.native_sync` from the repo root, so `uv` must be
on your `PATH` and the project's virtual environment must be set up
(`uv sync` in the repo root).

---

## Building a Distributable Installer

### Step 1 — Build the Python sync binary

The Python source is compiled into a self-contained executable with
**PyInstaller**. This step only needs to be re-run when the Python source
changes.

**macOS / Linux:**
```bash
bash native-app/build-scripts/build-python-mac.sh
```

**Windows (CMD or PowerShell):**
```cmd
native-app\build-scripts\build-python-win.bat
```

Output: `native-app/python-bin/sync` (macOS) or `native-app/python-bin/sync.exe` (Windows).

### Step 2 — Build the Electron installer

```bash
cd native-app

# macOS → dist/Troop Scout Stats-*.dmg
npm run build:mac

# Windows → dist/Troop Scout Stats Setup *.exe
npm run build:win

# Both platforms (requires macOS for cross-compile or CI)
npm run build:all
```

The installer bundles:
- The Electron runtime (Chromium + Node.js, ~150 MB)
- The bundled Python sync binary (no Python install needed by end-users)
- `dashboard.html` (the existing web dashboard, unchanged)

---

## Architecture

```
native-app/
├── main.js               Electron main process
│                         • Creates BrowserWindow
│                         • Handles IPC: paths, file I/O, navigation, sync spawn
├── preload.js            contextBridge — exposes window.electronAPI to renderer
│                         • Keeps renderer sandboxed (no direct Node.js access)
├── app/
│   ├── launcher.html     Welcome / setup screen (initial view)
│   ├── launcher.css      Launcher styles (Scout blue/gold theme)
│   └── launcher.js       Launcher logic (auth form, CSV picker, progress log)
├── python-bridge/
│   └── sync_runner.py    PyInstaller entry point
├── build-scripts/
│   ├── build-python-mac.sh
│   └── build-python-win.bat
├── sync-runner.spec      PyInstaller configuration
└── package.json          Electron + electron-builder config
```

**Navigation flow:**
```
App opens
  └─► launcher.html  (welcome/setup screen)
        ├─ "Open Database File" ──────────────────────► dashboard.html
        └─ "Sign In & Sync"
              └─ credentials entered
                    └─ Python sync runs (streams JSON progress)
                          └─ "View Dashboard →" ──────► dashboard.html
                                  │
                            "⇄ Sync" button ──────────► launcher.html
```

**Python sync pipeline** (`src/scouting_db/native_sync.py`):
1. Authenticate with `my.scouting.org` → JWT token
2. Save token to `config.json` in userData
3. `init_db` — create/migrate SQLite schema
4. `sync_ranks` — download public rank definitions
5. `import_roster_csv` — upsert Scouts from CSV (if provided)
6. `sync_scouts` — download per-Scout advancement, merit badges, leadership, birthdate
7. Emit `{"type": "complete", "db_path": "…"}` to stdout

Progress is emitted as JSON-newline messages so the Electron renderer can
display a live log without polling.

---

## Changes to `dashboard.html`

Only two minimal additions were made so the dashboard works unchanged in both
the native app and a plain browser:

1. **Header button** — `<button id="electron-sync-btn">` (hidden by default,
   revealed only when `window.electronAPI` is present).

2. **Integration script** at the bottom of the file — detects
   `window.electronAPI` and, if present:
   - Auto-loads the database from the OS user-data path.
   - Wires the "⇄ Sync" button to navigate back to the launcher.

---

## Known Limitations (POC)

- **`sql.js` loaded from CDN** — the dashboard fetches the SQLite WASM binary
  from `cdnjs.cloudflare.com` at startup. A production build should vendor this
  file locally to support offline use.
- **No auto-update** — a production app would use `electron-updater`.
- **Code signing** — macOS and Windows installers require code signing
  certificates for Gatekeeper / SmartScreen approval. The POC builds unsigned.
- **Single-arch builds** — the PyInstaller binary must be compiled on the
  target platform (or in CI). Universal macOS binaries require separate
  x64 + arm64 builds merged with `lipo`.
