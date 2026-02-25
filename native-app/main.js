'use strict';

const { app, BrowserWindow, ipcMain, dialog, nativeImage, session } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');

const isDev = process.env.NODE_ENV === 'development';

// ─── Single instance lock ────────────────────────────────────────────────────
// Prevent multiple copies of the app from running simultaneously.

const gotTheLock = app.requestSingleInstanceLock();

if (!gotTheLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    // Someone tried to open a second instance — focus the existing window.
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });
}

// ─── App metadata ────────────────────────────────────────────────────────────

app.setName('Troop Scout Stats');

// ─── Paths ────────────────────────────────────────────────────────────────────

function getDbPath() {
  return path.join(app.getPath('userData'), 'scouting_troop.db');
}

function getConfigPath() {
  return path.join(app.getPath('userData'), 'config.json');
}

/**
 * Returns the command and args needed to run the Python sync script.
 *
 * Production: uses the bundled PyInstaller binary in Resources/python-bin/
 * Development: falls back to `uv run python -m scouting_db.native_sync`
 *              from the repo root (requires uv on PATH).
 */
function getPythonCmd() {
  if (!isDev) {
    const binName = process.platform === 'win32' ? 'sync.exe' : 'sync';
    const bundledPath = path.join(process.resourcesPath, 'python-bin', binName);
    if (fs.existsSync(bundledPath)) {
      return { cmd: bundledPath, args: [], cwd: path.dirname(bundledPath) };
    }
  }
  // Dev fallback: run via uv from the project root
  const projectRoot = path.join(__dirname, '..');
  return { cmd: 'uv', args: ['run', 'python', '-m', 'scouting_db.native_sync'], cwd: projectRoot };
}

/**
 * Resolve the path to the app icon (used for About panel and window icon).
 */
function getIconPath() {
  const ext = process.platform === 'win32' ? 'ico' : 'png';
  // In packaged app, icons are in the build-resources dir which is relative to
  // the app.asar. electron-builder copies them into the app directory.
  const candidates = [
    path.join(__dirname, 'build-resources', `icon.${ext}`),
    path.join(__dirname, '..', 'build-resources', `icon.${ext}`),
    path.join(process.resourcesPath || '', `icon.${ext}`),
  ];
  for (const p of candidates) {
    if (fs.existsSync(p)) return p;
  }
  return null;
}

// ─── Window management ────────────────────────────────────────────────────────

let mainWindow = null;

function createWindow() {
  const iconPath = getIconPath();

  const windowOpts = {
    width: 1280,
    height: 860,
    minWidth: 880,
    minHeight: 560,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    title: 'Troop Scout Stats',
    show: false,
    backgroundColor: '#003F87',
  };

  // Set window icon (Linux and Windows — macOS uses the .icns in the bundle)
  if (iconPath && process.platform !== 'darwin') {
    windowOpts.icon = nativeImage.createFromPath(iconPath);
  }

  mainWindow = new BrowserWindow(windowOpts);

  mainWindow.loadFile(path.join(__dirname, 'app', 'launcher.html'));
  mainWindow.once('ready-to-show', () => mainWindow.show());

  if (isDev) {
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  }

  mainWindow.on('closed', () => { mainWindow = null; });
}

// ─── Content Security Policy ─────────────────────────────────────────────────
// Set a restrictive CSP for all pages loaded in the app.

app.on('ready', () => {
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        'Content-Security-Policy': [
          "default-src 'self';" +
          " script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net;" +
          " style-src 'self' 'unsafe-inline';" +
          " img-src 'self' data: blob:;" +
          " font-src 'self' data:;" +
          " connect-src 'self';" +
          " object-src 'none';" +
          " base-uri 'self';"
        ],
      },
    });
  });
});

// ─── macOS About panel ───────────────────────────────────────────────────────

if (process.platform === 'darwin') {
  app.setAboutPanelOptions({
    applicationName: 'Troop Scout Stats',
    applicationVersion: app.getVersion(),
    version: '', // hides the build number row
    copyright: 'Copyright \u00A9 2025 Troop Scout Stats',
    iconPath: getIconPath(),
  });
}

// ─── App lifecycle ───────────────────────────────────────────────────────────

app.whenReady().then(createWindow);

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});

// ─── IPC: paths ───────────────────────────────────────────────────────────────

ipcMain.handle('get-paths', () => ({
  dbPath: getDbPath(),
  configPath: getConfigPath(),
  userDataPath: app.getPath('userData'),
}));

// ─── IPC: app info ────────────────────────────────────────────────────────────

ipcMain.handle('get-app-info', () => ({
  version: app.getVersion(),
  name: app.getName(),
  platform: process.platform,
}));

// ─── IPC: file I/O ────────────────────────────────────────────────────────────

// Read a file and return its contents as an ArrayBuffer (for sql.js)
ipcMain.handle('read-file', async (_event, filePath) => {
  try {
    const nodeBuf = fs.readFileSync(filePath);
    // Copy into a fresh ArrayBuffer (avoids Node.js Buffer pool sharing issues)
    const ab = nodeBuf.buffer.slice(
      nodeBuf.byteOffset,
      nodeBuf.byteOffset + nodeBuf.byteLength
    );
    return ab;
  } catch {
    return null;
  }
});

// Native file open dialog
ipcMain.handle('show-open-dialog', async (_event, options) => {
  const result = await dialog.showOpenDialog(mainWindow, options);
  return result.canceled ? null : result.filePaths[0];
});

// ─── IPC: navigation ─────────────────────────────────────────────────────────

ipcMain.handle('navigate', async (_event, page) => {
  if (!mainWindow) return;
  if (page === 'dashboard') {
    // In production, dashboard.html is bundled into the app directory.
    // In dev, it lives one level up at the repo root.
    const dashboardPath = isDev
      ? path.join(__dirname, '..', 'dashboard.html')
      : path.join(__dirname, 'dashboard.html');
    await mainWindow.loadFile(dashboardPath);
  } else if (page === 'launcher') {
    await mainWindow.loadFile(path.join(__dirname, 'app', 'launcher.html'));
  }
});

// ─── IPC: sync ────────────────────────────────────────────────────────────────

/**
 * Spawn the Python sync process and stream progress back to the renderer.
 *
 * The Python script emits JSON-newline messages to stdout:
 *   {"type": "step",     "message": "Authenticating\u2026"}
 *   {"type": "log",      "message": "  [1/23] John Smith"}
 *   {"type": "error",    "message": "Authentication failed"}
 *   {"type": "complete", "db_path": "/path/to/scouting_troop.db"}
 *
 * Password is passed via environment variable, never on the command line.
 */
ipcMain.handle('sync-data', async (event, { username, password, troopName, csvPath }) => {
  const dbPath = getDbPath();
  const configPath = getConfigPath();
  const { cmd, args, cwd } = getPythonCmd();

  const syncArgs = [
    ...args,
    '--username', username,
    '--troop-name', troopName || 'My Troop',
    '--db-path', dbPath,
    '--config-path', configPath,
  ];
  if (csvPath) syncArgs.push('--csv-path', csvPath);

  // Never pass password on the command line — use an env var
  const env = { ...process.env, SCOUTING_PASSWORD: password };

  return new Promise((resolve, reject) => {
    let proc;
    try {
      proc = spawn(cmd, syncArgs, { env, cwd });
    } catch (spawnErr) {
      reject(new Error(`Could not start sync process: ${spawnErr.message}`));
      return;
    }

    let buffer = '';

    function processOutput(chunk) {
      buffer += chunk;
      const lines = buffer.split('\n');
      buffer = lines.pop(); // keep incomplete line
      for (const line of lines) {
        if (!line.trim()) continue;
        let msg;
        try {
          msg = JSON.parse(line);
        } catch {
          msg = { type: 'log', message: line };
        }
        event.sender.send('sync-progress', msg);
      }
    }

    proc.stdout.on('data', (data) => processOutput(data.toString()));

    proc.stderr.on('data', (data) => {
      const text = data.toString().trim();
      if (text) {
        event.sender.send('sync-progress', { type: 'log', message: text });
      }
    });

    proc.on('close', (code) => {
      // Flush any remaining buffered output
      if (buffer.trim()) {
        event.sender.send('sync-progress', { type: 'log', message: buffer });
      }
      if (code === 0) {
        resolve({ success: true, dbPath });
      } else {
        reject(new Error(`Sync process exited with code ${code}`));
      }
    });

    proc.on('error', (err) => {
      reject(new Error(`Sync failed: ${err.message}`));
    });
  });
});
