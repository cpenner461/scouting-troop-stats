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

* **Shared dashboard** — `dashboard.html` and `vendor/sql-wasm.*` in the repository root are
  referenced directly by the Xcode project as bundle resources; no duplication needed.

---

## Requirements

| Tool | Version |
|------|---------|
| Xcode | 15.0+ |
| macOS SDK | 13.0+ |
| macOS (run) | 13.0 Ventura+ |
| [XcodeGen](https://github.com/yonaskolb/XcodeGen) | 2.40+ (optional, for project generation) |

---

## Building

### Option A — Generate with XcodeGen (recommended)

```bash
# Install XcodeGen once
brew install xcodegen

# From the macos-app directory:
cd macos-app
xcodegen generate

# Open the generated project
open ScoutingTroopStats.xcodeproj
```

Then in Xcode: **Product → Run** (⌘R) or **Product → Archive** for a distributable build.

### Option B — Create the Xcode project manually

1. Open Xcode → **File → New → Project → macOS → App**
2. Set:
   - Product Name: `ScoutingTroopStats`
   - Bundle ID: `com.scoutingtroop.ScoutingTroopStats`
   - Language: Swift, Interface: SwiftUI
   - Deployment target: macOS 13.0
3. Delete the auto-generated `ContentView.swift` and `ScoutingTroopStatsApp.swift`
4. Drag all `.swift` files from this directory into the project
5. Add bundle resources:
   - `../dashboard.html` → copy to bundle
   - `../vendor/sql-wasm.js` → copy to bundle
   - `../vendor/sql-wasm.wasm` → copy to bundle
6. Replace `Info.plist` with the one in this directory
7. Set the entitlements file in Build Settings → `CODE_SIGN_ENTITLEMENTS`

---

## Project structure

```
macos-app/
├── project.yml                         XcodeGen spec
├── ScoutingTroopStats/
│   ├── ScoutingTroopStatsApp.swift     @main entry point
│   ├── AppState.swift                  Shared ObservableObject state
│   ├── Info.plist
│   ├── ScoutingTroopStats.entitlements
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

Bundle resources (referenced from repo root, not duplicated):
```
../dashboard.html          → scouting://localhost/dashboard.html
../vendor/sql-wasm.js      → scouting://localhost/vendor/sql-wasm.js
../vendor/sql-wasm.wasm    → scouting://localhost/vendor/sql-wasm.wasm
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

---

## Distributing

### Developer ID (direct download)

1. In Xcode: **Product → Archive**
2. **Distribute App → Developer ID → Upload** (for notarisation)
3. After notarisation, export the `.app` and wrap in a DMG

### App Store

Remove the `temporary-exception` entitlement, add `com.apple.security.app-sandbox` hardened
runtime settings, and submit via App Store Connect.
