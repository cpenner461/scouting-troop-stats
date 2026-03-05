# Scouting Stats — Native macOS App

A native macOS application built with **SwiftUI + WKWebView**.
No Electron, no bundled runtime — just Swift and WebKit.

| | Electron (previous) | Native Swift |
|---|---|---|
| Binary size | ~200–300 MB | ~5–15 MB |
| Runtime dep | Node.js + Python | None (macOS built-ins only) |
| Language | JS + Python | Swift 5.9 |
| Min macOS | 10.13 | 13.0 (Ventura) |

---

## Architecture

```
┌─────────────────────────────────────┐
│  ScoutingTroopStatsApp (SwiftUI)    │
│                                     │
│  LauncherView   ──► SyncProgressView│
│       │                             │
│       └──────────► DashboardView    │
│                     (WKWebView)     │
└─────────────────────────────────────┘
         │ serves via
         ▼
┌──────────────────────────────────────┐
│  ScoutingURLSchemeHandler            │
│  scouting://localhost/dashboard.html │
│  scouting://localhost/vendor/…       │
│  scouting://localhost/scouting_troop.db │
└──────────────────────────────────────┘
         │ populated by
         ▼
┌──────────────────────────────────────┐
│  SyncService                         │
│    ScoutingAPIService  (URLSession)  │
│    DatabaseService     (sqlite3)     │
└──────────────────────────────────────┘
```

### Key design decisions

* **No local HTTP server** — a `WKURLSchemeHandler` for the `scouting://` scheme serves
  `dashboard.html`, the sql.js WASM assets, and the database directly from the app bundle
  and the user's file system.  No port, no socket.

* **Offline-capable** — sql.js (`sql-wasm.js` + `sql-wasm.wasm`) is bundled inside the app.
  A small JavaScript bridge injected at document start defines `window.electronAPI` so the
  dashboard's existing Electron code path is taken, loading WASM from the bundle rather than
  CDN.

* **Python-free** — all sync logic (authentication, HTTP calls, SQLite schema, data import)
  is re-implemented in Swift using `URLSession` and the `sqlite3` C library that ships with
  macOS.  The resulting binary has zero non-system dependencies.

* **Self-contained resources** — `dashboard.html` is referenced from the repository root,
  and the sql.js WASM files live in `ScoutingTroopStats/Resources/vendor/` within the macOS
  app directory.  XcodeGen bundles all three automatically — no manual build-phase setup.

---

## Requirements

| Tool | Version |
|------|---------|
| Xcode | 15.0+ |
| macOS SDK | 13.0+ |
| macOS (run) | 13.0 Ventura+ |
| [XcodeGen](https://github.com/yonaskolb/XcodeGen) | 2.40+ |
| [uv](https://docs.astral.sh/uv/) | 0.4+ |

Install dependencies once:

```bash
brew install xcodegen
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Python packages (Pillow, dmgbuild) are managed automatically by `uv` at build time — no manual `pip install` needed.

---

## Building

### Quick build (Xcode)

```bash
cd macos-app
xcodegen generate
open ScoutingTroopStats.xcodeproj
```

Then **Product → Run** (⌘R).

### Build a DMG for distribution

The included Makefile automates project generation, building, and DMG creation:

```bash
cd macos-app
make dmg
```

This will:
1. Run `xcodegen generate` to create the Xcode project
2. Build a Release configuration
3. Package the `.app` into a styled DMG at `build/Scouting Stats.dmg` with a background image, positioned icons, and an Applications shortcut for drag-to-install

### Other Makefile targets

| Target | Description |
|--------|-------------|
| `make generate` | Generate the Xcode project from `project.yml` |
| `make build` | Build in Release mode |
| `make app` | Build and copy the `.app` to `build/export/` |
| `make dmg` | Build and create a styled drag-to-install DMG |
| `make dmg-background` | Regenerate the DMG background image |
| `make archive` | Create an Xcode archive (for notarization/signing) |
| `make export` | Archive + export with Developer ID signing |
| `make clean` | Remove all build artifacts and the generated Xcode project |

### Signed distribution

For notarized distribution outside the App Store:

```bash
# Archive and export with Developer ID
make export

# Notarize the DMG (requires Apple Developer account)
xcrun notarytool submit "build/Scouting Stats.dmg" \
    --apple-id "you@example.com" \
    --team-id "XXXXXXXXXX" \
    --password "@keychain:AC_PASSWORD" \
    --wait

# Staple the notarization ticket
xcrun stapler staple "build/Scouting Stats.dmg"
```

---

## Project structure

```
macos-app/
├── project.yml                         XcodeGen spec
├── Makefile                            Build automation (DMG, archive, etc.)
├── ExportOptions.plist                 Archive export config
├── scripts/
│   ├── generate-dmg-background.py      Generates the DMG installer background image
│   └── dmgbuild-settings.py            Configuration for dmgbuild (icon layout, background)
├── dmg-resources/
│   ├── background.png                  DMG background (660×400 @1x)
│   └── background@2x.png              DMG background (1320×800 @2x retina)
├── ScoutingTroopStats/
│   ├── ScoutingTroopStatsApp.swift     @main entry point
│   ├── AppState.swift                  Shared ObservableObject state
│   ├── Info.plist
│   ├── ScoutingTroopStats.entitlements
│   ├── Assets.xcassets/                App icon (fleur-de-lis)
│   ├── Resources/
│   │   └── vendor/
│   │       ├── sql-wasm.js             sql.js loader
│   │       └── sql-wasm.wasm           SQLite WASM binary
│   ├── Views/
│   │   ├── ContentView.swift           Root view — switches between screens
│   │   ├── LauncherView.swift          Welcome screen (open DB / sign in & sync)
│   │   ├── SyncProgressView.swift      Live sync log display
│   │   └── DashboardView.swift         WKWebView wrapper for dashboard.html
│   └── Services/
│       ├── ScoutingURLSchemeHandler.swift  Serves assets via scouting:// scheme
│       ├── ScoutingAPIService.swift        HTTP client (mirrors api.py)
│       ├── DatabaseService.swift           SQLite operations (mirrors db.py)
│       └── SyncService.swift               Sync orchestration (mirrors native_sync.py)
└── README.md
```

Bundle resources:
```
../dashboard.html                              → scouting://localhost/dashboard.html
ScoutingTroopStats/Resources/vendor/sql-wasm.js   → scouting://localhost/vendor/sql-wasm.js
ScoutingTroopStats/Resources/vendor/sql-wasm.wasm → scouting://localhost/vendor/sql-wasm.wasm
```

---

## Usage

### Opening an existing database

1. Launch the app → click **Open Database**
2. Pick your `scouting_troop.db` file
3. The dashboard loads instantly — no internet required

### Syncing fresh data

1. Launch the app → click **Sign In & Sync**
2. Enter your `my.scouting.org` credentials and troop name
3. Optionally select a Scoutbook roster CSV
4. Click **Start Sync** — watch live progress
5. On completion, the dashboard opens automatically

Data is stored at:
```
~/Library/Application Support/ScoutingTroopStats/scouting_troop.db
```

---

## Sandboxing & permissions

The app runs in the macOS sandbox with these entitlements:

| Entitlement | Reason |
|---|---|
| `network.client` | HTTPS calls to api.scouting.org and my.scouting.org |
| `files.user-selected.read-write` | Opening `.db` and `.csv` files via file picker |
| `files.bookmarks.app-scope` | Remembering file locations across launches |
