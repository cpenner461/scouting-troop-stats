# Troop Scout Stats — Native Desktop App

Electron-based desktop application that ships the existing `dashboard.html` as a
native macOS, Windows, or Linux application — no terminal, no Python, no browser.

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

### Prerequisites

- **Node.js ≥ 18** and **npm**
- **[uv](https://docs.astral.sh/uv/)** (for building the Python sync binary)
- **Python 3** with **Pillow** (only needed to regenerate icons: `pip install Pillow`)

### Step 0 — Install npm dependencies

```bash
cd native-app
npm install
```

### Step 1 — Build the Python sync binary

The Python source is compiled into a self-contained executable with
**PyInstaller**. This step only needs to be re-run when the Python source
changes.

**macOS:**
```bash
bash native-app/build-scripts/build-python-mac.sh
```

**Linux:**
```bash
bash native-app/build-scripts/build-python-linux.sh
```

**Windows (CMD or PowerShell):**
```cmd
native-app\build-scripts\build-python-win.bat
```

Output: `native-app/python-bin/sync` (macOS/Linux) or `native-app/python-bin/sync.exe` (Windows).

### Step 2 — Build the Electron installer

```bash
cd native-app

# macOS → dist/Troop Scout Stats-<version>-mac-{x64,arm64}.dmg + .zip
npm run build:mac

# Windows → dist/Troop Scout Stats-<version>-win-x64.exe (installer + portable)
npm run build:win

# Linux → dist/Troop Scout Stats-<version>-linux-x64.AppImage + .deb
npm run build:linux

# All platforms (requires macOS host for mac builds, or CI)
npm run build:all
```

The installer bundles:
- The Electron runtime (Chromium + Node.js)
- The bundled Python sync binary (no Python install needed by end-users)
- `dashboard.html` (the existing web dashboard, unchanged)

### Regenerating the App Icon

The app icon is an olive-green rounded square with a white fleur-de-lis.
To regenerate icons after modifying the design:

```bash
cd native-app
npm run generate-icons    # requires Python 3 + Pillow
```

This produces `build-resources/icon.{png,ico,icns}` and
`build-resources/icons/{16..1024}x{16..1024}.png` for all platforms.

---

## Architecture

```
native-app/
├── main.js               Electron main process
│                         • Creates BrowserWindow
│                         • Single-instance lock
│                         • Content Security Policy
│                         • Handles IPC: paths, file I/O, navigation, sync spawn
├── preload.js            contextBridge — exposes window.electronAPI to renderer
│                         • Keeps renderer sandboxed (no direct Node.js access)
├── app/
│   ├── launcher.html     Welcome / setup screen (initial view)
│   ├── launcher.css      Launcher styles (Scout blue/gold theme)
│   └── launcher.js       Launcher logic (auth form, CSV picker, progress log)
├── build-resources/      Generated app icons (all platforms)
│   ├── icon.png          1024x1024 master icon
│   ├── icon.icns         macOS icon bundle
│   ├── icon.ico          Windows icon bundle
│   └── icons/            Linux PNG sizes (16-1024px)
├── scripts/
│   └── generate-icons.py Icon generator (Python + Pillow)
├── python-bridge/
│   └── sync_runner.py    PyInstaller entry point
├── build-scripts/
│   ├── build-python-mac.sh
│   ├── build-python-linux.sh
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

## Known Limitations

- **`sql.js` loaded from CDN** — the dashboard fetches the SQLite WASM binary
  from `cdnjs.cloudflare.com` at startup. A production build should vendor this
  file locally to support offline use.
- **No auto-update** — a production app would use `electron-updater`.
- **Code signing** — macOS and Windows installers require code signing
  certificates for Gatekeeper / SmartScreen approval. Unsigned builds will
  trigger security warnings on end-user machines.
- **Single-arch builds** — the PyInstaller binary must be compiled on the
  target platform (or in CI). Universal macOS binaries require separate
  x64 + arm64 builds merged with `lipo`.
