'use strict';

/**
 * Electron preload script — contextBridge between the main process and renderer.
 *
 * Exposes a safe `window.electronAPI` object to the renderer. Only the
 * explicitly listed functions are accessible; the renderer cannot access
 * Node.js or Electron internals directly.
 */

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  // ── App info ─────────────────────────────────────────────────────────────
  /** Returns { version, name, platform } */
  getAppInfo: () => ipcRenderer.invoke('get-app-info'),

  // ── Paths ──────────────────────────────────────────────────────────────────
  /** Returns { dbPath, configPath, userDataPath, vendorPath } */
  getPaths: () => ipcRenderer.invoke('get-paths'),

  // ── File I/O ───────────────────────────────────────────────────────────────
  /**
   * Read a file from disk and return its contents as an ArrayBuffer.
   * Returns null if the file doesn't exist.
   */
  readFile: (filePath) => ipcRenderer.invoke('read-file', filePath),

  /**
   * Show a native file-open dialog.
   * @param {Electron.OpenDialogOptions} options
   * @returns {Promise<string|null>} Selected file path, or null if cancelled.
   */
  showOpenDialog: (options) => ipcRenderer.invoke('show-open-dialog', options),

  // ── Navigation ─────────────────────────────────────────────────────────────
  /**
   * Navigate the main window to a different page.
   * @param {'dashboard'|'launcher'} page
   */
  navigate: (page) => ipcRenderer.invoke('navigate', page),

  // ── Sync ───────────────────────────────────────────────────────────────────
  /**
   * Run the Python sync process.
   * Password is never logged or passed on the command line.
   * @param {{ username: string, password: string, troopName?: string, csvPath?: string }} opts
   * @returns {Promise<{ success: boolean, dbPath: string }>}
   */
  syncData: (opts) => ipcRenderer.invoke('sync-data', opts),

  /**
   * Listen for progress events streamed from the sync process.
   * Messages have shape: { type: 'step'|'log'|'error'|'complete', message?: string, db_path?: string }
   */
  onSyncProgress: (callback) => {
    ipcRenderer.on('sync-progress', (_event, msg) => callback(msg));
  },

  /** Remove all sync-progress listeners (call before re-registering). */
  removeSyncProgressListener: () => {
    ipcRenderer.removeAllListeners('sync-progress');
  },
});
